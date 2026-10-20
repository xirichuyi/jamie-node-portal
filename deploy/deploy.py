"""Local deployment. Never print credentials; keep handoff file owner-only."""
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parent.parent
os.umask(0o077)
def ssh(command, data=None):
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','Noether',command],
        input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    return p.stdout

archive=io.BytesIO()
public = ROOT / 'dist/portal'
if not (public / 'index.html').is_file():
    raise SystemExit('Frontend build missing. Run npm run verify before deployment.')
runtime_files = ['install.py', 'portal_runtime.py', 'subscription_adapter.py']
runtime_files += [p.name for p in (ROOT / 'deploy').glob('jamie-portal*.service')]
runtime_files += [p.name for p in (ROOT / 'deploy').glob('jamie-portal*.timer')]
with tarfile.open(fileobj=archive,mode='w:gz') as tar:
    tar.add(ROOT/'backend',arcname='backend',filter=lambda x:
            None if '__pycache__' in x.name or Path(x.name).name.startswith('test_') else x)
    tar.add(public,arcname='public')
    for name in sorted(runtime_files):
        tar.add(ROOT/'deploy'/name,arcname='deploy/'+name)
stage=ssh('mktemp -d /root/jamie-portal-stage.XXXXXX').decode().strip()
if not stage.startswith('/root/jamie-portal-stage.'):
    raise SystemExit('Unexpected staging directory')
ssh('tar xzf - -C '+shlex.quote(stage),archive.getvalue())
config_exists=ssh('test ! -e /etc/jamie-portal.json || echo exists').strip()
if not config_exists:
    # First install only: panel credentials come from a private local env file.
    env={}
    env_file=Path(os.environ.get('JAMIE_XUI_ENV','/Users/ml/.ssh/noether-3xui.env'))
    for line in env_file.read_text().splitlines():
        if '=' in line:
            k,v=line.split('=',1)
            env[k]=shlex.split(v)[0] if v else ''
    from urllib.parse import urlsplit
    path=urlsplit(env['XUI_ACCESS_URL']).path.rstrip('/')
    config={'database':'/var/lib/jamie-portal/portal.db','origin':'https://sub.chuyi.uk',
            'port':18766,'panel_url':'https://panel.chuyi.uk:48173'+path,
            'panel_token':env['XUI_API_TOKEN'],'node_catalog':'/etc/jamie-node-catalog.json'}
    # Credential provisioning over SSH stdin; never command arguments or output.
    ssh("umask 077; python3 -c 'import sys,pathlib; pathlib.Path(\"/etc/jamie-portal.json\").write_bytes(sys.stdin.buffer.read())'",json.dumps(config).encode())
ssh("getent passwd jamie-portal >/dev/null || useradd --system --home-dir /var/lib/jamie-portal --shell /usr/sbin/nologin jamie-portal")
ssh('chown root:jamie-portal /etc/jamie-portal.json && chmod 640 /etc/jamie-portal.json && install -d -o jamie-portal -g jamie-portal -m 700 /var/lib/jamie-portal')
# Bootstrap only when no administrator exists; first-login password change required.
check=ssh("python3 -c 'import sqlite3,pathlib; p=pathlib.Path(\"/var/lib/jamie-portal/portal.db\"); print(\"exists\" if p.exists() else \"new\")'").strip()
if check==b'new':
    result=ssh('python3 '+shlex.quote(stage+'/backend/server.py')+' --bootstrap-admin')
    credentials=json.loads(result)
    private=ROOT/'private-admin.json'
    private.write_text(json.dumps({'url':'https://sub.chuyi.uk','username':credentials['username'],'password':credentials['password']},ensure_ascii=False,indent=2))
    private.chmod(0o600)
    ssh('chown -R jamie-portal:jamie-portal /var/lib/jamie-portal')
print(ssh('python3 '+shlex.quote(stage+'/deploy/install.py')).decode())
ssh('rm -rf -- '+shlex.quote(stage))
print('Admin credentials, when newly created, saved privately to private-admin.json')
