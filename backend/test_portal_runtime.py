"""Open browser tabs must survive deployment without trusting arbitrary proxies."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    'portal_runtime', Path(__file__).resolve().parents[1] / 'deploy' / 'portal_runtime.py'
)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class PortalRuntimeTests(unittest.TestCase):
    def test_assets_survive_and_expire_without_overwriting_current_build(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / 'old', Path(directory) / 'new'
            for release in (old, new):
                (release / 'public/assets').mkdir(parents=True)
            for name in ('previous.js', 'expired.js', 'current.js'):
                (old / 'public/assets' / name).write_text('old')
            (new / 'public/assets/current.js').write_text('new')
            os.utime(old / 'public/assets/expired.js', (1, 1))
            runtime.retain_assets(old, new)
            self.assertEqual((new / 'public/assets/previous.js').read_text(), 'old')
            self.assertEqual((new / 'public/assets/current.js').read_text(), 'new')
            self.assertFalse((new / 'public/assets/expired.js').exists())

    def test_proxy_trust_does_not_include_arbitrary_peers(self):
        import ipaddress
        networks = [ipaddress.ip_network(value) for value in runtime.CLOUDFLARE_NETWORKS]
        for address in ('127.0.0.1', '8.8.8.8', '::1'):
            self.assertFalse(any(ipaddress.ip_address(address) in net for net in networks))
        self.assertIn('real_ip_header CF-Connecting-IP;', runtime.trusted_proxy_config())
