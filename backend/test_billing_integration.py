import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from server import App
from entitlements import DomainError, GIB
from test_server import FakePanel


class BillingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.panel = FakePanel()
        self.panel.request = Mock(return_value=[])
        self.app = App(
            {
                'database': str(Path(self.temp.name) / 'db'),
                'origin': 'https://example.test',
                'package_billing': True,
            },
            self.panel,
        )

    def tearDown(self):
        self.temp.cleanup()

    def card(self, kind='base', days=30):
        return self.app.ledger.issue('admin', 'Test', 1, days, 1, 30, kind=kind)[0]['code']

    def user(self):
        token = self.app.register_with_card('alice', 'Secret-password-123', self.card())
        return self.app.session(token)

    def sample(self, user, raw):
        with self.app.ledger.connect() as db:
            email = db.execute(
                'SELECT panel_email FROM members WHERE id=?', (user['id'],)
            ).fetchone()[0]
        self.panel.request.return_value = [{'email': email, 'traffic': {'up': raw, 'down': 0}}]
        self.app.refresh_billing()

    def test_register_base_addon_and_double_redemption(self):
        user = self.user()
        state = self.app.ledger.billing_snapshot(user['id'])
        self.assertEqual(state['remaining'], GIB)
        target = state['packages'][0]['id']
        expiry = state['packages'][0]['expires']
        code = self.card('addon')
        for register in (False, True):
            with self.assertRaises(DomainError):
                if register:
                    self.app.register_with_card('bob', 'Secret-password-123', code)
                else:
                    self.app.card_preview(code)
        self.assertEqual(self.app.features.preview(user['id'], code)['kind'], 'addon')
        with self.assertRaises(DomainError):
            self.app.ledger.redeem(user['id'], code)
        self.app.ledger.redeem(user['id'], code, target=target)
        self.app.ledger.redeem(user['id'], code, target=target)
        state = self.app.ledger.billing_snapshot(user['id'])
        self.assertEqual(state['remaining'], 2 * GIB)
        self.assertEqual({p['expires'] for p in state['packages']}, {expiry})
        self.sample(user, GIB // 2)
        self.assertEqual(self.app.overview(user)['subscription']['used'], GIB // 2)

    def test_new_package_does_not_extend_old_and_expiry_reduces_panel_target(self):
        user = self.user()
        self.sample(user, 100)
        before = self.app.ledger.billing_snapshot(user['id'])
        self.app.ledger.redeem(user['id'], self.card(days=60))
        now = int(time.time())
        with self.app.ledger.transaction() as db:
            db.execute(
                'UPDATE entitlement_packages SET expires=? WHERE id=?',
                (now - 1, before['packages'][0]['id']),
            )
        self.app.refresh_billing()
        state = self.app.ledger.billing_snapshot(user['id'])
        self.assertEqual(state['remaining'], GIB)
        with self.app.ledger.connect() as db:
            m = dict(db.execute('SELECT * FROM members WHERE id=?', (user['id'],)).fetchone())
        self.assertEqual(m['quota'], GIB + 100)
        self.assertFalse(m['billing_blocked'])

    def test_counter_rollback_blocks_node_without_disabling_website(self):
        user = self.user()
        self.sample(user, 100)
        self.sample(user, 0)
        with self.app.ledger.connect() as db:
            m = dict(db.execute('SELECT * FROM members WHERE id=?', (user['id'],)).fetchone())
        self.assertEqual(m['billing_blocked'], 1)
        self.assertEqual(m['disabled'], 0)
        code = self.card()
        with self.assertRaises(DomainError):
            self.app.ledger.redeem(user['id'], code)
        with self.app.ledger.connect() as db:
            self.assertIsNone(
                db.execute(
                    'SELECT redeemed_by FROM cards WHERE digest=?', (self.app.ledger.digest(code),)
                ).fetchone()[0]
            )

    def test_existing_user_migration_is_idempotent_and_requires_actual_sample(self):
        uid = self.app.register('legacy', 'Secret-password-123')
        with self.app.ledger.connect() as db:
            db.execute(
                'UPDATE members SET quota=?,expires=?,revision=1 WHERE id=?',
                (GIB, int(time.time()) + 86400, uid),
            )
        self.app.refresh_billing()
        self.assertIsNone(self.app.ledger.billing_snapshot(uid))
        self.sample({'id': uid}, 250)
        self.sample({'id': uid}, 300)
        state = self.app.ledger.billing_snapshot(uid)
        self.assertEqual(state['remaining'], GIB - 300)
        self.assertEqual(len(state['packages']), 1)
        self.assertEqual(state['packages'][0]['kind'], 'transition')
