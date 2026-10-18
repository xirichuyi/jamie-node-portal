import tempfile
import time
import unittest
from unittest.mock import Mock
from pathlib import Path
from server import App, hash_password, verify_password
from entitlements import DomainError
from panel import Panel
from test_server import FakePanel
import test_server


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = App(
            {'database': str(Path(self.temp.name) / 'app.db'), 'origin': 'https://sub.chuyi.uk'},
            FakePanel(),
        )
        self.uid = self.app.register('feature_user', 'Feature-password-123')
        self.other = self.app.register('other_user', 'Feature-password-123')
        self.account = {'id': self.uid}
        self.f = self.app.features

    def tearDown(self):
        self.temp.cleanup()

    def test_recovery_code_single_use_replaces_old_and_revokes_sessions(self):
        token = self.app.new_session(self.uid, 'Test Browser', '127.0.0.1')
        old = self.f.recovery_generate(self.account)['code']
        code = self.f.recovery_generate(self.account)['code']
        hashed = hash_password('Changed-password-123')
        with self.assertRaises(DomainError):
            self.f.recovery_reset('feature_user', old, hashed)
        with self.assertRaises(DomainError):
            self.f.recovery_reset('other_user', code, hashed)
        self.f.recovery_reset('feature_user', code, hashed)
        self.assertIsNone(self.app.session(token))
        with self.assertRaises(DomainError):
            self.f.recovery_reset('feature_user', code, hashed)
        with self.app.ledger.connect() as db:
            stored = db.execute('SELECT password FROM accounts WHERE id=?', (self.uid,)).fetchone()[
                0
            ]
            self.assertTrue(verify_password('Changed-password-123', stored))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM session_details').fetchone()[0], 0)

    def test_session_owner_and_current_session_protection(self):
        first = self.app.new_session(self.uid, 'Browser A', '127.0.0.1')
        second = self.app.new_session(self.uid, 'Browser B', '127.0.0.2')
        stranger = self.app.new_session(self.other)
        sessions = self.f.sessions(self.account, first)['sessions']
        self.assertEqual(len(sessions), 2)
        current = next(s for s in sessions if s['current'])
        target = next(s for s in sessions if not s['current'])
        with self.assertRaises(DomainError):
            self.f.revoke_session(self.account, current['id'], first)
        with self.assertRaises(DomainError):
            self.f.revoke_session({'id': self.other}, target['id'], stranger)
        self.f.revoke_session(self.account, target['id'], first)
        self.assertIsNone(self.app.session(second))
        self.assertIsNotNone(self.app.session(first))

    def test_ticket_isolation_staff_reply_close_and_limits(self):
        tid = self.f.ticket_write(
            self.account,
            {'subject': '无法连接', 'category': 'connection', 'body': '客户端提示超时'},
        )['id']
        self.assertEqual(self.f.tickets({'id': self.other})['tickets'], [])
        with self.assertRaises(DomainError):
            self.f.ticket({'id': self.other}, tid)
        with self.assertRaises(DomainError):
            self.f.ticket_write({'id': self.other}, {'id': tid, 'body': 'not allowed'})
        self.f.ticket_write({'id': self.other}, {'id': tid, 'body': '请更新配置'}, staff=True)
        self.assertEqual(self.f.tickets(self.account)['tickets'][0]['unread'], 1)
        detail = self.f.ticket(self.account, tid)
        mid = detail['messages'][-1]['id']
        with self.assertRaises(DomainError):
            self.f.ticket_read({'id': self.other}, tid, mid)
        self.f.ticket_read(self.account, tid, mid)
        self.assertEqual(self.f.tickets(self.account)['tickets'][0]['unread'], 0)
        self.assertEqual(detail['ticket']['status'], 'replied')
        self.assertEqual(detail['messages'][-1]['staff'], 1)
        self.f.ticket_write(self.account, {'id': tid, 'close': True})
        with self.assertRaises(DomainError):
            self.f.ticket_write(self.account, {'id': tid, 'body': 'closed'})
        for _ in range(5):
            self.f.ticket_write(
                self.account, {'subject': '问题', 'category': 'other', 'body': '详情'}
            )
        with self.assertRaises(DomainError):
            self.f.ticket_write(
                self.account, {'subject': '问题', 'category': 'other', 'body': '详情'}
            )

    def test_opt_in_ticket_email_and_read_cancellation(self):
        mail = self.app.email_auth
        mail.enabled = True
        mail.deliver = Mock()
        with self.app.ledger.transaction() as db:
            db.execute(
                'INSERT INTO verified_emails VALUES(?,?,?)',
                (self.uid, 'test@example.com', int(time.time())),
            )
        notifications = self.app.ticket_notifications
        self.assertTrue(notifications.preferences(self.account)['ticket_email'])
        tid = self.f.ticket_write(
            self.account, {'subject': 'test', 'body': 'private body', 'category': 'other'}
        )['id']
        self.f.ticket_write({'id': self.other}, {'id': tid, 'body': 'private staff reply'}, True)
        notifications.deliver_pending()
        mail.deliver.assert_called_once()
        self.assertNotIn('private', str(mail.deliver.call_args))
        notifications.deliver_pending()
        mail.deliver.assert_called_once()
        self.f.ticket_write({'id': self.other}, {'id': tid, 'body': 'another reply'}, True)
        detail = self.f.ticket(self.account, tid)
        self.f.ticket_read(self.account, tid, detail['messages'][-1]['id'])
        notifications.deliver_pending()
        mail.deliver.assert_called_once()
        self.f.ticket_write({'id': self.other}, {'id': tid, 'body': 'third reply'}, True)
        notifications.preferences(self.account, False)
        notifications.deliver_pending()
        mail.deliver.assert_called_once()

    def test_ticket_mail_failure_is_retryable_not_duplicate_reply(self):
        self.app.email_auth.enabled = True
        self.app.email_auth.deliver = Mock(side_effect=DomainError('temporary'))
        with self.app.ledger.transaction() as db:
            db.execute(
                'INSERT INTO verified_emails VALUES(?,?,?)',
                (self.uid, 'test@example.com', int(time.time())),
            )
        n = self.app.ticket_notifications
        n.preferences(self.account, True)
        tid = self.f.ticket_write(
            self.account, {'subject': 'test', 'body': 'question', 'category': 'other'}
        )['id']
        self.f.ticket_write({'id': self.other}, {'id': tid, 'body': 'reply'}, True)
        n.deliver_pending()
        with self.app.ledger.connect() as db:
            row = db.execute('SELECT status,attempts FROM ticket_mail_queue').fetchone()
            self.assertEqual((row['status'], row['attempts']), ('pending', 1))
        self.assertEqual(len(self.f.ticket(self.account, tid)['messages']), 2)

    def test_preview_never_consumes_and_final_redemption_rechecks(self):
        card = self.app.ledger.issue('admin', '测试套餐', 5, 30, 1, 1)[0]
        for _ in range(2):
            preview = self.f.preview(self.uid, card['code'])
            self.assertEqual(preview['quota'], 5 * 1024**3)
        self.app.ledger.redeem(self.other, card['code'])
        with self.assertRaises(DomainError):
            self.app.ledger.redeem(self.uid, card['code'])
        with self.assertRaises(DomainError):
            self.f.preview(self.uid, card['code'])

    def test_rotation_preserves_entitlement_and_hides_pending_url(self):
        card = self.app.ledger.issue('admin', '测试', 1, 1, 1, 1)[0]
        self.app.ledger.redeem(self.uid, card['code'])
        with self.assertRaises(DomainError):
            self.f.rotate(self.uid)
        self.app.ledger.sync_member(self.uid, self.app.panel)
        with self.app.ledger.connect() as db:
            before = dict(db.execute('SELECT * FROM members WHERE id=?', (self.uid,)).fetchone())
        self.f.rotate(self.uid)
        with self.app.ledger.connect() as db:
            after = dict(db.execute('SELECT * FROM members WHERE id=?', (self.uid,)).fetchone())
            account = db.execute('SELECT * FROM accounts WHERE id=?', (self.uid,)).fetchone()
        for key in ('quota', 'expires', 'panel_auth', 'panel_email'):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after['previous_sub_id'], before['sub_id'])
        self.assertNotEqual(after['sub_id'], before['sub_id'])
        self.assertIsNone(self.app.overview(account)['subscription']['url'])
        self.app.ledger.sync_member(self.uid, self.app.panel)
        self.assertTrue(self.app.overview(account)['subscription']['url'].endswith(after['sub_id']))

    def test_usage_baseline_no_invented_history_resets_and_owner_scope(self):
        now = int(time.time())
        self.f.sample_usage({self.uid: 5000}, now - 600)
        self.f.sample_usage({self.uid: 5500}, now - 300)
        self.f.sample_usage({self.uid: 100}, now)
        usage = self.f.usage(self.uid)
        self.assertEqual(sum(d['bytes'] or 0 for d in usage['days']), 500)
        self.assertTrue(any(d['partial'] for d in usage['days'] if d['bytes'] is not None))
        self.assertTrue(all(d['bytes'] is None for d in self.f.usage(self.other)['days']))
        self.assertEqual(len(usage['days']), 30)

    def test_incidents_and_operations_empty_states(self):
        iid = self.f.incident_save(
            self.account, {'title': '维护', 'body': '安排维护', 'status': 'maintenance'}
        )['id']
        self.f.incident_save(
            self.account, {'id': iid, 'title': '维护完成', 'body': '已恢复', 'status': 'resolved'}
        )
        self.assertEqual(self.f.service_status()['incidents'][0]['status'], 'resolved')
        ops = self.f.operations()
        self.assertEqual(ops['counts']['users'], 2)
        self.assertIsNone(ops['backup_at'])
        self.assertEqual(ops['budgets'], [])


