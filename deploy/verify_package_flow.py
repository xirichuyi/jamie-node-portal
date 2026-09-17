"""Live package API acceptance using exclusively owned temporary cards/accounts.

No customer credentials or balances are touched. Funded QA identity is disabled,
confirmed synced, and deleted from the panel before local test data is removed.
"""
import http.client
import json
from pathlib import Path
import secrets
import sys
import time
sys.path.insert(0,'/opt/jamie-portal/current/backend')
from server import App, COOKIE

app=App(json.loads(Path('/etc/jamie-portal.json').read_text()))
suffix=secrets.token_hex(7)
password=secrets.token_urlsafe(24)
admin_id=None;user_id=None;admin_token='';codes=[]

def call(path,data=None,token=''):
    conn=http.client.HTTPConnection('127.0.0.1',18766,timeout=45)
    conn.request('GET' if data is None else 'POST','/api/'+path,
        None if data is None else json.dumps(data),
        {'Origin':app.config['origin'],'Content-Type':'application/json',
         'X-Jamie-Request':'1','Cookie':COOKIE+'='+token})
    response=conn.getresponse();body=json.loads(response.read());status=response.status
    cookie=response.getheader('Set-Cookie','');conn.close()
    return status,body,cookie

try:
    assert app.ledger.package_billing
    admin_id=app.register('qa_ba_'+suffix,password,True)
    with app.ledger.connect() as db:db.execute('UPDATE accounts SET must_change=0 WHERE id=?',(admin_id,))
    admin_token=app.new_session(admin_id)
    def issue(kind):
        status,result,_=call('admin/cards',{'label':'Temporary billing QA','kind':kind,'quota_gib':1,'days':30,'count':1,'valid_days':1},admin_token)
        assert status==200,(kind,status)
        code=result['codes'][0]['code'];codes.append(code);return code
    base=issue('base');addon=issue('addon')
    assert call('register/preview',{'code':addon})[0]==400
    status,_,cookie=call('register',{'username':'qa_bu_'+suffix,'password':password,'code':base})
    assert status==200
    token=cookie.split(';',1)[0].split('=',1)[1]
    with app.ledger.connect() as db:user_id=db.execute('SELECT id FROM accounts WHERE username=?',('qa_bu_'+suffix,)).fetchone()[0]
    s=call('me',token=token)[1]['subscription'];assert len(s['billing']['packages'])==1
    p=s['billing']['packages'][0];target=p['id'];expires=p['expires']
    assert call('redeem',{'code':addon},token)[0]==400
    assert call('redeem',{'code':addon,'target':'not-owned'},token)[0]==400
    status,preview,_=call('redeem/preview',{'code':addon,'target':target},token)
    assert status==200 and preview['after_expires']==expires and preview['days']==0
    assert call('redeem',{'code':addon,'target':target},token)[0]==200
    status,retry,_=call('redeem',{'code':addon,'target':target},token)
    assert status==200 and retry['already_redeemed']
    s=call('me',token=token)[1]['subscription']
    assert len(s['billing']['packages'])==2 and s['billing']['remaining']==2*1024**3
    assert all(p['expires']==expires for p in s['billing']['packages'])
    assert call('admin/users',token=token)[0]==403
    assert call('admin/cards',{'kind':'addon'},token)[0]==403
    print(json.dumps({'registration':'PASS','addon_registration_rejected':'PASS','owned_target_required':'PASS',
        'addon_expiry_unchanged':'PASS','duplicate_redemption':'PASS','permissions':'PASS'}),flush=True)
finally:
    if user_id:
        status,_,_=call('admin/member',{'id':user_id,'disabled':True},admin_token)
        assert status==200,'QA disable failed; preserve records for safe cleanup'
        for _ in range(90):
            with app.ledger.connect() as db:
                member=dict(db.execute('SELECT * FROM members WHERE id=?',(user_id,)).fetchone())
            if member['revision']==member['synced_revision']:break
            time.sleep(1)
        else:raise RuntimeError('QA disable not synced; preserve records for safe cleanup')
        current=app.panel.get(member['panel_email'])
        assert current['client']['auth']==member['panel_auth'] and not current['client']['enable']
        app.panel.request('clients/del/'+member['panel_email'],{})
        assert not any(c['email']==member['panel_email'] for c in app.panel.request('clients/list'))
    with app.ledger.transaction() as db:
        for uid in (user_id,admin_id):
            if not uid:continue
            name=db.execute('SELECT username FROM accounts WHERE id=?',(uid,)).fetchone()[0]
            assert name in ('qa_bu_'+suffix,'qa_ba_'+suffix)
            db.execute('DELETE FROM login_events WHERE username=?',(name,))
            db.execute('DELETE FROM billing_events WHERE member_id=?',(uid,))
            db.execute('DELETE FROM entitlement_packages WHERE member_id=?',(uid,))
            db.execute('DELETE FROM billing_accounts WHERE member_id=?',(uid,))
            for table,column in [('usage_days','account_id'),('usage_baselines','account_id'),
                                 ('user_traffic_activity','member_id'),('sessions','account_id')]:
                db.execute('DELETE FROM '+table+' WHERE '+column+'=?',(uid,))
            db.execute('DELETE FROM audit WHERE actor=? OR target=?',(uid,uid))
        for code in codes:
            cid=db.execute('SELECT id FROM cards WHERE digest=?',(app.ledger.digest(code),)).fetchone()[0]
            db.execute('DELETE FROM audit WHERE target=?',(cid,))
            db.execute('DELETE FROM cards WHERE id=?',(cid,))
        for uid in (user_id,admin_id):
            if uid:
                db.execute('DELETE FROM accounts WHERE id=?',(uid,))
                db.execute('DELETE FROM members WHERE id=?',(uid,))
    print('Owned temporary cards, accounts, panel identity and QA ledger removed; customer records untouched.',flush=True)
