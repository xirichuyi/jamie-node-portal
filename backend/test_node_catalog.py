import copy
import json
from pathlib import Path
import tempfile
import unittest
from node_catalog import active_nodes, validate_catalog
from panel import Panel
from content import NodeMonitor
from entitlements import Ledger
from node_sync import enqueue_catalog


class CatalogTests(unittest.TestCase):
    def catalog(self):
        return {
            'version': 1,
            'quota_groups': {'account': 9000},
            'nodes': [
                {
                    'inbound_id': 31,
                    'node_id': 71,
                    'server': '8.8.4.4',
                    'port': 8443,
                    'name': '测试地区 01',
                    'region': '测试地区',
                    'quota_group': 'account',
                    'quota_bytes': 5000,
                    'enabled': True,
                }
            ],
        }

    def test_quota_and_unique_identity_validation(self):
        data = self.catalog()
        self.assertEqual(validate_catalog(data), data)
        other = copy.deepcopy(data['nodes'][0])
        other.update(inbound_id=32, node_id=72, server='1.1.1.1', name='测试地区 02')
        data['nodes'].append(other)
        with self.assertRaises(ValueError):
            validate_catalog(data)
        other['quota_bytes'] = 4000
        validate_catalog(data)
        other['name'] = data['nodes'][0]['name']
        with self.assertRaises(ValueError):
            validate_catalog(data)

    def test_private_endpoint_rejected(self):
        data = self.catalog()
        for address in ('127.0.0.1', '10.0.0.1', '169.254.169.254'):
            data['nodes'][0]['server'] = address
            with self.assertRaises(ValueError):
                validate_catalog(data)

    def test_catalog_changes_reload_without_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nodes.json'
            data = self.catalog()
            path.write_text(json.dumps(data))
            panel = Panel(
                {
                    'panel_url': 'https://example.invalid',
                    'panel_token': 'test',
                    'node_catalog': str(path),
                }
            )
            self.assertEqual(panel.inbounds, [31])
            monitor = NodeMonitor(panel, str(path))
            self.assertEqual(monitor.names, {31: '测试地区 01'})
            data['nodes'][0]['name'] = '新地区名称'
            path.write_text(json.dumps(data))
            monitor.load_names()
            self.assertEqual(monitor.names, {31: '新地区名称'})
            data['nodes'][0]['enabled'] = False
            path.write_text(json.dumps(data))
            self.assertEqual(panel.inbounds, [])
            self.assertEqual(active_nodes(path), [])
            path.write_text('{broken')
            with self.assertRaises(ValueError):
                _ = panel.inbounds

    def test_catalog_outbox_is_idempotent_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_text(json.dumps(self.catalog()))
            ledger = Ledger(str(Path(directory) / 'portal.db'))
            ledger.create_member('test')
            ledger.create_member('unfunded')
            with ledger.connect() as db:
                db.execute('UPDATE members SET quota=10 WHERE id=?', ('test',))
            self.assertEqual(enqueue_catalog(ledger, path), 1)
            self.assertEqual(enqueue_catalog(ledger, path), 0)
            reopened = Ledger(ledger.path)
            self.assertEqual(enqueue_catalog(reopened, path), 0)
            with ledger.connect() as db:
                member = dict(db.execute('SELECT * FROM members WHERE id=?', ('test',)).fetchone())
            self.assertEqual(member['quota'], 10)
            self.assertGreater(member['revision'], member['synced_revision'])
            with ledger.connect() as db:
                self.assertEqual(
                    db.execute('SELECT revision FROM members WHERE id=?', ('unfunded',)).fetchone()[
                        0
                    ],
                    0,
                )

    def test_zero_allowance_never_becomes_unlimited_panel_access(self):
        panel = Panel(
            {'panel_url': 'https://example.invalid', 'panel_token': 'test', 'inbounds': [31]}
        )
        saved = {}

        def request(path, payload=None):
            if path == 'clients/list':
                return []
            if path == 'clients/add':
                saved.update(payload)
                return {}
            if path.startswith('clients/get/'):
                return saved
            raise AssertionError(path)

        panel.request = request
        panel.apply(
            {
                'panel_email': 'unfunded',
                'panel_auth': 'test',
                'sub_id': 'test',
                'quota': 0,
                'expires': 2000000000,
                'disabled': False,
            }
        )
        self.assertFalse(saved['client']['enable'])


if __name__ == '__main__':
    unittest.main()
