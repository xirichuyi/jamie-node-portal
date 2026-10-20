"""Run on a freshly prepared node. Pin the core used by deployed Mihomo clients."""

import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

VERSION = '26.6.27'
ARCHES = {'aarch64': ('arm64-v8a', 'arm64'), 'x86_64': ('64', 'amd64')}
BIN_DIR = Path('/usr/local/x-ui/bin')
MARKER = Path('/etc/x-ui/jamie-new-tcp-core')
BACKUP_DIR = Path('/root/codex-backups/jamie-tcp-core')


def service_command(action):
    if Path('/etc/alpine-release').exists():
        return ['rc-service', 'x-ui', action]
    return ['systemctl', action, 'x-ui']


def main():
    archive_arch, binary_arch = ARCHES[platform.machine()]
    binary = BIN_DIR / ('xray-linux-' + binary_arch)
    marker = MARKER
    current = subprocess.run([str(binary), 'version'], capture_output=True, text=True, check=True)
    if current.stdout.startswith('Xray ' + VERSION + ' '):
        if marker.exists():
            subprocess.run(service_command('start'), check=True, capture_output=True)
        marker.unlink(missing_ok=True)
        return
    if not marker.exists():
        raise RuntimeError('Existing core differs; will not replace an existing installation')
    with tempfile.TemporaryDirectory(prefix='jamie-core-') as directory:
        archive = Path(directory) / 'xray.zip'
        url = f'https://github.com/XTLS/Xray-core/releases/download/v{VERSION}/Xray-linux-{archive_arch}.zip'
        with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as target:
            shutil.copyfileobj(response, target)
        with urllib.request.urlopen(url + '.dgst', timeout=30) as response:
            checksums = response.read().decode()
        expected = next(line.split('=', 1)[1].strip() for line in checksums.splitlines()
                        if line.startswith('SHA2-256='))
        with archive.open('rb') as source:
            actual = hashlib.file_digest(source, 'sha256').hexdigest()
        if actual != expected:
            raise RuntimeError('Official Xray SHA256 mismatch')
        pending = binary.with_suffix('.new')
        with zipfile.ZipFile(archive) as source, source.open('xray') as executable, pending.open('wb') as target:
            shutil.copyfileobj(executable, target)
        pending.chmod(0o755)
        backup = BACKUP_DIR
        backup.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not (backup / binary.name).exists():
            shutil.copy2(binary, backup / binary.name)
        subprocess.run(service_command('stop'), check=True, capture_output=True)
        try:
            os.replace(pending, binary)
        finally:
            subprocess.run(service_command('start'), check=True, capture_output=True)
        marker.unlink()
    print('Compatible Xray core installed; official SHA256 verified')


if __name__ == '__main__':
    main()
