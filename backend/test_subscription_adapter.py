import base64
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import yaml
from test_proxy_links import VLESS

spec = importlib.util.spec_from_file_location(
    'subscription_adapter',
    Path(__file__).resolve().parent.parent / 'deploy/subscription_adapter.py',
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class DynamicSubscriptionTests(unittest.TestCase):
    def setUp(self):
        settings = {
            'origin': 'https://portal.example.test',
            'panel_host': 'panel.example.test',
            'master_ip': '8.8.4.4',
            'probe_url': 'https://probe.example.test/204',
            'title': 'Test-Profile',
        }
        mock = patch.object(adapter, 'service_settings', return_value=settings)
        mock.start()
        self.addCleanup(mock.stop)

    def test_one_seven_and_twelve_nodes(self):
        for count in (1, 7, 12):
            rows = [
                {'server': f'8.8.4.{i + 1}', 'port': 8443, 'name': f'地区 {i + 1}'}
                for i in range(count)
            ]
            raw = '\n'.join(
                f'hy2://secret@{r["server"]}:8443?pinSHA256=' + 'a' * 64 for r in rows
            ).encode()
            with patch.object(adapter, 'active_nodes', return_value=rows):
                clash = yaml.safe_load(adapter.convert(raw))
                native = base64.b64decode(adapter.native_subscription(raw)).decode().splitlines()
            self.assertEqual(len(clash['proxies']), count)
            self.assertEqual(len(native), count)
            self.assertEqual([p['name'] for p in clash['proxies']], [r['name'] for r in rows])
            self.assertIn('DOMAIN,portal.example.test,DIRECT', clash['rules'])
            self.assertIn('IP-CIDR,8.8.4.4/32,DIRECT,no-resolve', clash['rules'])
            self.assertEqual(clash['proxy-groups'][1]['url'], 'https://probe.example.test/204')

    def test_policy_groups_rules_and_shadowrocket_profile(self):
        rows = [{'server': '8.8.4.1', 'port': 8443, 'name': '🇯🇵 日本 01', 'region': '日本'},
                {'server': '8.8.4.2', 'port': 8443, 'name': '🇩🇪 德国 01', 'region': '德国'},
                {'server': '8.8.4.3', 'port': 8443, 'name': '🇺🇸 美国 01', 'region': '美国'}]
        raw = '\n'.join(f'hy2://secret@{r["server"]}:8443?pinSHA256=' + 'a' * 64 for r in rows).encode()
        with patch.object(adapter, 'active_nodes', return_value=rows):
            text = adapter.convert(raw).decode()
            rocket = adapter.shadowrocket_config(raw, 'https://portal.example.test/sub/x').decode()
        clash = yaml.safe_load(text)
        self.assertNotIn('&id', text)
        groups = {g['name']: g for g in clash['proxy-groups']}
        # AI prefers US/Japan regions; region groups only hold their own nodes.
        self.assertEqual(groups[adapter.AI]['proxies'][:2], ['🇺🇸 美国节点', '🇯🇵 日本节点'])
        self.assertEqual(groups['🇩🇪 德国节点']['proxies'], ['🇩🇪 德国 01'])
        used = {r.split(',')[1] for r in clash['rules'] if r.startswith('RULE-SET,')}
        self.assertEqual(used, set(clash['rule-providers']))
        for rule in clash['rules']:
            target = rule.split(',')[-2 if rule.endswith('no-resolve') else -1]
            self.assertTrue(target in groups or target in ('DIRECT', 'REJECT'), rule)
        self.assertEqual(clash['rules'][-1], 'MATCH,' + adapter.FINAL)
        self.assertNotIn('no-resolve', next(r for r in clash['rules'] if 'cn_ip' in r))
        self.assertIn('🇺🇸 美国节点 = url-test', rocket)
        self.assertIn('policy-regex-filter=德国', rocket)
        self.assertIn('FINAL,' + adapter.FINAL, rocket)
        self.assertNotIn('secret', rocket)
        self.assertEqual(adapter.choose_format('/sub/x', {'format': ['shadowrocket-conf']}, '', ''), 'conf')

    def test_unpublished_node_is_not_exposed(self):
        raw = ('hy2://secret@8.8.4.4:8443?pinSHA256=' + 'a' * 64).encode()
        with patch.object(adapter, 'active_nodes', return_value=[]):
            with self.assertRaises(ValueError):
                adapter.native_subscription(raw)
            with self.assertRaises(ValueError):
                adapter.convert(raw)

    def test_mixed_hy2_and_reality_subscriptions(self):
        rows = [{'server': '8.8.4.4', 'port': 8443, 'name': 'UDP node'},
                {'server': '8.8.4.4', 'port': 21227, 'name': 'TCP node'}]
        raw = ('hy2://secret@8.8.4.4:8443?pinSHA256=' + 'a' * 64 + '\n' + VLESS).encode()
        with patch.object(adapter, 'active_nodes', return_value=rows):
            clash = yaml.safe_load(adapter.convert(raw))
            native = base64.b64decode(adapter.native_subscription(raw)).decode()
        tcp = clash['proxies'][1]
        self.assertEqual(tcp['type'], 'vless')
        self.assertTrue(tcp['tls'])
        self.assertFalse(tcp['skip-cert-verify'])
        self.assertEqual(tcp['reality-opts']['public-key'], 'a' * 43)
        self.assertEqual(tcp['servername'], 'www.example.com')
        self.assertIn('vless://', native)

    def test_unpublished_transport_change_does_not_break_other_nodes(self):
        raw = ('hy2://secret@8.8.4.4:8443?pinSHA256=' + 'a' * 64 + '\n' + VLESS).encode()
        with patch.object(adapter, 'active_nodes', return_value=[{'server': '8.8.4.4', 'port': 8443, 'name': 'UDP node'}]):
            self.assertEqual(len(yaml.safe_load(adapter.convert(raw))['proxies']), 1)


if __name__ == '__main__':
    unittest.main()
