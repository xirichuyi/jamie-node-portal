import tempfile
import time
import unittest
import http.client
import json
import threading
from pathlib import Path
from unittest.mock import Mock

from server import App, Server, COOKIE
from errors import DomainError
from panel import Panel
from test_server import FakePanel


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.panel = FakePanel()
        self.panel.remove = Mock()
        self.app = App(
            {'database': str(Path(self.temp.name) / 'test.db'), 'origin': 'https://sub.chuyi.uk'},
            self.panel,
        )
        self.uid = self.app.register('delete_user', 'Good-password-123')
        self.other = self.app.register('keep_user', 'Good-password-123')
        self.aid = self.app.register('admin', 'Good-password-123', True)
        self.token = self.app.new_session(self.uid)
        self.user = self.app.session(self.token)
        self.admin = self.app.session(self.app.new_session(self.aid))
        self.deletion = self.app.account_deletion

    def test_self_delete_cleans_related_data_and_cannot_reuse_card(self):
        card = self.app.ledger.issue(self.aid, 'plan', 1, 30, 1, 30)[0]['code']
        self.app.ledger.redeem(self.uid, card)
        self.app.features.sample_usage({self.uid: 10, self.other: 20})
        tid = self.app.features.ticket_write(
            self.user, {'subject': 'private', 'body': 'private', 'category': 'other'}
        )['id']
        self.app.features.ticket_write(self.admin, {'id': tid, 'body': 'staff reply'}, True)
        self.app.features.recovery_generate(self.user)
        self.app.operations.login_event('delete_user', 'success')
        with self.app.ledger.transaction() as db:
            db.execute(
                'INSERT INTO verified_emails VALUES(?,?,?)',
                (self.uid, 'delete@example.com', int(time.time())),
            )
        self.assertTrue(
            self.deletion.request(self.user, self.uid, 'delete_user', 'Good-password-123')[
                'pending'
            ]
        )
        self.assertIsNone(self.app.session(self.token))
        self.deletion.process()
        self.panel.remove.assert_called_once()
        self.assertTrue(self.panel.remove.call_args.args[0]['disabled'])
        with self.app.ledger.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            for table in ('members', 'accounts'):
                self.assertIsNone(
                    db.execute('SELECT * FROM ' + table + ' WHERE id=?', (self.uid,)).fetchone()
                )
            for table in (
                'sessions',
                'verified_emails',
                'recovery_codes',
                'usage_days',
                'usage_baselines',
                'support_tickets',
                'account_deletions',
            ):
                self.assertIsNone(
                    db.execute(
                        'SELECT * FROM ' + table + ' WHERE account_id=?', (self.uid,)
                    ).fetchone()
                )
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ticket_messages').fetchone()[0], 0)
            self.assertEqual(
                db.execute(
                    'SELECT COUNT(*) FROM login_events WHERE username=?', ('delete_user',)
                ).fetchone()[0],
                0,
            )
            self.assertIsNotNone(
                db.execute('SELECT id FROM accounts WHERE id=?', (self.other,)).fetchone()
            )
        with self.assertRaises(DomainError):
            self.app.ledger.redeem(self.other, card)
        self.deletion.process()
        self.panel.remove.assert_called_once()

    def test_failure_is_pending_and_normal_sync_cannot_recreate_client(self):
        self.panel.remove.side_effect = RuntimeError('offline')
        self.deletion.request(self.admin, self.uid, 'delete_user', 'Good-password-123')
        self.deletion.process()
        with self.app.ledger.connect() as db:
            row = db.execute('SELECT * FROM members WHERE id=?', (self.uid,)).fetchone()
            self.assertEqual(row['deleting'], 1)
            self.assertIn('自动重试', row['sync_error'])
        self.assertFalse(self.app.ledger.sync_member(self.uid, self.panel))
        self.panel.remove.side_effect = None
        with self.app.ledger.transaction() as db:
            db.execute('UPDATE account_deletions SET next_attempt=0')
        self.deletion.process()
        with self.app.ledger.connect() as db:
            self.assertIsNone(
                db.execute('SELECT id FROM accounts WHERE id=?', (self.uid,)).fetchone()
            )

    def test_guards(self):
        for actor, uid, confirmation, password in [
            (self.user, self.uid, 'delete_user', 'wrong'),
            (self.user, self.other, 'keep_user', 'Good-password-123'),
            (self.user, self.uid, 'wrong name', 'Good-password-123'),
            (self.admin, self.aid, 'admin', 'Good-password-123'),
        ]:
            with self.assertRaises(DomainError):
                self.deletion.request(actor, uid, confirmation, password)
        self.assertIsNotNone(self.app.session(self.token))
        self.panel.remove.assert_not_called()

    def test_package_and_addon_foreign_keys_are_erased(self):
        self.app.ledger.package_billing = True
        base = self.app.ledger.issue(self.aid, 'base', 1, 30, 1, 30)[0]['code']
        self.app.ledger.redeem(self.uid, base)
        parent = self.app.ledger.billing_snapshot(self.uid)['packages'][0]['id']
        addon = self.app.ledger.issue(self.aid, 'extra', 1, 1, 1, 30, kind='addon')[0]['code']
        self.app.ledger.redeem(self.uid, addon, target=parent)
        self.deletion.request(self.admin, self.uid, 'delete_user', 'Good-password-123')
        self.deletion.process()
        with self.app.ledger.connect() as db:
            for table in ('billing_accounts', 'entitlement_packages', 'billing_events'):
                self.assertEqual(
                    db.execute(
                        'SELECT COUNT(*) FROM ' + table + ' WHERE member_id=?', (self.uid,)
                    ).fetchone()[0],
                    0,
                )
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertIsNone(
                db.execute('SELECT id FROM accounts WHERE id=?', (self.uid,)).fetchone()
            )

    def test_http_guards_and_self_cookie_revocation(self):
        server = Server(('127.0.0.1', 0), self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:

            def post(path, data, origin='https://sub.chuyi.uk'):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1])
                conn.request(
                    'POST',
                    path,
                    json.dumps(data),
                    {
                        'Content-Type': 'application/json',
                        'Origin': origin,
                        'X-Jamie-Request': '1',
                        'Cookie': COOKIE + '=' + self.token,
                    },
                )
                r = conn.getresponse()
                result = (r.status, r.getheader('Set-Cookie'), json.loads(r.read()))
                conn.close()
                return result

            payload = {
                'id': self.other,
                'password': 'Good-password-123',
                'confirmation': 'delete_user',
            }
            self.assertEqual(post('/api/admin/user-delete', payload)[0], 403)
            self.assertEqual(post('/api/account/delete', payload, 'https://untrusted.test')[0], 403)
            result = post('/api/account/delete', payload)
            self.assertEqual(result[0], 202)
            self.assertIn('Max-Age=0', result[1])
            self.assertTrue(result[2]['pending'])
            with self.app.ledger.connect() as db:
                self.assertEqual(
                    db.execute('SELECT deleting FROM members WHERE id=?', (self.other,)).fetchone()[
                        0
                    ],
                    0,
                )
        finally:
            server.shutdown()
            server.server_close()

    def test_panel_deletion_checks_ownership_and_verifies_removal(self):
        panel = Panel.__new__(Panel)
        member = {'panel_email': 'owned', 'panel_auth': 'auth', 'sub_id': 'sub', 'disabled': 1}
        panel.apply = Mock()
        panel.get = Mock(return_value={'client': {'subId': 'someone-else', 'auth': 'auth'}})
        panel.request = Mock(return_value=[{'email': 'owned'}])
        with self.assertRaises(RuntimeError):
            panel.remove(member)
        panel.apply.assert_not_called()
        panel.get.return_value = {'client': {'subId': 'sub', 'auth': 'auth'}}
        panel.request = Mock(side_effect=[[{'email': 'owned'}], None, []])
        panel.remove(member)
        panel.apply.assert_called_once_with(member)
        self.assertEqual(
            panel.request.call_args_list[1].args, ('clients/del/owned?keepTraffic=0', {})
        )
