"""Target selection and adapter updates without live credentials or networking."""

import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
from nodes import client_probe, subscriptions


class ClientProbeTests(unittest.TestCase):
    def test_only_new_endpoint_is_tested_even_with_other_nodes_offline(self):
        target = '2603:c021:8027:deee::1'
        links = ['hy2://test@8.8.4.4:8443?pinSHA256=' + 'a' * 64,
                 f'hy2://test@[{target}]:8444?pinSHA256=' + 'b' * 64]
        response = MagicMock()
        response.__enter__.return_value.read.return_value = base64.b64encode('\n'.join(links).encode())
        def remote(command):
            if 'probe-identity' in command:
                return b'{"sub_id":"test"}'
            return json.dumps({'service': {'origin': 'https://example.test', 'probe_url': 'https://example.test/204'}}).encode()
        with patch.object(client_probe.urllib.request, 'urlopen', return_value=response), \
             patch.object(client_probe, 'test', return_value={'ok': True}) as check:
            result = client_probe.check_subscription(remote, {'ip': target, 'port': 8444, 'name': 'JP'})
        self.assertTrue(result['ok'])
        self.assertEqual(check.call_count, 1)
        self.assertEqual(check.call_args.args[0]['settings']['address'], target)

    def test_adapter_patch_preserves_dns_and_routing_and_is_idempotent(self):
        source = "def convert(proxies):\n return {'mode': 'rule', 'ipv6': False,\n 'dns': {'ipv6': False}, 'rules':['KEEP']}\n"
        changed = subscriptions.upgrade(source)
        self.assertIn("'dns': {'ipv6': False}", changed)
        self.assertIn("'rules':['KEEP']", changed)
        self.assertEqual(subscriptions.upgrade(changed), changed)
        with self.assertRaises(RuntimeError):
            subscriptions.upgrade('unknown_configuration = True')