class FeatureHTTPTests(unittest.TestCase):
    call = test_server.ServerTests.call

    @classmethod
    def setUpClass(cls):
        from server import Server
        import threading

        cls.temp = tempfile.TemporaryDirectory()
        cls.app = App(
            {'database': str(Path(cls.temp.name) / 'app.db'), 'origin': 'https://sub.chuyi.uk'},
            FakePanel(),
        )
        cls.uid = cls.app.register('http_user', 'HTTP-password-123')
        cls.http = Server(('127.0.0.1', 0), cls.app)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.temp.cleanup()

    def test_auth_role_csrf_and_recovery_flow(self):
        for path in (
            'usage',
            'sessions',
            'tickets',
            'service-status',
            'admin/operations',
            'admin/tickets',
        ):
            self.assertEqual(self.call(path)[0], 401)
        status, _, cookie = self.call(
            'login', {'username': 'http_user', 'password': 'HTTP-password-123'}
        )
        self.assertEqual(status, 200)
        for path in ('usage', 'sessions', 'tickets', 'service-status'):
            self.assertEqual(self.call(path, cookie=cookie)[0], 200)
        for path in ('admin/operations', 'admin/tickets'):
            self.assertEqual(self.call(path, cookie=cookie)[0], 403)
        self.assertEqual(self.call('admin/incident', {}, cookie)[0], 403)
        self.assertEqual(
            self.call(
                'recovery-code', {'password': 'HTTP-password-123'}, cookie, 'https://evil.example'
            )[0],
            403,
        )
        self.assertEqual(self.call('recovery-code', {'password': 'incorrect'}, cookie)[0], 400)
        status, result, _ = self.call('recovery-code', {'password': 'HTTP-password-123'}, cookie)
        self.assertEqual(status, 200)
        self.assertEqual(
            self.call(
                'recover',
                {
                    'username': 'http_user',
                    'code': result['code'],
                    'new_password': 'Recovered-password-123',
                },
            )[0],
            200,
        )
        self.assertEqual(self.call('me', cookie=cookie)[0], 401)
        self.assertEqual(
            self.call('login', {'username': 'http_user', 'password': 'Recovered-password-123'})[0],
            200,
        )


class PanelRotationTests(unittest.TestCase):
    def test_retry_accepts_old_or_new_id_not_foreign_identity(self):
        panel = Panel(
            {'panel_url': 'https://example.invalid', 'panel_token': 'test', 'inbounds': [1, 2, 3]}
        )
        member = {
            'panel_email': 'test',
            'panel_auth': 'owned-auth',
            'sub_id': 'new',
            'previous_sub_id': 'old',
            'quota': 1024,
            'expires': 2000000000,
            'disabled': 0,
        }
        current = {
            'client': {
                'subId': 'old',
                'auth': 'owned-auth',
                'enable': True,
                'totalGB': 1024,
                'expiryTime': 2000000000000,
            },
            'inboundIds': [1, 2, 3],
        }

        def request(path, payload=None):
            if path == 'clients/list':
                return [{'email': 'test'}]
            if path.startswith('clients/get/'):
                return current
            if path.startswith('clients/update/'):
                current['client'].update(payload)
                return {}
            raise AssertionError(path)

        panel.request = request
        panel.apply(member)
        panel.apply(member)
        self.assertEqual(current['client']['subId'], 'new')
        current['client']['subId'] = 'foreign'
        with self.assertRaises(RuntimeError):
            panel.apply(member)
