"""Run on Noether as root. Preserve subscription locations and panel vhost."""
import datetime
import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import urllib.request

def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout

stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
source = Path(__file__).resolve().parent.parent
backup = Path('/root/codex-backups') / ('jamie-portal-' + stamp)
backup.mkdir(mode=0o700, parents=True)
nginx = Path('/etc/nginx/conf.d/jamie-domains.conf')
original = nginx.read_text()
shutil.copy2(nginx, backup / 'jamie-domains.conf')
try:
    pwd.getpwnam('jamie-portal')
except KeyError:
    run('useradd','--system','--home-dir','/var/lib/jamie-portal','--shell','/usr/sbin/nologin','jamie-portal')
uid = pwd.getpwnam('jamie-portal').pw_uid
gid = grp.getgrnam('jamie-portal').gr_gid
state = Path('/var/lib/jamie-portal')
state.mkdir(mode=0o700, exist_ok=True)
os.chown(state,uid,gid)
root = Path('/opt/jamie-portal')
release = root / 'releases' / stamp
release.mkdir(parents=True)
shutil.copytree(source / 'backend',release / 'backend',ignore=shutil.ignore_patterns('__pycache__','test_*.py'))
shutil.copytree(source / 'public',release / 'public')
for item in release.rglob('*'):
    item.chmod(0o755 if item.is_dir() else 0o644)
current = root / 'current'
previous = str(current.resolve()) if current.exists() else None
if previous:
    # Backup using the OLD running version before the new additive schema starts.
    run('systemctl','start','jamie-portal-backup.service')
    (backup/'previous-release.txt').write_text(previous)
candidate = root / ('current-' + stamp)
candidate.symlink_to(release)
candidate.replace(current)
for name in ('jamie-portal.service','jamie-portal-backup.service','jamie-portal-backup.timer','jamie-portal-probe.service','jamie-portal-probe.timer'):
    dest=Path('/etc/systemd/system')/name
    if dest.exists():
        shutil.copy2(dest,backup/name)
    shutil.copy2(source/'deploy'/name,dest)
run('systemctl','daemon-reload')
run('systemctl','enable','--now','jamie-portal.service')
run('systemctl','restart','jamie-portal.service')
import time
for attempt in range(20):
    try:
        with urllib.request.urlopen('http://127.0.0.1:18766/api/health',timeout=2) as response:
            assert json.load(response)['ok']
        break
    except Exception:
        time.sleep(0.5)
else:
    if previous:
        rollback = root / ('rollback-' + stamp)
        rollback.symlink_to(previous)
        rollback.replace(current)
        run('systemctl','restart','jamie-portal.service')
    raise SystemExit('Portal health failed; nginx unchanged. See systemd journal.')
adapter = Path('/opt/xui-clash/clash-subscription.py')
if (source / 'deploy/subscription_adapter.py').exists() and adapter.exists():
    shutil.copy2(adapter, backup / 'subscription_adapter.py')
    candidate_adapter = source / 'deploy/subscription_adapter.py'
    compile(candidate_adapter.read_text(), str(candidate_adapter), 'exec')
    try:
        shutil.copyfile(candidate_adapter, adapter)
        run('systemctl', 'restart', 'xui-clash')
        run('systemctl', 'is-active', 'xui-clash')
    except Exception:
        shutil.copyfile(backup / 'subscription_adapter.py', adapter)
        if previous:
            rollback = root / ('rollback-adapter-' + stamp)
            rollback.symlink_to(previous)
            rollback.replace(current)
            run('systemctl', 'restart', 'jamie-portal')
        run('systemctl', 'restart', 'xui-clash')
        raise
old = '''    location = / {
        default_type text/plain;
        return 200 "Jamie-Node: use your personal subscription URL.\\n";
    }
    location / { return 404; }'''
new = '''    # Jamie-Node portal: subscriptions above retain their existing adapter.
    root /opt/jamie-portal/current/public;
    client_max_body_size 16k;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;
    add_header X-Frame-Options DENY always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'" always;
    location ^~ /api/ {
        limit_req zone=jamie_portal_api burst=20 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:18766;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Host $host;
        proxy_read_timeout 30s;
        proxy_connect_timeout 3s;
        proxy_buffering off;
    }
    location /assets/ { try_files $uri =404; }
    location / {
        try_files $uri /index.html;
    }'''
if old in original:
    updated = 'limit_req_zone $binary_remote_addr zone=jamie_portal_api:1m rate=5r/s;\n' + original.replace(old,new,1)
elif '# Jamie-Node portal:' in original:
    updated = original
else:
    raise SystemExit('Unexpected nginx configuration; left unchanged')
nginx.write_text(updated)
try:
    run('nginx','-t')
    run('systemctl','reload','nginx')
except Exception:
    nginx.write_text(original)
    run('nginx','-t')
    run('systemctl','reload','nginx')
    raise
run('systemctl','enable','--now','jamie-portal-backup.timer')
run('systemctl','start','jamie-portal-backup.service')
print(json.dumps({'release':str(release),'backup':str(backup),'previous':previous,'status':'installed'}))
