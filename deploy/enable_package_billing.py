"""Guarded, idempotent production cutover. Never reset panel counters.

Run as root after release validation and independent data-plane acceptance.
Stop portal briefly so registration/redemption cannot race the migration.
The verified backup is for disaster recovery, NOT an automatic balance rollback.
"""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,'/opt/jamie-portal/current/backend')
from server import App
from backup import run as backup
from package_ledger import initialize

os.umask(0o077)
config_path=Path('/etc/jamie-portal.json')
config=json.loads(config_path.read_text())
if config.get('package_billing'):
    raise SystemExit('Package billing already enabled; no remigration')
app=App(config)
if app.ledger.package_billing:
    raise SystemExit('Package billing already committed in database; no remigration')
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
record=Path('/root/codex-backups')/('package-billing-'+stamp)
record.mkdir(mode=0o700)
(record/'config-before.json').write_text(json.dumps(config))
subprocess.run(['systemctl','stop','jamie-portal.service'],check=True)
try:
    backup(Path(config['database']).parent)
    clients={r['email']:r for r in app.panel.request('clients/list')}
    now=int(time.time())
    report=[]
    with app.ledger.transaction() as db:
        for m in db.execute('SELECT * FROM members WHERE revision>0').fetchall():
            c=clients.get(m['panel_email'])
            if not c or c['totalGB']!=m['quota'] or c['expiryTime']!=m['expires']*1000:
                raise RuntimeError('Panel entitlement mismatch; migration transaction rolled back')
            stat=c.get('traffic')
            if not stat or type(stat.get('up')) is not int or type(stat.get('down')) is not int:
                raise RuntimeError('Missing reliable counter; migration transaction rolled back')
            raw=stat['up']+stat['down']
            baseline=db.execute('SELECT raw FROM usage_baselines WHERE account_id=?',(m['id'],)).fetchone()
            if baseline and raw<baseline['raw']:
                raise RuntimeError('Counter rollback; migration transaction rolled back')
            initialize(db,m,raw,now)
            app.ledger.refresh_desired(db,m['id'],now)
            app.ledger.audit(db,'system','billing.migrate',m['id'])
            report.append({'id':m['id'],'old_quota':m['quota'],'raw':raw,
                           'remaining':max(0,m['quota']-raw),'expires':m['expires']})
        db.execute('INSERT INTO billing_rollout(id,enabled) VALUES(1,1)')
    # The transactional DB marker is authoritative even if the following config
    # write fails. Restarting cannot accidentally resume legacy redemption.
    config['package_billing']=True
    tmp=config_path.with_suffix('.billing.tmp')
    tmp.write_text(json.dumps(config))
    stat=config_path.stat();os.chown(tmp,stat.st_uid,stat.st_gid);os.chmod(tmp,0o640)
    tmp.replace(config_path)
    (record/'migration.json').write_text(json.dumps({'at':now,'members':report}))
    print(json.dumps({'migrated_accounts':len(report),'package_billing':True,'balances_reset':False}))
finally:
    subprocess.run(['systemctl','start','jamie-portal.service'],check=True)
