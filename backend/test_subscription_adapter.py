import base64
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import yaml

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

    def test_unpublished_node_is_not_exposed(self):
        raw = ('hy2://secret@8.8.4.4:8443?pinSHA256=' + 'a' * 64).encode()
        with patch.object(adapter, 'active_nodes', return_value=[]):
            with self.assertRaises(ValueError):
                adapter.native_subscription(raw)
            with self.assertRaises(ValueError):
                adapter.convert(raw)


if __name__ == '__main__':
    unittest.main()
