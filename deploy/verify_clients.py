"""Local installed Mihomo validation using the dedicated monitoring subscription.
No system proxy changes; no customer secrets or URLs are printed.
"""
import base64
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

os.umask(0o077)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--master', default='Noether')
parser.add_argument('--node', help='Only test the selected public IPv4 data plane')
parser.add_argument('--metadata-only', action='store_true')
args = parser.parse_args()
catalog=json.loads(subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',args.master,
    'cat /etc/jamie-node-catalog.json'],capture_output=True,text=True,check=True).stdout)
expected={(n['server'],n['port']) for n in catalog['nodes'] if n['enabled']}
service=catalog['service']
assert expected
identity=json.loads(subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',args.master,
    'cat /var/lib/jamie-portal/probe-identity.json'],capture_output=True,text=True,check=True).stdout)
selected = {n['name'] for n in catalog['nodes'] if n['enabled'] and (not args.node or n['server'] == args.node)}
if not selected:
    raise RuntimeError('Requested node is not published')
url=service['origin'].rstrip('/')+'/sub/'+identity['sub_id']
def fetch(agent, suffix=''):
    req=urllib.request.Request(url+suffix,headers={'User-Agent':agent})
    with urllib.request.urlopen(req,timeout=25) as r:
        assert r.headers.get('profile-title')==service['title']
        assert r.headers.get('subscription-userinfo')
        usage = dict(pair.strip().split('=', 1) for pair in r.headers['subscription-userinfo'].split(';') if '=' in pair)
        assert all(int(usage[field]) >= 0 for field in ('upload', 'download', 'total', 'expire'))
        assert r.headers.get('profile-web-page-url') == service['origin'].rstrip('/')+'/'
        assert r.headers.get('support-url') == service['origin'].rstrip('/')+'/#/help'
        assert '"' not in r.headers.get('Content-Disposition','')
        return r.read()

yaml=fetch('ClashVergeRev/2.4').decode()
assert yaml.count('type: hysteria2')+yaml.count('type: vless')==len(expected) and 'rule-providers:' in yaml
assert len(re.findall(r'^  fingerprint:',yaml,re.M))==yaml.count('type: hysteria2')
assert yaml.count('reality-opts:')==yaml.count('type: vless') and 'skip-cert-verify: true' not in yaml
assert yaml==fetch('Mozilla/5.0','?format=clash').decode()
rule_sets=len(re.findall(r'^    behavior:',yaml,re.M))
rocket=fetch('Shadowrocket/2','?format=shadowrocket-conf').decode()
assert '[Proxy Group]' in rocket and 'FINAL,' in rocket and 'pinSHA256' not in rocket
native=base64.b64decode(fetch('Shadowrocket/2'),validate=True).decode()
assert len(native.splitlines())==len(expected)
assert {(urllib.parse.urlsplit(line).hostname, urllib.parse.urlsplit(line).port) for line in native.splitlines()} == expected
assert native==base64.b64decode(fetch('Mozilla/5.0','?format=shadowrocket'),validate=True).decode()
for line in native.splitlines():
    u=urllib.parse.urlsplit(line);assert u.scheme in ('hy2','hysteria2','vless')
    q=urllib.parse.parse_qs(u.query)
    if u.scheme=='vless':
        assert q.get('security')==['reality'] and q.get('pbk') and q.get('sid')
    else:
        assert 'pinSHA256' in q
print('Clash and Shadowrocket auto/explicit formats and metadata: PASS')
for agent in ('ClashVergeRev/2.4', 'Shadowrocket/2'):
    with urllib.request.urlopen(urllib.request.Request(url, method='HEAD', headers={'User-Agent': agent}), timeout=25) as response:
        assert response.headers.get('subscription-userinfo')
        assert response.headers.get('profile-web-page-url') == service['origin'].rstrip('/')+'/'
        assert response.read() == b''
print('HEAD usage metadata and portal links: PASS')
if args.metadata_only:
    sys.exit(0)

core='/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo'
def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
socks,controller=port(),port()
with tempfile.TemporaryDirectory(prefix='jamie-client-qa-') as work:
    config=Path(work)/'config.yaml'
    config.write_text(yaml.replace('mixed-port: 7890',f'mixed-port: {socks}')+f'\nexternal-controller: 127.0.0.1:{controller}\n')
    tested=subprocess.run([core,'-t','-d',work,'-f',str(config)],capture_output=True,text=True,timeout=40)
    if tested.returncode:raise RuntimeError('Mihomo configuration validation failed')
    log=open(Path(work)/'core.log','w')
    process=subprocess.Popen([core,'-d',work,'-f',str(config)],stdout=log,stderr=log)
    local=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with local.open(f'http://127.0.0.1:{controller}'+path,timeout=3) as r:return json.load(r)
    try:
        for _ in range(50):
            try:proxies=get('/proxies')['proxies'];break
            except OSError:time.sleep(.2)
        else:raise RuntimeError('Isolated Mihomo did not start')
        for _ in range(60):
            providers=get('/providers/rules')['providers']
            if len(providers)==rule_sets and all(x.get('ruleCount',0)>0 for x in providers.values()):break
            time.sleep(.5)
        else:raise RuntimeError('Rule provider loading incomplete before requests')
        failures=[]
        for name,p in proxies.items():
            if p['type'].lower() not in ('hysteria2','vless'):continue
            if name not in selected:continue
            req=urllib.request.Request(f'http://127.0.0.1:{controller}/proxies/'+urllib.parse.quote('节点选择'),
                data=json.dumps({'name':name}).encode(),method='PUT',headers={'Content-Type':'application/json'})
            local.open(req,timeout=3).close()
            result=subprocess.run(['curl','-q','--silent','--show-error','--proxy',f'socks5h://127.0.0.1:{socks}','--noproxy','',
                '--max-time','15','--output','/dev/null','--write-out','%{http_code}',service['probe_url']],
                capture_output=True,text=True,timeout=20)
            print('Mihomo end-to-end',name,'PASS' if result.returncode==0 and result.stdout=='204' else 'FAIL')
            if result.returncode!=0 or result.stdout!='204':
                failures.append(name)
                print('Failure code:',result.returncode,'HTTP:',result.stdout)
                print(result.stderr.replace(identity['auth'],'[redacted]').replace(identity['sub_id'],'[redacted]')[:500])
                log.flush();text=(Path(work)/'core.log').read_text()
                print('Core error categories:',[word for word in ['timeout','certificate','refused','unreachable','handshake','authentication','resolve'] if word in text.lower()])
                for line in [l for l in text.splitlines() if 'level=warning' in l or 'level=error' in l][-3:]:
                    print(line.replace(identity['auth'],'[redacted]').replace(identity['sub_id'],'[redacted]')[:500])
                for line in [l for l in text.splitlines() if 'gstatic' in l][-2:]:
                    print(line.replace(identity['auth'],'[redacted]').replace(identity['sub_id'],'[redacted]')[:500])
                if not text:print('No client log output')
                for line in text.splitlines()[-5:]:
                    print('Client log:',line.replace(identity['auth'],'[redacted]').replace(identity['sub_id'],'[redacted]')[:500])
        if failures:raise RuntimeError('Proxy verification failed for '+', '.join(failures))
        for _ in range(20):
            providers=get('/providers/rules')['providers']
            if len(providers)==rule_sets and all(x.get('ruleCount',0)>0 for x in providers.values()):break
            time.sleep(.5)
        else:raise RuntimeError('Rule provider loading incomplete')
        print('Rule providers: PASS')
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()
print('Isolated client stopped; temporary subscription configuration removed')
