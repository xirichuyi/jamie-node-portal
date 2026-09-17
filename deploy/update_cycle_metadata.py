"""Backed-up adapter integration: business quota/expiry, not enforcement cutoff."""

import subprocess

script = r'''
from pathlib import Path
from datetime import datetime, timezone
import shutil
import subprocess
path = Path('/opt/xui-clash/clash-subscription.py')
original = path.read_text()
anchor = "                usage = response.headers.get('subscription-userinfo')"
addition = """
                # Portal ledger owns package/cycle metadata; the panel enforces access.
                with urllib.request.urlopen('http://127.0.0.1:18766/internal/subscription-info/' + match[1], timeout=3) as info:
                    portal_usage = json.loads(info.read(4096)).get('usage')
                if portal_usage is not None:
                    usage = portal_usage"""
if '/internal/subscription-info/' not in original:
    assert original.count(anchor) == 1
    updated = original.replace(anchor, anchor + addition)
    compile(updated, str(path), 'exec')
    backup = path.with_name('clash-subscription.py.' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.bak')
    shutil.copy2(path, backup)
    path.write_text(updated)
    try:
        subprocess.run(['systemctl', 'restart', 'xui-clash'], check=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'xui-clash'], check=True)
    except Exception:
        shutil.copy2(backup, path)
        subprocess.run(['systemctl', 'restart', 'xui-clash'], check=True)
        raise
    print('Cycle metadata adapter updated; backup:', backup)
else:
    print('Cycle metadata already current')
'''
subprocess.run(
    ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', 'Noether', 'python3 -'],
    input=script,
    text=True,
    check=True,
)
