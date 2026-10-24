"""Unified node tool InstaBox backend, using the official platform API.

Use INSTABOX_API_KEY in the environment. Never creates machines or changes billing.
The normal node registration helper probes before publishing and preserves counters.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent


def api(path, data=None, method=None, timeout=650):
    headers = {'X-API-Key': os.environ['INSTABOX_API_KEY'], 'Content-Type': 'application/json'}
    if data is not None and not path.endswith('/exec'):
        headers['Idempotency-Key'] = str(uuid.uuid4())
    request = urllib.request.Request('https://api.instabox.sh/v1/' + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response) if response.status != 204 else None


def run(machine, script, timeout=600):
    encoded = base64.b64encode(script.encode()).decode()
    result = api('machines/' + machine['id'] + '/exec',
                 {'cmd': 'printf %s ' + encoded + ' | base64 -d | sudo bash', 'timeoutSeconds': timeout})
    if result.get('exitCode') != 0:
        # Commands can carry credentials. Do not print raw command output on failure.
        raise RuntimeError(machine['name'] + ': remote step failed; inspect private installation log')
    return result['stdout']


def put(path, data, mode='600'):
    encoded = base64.b64encode(data.encode()).decode()
    return f'printf %s {encoded} | base64 -d > {shlex.quote(path)}\nchmod {mode} {shlex.quote(path)}\n'


def prepare(machine, master_ip):
    state = run(machine, 'test -f /etc/x-ui/install-result.env && echo ready || echo fresh').strip()
    if state == 'fresh':
        script = ('set -euo pipefail\nexport PATH=/usr/sbin:/usr/bin:/sbin:/bin\n'
                  'test ! -e /usr/local/x-ui\n')
        script += (ROOT / 'prepare_small_node.sh').read_text().replace(
            'ip="$1"', 'ip="' + master_ip + '"').replace('port="$2"', 'port=48180').replace(
            'master_ip="$3"', 'master_ip="' + master_ip + '"')
        run(machine, script)
        run(machine, 'touch /etc/x-ui/jamie-new-tcp-core')
    # The pin helper refuses to downgrade an existing unmarked install.
    run(machine, "python3 - <<'PYCORE'\n" + (ROOT / 'prepare_tcp_core.py').read_text() + '\nPYCORE\n')
    run(machine, "python3 - <<'PYSETTINGS'\n" + (ROOT / 'settings.py').read_text() + '\nPYSETTINGS\n')
    script = 'set -euo pipefail\numask 077\ninstall -d -m 700 /opt/jamie-instabox\n'
    script += put('/opt/jamie-instabox/api_gateway.py', (ROOT / 'instabox_api_gateway.py').read_text())
    script += put('/etc/systemd/system/jamie-instabox-api.service', '''[Unit]
Description=Authenticated InstaBox node API bridge
After=network-online.target x-ui.service
Wants=network-online.target
[Service]
ExecStart=/usr/bin/python3 /opt/jamie-instabox/api_gateway.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/opt/jamie-instabox
[Install]
WantedBy=multi-user.target
''', '644')
    script += ('systemctl daemon-reload\nsystemctl enable --now jamie-instabox-api\n'
               'systemctl restart jamie-instabox-api\nsystemctl is-active x-ui jamie-instabox-api\n')
    print(machine['name'] + ': ' + run(machine, script, 60).strip().replace('\n', ', '), flush=True)


def register(machine, master):
    # Credentials travel only over encrypted API and SSH stdin, never in argv/output.
    raw = run(machine, 'cat /etc/x-ui/install-result.env')
    env = {}
    for line in raw.splitlines():
        key, value = line.split('=', 1)
        env[key] = shlex.split(value)[0] if value else ''
    published = {}
    for port, label in ((48181, 'authenticated-node-api'), (8080, 'VLESS WebSocket')):
        result = api('machines/' + machine['id'] + '/ports', {'port': port, 'name': label})
        published[port] = urllib.parse.urlsplit(result['url']).hostname
    params = {
        'server': published[8080], 'port': 443, 'listener_port': 8080,
        'management_server': published[48181], 'management_port': 443,
        'name': machine['name'], 'region': '美国', 'quota_group': 'instabox-unlimited',
        'quota_bytes': 0, 'group_limit': 0, 'protocol': 'vless', 'transport': 'ws',
        'ws_path': '/jamie-' + hashlib.sha256(machine['id'].encode()).hexdigest()[:24],
        'base': '/' + env['XUI_WEB_BASE_PATH'].strip('/') + '/',
        'token': env['XUI_API_TOKEN'], 'pin': '', 'xray_pin': '',
    }
    command = 'python3 -c ' + shlex.quote((ROOT / 'register.py').read_text())
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', master, command],
                            input=json.dumps(params).encode(), capture_output=True, timeout=300)
    if result.returncode:
        raise RuntimeError(machine['name'] + ': registration failed, not published; inspect panel status')
    print(result.stdout.decode().strip(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'register'])
    parser.add_argument('--names', nargs='+', required=True)
    parser.add_argument('--master', default='Noether')
    parser.add_argument('--master-ip', default='138.2.82.194')
    args = parser.parse_args()
    listing = api('machines')
    if listing.get('nextCursor'):
        raise RuntimeError('Paginated account: explicitly resolve machines before proceeding')
    by_name = {m['name']: m for m in listing['machines']}
    for name in args.names:
        machine = by_name[name]
        if machine['state'] != 'running':
            raise RuntimeError(name + ' is not running')
        if args.action == 'prepare':
            prepare(machine, args.master_ip)
        else:
            register(machine, args.master)


if __name__ == '__main__':
    main()
