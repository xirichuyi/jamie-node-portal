"""One-time migration of the verified fleet; run on master before catalog rollout."""
import ast
import json
import os
from pathlib import Path
import shutil
import sys
import time
sys.path.insert(0, '/opt/jamie-portal/current/backend')
sys.path.insert(0, '/root/jamie-catalog-stage')
from node_catalog import validate_catalog
from panel import Panel

path = Path('/etc/jamie-node-catalog.json')
if path.exists():
    validate_catalog(json.loads(path.read_text()))
    print('Catalog already migrated; preserved existing inventory')
    raise SystemExit(0)
config_path = Path('/etc/jamie-portal.json')
config = json.loads(config_path.read_text())
panel = Panel(config)
tree = ast.parse(Path('/opt/xui-clash/clash-subscription.py').read_text())
names = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'REGIONS' for t in n.targets))
regions = {'161.33.217.26': '日本', '140.245.88.56': '日本',
           '168.107.64.69': '新加坡', '168.138.190.68': '新加坡',
           '149.118.144.221': '马来西亚', '192.9.148.252': '美国'}
data = {'version': 1, 'quota_groups': {r: 9000000000000 for r in set(regions.values())}, 'nodes': []}
for row in panel.request('inbounds/list'):
    if row['id'] not in config['inbounds']:
        continue
    stream = row['streamSettings']
    if isinstance(stream, str): stream = json.loads(stream)
    proxy = stream['externalProxy'][0]
    ip = proxy['dest']
    data['nodes'].append({'inbound_id': row['id'], 'node_id': row['nodeId'],
                         'server': ip, 'port': proxy['port'], 'name': names[ip],
                         'region': regions[ip], 'quota_group': regions[ip],
                         'quota_bytes': row['total'], 'enabled': True})
validate_catalog(data)
backup = Path('/root/codex-backups') / ('catalog-migration-' + str(int(time.time())))
backup.mkdir(mode=0o700)
shutil.copy2(config_path, backup / 'portal-config.json')
path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
path.chmod(0o644)  # Only public node metadata; no tokens or customer identities.
config['node_catalog'] = str(path)
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
print('Migrated catalog:', len(data['nodes']), 'nodes')
