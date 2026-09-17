"""Local installed Mihomo validation using the dedicated monitoring subscription.
No system proxy changes; no customer secrets or URLs are printed.
"""
import base64
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
identity=json.loads(subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','Noether',
    'cat /var/lib/jamie-portal/probe-identity.json'],capture_output=True,text=True,check=True).stdout)
url='https://sub.chuyi.uk/sub/'+identity['sub_id']
def fetch(agent, suffix=''):
    req=urllib.request.Request(url+suffix,headers={'User-Agent':agent})
    with urllib.request.urlopen(req,timeout=25) as r:
        assert r.headers.get('profile-title')=='Jamie-Node'
        assert r.headers.get('subscription-userinfo')
        usage = dict(pair.strip().split('=', 1) for pair in r.headers['subscription-userinfo'].split(';') if '=' in pair)
        assert all(int(usage[field]) >= 0 for field in ('upload', 'download', 'total', 'expire'))
        assert r.headers.get('profile-web-page-url') == 'https://sub.chuyi.uk/'
        assert r.headers.get('support-url') == 'https://sub.chuyi.uk/#/help'
        assert '"' not in r.headers.get('Content-Disposition','')
        return r.read()

yaml=fetch('ClashVergeRev/2.4').decode()
assert yaml.count('type: hysteria2')==3 and 'rule-providers:' in yaml
assert yaml.count('fingerprint:')==3 and 'skip-cert-verify: true' not in yaml
assert yaml==fetch('Mozilla/5.0','?format=clash').decode()
native=base64.b64decode(fetch('Shadowrocket/2'),validate=True).decode()
assert len(native.splitlines())==3
assert native==base64.b64decode(fetch('Mozilla/5.0','?format=shadowrocket'),validate=True).decode()
for line in native.splitlines():
    u=urllib.parse.urlsplit(line);assert u.scheme in ('hy2','hysteria2')
    assert 'pinSHA256' in urllib.parse.parse_qs(u.query)
print('Clash and Shadowrocket auto/explicit formats and metadata: PASS')
for agent in ('ClashVergeRev/2.4', 'Shadowrocket/2'):
    with urllib.request.urlopen(urllib.request.Request(url, method='HEAD', headers={'User-Agent': agent}), timeout=25) as response:
        assert response.headers.get('subscription-userinfo')
        assert response.headers.get('profile-web-page-url') == 'https://sub.chuyi.uk/'
        assert response.read() == b''
print('HEAD usage metadata and portal links: PASS')
if '--metadata-only' in sys.argv:
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
            if len(providers)==4 and all(x.get('ruleCount',0)>0 for x in providers.values()):break
            time.sleep(.5)
        else:raise RuntimeError('Rule provider loading incomplete before requests')
        failures=[]
        for name,p in proxies.items():
            if p['type']!='Hysteria2':continue
            req=urllib.request.Request(f'http://127.0.0.1:{controller}/proxies/'+urllib.parse.quote('Jamie-Node'),
                data=json.dumps({'name':name}).encode(),method='PUT',headers={'Content-Type':'application/json'})
            local.open(req,timeout=3).close()
            result=subprocess.run(['curl','-q','--silent','--show-error','--proxy',f'socks5h://127.0.0.1:{socks}','--noproxy','',
                '--max-time','15','--output','/dev/null','--write-out','%{http_code}','https://www.gstatic.com/generate_204'],
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
            if len(providers)==4 and all(x.get('ruleCount',0)>0 for x in providers.values()):break
            time.sleep(.5)
        else:raise RuntimeError('Rule provider loading incomplete')
        print('Rule providers: PASS')
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()
print('Isolated client stopped; temporary subscription configuration removed')
