"""Registration exercises with fake panels: no network, real users or live databases."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import node_register


class FakePanel:
    def __init__(self):
        self.inbounds = [{
            'id': 1, 'nodeId': 1, 'tag': 'template', 'protocol': 'hysteria',
            'streamSettings': {'tlsSettings': {'settings': {}}},
            'sniffing': '{}'}]
        self.clients = []
        self.attached = []

    def request(self, path, data=None):
        if path == 'nodes/list':
            return [{'id': 13, 'address': '8.8.4.4', 'port': 21116}]
        if path == 'inbounds/list':
            return copy.deepcopy(self.inbounds)
        if path.startswith('inbounds/get/'):
            return copy.deepcopy(next(n for n in self.inbounds if n['id'] == int(path.split('/')[-1])))
        if path == 'inbounds/add':
            self.inbounds.append({**copy.deepcopy(data), 'id': 13})
            return None
        if path == 'clients/add':
            self.clients.append(data['client'])
            return None
        if path == 'clients/list':
            return copy.deepcopy(self.clients)
        if path.startswith('clients/del/'):
            self.clients = []
            return None
        raise AssertionError('Unexpected panel operation: ' + path)

    def get(self, _email):
        return {'client': {'auth': 'monitor-auth', 'subId': 'monitor-sub'}}

    def attach_existing(self, email, ids):
        self.attached.append((email, ids))


class RegistrationTests(unittest.TestCase):
    def exercise(self, success=True, retry=False):
        panel = FakePanel()
        params = dict(server='8.8.4.4', port=21117, management_port=21116,
                      name='test-node', region='test', quota_group='test', quota_bytes=0,
                      group_limit=0, protocol='vless', pin='test', xray_pin='test')
        catalog = {'version': 1, 'nodes': [], 'quota_groups': {}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / 'catalog.json'
            live.write_text(json.dumps(catalog))
            config = root / 'config.json'
            config.write_text('{}')
            monitor = root / 'monitor.json'
            monitor.write_text(json.dumps(dict(email='monitor', auth='monitor-auth', sub_id='monitor-sub')))
            with patch.object(node_register, 'CATALOG_PATH', str(live)), \
                 patch.object(node_register, 'CONFIG_PATH', str(config)), \
                 patch.object(node_register, 'MONITOR_PATH', str(monitor)), \
                 patch.object(node_register, 'BACKUP_ROOT', directory), \
                 patch.object(node_register, 'load_catalog', side_effect=lambda: json.loads(live.read_text())), \
                 patch.object(node_register, 'Panel', return_value=panel), \
                 patch.object(node_register.sqlite3, 'connect', return_value=MagicMock()), \
                 patch.object(node_register.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'PrivateKey: secret\nPassword: public\n')), \
                 patch.object(node_register, 'outbound', side_effect=lambda uri, _: uri), \
                 patch.object(node_register, 'test_outbound') as probe, \
                 patch.object(node_register.time, 'sleep'):
                seen = []

                def check(uri, *_args):
                    client = panel.clients[-1]
                    self.assertTrue(uri.startswith('vless://' + client['id'] + '@'))
                    self.assertIn('pbk=public', uri)
                    seen.append(uri)
                    return {'ok': success}

                probe.side_effect = check
                if not success:
                    with self.assertRaisesRegex(RuntimeError, 'not published'):
                        node_register.run(params)
                    self.assertEqual(json.loads(live.read_text()), catalog)
                    self.assertEqual(panel.attached, [])
                else:
                    node_register.run(params)
                    before = copy.deepcopy(panel.inbounds)
                    if retry:
                        node_register.run(params)
                        self.assertEqual(panel.inbounds, before)
                    row = json.loads(live.read_text())['nodes'][0]
                    self.assertEqual((row['protocol'], row['inbound_id']), ('vless', 13))
                self.assertTrue(seen)
                self.assertEqual(panel.clients, [])

    def test_new_tcp_node_is_probed_with_same_uuid_before_publication(self):
        self.exercise()

    def test_failed_tcp_probe_never_publishes_and_removes_temporary_identity(self):
        self.exercise(success=False)

    def test_retry_preserves_inbound_credentials_and_counters(self):
        self.exercise(retry=True)
