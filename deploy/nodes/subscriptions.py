"""Enable IPv6 endpoints in the installed adapter without replacing routing rules."""

import ast
import json
from pathlib import Path
import shutil
import subprocess
import time


def upgrade(source):
    lines = source.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if "'mode': 'rule'" in line and "'ipv6': False" in line:
            lines[index] = line.replace("'ipv6': False", "'ipv6': any(':' in p['server'] for p in proxies)")
    changed = ''.join(lines)
    if "'ipv6 = false'" in changed:
        if 'def shadowrocket_config(' not in changed or '    _, region_of = collect_proxies(raw)' not in changed:
            raise RuntimeError('Unknown Shadowrocket adapter; refusing to overwrite live routing')
        changed = changed.replace('    _, region_of = collect_proxies(raw)', '    proxies, region_of = collect_proxies(raw)')
        changed = changed.replace("'ipv6 = false'", "'ipv6 = ' + str(any(':' in p['server'] for p in proxies)).lower()")
    if "'ipv6': any(':' in p['server'] for p in proxies)" not in changed:
        raise RuntimeError('Unknown adapter IPv6 configuration; no changes applied')
    ast.parse(changed)
    return changed


def main():
    path = Path('/opt/xui-clash/clash-subscription.py')
    source = path.read_text()
    updated = upgrade(source)
    if source == updated:
        print(json.dumps({'ipv6_ready': True, 'changed': False}))
        return
    backup = Path('/root/codex-backups') / ('node-ipv6-adapter-' + str(time.time_ns()))
    backup.mkdir(mode=0o700)
    shutil.copy2(path, backup / path.name)
    temporary = path.with_suffix('.py.tmp')
    temporary.write_text(updated)
    temporary.chmod(0o644)
    temporary.replace(path)
    try:
        subprocess.run(['systemctl', 'restart', 'xui-clash'], check=True, capture_output=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'xui-clash'], check=True)
    except subprocess.SubprocessError:
        shutil.copy2(backup / path.name, path)
        subprocess.run(['systemctl', 'restart', 'xui-clash'], check=False, capture_output=True)
        raise RuntimeError('Adapter restart failed; previous routing restored') from None
    print(json.dumps({'ipv6_ready': True, 'changed': True}))


if __name__ == '__main__':
    main()
