"""Post-release smoke check. Uses temporary unfunded accounts, never real passwords.

Run via SSH stdin as root. No panel clients are created or modified.
"""
import http.client
import json
import secrets
import sys
from pathlib import Path
sys.path.insert(0,'/opt/jamie-portal/current/backend')
from server import App, COOKIE

app=App(json.loads(Path('/etc/jamie-portal.json').read_text()))
uids=[]
password=secrets.token_urlsafe(24)
suffix=secrets.token_hex(5)
def request(path,data=None,token=''):
    conn=http.client.HTTPConnection('127.0.0.1',18766,timeout=25)
    headers={'Origin':app.config['origin'],'Content-Type':'application/json','X-Jamie-Request':'1','Cookie':COOKIE+'='+token}
    conn.request('GET' if data is None else 'POST','/api/'+path,None if data is None else json.dumps(data),headers)
    r=conn.getresponse(); value=json.loads(r.read()); status=r.status;conn.close()
    return status,value
try:
    for name,is_admin in [('qa_u_'+suffix,False),('qa_a_'+suffix,True)]:
        uid=app.register(name,password,admin=is_admin);uids.append(uid)
    with app.ledger.connect() as db:
        db.execute('UPDATE accounts SET must_change=0 WHERE id=?',(uids[1],))
    user=app.new_session(uids[0],'Release smoke check','127.0.0.1')
    admin=app.new_session(uids[1],'Release smoke check','127.0.0.1')
    assert request('health')[0]==200
    for path in ('usage','sessions','tickets','service-status'):
        assert request(path,token=user)[0]==200,path
        assert request(path)[0]==401,path
    assert request('admin/operations',token=user)[0]==403
    status,ops=request('admin/operations',token=admin)
    assert status==200
    assert len(ops['budgets'])==3 and all(b['total']==9000000000000 for b in ops['budgets'])
    assert ops['backup_at']
    for path in ('admin/card-search','admin/login-diagnosis'):
        assert request(path,{},user)[0]==403
        assert request(path,{})[0]==401
    status,ready=request('admin/readiness',token=admin)
    assert status==200 and ready['backup']['restore_verified']
    assert request('admin/readiness',token=user)[0]==403
    status,cards=request('admin/card-search',{'query':'','page':1},admin)
    assert status==200 and len(cards['cards'])<=25
    assert 'digest' not in json.dumps(cards)
    status,diagnosis=request('admin/login-diagnosis',{'username':'qa_u_'+suffix},admin)
    assert status==200 and diagnosis['account']['id']==uids[0]
    assert request('login',{'username':'qa_missing_'+suffix,'password':'Not-a-real-password'})[0]==401
    status,diagnosis=request('admin/login-diagnosis',{'username':'qa_missing_'+suffix},admin)
    assert status==200 and diagnosis['account'] is None and diagnosis['events'][0]['outcome']=='unknown_user'
    for path in ('admin/users','admin/user?id='+uids[0],'admin/cards-overview'):
        assert request(path,token=user)[0]==403
        assert request(path)[0]==401
        status,result=request(path,token=admin)
        assert status==200,path
        assert 'panel_auth' not in json.dumps(result) and 'sub_id' not in json.dumps(result)
    listing=request('admin/users?q=qa_u_'+suffix,token=admin)[1]
    assert listing['total']==1 and listing['members'][0]['id']==uids[0]
    for ordering in ('created','username','remaining','used','expires','last_proxy_activity','last_web_seen'):
        status,sorted_users=request('admin/users?sort='+ordering+'&direction=asc',token=admin)
        assert status==200 and all('proxy_activity' in r for r in sorted_users['members'])
    assert request('admin/users?sort=password',token=admin)[0]==400
    assert request('admin/member',{'id':uids[0],'disabled':True,'expected_disabled':False},admin)[0]==200
    assert request('me',token=user)[0]==401
    assert request('admin/user?id='+uids[0],token=admin)[1]['member']['primary_state']=='disabled'
    assert request('admin/member',{'id':uids[0],'disabled':False,'expected_disabled':True},admin)[0]==200
    user=app.new_session(uids[0],'Release smoke check','127.0.0.1')
    assert request('admin/user-sync',{'id':uids[0]},admin)[1]['pending'] is False
    assert request('admin/user-sessions',{'id':uids[0]},admin)[0]==200
    assert request('me',token=user)[0]==401
    user=app.new_session(uids[0],'Release smoke check','127.0.0.1')
    status,t=request('tickets',{'subject':'Release smoke check','category':'other','body':'Temporary verification ticket; automatically removed.'},user)
    assert status==200
    assert request('admin/tickets',{'id':t['id'],'body':'Verified'},admin)[0]==200
    status,detail=request('tickets?id='+t['id'],token=user)
    assert status==200 and detail['ticket']['status']=='replied'
    assert request('tickets',{'id':t['id'],'close':True},user)[0]==200
    second=app.new_session(uids[0],'Temporary second browser','127.0.0.1')
    sessions=request('sessions',token=user)[1]['sessions']
    target=next(s for s in sessions if not s['current'])
    assert request('sessions/revoke',{'id':target['id']},user)[0]==200
    assert request('me',token=second)[0]==401
    status,recovery=request('recovery-code',{'password':password},user)
    assert status==200
    assert request('recover',{'username':'qa_u_'+suffix,'code':recovery['code'],'new_password':secrets.token_urlsafe(24)})[0]==200
    assert request('me',token=user)[0]==401
    status,reset=request('admin/reset-password',{'id':uids[0]},admin)
    assert status==200 and reset.get('password')
    assert request('login',{'username':'qa_u_'+suffix,'password':reset['password']})[0]==200
    assert request('admin/user?id='+uids[0],token=admin)[1]['member']['must_change']==1
    print(json.dumps({'features':'PASS','user_workspace':'PASS','user_disable_restore':'PASS','admin_password_reset':'PASS','admin_session_revoke':'PASS','permissions':'PASS','ticket_reply':'PASS','session_revoke':'PASS','recovery':'PASS','node_budgets_tb':[b['total']/1e12 for b in ops['budgets']],'backup':'present'}))
finally:
    with app.ledger.transaction() as db:
        db.execute('DELETE FROM login_events WHERE username IN (?,?,?)',('qa_u_'+suffix,'qa_a_'+suffix,'qa_missing_'+suffix))
        for uid in uids:
            row=db.execute('SELECT username FROM accounts WHERE id=?',(uid,)).fetchone()
            assert row and row['username'] in ('qa_u_'+suffix,'qa_a_'+suffix)
            db.execute('DELETE FROM ticket_messages WHERE ticket_id IN (SELECT id FROM support_tickets WHERE account_id=?)',(uid,))
            db.execute('DELETE FROM ticket_messages WHERE account_id=?',(uid,))
            db.execute('DELETE FROM support_tickets WHERE account_id=?',(uid,))
            db.execute('DELETE FROM recovery_codes WHERE account_id=?',(uid,))
            db.execute('DELETE FROM sessions WHERE account_id=?',(uid,))
            db.execute('DELETE FROM audit WHERE actor=?',(uid,))
            db.execute('DELETE FROM audit WHERE target=?',(uid,))
            db.execute('DELETE FROM accounts WHERE id=?',(uid,))
            db.execute('DELETE FROM user_traffic_activity WHERE member_id=?',(uid,))
            db.execute('DELETE FROM members WHERE id=?',(uid,))
    print('Temporary unfunded QA accounts, sessions and tickets removed; existing users untouched.')
