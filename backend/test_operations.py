import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from server import App
from test_server import FakePanel
from entitlements import DomainError
from panel import Panel
from backup import run as backup_run
from probe import outbound


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.panel = FakePanel()
        self.panel.request = Mock(return_value=[])
        self.app = App(
            {'database': str(self.root / 'portal.db'), 'origin': 'https://example.test'}, self.panel
        )
        self.uid = self.app.register('card_owner', 'Test-password-123')
        self.card = self.app.ledger.issue('admin', '测试卡', 10, 30, 1, 30)[0]
        self.app.ledger.redeem(self.uid, self.card['code'])
        self.app.ledger.sync_member(self.uid, self.panel)

    def tearDown(self):
        self.temp.cleanup()

    def test_card_lookup_never_returns_secrets_and_searches_all_pages(self):
        for _ in range(6):
            self.app.ledger.issue('admin', '更多卡', 1, 1, 100, 1)
        for query in [self.card['code'], self.card['code'][-8:], 'card_owner']:
            result = self.app.operations.cards({'query': query})
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['cards'][0]['account_id'], self.uid)
            for key in ('digest', 'code', 'password', 'panel_auth', 'sub_id'):
                self.assertNotIn('"' + key + '"', json.dumps(result))
        result = self.app.operations.cards({'page': 999})
        self.assertEqual(result['total'], 601)
        self.assertEqual(result['page'], 25)
        self.assertEqual(self.app.operations.cards({'scope': 'available'})['total'], 600)
        self.assertEqual(self.app.operations.cards({'query': "' OR 1=1 --"})['total'], 0)

    def test_login_diagnostics_retention_and_unknown_user(self):
        with self.app.ledger.connect() as db:
            db.execute(
                'INSERT INTO login_events(username,outcome,created) VALUES(?,?,?)',
                ('card_owner', 'wrong_password', int(time.time()) - 8 * 86400),
            )
        self.app.operations.login_event('card_owner', 'success')
        self.app.operations.login_event('not_registered', 'unknown_user')
        result = self.app.operations.login_diagnosis({'username': 'CARD_OWNER'})
        self.assertEqual(result['account']['id'], self.uid)
        self.assertEqual([e['outcome'] for e in result['events']], ['success'])
        result = self.app.operations.login_diagnosis({'username': 'not_registered'})
        self.assertIsNone(result['account'])
        self.assertEqual(result['events'][0]['outcome'], 'unknown_user')
        for key in ('password', 'digest', 'ip', 'agent'):
            self.assertNotIn('"' + key + '"', json.dumps(result))

    def test_full_rotation_preserves_entitlement_and_retries(self):
        with self.app.ledger.connect() as db:
            before = dict(db.execute('SELECT * FROM members WHERE id=?', (self.uid,)).fetchone())
        self.app.features.rotate(self.uid, credentials=True)
        with self.app.ledger.connect() as db:
            after = dict(db.execute('SELECT * FROM members WHERE id=?', (self.uid,)).fetchone())
        for k in ('quota', 'expires', 'panel_email'):
            self.assertEqual(before[k], after[k])
        for k in ('sub_id', 'panel_auth'):
            self.assertNotEqual(before[k], after[k])
        self.assertEqual(after['previous_panel_auth'], before['panel_auth'])
        with self.assertRaises(DomainError):
            self.app.features.rotate(self.uid, credentials=True)
        self.assertTrue(self.app.ledger.sync_member(self.uid, self.panel))
        with self.app.ledger.connect() as db:
            self.assertIsNone(
                db.execute(
                    'SELECT previous_panel_auth FROM members WHERE id=?', (self.uid,)
                ).fetchone()[0]
            )

    def test_backup_restores_copy_without_changing_live_records(self):
        result = backup_run(self.root)
        self.assertTrue(result['restore_verified'])
        self.assertEqual(result['counts']['accounts'], 1)
        self.assertTrue((self.root / 'backups' / 'verification.json').exists())
        self.assertFalse(list((self.root / 'backups').glob('restore-check-*')))
        self.assertTrue(self.app.operations.readiness()['backup']['restore_verified'])

    def test_probe_requires_expected_host_and_certificate_pin(self):
        uri = 'hysteria2://test@161.33.217.26:8443?sni=test.example&pinSHA256=' + 'a' * 64
        nodes = {
            ('161.33.217.26', 8443): '日本',
            ('192.9.148.252', 8443): '美国',
            ('140.245.88.56', 8443): '日本 02',
            ('168.138.190.68', 8443): '新加坡 02',
        }
        result = outbound(uri, nodes)
        self.assertFalse(result['streamSettings']['tlsSettings']['allowInsecure'])
        for host in ('192.9.148.252', '140.245.88.56', '168.138.190.68'):
            self.assertEqual(
                outbound(uri.replace('161.33.217.26', host), nodes)['settings']['address'], host
            )
        for bad in [
            uri.replace('161.33.217.26', '127.0.0.1'),
            uri.replace('8443', '22'),
            uri.split('&pin')[0],
        ]:
            with self.assertRaises(ValueError):
                outbound(bad, nodes)

    def test_panel_rotation_accepts_only_owned_previous_auth(self):
        panel = Panel(
            {'panel_url': 'https://example.invalid', 'panel_token': 'test', 'inbounds': [1, 2, 3]}
        )
        member = {
            'panel_email': 'test',
            'panel_auth': 'new-auth',
            'previous_panel_auth': 'old-auth',
            'sub_id': 'new',
            'previous_sub_id': 'old',
            'quota': 1024,
            'expires': 2000000000,
            'disabled': 0,
        }
        current = {
            'client': {
                'subId': 'old',
                'auth': 'old-auth',
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
        self.assertEqual(current['client']['auth'], 'new-auth')
        current['client']['auth'] = 'stranger'
        with self.assertRaises(RuntimeError):
            panel.apply(member)
