import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from application import App
from panel import Panel, PartialSync
import test_node_catalog
from test_server import FakePanel


class PartialSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'catalog.json'
        self.catalog = test_node_catalog.CatalogTests().catalog()
        first = self.catalog['nodes'][0]
        first['quota_bytes'] = 4000
        second = dict(first, inbound_id=32, node_id=72, server='1.1.1.1', name='测试地区 02')
        self.catalog['nodes'].append(second)
        self.path.write_text(json.dumps(self.catalog))
        self.panel = Panel(
            {
                'panel_url': 'https://example.invalid',
                'panel_token': 'test',
                'node_catalog': str(self.path),
            }
        )
        self.member = dict(
            panel_email='owned',
            panel_auth='test',
            sub_id='test',
            quota=1000,
            expires=2000000000,
            disabled=0,
        )
        self.current = {
            'client': {
                'email': 'owned',
                'auth': 'test',
                'subId': 'test',
                'totalGB': 1000,
                'expiryTime': 2000000000000,
                'enable': True,
                'trafficReset': 'never',
            },
            'inboundIds': [31, 32],
        }
        self.nodes = [
            dict(
                id=n,
                enable=True,
                status='online',
                xrayState='running',
                configDirty=False,
                lastHeartbeat=int(time.time()),
            )
            for n in (71, 72)
        ]
        self.calls = []
        self.panel.request = self.request

    def request(self, path, payload=None):
        self.calls.append((path, payload))
        if path == 'clients/list':
            return [{'email': 'owned'}]
        if path.startswith('clients/get/'):
            return copy.deepcopy(self.current)
        if path.startswith('clients/update/'):
            self.current['client'].update(payload)
            return {'nodePending': True}
        if path == 'nodes/list':
            return self.nodes
        raise AssertionError(path)

    def test_offline_node_does_not_block_confirmed_nodes(self):
        self.nodes[1]['status'] = 'offline'
        with self.assertRaises(PartialSync) as result:
            self.panel.apply(self.member)
        self.assertTrue(result.exception.usable)
        self.assertFalse(any(payload for _, payload in self.calls))  # no redundant dirty writes
        self.nodes[1]['status'] = 'online'
        self.panel.apply(self.member)

    def test_unconfirmed_stale_or_disabled_nodes_cannot_open_subscription(self):
        self.nodes[1]['status'] = 'offline'
        for field, value in [
            ('configDirty', True),
            ('lastHeartbeat', 0),
            ('enable', False),
            ('xrayState', 'stopped'),
        ]:
            old = self.nodes[0][field]
            self.nodes[0][field] = value
            with self.assertRaises(PartialSync) as result:
                self.panel.apply(self.member)
            self.assertFalse(result.exception.usable)
            self.nodes[0][field] = old

    def test_retired_node_is_not_updated_or_required(self):
        self.catalog['nodes'][1]['enabled'] = False
        self.path.write_text(json.dumps(self.catalog))
        self.nodes[1]['status'] = 'offline'
        self.member['quota'] = 2000
        self.panel.apply(self.member)
        writes = [path for path, payload in self.calls if payload]
        self.assertEqual(writes, ['clients/update/owned?inboundIds=31'])

    def test_disabled_or_identity_mismatch_never_ready(self):
        self.nodes[1]['status'] = 'offline'
        self.member['disabled'] = 1
        with self.assertRaises(PartialSync) as result:
            self.panel.apply(self.member)
        self.assertFalse(result.exception.usable)
        self.current['client']['auth'] = 'foreign'
        with self.assertRaisesRegex(RuntimeError, 'does not belong'):
            self.panel.apply(self.member)

    def test_delete_retry_waits_for_active_nodes_even_after_master_removal(self):
        request = self.panel.request
        self.panel.request = lambda path, payload=None: (
            [] if path == 'clients/list' else request(path, payload)
        )
        self.nodes[1]['status'] = 'offline'
        with self.assertRaises(PartialSync):
            self.panel.remove(self.member)
        self.catalog['nodes'][1]['enabled'] = False
        self.path.write_text(json.dumps(self.catalog))
        self.panel.remove(self.member)

    def test_partial_ready_keeps_retry_and_rotation_barrier(self):
        fake = FakePanel()
        app = App(
            {'database': str(Path(self.temp.name) / 'app.db'), 'origin': 'https://example.invalid'},
            fake,
        )
        uid = app.register('partial', 'Test-password-1234')
        card = app.ledger.issue('admin', 'test', 1, 30, 1, 90)[0]['code']
        app.ledger.redeem(uid, card)
        fake.apply = Mock(side_effect=PartialSync(usable=True))
        self.assertFalse(app.ledger.sync_member(uid, fake))
        with app.ledger.connect() as db:
            account = dict(db.execute('SELECT * FROM accounts WHERE id=?', (uid,)).fetchone())
            member = dict(db.execute('SELECT * FROM members WHERE id=?', (uid,)).fetchone())
        self.assertEqual(member['synced_revision'], 0)
        self.assertEqual(member['ready_revision'], 1)
        self.assertIn(uid, app.ledger.pending())
        self.assertIsNotNone(app.overview(account)['subscription']['url'])
        with app.ledger.connect() as db:
            db.execute(
                'UPDATE members SET previous_sub_id=?,revision=revision+1 WHERE id=?', ('old', uid)
            )
        self.assertFalse(app.ledger.sync_member(uid, fake))
        self.assertIsNone(app.overview(account)['subscription']['url'])
        fake.apply = Mock()
        self.assertTrue(app.ledger.sync_member(uid, fake))
        self.assertIsNotNone(app.overview(account)['subscription']['url'])


if __name__ == '__main__':
    unittest.main()
