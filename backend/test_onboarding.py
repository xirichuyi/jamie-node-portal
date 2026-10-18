"""Local onboarding safety and retry tests; no real SSH, packages, or production writes."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import onboard


FACTS = '''os=alpine
arch=aarch64
uid=0
memory_kib=24000000
memory_max=134217728
panel=ready
tcp=00000000:0016
tcp=00000000:52EA
udp=00000000:52EC
udp=00000000:52ED
managed_udp=21229
'''


class OnboardingTests(unittest.TestCase):
    def test_cgroup_limit_and_existing_listener_detection(self):
        facts = onboard.inspect(FACTS)
        self.assertEqual(facts['memory_mib'], 128)
        self.assertIn(21228, facts['udp'])
        self.assertEqual(onboard.choose_port([21228, 21229], {21228}), 21229)
        self.assertEqual(onboard.choose_port([21228, 21229], {21228, 21229}, 21229), 21229)
        with self.assertRaises(ValueError):
            onboard.choose_port([21228], {21228})
        with self.assertRaises(ValueError):
            onboard.choose_port([21228], set(), 21229)

    def test_unsupported_or_partial_installs_are_never_overwritten(self):
        for before, after in [('panel=ready', 'panel=partial'), ('uid=0', 'uid=1000'),
                              ('arch=aarch64', 'arch=armv7l'), ('os=alpine', 'os=unknown'),
                              ('134217728', '67108864')]:
            with self.subTest(after=after), self.assertRaises(ValueError):
                onboard.inspect(FACTS.replace(before, after))

    def test_port_ranges_reject_invalid_input(self):
        self.assertEqual(onboard.port_pool('21226-21227,21226'), [21226, 21227])
        for value in ('22', '65536', '5000-4000', '1024-65535', '1; echo bad', '1-2-3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                onboard.port_pool(value)

    def exercise(self, *, check=False, existing=True, retired=False, fail=False, facts=FACTS):
        catalog = {'service': {'master_ip': '8.8.8.8'}, 'nodes': []}
        if existing:
            catalog['nodes'].append(dict(server='158.101.142.111', port=21229,
                                         name='日本 03', region='日本', enabled=not retired,
                                         quota_group='limited', quota_bytes=1000))
        status = dict(published=True, subscription_present=True, catalog_observed=True,
                      sync_pending=0, sync_errors=0, connectivity_ok=False)
        commands, logins, registrations = [], [], []

        def call(_config, host, command, data=None):
            commands.append((host, command))
            if command == 'cat /etc/jamie-node-catalog.json':
                return json.dumps(catalog).encode()
            if command == 'sh -s':
                return facts.encode()
            if command.startswith('sed -n'):
                return b'21226'
            if command.startswith('python3 -c'):
                return json.dumps(status).encode()
            return b''

        def execute(command, **_kwargs):
            if command[-1] == 'true':
                logins.append(command[-2])
            return subprocess.CompletedProcess(command, 0)

        def register(options):
            registrations.append(options)
            if fail:
                raise RuntimeError('Node connectivity failed; not published')
            return {'ok': True}

        options = ['--host', '158.101.142.111', '--ssh-port', '21225', '--yes']
        if check:
            options.append('--check')
        if not existing:
            options += ['--name', '日本 03', '--region', '日本', '--tcp-ports', '21226-21227',
                        '--udp-ports', '21228-21229']
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(onboard.Path, 'home', return_value=Path(directory)), \
                 patch.object(onboard, 'call', side_effect=call), \
                 patch.object(onboard.subprocess, 'run', side_effect=execute), \
                 patch.object(onboard.node_manager, 'main', side_effect=register), \
                 contextlib.redirect_stdout(io.StringIO()):
                error = None
                try:
                    onboard.main(options)
                except RuntimeError as exc:
                    error = str(exc)
                profiles = [json.loads(p.read_text()) for p in Path(directory).rglob('*.json')]
        return commands, logins, registrations, profiles, error

    def test_check_is_read_only_and_does_not_save_a_profile(self):
        commands, _, registrations, profiles, error = self.exercise(check=True)
        self.assertIsNone(error)
        self.assertEqual(registrations, [])
        self.assertEqual(profiles, [])
        self.assertFalse(any('systemctl' in c or 'apk ' in c for _, c in commands))

    def test_published_node_is_not_registered_or_reinstalled_again(self):
        commands, _, registrations, profiles, error = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(registrations, [])
        self.assertFalse(any('apk ' in c for _, c in commands))
        self.assertEqual(profiles[0]['port'], 21229)
        self.assertNotIn('password', profiles[0])

    def test_retired_node_is_rejected_before_connecting_to_it(self):
        commands, logins, registrations, _, error = self.exercise(retired=True)
        self.assertIn('退役', error)
        self.assertEqual(logins, ['Noether'])
        self.assertEqual(registrations, [])
        self.assertFalse(any(c == 'sh -s' for _, c in commands))

    def test_another_process_cannot_be_claimed_as_the_managed_listener(self):
        _, _, registrations, profiles, error = self.exercise(facts=FACTS.replace('managed_udp=21229\n', ''))
        self.assertIn('被其他服务占用', error)
        self.assertEqual(registrations, [])
        self.assertEqual(profiles, [])

    def test_new_node_selects_free_ports_and_bootstraps_alpine(self):
        facts = FACTS.replace('panel=ready', 'panel=absent').replace('tcp=00000000:52EA\n', '')
        facts = facts.replace('udp=00000000:52ED\n', '').replace('managed_udp=21229\n', '')
        commands, _, registrations, _, error = self.exercise(existing=False, facts=facts)
        self.assertIsNone(error)
        self.assertIn('--prepare', registrations[0])
        self.assertIn('--unlimited', registrations[0])
        self.assertNotIn('--publish-unverified', registrations[0])
        self.assertEqual(registrations[0][registrations[0].index('--port') + 1], '21229')
        self.assertTrue(any('apk add' in c for _, c in commands))

    def test_failed_registration_preserves_parameters_and_does_not_claim_success(self):
        facts = FACTS.replace('udp=00000000:52ED\n', '')
        commands, _, registrations, profiles, error = self.exercise(existing=False, facts=facts, fail=True)
        self.assertIn('connectivity failed', error)
        self.assertNotIn('--prepare', registrations[0])
        self.assertEqual(profiles[0]['port'], 21229)
        self.assertFalse(any('systemctl' in c for _, c in commands))


if __name__ == '__main__':
    unittest.main()
