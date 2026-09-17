import concurrent.futures
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from server import App
from entitlements import DomainError, GIB
from test_server import FakePanel
from content import Content


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = App(
            {'database': str(Path(self.temp.name) / 'app.db'), 'origin': 'https://sub.chuyi.uk'},
            FakePanel(),
        )
        self.card = self.app.ledger.issue('test', '开通套餐', 100, 30, 1, 7)[0]
        self.password = 'Test-password-12345'

    def tearDown(self):
        self.temp.cleanup()

    def register(self, name='new_user', code=None, password=None):
        return self.app.register_with_card(
            name, password or self.password, code or self.card['code'], 'Browser', '127.0.0.1'
        )

    def row(self, table):
        with self.app.ledger.connect() as db:
            return dict(db.execute('SELECT * FROM ' + table).fetchone())

    def assert_unspent(self):
        self.assertIsNone(self.row('cards')['redeemed_by'])
        with self.app.ledger.connect() as db:
            for table in ('accounts', 'members', 'sessions', 'session_details'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)

    def test_preview_never_consumes_card_or_starts_expiry(self):
        result = self.app.card_preview(self.card['code'].lower().replace('-', ' '))
        self.assertEqual(result, {'label': '开通套餐', 'quota': 100 * GIB, 'days': 30})
        self.assert_unspent()
        self.assertNotIn('digest', result)

    def test_register_and_session_commit_together_with_entitlement(self):
        before = int(time.time())
        token = self.register()
        account = self.app.session(token)
        self.assertIsNotNone(account)
        self.assertEqual(account['admin'], 0)
        member = self.row('members')
        self.assertEqual(member['quota'], 100 * GIB)
        self.assertEqual(member['revision'], 1)
        self.assertEqual(member['synced_revision'], 0)
        self.assertGreaterEqual(member['expires'], before + 30 * 86400)
        self.assertEqual(self.row('cards')['redeemed_by'], account['id'])
        self.assertEqual(len(self.app.features.sessions(account, token)['sessions']), 1)

    def test_repeated_request_same_credentials_never_redeems_twice(self):
        first = self.register()
        initial = self.row('members')
        second = self.register('NEW_USER')
        self.assertEqual(self.app.session(first)['id'], self.app.session(second)['id'])
        self.assertEqual(self.row('members'), initial)
        with self.assertRaises(DomainError):
            self.register(password='Wrong-password-12345')
        with self.assertRaises(DomainError):
            self.register('other_user')
        with self.assertRaises(DomainError):
            self.app.card_preview(self.card['code'])

    def test_bad_card_or_bad_fields_create_nothing(self):
        for name, password, code in [
            ('ab', self.password, self.card['code']),
            ('valid', 'short', self.card['code']),
            ('valid', self.password, 'invalid'),
        ]:
            with self.assertRaises(DomainError):
                self.app.register_with_card(name, password, code)
            self.assert_unspent()

    def test_expired_or_revoked_after_preview_is_rechecked(self):
        self.app.card_preview(self.card['code'])
        with self.app.ledger.connect() as db:
            db.execute('UPDATE cards SET redeem_before=1')
        with self.assertRaises(DomainError):
            self.register()
        self.assert_unspent()
        with self.app.ledger.connect() as db:
            db.execute('UPDATE cards SET redeem_before=?,revoked_at=1', (int(time.time()) + 999,))
        with self.assertRaises(DomainError):
            self.register()
        self.assert_unspent()

    def test_session_storage_failure_rolls_back_account_card_and_audit(self):
        with patch.object(
            self.app.features,
            'session_created',
            side_effect=sqlite3.OperationalError('test failure'),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                self.register()
        self.assert_unspent()
        with self.app.ledger.connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM audit WHERE action IN ('account.register','card.redeem')"
                ).fetchone()[0],
                0,
            )
        self.assertIsNotNone(self.app.session(self.register()))

    def test_taken_username_does_not_spend_second_card(self):
        self.register()
        other = self.app.ledger.issue('test', '另一个套餐', 50, 10, 1, 7)[0]
        with self.assertRaises(DomainError):
            self.register(code=other['code'])
        self.assertEqual(self.app.card_preview(other['code'])['quota'], 50 * GIB)
        self.assertEqual(self.row('members')['quota'], 100 * GIB)

    def test_concurrent_consumers_only_one_account_wins(self):
        def attempt(name):
            try:
                return self.register(name)
            except DomainError:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ['first_user', 'second_user']))
        self.assertEqual(sum(token is not None for token in results), 1)
        with self.app.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0], 1)
        self.assertEqual(self.row('members')['quota'], 100 * GIB)

    def test_concurrent_identical_requests_are_idempotent(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.register(), range(2)))
        self.assertEqual(len({self.app.session(token)['id'] for token in results}), 1)
        self.assertEqual(self.row('members')['revision'], 1)

    def test_panel_failure_keeps_login_and_retryable_single_entitlement(self):
        token = self.register()
        uid = self.app.session(token)['id']
        with patch.object(self.app.panel, 'apply', side_effect=RuntimeError('offline')):
            self.assertFalse(self.app.ledger.sync_member(uid, self.app.panel))
        self.assertIsNotNone(self.app.session(token))
        self.assertEqual(self.row('members')['quota'], 100 * GIB)
        self.assertTrue(self.app.ledger.sync_member(uid, self.app.panel))
        self.assertEqual(self.row('members')['synced_revision'], 1)
        self.assertFalse(self.app.ledger.sync_member(uid, self.app.panel))

    def test_disabled_account_cannot_replay_registration_to_login(self):
        self.register()
        with self.app.ledger.connect() as db:
            db.execute('UPDATE members SET disabled=1')
        with self.assertRaises(DomainError):
            self.register()

    def test_new_flow_notice_does_not_overwrite_owner_edits(self):
        self.assertIn('先验证卡密', self.app.content.read()['notices'][0]['body'])
        with self.app.ledger.connect() as db:
            db.execute('DELETE FROM portal_migrations WHERE version=2')
            db.execute(
                "UPDATE portal_notices SET body='Owner custom notice',revision=3 WHERE id='welcome'"
            )
        Content(self.app.ledger)
        self.assertEqual(self.app.content.read()['notices'][0]['body'], 'Owner custom notice')
