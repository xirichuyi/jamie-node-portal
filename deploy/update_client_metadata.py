"""Idempotent, backed-up metadata-only patch to the existing subscription adapter."""
import subprocess

script = r'''
from pathlib import Path
from datetime import datetime, timezone
import shutil
import subprocess
path = Path('/opt/xui-clash/clash-subscription.py')
original = path.read_text()
updated = original
if "'profile-web-page-url'" not in updated:
    anchor = "            self.send_header('profile-update-interval', '6')"
    assert updated.count(anchor) == 1
    updated = updated.replace(anchor, anchor + "\n            self.send_header('profile-web-page-url', 'https://sub.chuyi.uk/')\n            self.send_header('support-url', 'https://sub.chuyi.uk/#/help')")
if 'def do_HEAD(self):' not in updated:
    anchor = '    def do_GET(self):'
    assert updated.count(anchor) == 1
    updated = updated.replace(anchor, '    def do_HEAD(self):\n        self.do_GET()\n\n' + anchor)
    anchor = '            self.wfile.write(result)'
    assert updated.count(anchor) == 1
    updated = updated.replace(anchor, "            if self.command != 'HEAD':\n                self.wfile.write(result)")
compile(updated, str(path), 'exec')
if updated != original:
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
    print('Adapter metadata updated; backup:', backup)
else:
    print('Adapter metadata already current')
'''
subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', 'Noether', 'python3 -'], input=script, text=True, check=True)
