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
from nodes import register as node_register


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
        if path.startswith('inbounds/update/'):
            inbound_id = int(path.split('/')[-1])
            self.inbounds = [copy.deepcopy(data) if row['id'] == inbound_id else row for row in self.inbounds]
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
    def exercise(self, success=True, retry=False, websocket=False, ipv6=False, split=False):
        panel = FakePanel()
        params = dict(server='8.8.4.4', port=21117, management_port=21116,
                      name='test-node', region='test', quota_group='test', quota_bytes=0,
                      group_limit=0, protocol='vless', pin='test', xray_pin='test')
        if websocket:
            params.update(transport='ws', ws_path='/node', listener_port=8080, port=443)
        if ipv6:
            params.update(server='2603:c021:8027:deee::1', management_server='8.8.4.4',
                          protocol='hysteria')
        catalog = {'version': 1, 'nodes': [], 'quota_groups': {}}
        if split:
            params.update(quota_bytes=4000, group_limit=8000, split_from_id=9, split_original_bytes=8000)
            catalog['quota_groups']['test'] = 8000
            catalog['nodes'].append(dict(server='8.8.4.4', port=8443, name='existing', region='test',
                                        quota_group='test', quota_bytes=8000, inbound_id=9, node_id=13,
                                        enabled=True, protocol='vless'))
            panel.inbounds.append(dict(id=9, nodeId=13, tag='existing', protocol='vless',
                                       port=8443, up=50, down=100, total=8000,
                                       settings={}, streamSettings={}, sniffing={}))
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
                    if ipv6:
                        parsed = node_register.urllib.parse.urlsplit(uri)
                        self.assertEqual(parsed.scheme, 'hysteria2')
                        self.assertEqual(parsed.hostname, params['server'])
                        self.assertEqual(parsed.port, params['port'])
                        self.assertEqual(parsed.username, client['auth'])
                    else:
                        self.assertTrue(uri.startswith('vless://' + client['id'] + '@'))
                        self.assertIn('type=ws' if websocket else 'pbk=public', uri)
                    if websocket:
                        self.assertIn('security=tls', uri)
                        self.assertEqual(panel.inbounds[-1]['port'], 8080)
                    seen.append(uri)
                    return {'ok': success}

                probe.side_effect = check
                if not success:
                    with self.assertRaisesRegex(RuntimeError, 'not published'):
                        node_register.run(params)
                    expected = copy.deepcopy(catalog)
                    if split:
                        expected['nodes'][0]['quota_bytes'] = 4000
                    self.assertEqual(json.loads(live.read_text()), expected)
                    self.assertEqual(panel.attached, [])
                else:
                    node_register.run(params)
                    before = copy.deepcopy(panel.inbounds)
                    if retry:
                        node_register.run(params)
                        self.assertEqual(panel.inbounds, before)
                    row = json.loads(live.read_text())['nodes'][-1]
                    self.assertEqual((row['protocol'], row['inbound_id']), (params['protocol'], 13))
                self.assertTrue(seen)
                self.assertEqual(panel.clients, [])
                if split:
                    donor = next(i for i in panel.inbounds if i['id'] == 9)
                    self.assertEqual((donor['total'], donor['up'], donor['down']), (4000, 50, 100))
                    self.assertEqual(sum(n['quota_bytes'] for n in json.loads(live.read_text())['nodes']),
                                     8000 if success else 4000)

    def test_new_tcp_node_is_probed_with_same_uuid_before_publication(self):
        self.exercise()

    def test_failed_tcp_probe_never_publishes_and_removes_temporary_identity(self):
        self.exercise(success=False)

    def test_retry_preserves_inbound_credentials_and_counters(self):
        self.exercise(retry=True)

    def test_websocket_external_tls_port_and_retry(self):
        self.exercise(retry=True, websocket=True)

    def test_failed_websocket_probe_is_not_published(self):
        self.exercise(success=False, websocket=True)

    def test_ipv6_hy2_probe_uses_valid_bracketed_uri(self):
        self.exercise(ipv6=True, retry=True)

    def test_added_protocol_splits_cap_once_and_preserves_counters_on_retry(self):
        self.exercise(ipv6=True, split=True, retry=True)

    def test_failed_added_protocol_keeps_reserved_cap_without_publishing(self):
        self.exercise(ipv6=True, split=True, success=False)
