import http.client
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock
from pathlib import Path
from server import App, Server


class FakePanel:
    def __init__(self):
        self.members = {}

    def apply(self, m):
        self.members[m['panel_email']] = m

    def get(self, email):
        m = self.members[email]
        return {'usedTraffic': 12345, 'client': {'enable': not m['disabled']}}


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = App(
            {'database': str(Path(cls.temp.name) / 'app.db'), 'origin': 'https://sub.chuyi.uk'},
            FakePanel(),
        )
        cls.admin_id = cls.app.register('admin', 'Admin-password-12345', True)
        cls.http = Server(('127.0.0.1', 0), cls.app)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.temp.cleanup()

    def call(self, path, data=None, cookie='', origin='https://sub.chuyi.uk'):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_address[1])
        headers = {
            'Cookie': cookie,
            'Origin': origin,
            'Content-Type': 'application/json',
            'X-Jamie-Request': '1',
        }
        conn.request(
            'GET' if data is None else 'POST',
            '/api/' + path,
            None if data is None else json.dumps(data),
            headers,
        )
        response = conn.getresponse()
        body = json.loads(response.read())
        result = response.status, body, response.getheader('Set-Cookie', '')
        conn.close()
        return result

    def test_full_workflow_and_access_controls(self):
        status, _, cookie = self.call(
            'login', {'username': 'admin', 'password': 'Admin-password-12345'}
        )
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('Secure', cookie)
        self.assertIn('SameSite=Strict', cookie)
        self.assertEqual(self.call('admin/users', cookie=cookie)[0], 403)
        status, _, admin_cookie = self.call(
            'password',
            {'old_password': 'Admin-password-12345', 'new_password': 'New-admin-password-12345'},
            cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.call('me', cookie=cookie)[0], 401)
        activation = self.app.ledger.issue(self.admin_id, '开通卡', 1, 1, 1, 1)[0]['code']
        self.assertEqual(
            self.call('register', {'username': 'nocard', 'password': 'User-password-12345'})[0], 503
        )
        self.app.email_auth.config = {'api_key': 'test-mail-key', 'from': 'test@example.com'}
        self.app.email_auth.enabled = True
        self.app.email_auth.send = Mock()
        self.assertEqual(
            self.call(
                'register',
                {'username': 'alice', 'password': 'User-password-12345', 'code': activation},
            )[0],
            400,
        )
        self.assertEqual(
            self.call(
                'email/code',
                {'email': 'alice@example.com', 'purpose': 'register', 'code': activation},
            )[0],
            200,
        )
        otp = self.app.email_auth.send.call_args.args[2]
        self.assertEqual(self.call('register/preview', {'code': activation})[1]['quota'], 1024**3)
        self.assertEqual(
            self.call('register/preview', {'code': activation}, origin='https://evil.example')[0],
            403,
        )
        status, _, user_cookie = self.call(
            'register',
            {
                'username': 'alice@example.com',
                'email_code': otp,
                'password': 'User-password-12345',
                'code': activation,
                'admin': True,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.call('admin/users', cookie=user_cookie)[0], 403)
        self.assertEqual(self.call('admin/overview', cookie=admin_cookie)[0], 404)
        for endpoint in ('admin/users', 'admin/user?id=missing', 'admin/orders'):
            self.assertEqual(self.call(endpoint)[0], 401)
            self.assertEqual(self.call(endpoint, cookie=user_cookie)[0], 403)
        for endpoint in ('admin/user-sessions', 'admin/user-sync'):
            self.assertEqual(self.call(endpoint, {'id': 'missing'}, user_cookie)[0], 403)
        for endpoint in ('admin/card-search', 'admin/login-diagnosis'):
            self.assertEqual(self.call(endpoint, {})[0], 401)
            self.assertEqual(self.call(endpoint, {}, user_cookie)[0], 403)
            self.assertEqual(self.call(endpoint, {}, admin_cookie, 'https://evil.example')[0], 403)
        self.assertEqual(self.call('admin/readiness', cookie=user_cookie)[0], 403)
        self.assertEqual(self.call('admin/readiness', cookie=admin_cookie)[0], 200)
        self.assertIn('HttpOnly', user_cookie)
        self.assertIn('Secure', user_cookie)
        self.assertIn('SameSite=Strict', user_cookie)
        self.assertEqual(self.call('admin/content', cookie=user_cookie)[0], 403)
        self.assertEqual(self.call('admin/plan', {'name': 'unauthorized'}, user_cookie)[0], 403)
        public = self.call('content')[1]
        self.assertEqual(len(public['plans']), 1)
        self.assertEqual(self.call('nodes')[0], 401)
        self.assertEqual(self.call('nodes', cookie=user_cookie)[0], 200)
        catalog = self.call('admin/content', cookie=admin_cookie)[1]
        self.assertEqual(len(catalog['plans']), 3)
        draft = catalog['plans'][0]
        self.assertEqual(
            self.call(
                'admin/cards', {'plan_id': draft['id'], 'count': 1, 'valid_days': 1}, admin_cookie
            )[0],
            400,
        )
        draft.update(published=True)
        self.assertEqual(self.call('admin/plan', draft, admin_cookie)[0], 200)
        self.assertEqual(len(self.call('content')[1]['plans']), 2)
        self.assertEqual(
            self.call(
                'admin/cards',
                {'plan_id': draft['id'], 'count': 1, 'valid_days': 1, 'quota_gib': 999},
                admin_cookie,
            )[0],
            200,
        )
        with self.app.ledger.connect() as db:
            self.assertEqual(
                db.execute('SELECT quota FROM cards WHERE label=?', (draft['name'],)).fetchone()[0],
                draft['quota_gib'] * 1024**3,
            )
        self.assertFalse(self.call('me', cookie=user_cookie)[1]['user']['admin'])
        self.assertEqual(
            self.call('redeem', {'code': 'x'}, user_cookie, 'https://evil.example')[0], 403
        )
        status, result, _ = self.call(
            'admin/cards',
            {'label': '测试卡', 'quota_gib': 1, 'days': 1, 'count': 1, 'valid_days': 1},
            admin_cookie,
        )
        self.assertEqual(status, 200)
        code = result['codes'][0]['code']
        self.assertEqual(self.call('redeem', {'code': code}, user_cookie)[0], 200)
        self.assertTrue(self.call('redeem', {'code': code}, user_cookie)[1]['already_redeemed'])
        for uid in self.app.ledger.pending():
            self.app.ledger.sync_member(uid, self.app.panel)
        status, me, _ = self.call('me', cookie=user_cookie)
        self.assertEqual(me['subscription']['quota'], 2 * 1024**3)
        self.assertEqual(me['subscription']['used'], 12345)
        self.assertTrue(me['subscription']['url'].startswith('https://sub.chuyi.uk/sub/'))
        self.assertNotIn('panel_auth', json.dumps(me))
        overview = self.call('admin/users', cookie=admin_cookie)[1]
        self.assertNotIn(code, json.dumps(overview))
        uid = next(m['id'] for m in overview['members'] if m['username'] == 'alice@example.com')
        detail = self.call('admin/user?id=' + uid, cookie=admin_cookie)
        self.assertEqual(detail[0], 200)
        self.assertNotIn('panel_auth', json.dumps(detail[1]))
        self.assertEqual(self.call('admin/users?q=alice', cookie=admin_cookie)[1]['total'], 1)
        self.assertEqual(
            self.call(
                'admin/member',
                {'id': uid, 'disabled': True, 'expected_disabled': True},
                admin_cookie,
            )[0],
            400,
        )
        self.assertEqual(
            self.call('admin/user-sync', {'id': uid}, admin_cookie)[1]['pending'], False
        )
        status, _, _ = self.call('admin/member', {'id': uid, 'disabled': True}, admin_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(self.call('me', cookie=user_cookie)[0], 401)
        self.assertEqual(self.call('admin/user-sessions', {'id': uid}, admin_cookie)[0], 200)
        self.assertEqual(
            self.call('admin/user-sessions', {'id': self.admin_id}, admin_cookie)[0], 400
        )
        self.assertEqual(
            self.call('admin/member', {'id': self.admin_id, 'disabled': True}, admin_cookie)[0], 400
        )
        self.app.ledger.sync_member(uid, self.app.panel)
        self.assertTrue(next(iter(self.app.panel.members.values()))['disabled'])
        self.assertEqual(self.call('me')[0], 401)
        self.assertEqual(
            self.call('login', {'username': "' OR 1=1 --", 'password': 'Anything-long-enough'})[0],
            401,
        )


if __name__ == '__main__':
    unittest.main()
