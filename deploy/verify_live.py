"""Live end-to-end smoke test; creates one clearly named test user and card.

Disables the test user's node access afterwards. Never prints credentials.
"""
import base64
import http.cookiejar
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.request

root=Path(__file__).resolve().parent.parent
private=root/'private-admin.json'
credentials=json.loads(private.read_text())
origin=credentials['url']
def client():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
admin=client()
user=client()
def call(opener,path,payload=None):
    req=urllib.request.Request(origin+'/api/'+path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Origin':origin,'Content-Type':'application/json','X-Jamie-Request':'1'})
    with opener.open(req,timeout=30) as res:
        return json.load(res)

call(admin,'login',{'username':credentials['username'],'password':credentials['password']})
if call(admin,'me')['user']['must_change']:
    new=secrets.token_urlsafe(24)
    call(admin,'password',{'old_password':credentials['password'],'new_password':new})
    credentials['password']=new
    private.write_text(json.dumps(credentials,ensure_ascii=False,indent=2))
    private.chmod(0o600)
print('Administrator login and password rotation PASS')
username='qa_'+secrets.token_hex(4)
uid=None
try:
    call(user,'register',{'username':username,'password':secrets.token_urlsafe(24)})
    overview=call(admin,'admin/overview')
    uid=next(m['id'] for m in overview['members'] if m['username']==username)
    code=call(admin,'admin/cards',{'label':'上线验证（勿售）','quota_gib':1,'days':1,'count':1,'valid_days':1})['codes'][0]['code']
    call(user,'redeem',{'code':code})
    assert call(user,'redeem',{'code':code})['already_redeemed']
    for attempt in range(20):
        state=call(user,'me')
        if not state['subscription']['pending'] and state['subscription']['url']:
            break
        time.sleep(3)
    else:
        raise AssertionError('Node synchronization did not finish')
    s=state['subscription']
    assert s['quota']==1024**3 and s['used'] is not None and s['enabled'] is True
    print('Registration, redemption, idempotency, panel sync, real quota read PASS')
    for ua,kind in [('ClashVergeRev/2.4','clash'),('Shadowrocket/2.2','shadowrocket')]:
        with urllib.request.urlopen(urllib.request.Request(s['url'],headers={'User-Agent':ua}),timeout=30) as r:
            body=r.read()
            assert 'total=1073741824' in r.headers['subscription-userinfo']
            if kind=='clash':
                assert body.count(b'type: hysteria2')==3 and b'rule-providers:' in body
            else:
                assert len(base64.b64decode(body).decode().splitlines())==3
        print(kind,'new subscription PASS')
    try:
        call(user,'admin/overview')
        raise AssertionError('Non-admin accepted')
    except urllib.error.HTTPError as exc:
        assert exc.code==403
    print('Live authorization isolation PASS')
finally:
    if uid:
        call(admin,'admin/member',{'id':uid,'disabled':True})
        for attempt in range(20):
            row=next(m for m in call(admin,'admin/overview')['members'] if m['id']==uid)
            if row['revision']==row['synced_revision']:
                print('QA account disabled and node sync confirmed')
                break
            time.sleep(3)
        else:
            raise AssertionError('QA disable still pending')
    call(admin,'logout',{})
    subprocess.run(['ssh','-o','BatchMode=yes','Noether',
        "python3 -c \"import sqlite3; c=sqlite3.connect('/var/lib/jamie-portal/portal.db'); c.execute('UPDATE accounts SET must_change=1 WHERE username=? AND admin=1',('jamie',)); c.commit()\""],check=True,capture_output=True)
    print('Administrator first-login password change requirement restored')
