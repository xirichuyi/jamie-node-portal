"""Attach the prepared San Jose node without exposing node credentials."""
raise SystemExit('Retired one-time migration. Use deploy/node_manager.py instead.')
import base64
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path


def ssh(host, command, data=None):
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', host, command], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(host + ': ' + result.stderr.decode().splitlines()[-1])
    return result.stdout


targets = {
 'axi': ('SanJose', '192.9.148.252', 48177, 9000000000000),
 'Elur': ('TokyoBackup', '140.245.88.56', 48178, 1000000000000),
 'Hilbert': ('SingaporeBackup', '168.138.190.68', 48179, 1000000000000),
}
host = sys.argv[1] if len(sys.argv) > 1 else 'axi'
name, address, port, quota = targets[host]
settings = Path('/Users/ml/Work/3xui-ops/node-settings.py').read_bytes()
ssh(host, 'python3 -', settings)
env = {}
for line in ssh(host, 'cat /etc/x-ui/install-result.env').decode().splitlines():
    key, value = line.split('=', 1)
    env[key] = shlex.split(value)[0] if value else ''
der = ssh(host, 'openssl x509 -in /etc/x-ui/tls/node.crt -outform DER')
payload = {'token': env['XUI_API_TOKEN'], 'base': '/' + env['XUI_WEB_BASE_PATH'].strip('/') + '/',
           'pin': hashlib.sha256(der).hexdigest(), 'xray_pin': base64.b64encode(hashlib.sha256(der).digest()).decode()}
payload.update(name=name, address=address, port=port, quota=quota,
               tag='in-sanjose-hy2' if host == 'axi' else 'in-' + name.lower() + '-hy2')
remote = r'''
import copy,json,sys,sqlite3,time,os
from pathlib import Path
sys.path.insert(0,'/opt/jamie-portal/current/backend')
from panel import Panel
os.umask(0o077)
params=json.load(sys.stdin)
panel=Panel(json.load(open('/etc/jamie-portal.json')))
backup=Path('/root/codex-backups')/('sanjose-attach-'+str(int(time.time())))
backup.mkdir(mode=0o700)
with sqlite3.connect('/etc/x-ui/x-ui.db') as src,sqlite3.connect(backup/'panel.db') as dst: src.backup(dst)
nodes=panel.request('nodes/list')
node=next((n for n in nodes if n['name']==params['name']),None)
if not node:
 panel.request('nodes/add',{'name':params['name'],'remark':'Jamie-Node '+params['name'],'scheme':'https','address':params['address'],'port':params['port'],'basePath':params['base'],'apiToken':params['token'],'enable':True,'allowPrivateAddress':False,'tlsVerifyMode':'pin','pinnedCertSha256':params['pin'],'inboundSyncMode':'all'})
 node=next(n for n in panel.request('nodes/list') if n['name']==params['name'])
rows=panel.request('inbounds/list')
inbound=next((r for r in rows if r['tag']==params['tag']),None)
if not inbound:
 template=panel.request('inbounds/get/1')
 stream=copy.deepcopy(template['streamSettings'])
 if isinstance(stream,str): stream=json.loads(stream)
 tls=stream['tlsSettings']
 tls['serverName']=params['address']
 tls['certificates']=[{'certificateFile':'/etc/x-ui/tls/node.crt','keyFile':'/etc/x-ui/tls/node.key','oneTimeLoading':False,'usage':'encipherment','buildChain':False}]
 tls['settings']['pinnedPeerCertSha256']=[params['xray_pin']]
 stream['externalProxy']=[{'forceTls':'same','dest':params['address'],'port':8443,'remark':params['name'],'allowInsecure':True,'pinnedPeerCertSha256':[params['xray_pin']]}]
 data={'nodeId':node['id'],'up':0,'down':0,'total':params['quota'],'remark':params['name']+'-HY2','enable':True,'expiryTime':0,'trafficReset':'never','trafficResetDay':1,'listen':'','port':8443,'protocol':'hysteria','tag':params['tag'],'settings':json.dumps({'version':2,'clients':[]}),'streamSettings':json.dumps(stream),'sniffing':template['sniffing']}
 panel.request('inbounds/add',data)
 inbound=next(r for r in panel.request('inbounds/list') if r['tag']==params['tag'])
print(json.dumps({'node_id':node['id'],'inbound_id':inbound['id'],'status':node['status'],'backup':str(backup)}))
'''
print(ssh('Noether', 'python3 -c ' + shlex.quote(remote), json.dumps(payload).encode()).decode())
if host == 'axi':
 print(ssh(host, 'ufw allow 8443/udp && systemctl is-active x-ui').decode())
