import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from application import App
from errors import DomainError
from test_server import FakePanel

GIB = 1024**3


class MailNotificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = App({'database': str(Path(temp.name) / 'db'), 'origin': 'https://example.test',
                        'package_billing': True, 'mail': {'reply_to': 'support@example.test'}}, FakePanel())
        self.now = int(time.time())
        card = self.app.ledger.issue('admin', '月卡', 100, 30, 1, 0)[0]['code']
        self.user = self.app.session(self.app.register_with_card('alice', 'Test-password-123', card))
        self.app.email_auth.enabled = True
        self.app.email_auth.deliver = Mock()
        self.uid = self.user['id']
        self.admin = self.app.register('boss', 'Admin-password-12345', True)
        with self.app.ledger.transaction() as db:
            db.execute('INSERT INTO verified_emails VALUES(?,?,?)', (self.uid, 'alice@example.test', self.now))
            self.email = db.execute('SELECT panel_email FROM members WHERE id=?', (self.uid,)).fetchone()[0]

    def sql(self, query, params=()):
        with self.app.ledger.transaction() as db:
            return [dict(r) for r in db.execute(query, params).fetchall()]

    def sent(self):
        return [(c.args[0], c.args[1]) for c in self.app.email_auth.deliver.call_args_list]

    # Receipts
    def test_activation_and_renewals_get_one_grouped_receipt(self):
        self.app.receipts.run()
        [(to, content)] = self.sent()
        self.assertEqual(to, 'alice@example.test')
        self.assertIn('兑换成功', content['subject'])
        self.assertIn('月卡', content['text'])
        self.assertIn('服务截止', content['text'])
        self.assertNotIn('/sub/', content['text'])
        self.app.receipts.run()
        self.assertEqual(len(self.sent()), 1)  # Never re-sent.
        self.app.ledger.sample_billing({self.email: 0}, now=int(time.time()))
        a, b = (c['code'] for c in self.app.ledger.issue('admin', '季卡', 50, 60, 2, 0))
        self.app.ledger.redeem(self.uid, a)
        self.app.ledger.redeem(self.uid, b)
        self.app.receipts.run()
        self.assertEqual(len(self.sent()), 2)
        text = self.sent()[-1][1]['text']
        self.assertEqual(text.count('季卡'), 2)
        self.assertIn('开始计时', text)  # Queued renewals say when they start.

    def test_grant_receipt_and_skips_without_verified_email(self):
        self.app.receipts.run()
        spec = self.app.ledger.card_spec('补偿', 5, 7, 1, 0)
        self.app.ledger.sample_billing({self.email: 0}, now=int(time.time()))
        self.app.ledger.grant(self.admin, self.uid, spec)
        self.app.receipts.run()
        self.assertIn('套餐已到账', self.sent()[-1][1]['subject'])
        self.assertIn('管理员为你发放', self.sent()[-1][1]['text'])
        with self.app.ledger.transaction() as db:
            db.execute('DELETE FROM verified_emails WHERE account_id=?', (self.uid,))
        self.app.ledger.sample_billing({self.email: 0}, now=int(time.time()))
        self.app.ledger.grant(self.admin, self.uid, spec)
        self.app.receipts.run()
        self.assertEqual(len(self.sent()), 2)
        statuses = sorted(r['status'] for r in self.sql('SELECT status FROM receipt_mail_queue'))
        self.assertEqual(statuses, ['cancelled', 'sent', 'sent'])

    def test_receipt_watermark_ignores_old_redemptions(self):
        with self.app.ledger.transaction() as db:
            db.execute('UPDATE cards SET redeemed_at=? WHERE redeemed_by=?', (self.now - 3 * 86400, self.uid))
        self.app.receipts.run()
        self.assertEqual(self.sent(), [])

    def test_failed_delivery_retries_then_gives_up(self):
        self.app.email_auth.deliver.side_effect = DomainError('down')
        for step in range(6):
            self.app.receipts.deliver_pending(self.now + step * 4000) if step else self.app.receipts.run()
        self.assertEqual(self.sql('SELECT status FROM receipt_mail_queue')[0]['status'], 'failed')

    # Staff alerts
    def ticket(self, account=None, **data):
        return self.app.features.ticket_write(account or self.user, data, staff=account is not None)

    def test_new_ticket_and_customer_reply_alert_staff_once(self):
        tid = self.ticket(category='connection', subject='连不上', body='超时')['id']
        self.app.staff_notifications.deliver_pending()
        [(to, content)] = self.sent()
        self.assertEqual(to, 'support@example.test')  # Fallback when no admin email.
        self.assertIn('新工单：连不上', content['subject'])
        self.assertIn('超时', content['text'])
        self.assertIn('/#/admin_tickets', content['text'])
        # Two quick replies produce a single alert for the latest one.
        self.ticket(id=tid, body='还是不行')
        self.ticket(id=tid, body='补充截图')
        self.app.staff_notifications.deliver_pending()
        self.assertEqual(len(self.sent()), 2)
        self.assertIn('补充截图', self.sent()[-1][1]['text'])

    def test_staff_reply_cancels_pending_alert_and_toggle_disables(self):
        tid = self.ticket(category='other', subject='问题', body='内容')['id']
        staff = self.app.session(self.app.new_session(self.admin))
        self.ticket(staff, id=tid, body='已处理')
        self.app.staff_notifications.deliver_pending()
        self.assertFalse(any('新工单' in c['subject'] for _, c in self.sent()))
        with self.app.ledger.transaction() as db:
            db.execute('INSERT INTO verified_emails VALUES(?,?,?)', (self.admin, 'boss@example.test', self.now))
        settings = self.app.staff_notifications.settings(False)
        self.assertEqual(settings['recipients'], ['boss@example.test'])
        self.ticket(category='other', subject='另一个', body='内容')
        self.app.staff_notifications.deliver_pending()
        self.assertFalse(any('另一个' in c['subject'] for _, c in self.sent()))
        with self.assertRaises(DomainError):
            self.app.staff_notifications.settings('yes')

    # Expiry reminders follow queued renewals
    def test_expiry_reminder_only_when_service_ends(self):
        n = self.app.subscription_notifications
        later = int(time.time()) + 29 * 86400
        with self.app.ledger.connect() as db:
            self.assertEqual([k for k, _ in n.events(db, self.uid, later, require_fresh=False).values()], ['expiry_email'])
        self.app.ledger.sample_billing({self.email: 0}, now=int(time.time()))
        self.app.ledger.redeem(self.uid, self.app.ledger.issue('admin', '续费', 100, 30, 1, 0)[0]['code'])
        with self.app.ledger.connect() as db:
            self.assertEqual(n.events(db, self.uid, later, require_fresh=False), {})
            final = n.events(db, self.uid, later + 30 * 86400, require_fresh=False)
        [(kind, content)] = final.values()
        self.assertEqual(kind, 'expiry_email')
        self.assertIn('续费', content['text'])

    def test_account_deletion_cancels_and_purges_new_queues(self):
        self.app.receipts.collect()
        self.ticket(category='other', subject='删号前', body='内容')
        self.app.users.save_note(self.admin, self.uid, '备注')
        self.app.account_deletion.request(self.user, self.uid, 'alice', 'Test-password-123')
        self.assertEqual({r['status'] for r in self.sql('SELECT status FROM receipt_mail_queue')}, {'cancelled'})
        self.app.account_deletion.purge(self.uid)
        for table in ('receipt_mail_queue', 'staff_mail_queue', 'admin_user_notes'):
            self.assertEqual(self.sql('SELECT * FROM ' + table), [], table)


if __name__ == '__main__':
    unittest.main()
