"""Core preparation must not downgrade live hosts or install unverified downloads."""

import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import prepare_tcp_core


class TcpCoreTests(unittest.TestCase):
    def test_existing_unmarked_installation_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(prepare_tcp_core, 'MARKER', Path(directory) / 'absent'), \
             patch.object(prepare_tcp_core.platform, 'machine', return_value='aarch64'), \
             patch.object(prepare_tcp_core.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Xray 26.9.9 ')) as run, \
             patch.object(prepare_tcp_core.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(RuntimeError, 'will not replace'):
                prepare_tcp_core.main()
            network.assert_not_called()
            self.assertEqual(run.call_count, 1)

    def test_checksum_failure_keeps_original_binary_and_retry_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'marker'
            marker.touch()
            binary = root / 'xray-linux-arm64'
            binary.write_bytes(b'old binary')
            with patch.object(prepare_tcp_core, 'MARKER', marker), \
                 patch.object(prepare_tcp_core, 'BIN_DIR', root), \
                 patch.object(prepare_tcp_core.platform, 'machine', return_value='aarch64'), \
                 patch.object(prepare_tcp_core.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Xray 26.9.9 ')) as run, \
                 patch.object(prepare_tcp_core.urllib.request, 'urlopen',
                              side_effect=[io.BytesIO(b'bad archive'), io.BytesIO(b'SHA2-256= incorrect')]):
                with self.assertRaisesRegex(RuntimeError, 'SHA256 mismatch'):
                    prepare_tcp_core.main()
                self.assertEqual(binary.read_bytes(), b'old binary')
                self.assertTrue(marker.exists())
                self.assertEqual(run.call_count, 1)
