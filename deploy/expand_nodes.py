"""Run on Noether. Back up, divide tenancy quotas, extend existing subscriptions.

Never resets traffic, changes credentials, or grants extra customer allowance.
The 9 TB limit covers managed VPN counters, not the OCI account bill.
"""
import json
raise SystemExit('Retired one-time migration. Use deploy/node_manager.py instead.')
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, '/opt/jamie-portal/current/backend')
from panel import Panel

os.umask(0o077)
backup = Path('/root/codex-backups') / ('node-expansion-' + str(int(time.time())))
backup.mkdir(mode=0o700)
config_path = Path('/etc/jamie-portal.json')
config = json.loads(config_path.read_text())
panel = Panel(config)
adapter = Path('/opt/xui-clash/clash-subscription.py')
shutil.copy2(config_path, backup / 'portal-config.json')
shutil.copy2(adapter, backup / 'clash-subscription.py')
for source, name in [('/etc/x-ui/x-ui.db', 'panel.db'), (config['database'], 'portal.db')]:
    with sqlite3.connect(source) as src, sqlite3.connect(backup / name) as dst:
        src.backup(dst)

expected = {4: 'in-sanjose-hy2', 5: 'in-tokyobackup-hy2', 6: 'in-singaporebackup-hy2'}
inbounds = {r['id']: r for r in panel.request('inbounds/list')}
nodes = {r['id']: r for r in panel.request('nodes/list')}
for ident, tag in expected.items():
    assert inbounds[ident]['tag'] == tag and inbounds[ident]['enable']
    assert nodes[inbounds[ident]['nodeId']]['status'] == 'online'

# Fixed slices of one shared 9 TB budget; no automatic counter reset.
for ident, limit in {1: 8000000000000, 2: 8000000000000,
                     4: 9000000000000, 5: 1000000000000, 6: 1000000000000}.items():
    current = panel.request('inbounds/get/' + str(ident))
    assert current['up'] + current['down'] < limit
    if current['total'] == limit:
        continue
    before = {k: current[k] for k in ('up', 'down', 'lastTrafficResetTime')}
    current.update(total=limit, trafficReset='never')
    for key in ('settings', 'streamSettings', 'sniffing'):
        if isinstance(current[key], dict):
            current[key] = json.dumps(current[key])
    panel.request('inbounds/update/' + str(ident), current)
    after = panel.request('inbounds/get/' + str(ident))
    assert after['total'] == limit and after['trafficReset'] == 'never'
    assert after['up'] >= before['up'] and after['down'] >= before['down']
    assert after['lastTrafficResetTime'] == before['lastTrafficResetTime']

names = {
    '161.33.217.26': '🇯🇵 日本 · 东京 01', '168.107.64.69': '🇸🇬 新加坡 01',
    '149.118.144.221': '🇲🇾 马来西亚 · 柔佛', '192.9.148.252': '🇺🇸 美国 · 圣何塞',
    '140.245.88.56': '🇯🇵 日本 · 东京 02', '168.138.190.68': '🇸🇬 新加坡 02',
}
original = adapter.read_text()
updated, count = re.subn(r'REGIONS = \{.*?\}', 'REGIONS = ' + repr(names), original, count=1, flags=re.S)
assert count == 1
compile(updated, str(adapter), 'exec')
adapter.write_text(updated)
subprocess.run(['systemctl', 'restart', 'xui-clash'], check=True)

attached = 0
for record in panel.request('clients/list'):
    email = record['email']
    current = panel.get(email)
    if not {1, 2, 3}.issubset(current['inboundIds']):
        continue  # Preserve intentionally restricted panel-managed identities.
    missing = {4, 5, 6} - set(current['inboundIds'])
    if not missing:
        continue
    client = dict(current['client'])
    protected = {k: client[k] for k in ('auth', 'subId', 'totalGB', 'expiryTime', 'enable')}
    client.pop('id', None)
    if client.get('uuid'):
        client['id'] = client.pop('uuid')
    client.pop('allowedIPs', None)
    result = panel.request('clients/add', {'client': client, 'inboundIds': sorted(missing)})
    assert not result or not result.get('nodePending')
    after = panel.get(email)
    assert {1, 2, 3, 4, 5, 6}.issubset(after['inboundIds'])
    assert all(after['client'][k] == value for k, value in protected.items())
    attached += 1

config['inbounds'] = [1, 2, 3, 4, 5, 6]
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
print(json.dumps({'attached_accounts': attached, 'inbounds': config['inbounds'], 'backup': str(backup)}))
