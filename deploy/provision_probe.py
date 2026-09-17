"""Run as root on Noether after deployment. Dedicated 1 GiB monitor identity."""
import json
import os
from pathlib import Path
import pwd
import secrets
import sys
import time
sys.path.insert(0,'/opt/jamie-portal/current/backend')
from panel import Panel

os.umask(0o077)
root=Path('/var/lib/jamie-portal');path=root/'probe-identity.json'
panel=Panel(json.loads(Path('/etc/jamie-portal.json').read_text()))
if path.exists():identity=json.loads(path.read_text())
else:
    if any(c['email']=='jamie_health_probe' for c in panel.request('clients/list')):
        raise SystemExit('Existing probe identity without local ownership proof; no changes made')
    identity={'email':'jamie_health_probe','auth':secrets.token_hex(24),'sub_id':secrets.token_hex(24)}
    path.write_text(json.dumps(identity));u=pwd.getpwnam('jamie-portal');os.chown(path,u.pw_uid,u.pw_gid)
rows=panel.request('clients/list')
if not any(c['email']==identity['email'] for c in rows):
    panel.request('clients/add',{'client':{'email':identity['email'],'auth':identity['auth'],'subId':identity['sub_id'],
       'enable':True,'totalGB':1024**3,'expiryTime':(int(time.time())+365*86400)*1000,
       'group':'Monitoring','trafficReset':'never','trafficResetDay':1,'limitIp':0,'tgId':0},'inboundIds':[1,2,3]})
current=panel.get(identity['email'])
if current['client']['auth']!=identity['auth'] or current['client']['subId']!=identity['sub_id']:
    raise SystemExit('Probe ownership mismatch')
print('Dedicated monitoring identity verified; no customer credentials changed')
