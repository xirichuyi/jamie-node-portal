"""Bounded data-plane quota check; owns only a newly created temporary identity.

Run on Noether via SSH stdin. Never changes customer or monitor entitlements.
At most a handful of fixed gstatic requests. Always disables the QA identity.
"""
import base64
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0,'/opt/jamie-portal/current/backend')
from panel import Panel
from probe import outbound, test_outbound
from node_catalog import active_nodes

os.umask(0o077)
panel = Panel(json.loads(Path('/etc/jamie-portal.json').read_text()))
identity = json.loads(Path('/var/lib/jamie-portal/probe-identity.json').read_text())
req = urllib.request.Request('https://sub.chuyi.uk/sub/'+identity['sub_id'],headers={'User-Agent':'Shadowrocket/Probe'})
nodes={(n['server'],n['port']):n['name'] for n in active_nodes()}
with urllib.request.urlopen(req,timeout=15) as response:
    configs = [outbound(line,nodes) for line in base64.b64decode(response.read()).decode().splitlines() if line]
assert len(configs)==len(nodes) and nodes
core='/usr/local/x-ui/bin/xray-linux-amd64'
def check(config):
    with tempfile.TemporaryDirectory(prefix='billing-qa-') as directory:
        return test_outbound(config,core,directory)['ok']
assert all(check(c) for c in configs), 'Healthy control probe required before quota test'
member={'panel_email':'jn_billing_qa_'+secrets.token_hex(8),'panel_auth':secrets.token_hex(24),
    'sub_id':secrets.token_hex(24),'quota':1024**2,'expires':int(time.time())+600,'disabled':False}
created=False
try:
    created=True  # Also clean up a partially applied add.
    panel.apply(member)
    for config in configs:
        config['streamSettings']['hysteriaSettings']['auth']=member['panel_auth']
    assert check(configs[0]), 'Funded QA connection failed'
    print('QA connected; waiting for panel accounting',flush=True)
    for attempt in range(120):
        if panel.get(member['panel_email'])['usedTraffic']>1: break
        if attempt and attempt % 30 == 0:
            print('Panel accounting still pending',flush=True)
        time.sleep(1)
    else: raise RuntimeError('QA traffic was not aggregated by panel')
    member['quota']=1
    panel.apply(member)
    results=[check(c) for c in configs]
    if any(results):
        time.sleep(15)
        results=[check(c) for c in configs]
    print(json.dumps({'shared_quota_blocked_all_nodes':not any(results),
                      'node_denied': [not ok for ok in results]}),flush=True)
    if any(results): raise RuntimeError('Shared quota enforcement acceptance failed')
finally:
    if created:
        member['disabled']=True
        member['expires']=int(time.time())-1
        try:
            panel.apply(member)
            # v3 route: failure leaves an expired, disabled QA record, never a
            # reusable account. Only this script's random identity is targeted.
            try:
                panel.request('clients/del/'+member['panel_email'],{})
                removed=not any(c['email']==member['panel_email'] for c in panel.request('clients/list'))
            except Exception:
                removed=False
            print(json.dumps({'temporary_identity_disabled':True,'temporary_identity_removed':removed}),flush=True)
        except Exception:
            print('QA cleanup needs attention; its original expiry is bounded to ten minutes',flush=True)
            raise
