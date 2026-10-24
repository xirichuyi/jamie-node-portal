import re
import base64
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import yaml
from test_proxy_links import VLESS, WSS, WSS_HOST

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
        # Two visible text-only groups; the AI group runs hidden over AI-friendly regions.
        visible = [g['name'] for g in clash['proxy-groups'] if not g.get('hidden') and not g['name'].startswith(('剩余', '有效期', '到期', '已到期'))]
        self.assertEqual(visible, ['节点选择', '自动选择'])
        self.assertTrue(groups['AI 服务']['hidden'])
        self.assertEqual(groups['AI 服务']['proxies'], ['🇯🇵 日本 01', '🇺🇸 美国 01'])
        self.assertFalse(re.search('[\U0001F300-\U0001FAFF]', ''.join(groups)))
        used = {r.split(',')[1] for r in clash['rules'] if r.startswith('RULE-SET,')}
        self.assertEqual(used, set(clash['rule-providers']))
        for rule in clash['rules']:
            target = rule.split(',')[-2 if rule.endswith('no-resolve') else -1]
            self.assertTrue(target in groups or target in ('DIRECT', 'REJECT'), rule)
        self.assertEqual(clash['rules'][-1], 'MATCH,' + adapter.FINAL)
        self.assertNotIn('no-resolve', next(r for r in clash['rules'] if 'cn_ip' in r))
        self.assertIn('AI 服务 = url-test', rocket)
        self.assertIn('policy-regex-filter=美国|日本', rocket)
        self.assertIn('FINAL,' + adapter.FINAL, rocket)
        self.assertNotIn('secret', rocket)
        self.assertEqual(adapter.choose_format('/sub/x', {'format': ['shadowrocket-conf']}, '', ''), 'conf')

    def test_shadowrocket_gets_readable_rules_from_clash_link(self):
        rows = [{'server': '8.8.4.1', 'port': 8443, 'name': '🇯🇵 日本 01', 'region': '日本'}]
        raw = ('hy2://secret@8.8.4.1:8443?pinSHA256=' + 'a' * 64).encode()
        with patch.object(adapter, 'active_nodes', return_value=rows):
            rocket = yaml.safe_load(adapter.convert(raw, None, 'shadowrocket'))
        self.assertEqual(rocket['proxies'][0]['type'], 'hysteria2')
        self.assertNotIn('rule-providers', rocket)
        self.assertFalse([r for r in rocket['rules'] if '.mrs' in r or 'PROCESS-NAME' in r])
        self.assertTrue(any(r.startswith('RULE-SET,https://') for r in rocket['rules']))
        # blackmatrix7 *_Domain.list files are plain domain sets and only work as DOMAIN-SET.
        sets = [r for r in rocket['rules'] if '_Domain.list' in r]
        self.assertTrue(sets and all(r.startswith('DOMAIN-SET,') for r in sets))
        self.assertIn('DOMAIN-SET,' + adapter.ROCKET_RULES + 'ChinaMax/ChinaMax_Domain.list,DIRECT', rocket['rules'])
        self.assertEqual(rocket['rules'][-2:], ['GEOIP,CN,DIRECT', 'MATCH,' + adapter.FINAL])
        pick = adapter.choose_format
        self.assertEqual(pick('/sub/x', {'format': ['clash']}, 'Shadowrocket/2070 CFNetwork', ''), 'rocket-yaml')
        self.assertEqual(pick('/clash/x', {}, 'Shadowrocket/2070', ''), 'rocket-yaml')
        self.assertEqual(pick('/sub/x', {'format': ['clash']}, 'clash-verge/v2', ''), 'clash')
        self.assertEqual(pick('/sub/x', {}, 'Shadowrocket/2070', ''), 'base64')

    def test_unpublished_node_is_not_exposed(self):
        raw = ('hy2://secret@8.8.4.4:8443?pinSHA256=' + 'a' * 64).encode()
        with patch.object(adapter, 'active_nodes', return_value=[]):
            with self.assertRaises(ValueError):
                adapter.native_subscription(raw)
            with self.assertRaises(ValueError):
                adapter.convert(raw)

    def test_ipv6_hy2_enables_connections_and_preserves_bracketed_native_link(self):
        host = '2603:c021:8027:deee::1'
        rows = [{'server': host, 'port': 8443, 'name': 'IPv6 HY2'}]
        raw = ('hy2://secret@[' + host + ']:8443?pinSHA256=' + 'a' * 64).encode()
        with patch.object(adapter, 'active_nodes', return_value=rows):
            config = yaml.safe_load(adapter.convert(raw))
            native = base64.b64decode(adapter.native_subscription(raw)).decode()
            rocket = yaml.safe_load(adapter.convert(raw, client='shadowrocket'))
            rocket_profile = adapter.shadowrocket_config(raw, 'https://example.test/config').decode()
        self.assertTrue(config['ipv6'])
        self.assertFalse(config['dns']['ipv6'])
        self.assertEqual(config['proxies'][0]['server'], host)
        self.assertIn('@[' + host + ']:8443', native)
        self.assertFalse(config['proxies'][0]['skip-cert-verify'])
        self.assertTrue(rocket['ipv6'])
        self.assertIn('ipv6 = true', rocket_profile)

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

    def test_mixed_websocket_and_reality_preserve_transport_and_tls(self):
        rows = [{'server': WSS_HOST, 'port': 443, 'name': 'Instabox'},
                {'server': '8.8.4.4', 'port': 21227, 'name': 'Existing'}]
        raw = (WSS + '\n' + VLESS).encode()
        with patch.object(adapter, 'active_nodes', return_value=rows):
            config = yaml.safe_load(adapter.convert(raw))
            native = base64.b64decode(adapter.native_subscription(raw)).decode()
        ws, tcp = config['proxies']
        self.assertEqual(ws['network'], 'ws')
        self.assertEqual(ws['ws-opts'], {'path': '/node', 'headers': {'Host': WSS_HOST}})
        self.assertFalse(ws['skip-cert-verify'])
        self.assertNotIn('reality-opts', ws)
        self.assertIn('reality-opts', tcp)
        self.assertIn('security=tls', native)



if __name__ == '__main__':
    unittest.main()
