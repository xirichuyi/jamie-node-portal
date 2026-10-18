import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

from application import App
from errors import DomainError
from routes_support import dispatch
from email_templates import service_email
import mail_history
from test_server import FakePanel

GIB = 1024**3


class SubscriptionNotificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = App({'database': str(Path(temp.name) / 'db'), 'origin': 'https://example.test',
                        'package_billing': True}, FakePanel())
        card = self.app.ledger.issue('admin', 'Test plan', 100, 30, 1, 0)[0]['code']
        self.user = self.app.session(self.app.register_with_card('alice', 'Test-password-123', card))
        self.uid = self.user['id']
        self.now = int(time.time())
        self.n = self.app.subscription_notifications
        self.app.email_auth.enabled = True
        self.app.email_auth.deliver = Mock()
        with self.app.ledger.transaction() as db:
            db.execute('INSERT INTO verified_emails VALUES(?,?,?)', (self.uid, 'alice@example.test', self.now))
            self.email = db.execute('SELECT panel_email FROM members WHERE id=?', (self.uid,)).fetchone()[0]

    def sample(self, used=90, now=None):
        self.app.ledger.sample_billing({self.email: used * GIB}, now=self.now if now is None else now)

    def sql(self, query, params=()):
        with self.app.ledger.transaction() as db:
            return [dict(r) for r in db.execute(query, params).fetchall()]

    def queue(self):
        return self.sql('SELECT * FROM subscription_mail_queue')

    def process(self):
        self.n.collect(self.now)
        self.n.deliver_pending(self.now)

    def test_threshold_dedup_survives_reinitialization(self):
        self.sample(89)
        self.process()
        self.assertEqual(self.queue(), [])
        self.sample(90)
        self.process()
        self.n = type(self.n)(self.app)
        self.process()
        self.app.email_auth.deliver.assert_called_once()
        self.assertEqual(self.queue()[0]['status'], 'sent')
        rows = mail_history.listing(self.app, {})['items']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['subject'], '流量提醒')
        self.assertNotIn('/sub/', str(self.app.email_auth.deliver.call_args))

    def test_expiry_per_package_not_addon_or_permanent(self):
        self.sql('UPDATE entitlement_packages SET expires=?', (self.now + 3 * 86400,))
        self.process()
        self.assertEqual(self.queue()[0]['kind'], 'expiry_email')
        self.assertIn('Test plan', self.app.email_auth.deliver.call_args.args[1]['text'])
        self.sql('DELETE FROM subscription_mail_queue')
        self.sql('UPDATE entitlement_packages SET permanent=1')
        self.process()
        self.assertEqual(self.queue(), [])
        self.sql("UPDATE entitlement_packages SET permanent=0,kind='addon'")
        self.process()
        self.assertEqual(self.queue(), [])

    def test_stale_sampling_and_fault_do_not_send(self):
        self.sample()
        self.n.collect(self.now)
        self.n.deliver_pending(self.now + 121)
        self.app.email_auth.deliver.assert_not_called()
        self.assertEqual(self.queue()[0]['status'], 'pending')
        self.sample(now=self.now + 421)
        self.n.deliver_pending(self.now + 421)
        self.app.email_auth.deliver.assert_called_once()
        self.sql('DELETE FROM subscription_mail_queue')
        self.sql("UPDATE billing_accounts SET fault='counter_rollback'")
        self.process()
        self.assertEqual(self.queue(), [])

    def test_retry_uses_same_payload_and_key_and_is_bounded(self):
        self.sample()
        self.app.email_auth.deliver.side_effect = DomainError('temporary')
        self.process()
        first = self.app.email_auth.deliver.call_args
        self.n.deliver_pending(self.now)
        self.assertEqual(self.app.email_auth.deliver.call_count, 1)
        for _ in range(4):
            self.sql('UPDATE subscription_mail_queue SET next_attempt=0')
            self.process()
        self.assertEqual(self.app.email_auth.deliver.call_args, first)
        self.assertEqual(self.queue()[0]['status'], 'failed')
        self.process()
        self.assertEqual(self.app.email_auth.deliver.call_count, 5)

    def test_opt_out_cancels_pending_and_preserves_other_preferences(self):
        self.sample()
        self.n.collect(self.now)
        self.n.preferences(self.user, {'traffic_email': False})
        self.process()
        self.app.email_auth.deliver.assert_not_called()
        self.assertEqual(self.queue()[0]['status'], 'cancelled')
        self.assertEqual(self.n.preferences(self.user), {'traffic_email': False, 'expiry_email': True})
        self.assertFalse(type(self.n)(self.app).preferences(self.user)['traffic_email'])

    def test_topup_cancels_obsolete_reminder(self):
        self.sample()
        self.n.collect(self.now)
        self.sql('UPDATE entitlement_packages SET granted=granted+?', (100 * GIB,))
        self.n.deliver_pending(self.now)
        self.app.email_auth.deliver.assert_not_called()
        self.assertEqual(self.queue()[0]['status'], 'cancelled')

    def test_renewal_cancels_old_expiry(self):
        self.sql('UPDATE entitlement_packages SET expires=?', (self.now + 86400,))
        self.n.collect(self.now)
        self.sql('UPDATE entitlement_packages SET expires=?', (self.now + 30 * 86400,))
        self.n.deliver_pending(self.now)
        self.app.email_auth.deliver.assert_not_called()

    def test_new_cycle_can_notify_again(self):
        self.sample()
        self.process()
        self.sql('UPDATE entitlement_packages SET next_reset=?,spent=0', (self.now + 86400,))
        self.process()
        self.assertEqual(self.app.email_auth.deliver.call_count, 1)
        self.sample(180)
        self.process()
        self.assertEqual(self.app.email_auth.deliver.call_count, 2)

    def test_unverified_disabled_deleting_and_email_change_suppress_delivery(self):
        self.sample()
        for column in ('disabled', 'deleting'):
            self.sql(f'UPDATE members SET {column}=1')
            self.n.collect(self.now)
            self.assertEqual(self.queue(), [])
            self.sql(f'UPDATE members SET {column}=0')
        self.n.collect(self.now)
        self.sql("UPDATE verified_emails SET email='changed@example.test'")
        self.n.deliver_pending(self.now)
        self.app.email_auth.deliver.assert_not_called()
        self.sql('DELETE FROM subscription_mail_queue')
        self.sql('DELETE FROM verified_emails')
        self.process()
        self.assertEqual(self.queue(), [])

    def test_retry_expires_before_provider_idempotency_window(self):
        self.sample()
        self.n.collect(self.now)
        self.n.deliver_pending(self.now + 23 * 3600)
        self.app.email_auth.deliver.assert_not_called()
        self.assertEqual(self.queue()[0]['status'], 'failed')

    def test_preferences_reject_invalid_values(self):
        for patch in ({'traffic_email': 1}, {'unknown': True}):
            with self.assertRaises(DomainError):
                self.n.preferences(self.user, patch)

    def test_preferences_api_defaults_partial_updates_and_existing_opt_out(self):
        ctx = SimpleNamespace(app=self.app, path='/api/notifications', account=self.user,
                              write=False, data={}, reply=lambda status, body: body)
        self.assertTrue(all(dispatch(ctx)[k] for k in ('ticket_email', 'traffic_email', 'expiry_email')))
        self.app.ticket_notifications.preferences(self.user, False)
        ctx.write, ctx.data = True, {'traffic_email': False}
        result = dispatch(ctx)
        self.assertEqual([result[k] for k in ('ticket_email', 'traffic_email', 'expiry_email')],
                         [False, False, True])
        ctx.data = {'expiry_email': False, 'unexpected': True}
        with self.assertRaises(DomainError):
            dispatch(ctx)
        self.assertTrue(self.n.preferences(self.user)['expiry_email'])

    def test_email_escapes_package_labels(self):
        content = service_email('提醒', '<img src=x onerror=alert(1)>', 'https://example.test')
        self.assertNotIn('<img', content['html'])
        self.assertIn('&lt;img', content['html'])
        self.assertIn('/#/sessions', content['text'])

    def test_account_deletion_cancels_and_erases_reminders(self):
        self.sample()
        self.n.collect(self.now)
        self.n.preferences(self.user, {'expiry_email': True})
        self.app.account_deletion.request(self.user, self.uid, 'alice', 'Test-password-123')
        self.assertEqual(self.queue()[0]['status'], 'cancelled')
        self.app.account_deletion.purge(self.uid)
        self.assertEqual(self.queue(), [])
        self.assertEqual(self.sql('SELECT * FROM subscription_mail_preferences'), [])
