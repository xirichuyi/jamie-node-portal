"""Self-service features. All records are scoped on the server, never by UI claims."""

import datetime
import hashlib
import json
import secrets
import time
from pathlib import Path
from errors import DomainError


def text(value, maximum, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise DomainError('内容长度不正确')
    return value.strip()


def day(ts):
    return (
        datetime.datetime.fromtimestamp(ts, datetime.timezone(datetime.timedelta(hours=8)))
        .date()
        .isoformat()
    )


class Features:
    def __init__(self, app):
        self.app, self.ledger = app, app.ledger
        with self.ledger.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS session_details (
                    digest TEXT PRIMARY KEY REFERENCES sessions(digest) ON DELETE CASCADE,
                    public_id TEXT NOT NULL UNIQUE, created INTEGER NOT NULL,
                    seen INTEGER NOT NULL, agent TEXT NOT NULL, ip TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recovery_codes (
                    account_id TEXT PRIMARY KEY REFERENCES accounts(id), digest TEXT NOT NULL,
                    created INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
                    subject TEXT NOT NULL, category TEXT NOT NULL, status TEXT NOT NULL,
                    created INTEGER NOT NULL, updated INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tickets_owner ON support_tickets(account_id,updated);
                CREATE TABLE IF NOT EXISTS ticket_messages (
                    id INTEGER PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES support_tickets(id),
                    account_id TEXT NOT NULL REFERENCES accounts(id), staff INTEGER NOT NULL,
                    body TEXT NOT NULL, created INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_ticket ON ticket_messages(ticket_id,id);
                CREATE TABLE IF NOT EXISTS usage_baselines (
                    account_id TEXT PRIMARY KEY REFERENCES accounts(id), raw INTEGER NOT NULL,
                    sampled INTEGER NOT NULL, started INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage_days (
                    account_id TEXT NOT NULL REFERENCES accounts(id), day TEXT NOT NULL,
                    bytes INTEGER NOT NULL DEFAULT 0, partial INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(account_id,day)
                );
                CREATE TABLE IF NOT EXISTS service_events (
                    id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL, name TEXT NOT NULL,
                    status TEXT NOT NULL, created INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS monitor_states (
                    node_id INTEGER PRIMARY KEY, status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portal_incidents (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
                    status TEXT NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feature_cache (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated INTEGER NOT NULL
                );
            """)
            for row in db.execute(
                'SELECT digest FROM sessions WHERE digest NOT IN (SELECT digest FROM session_details)'
            ).fetchall():
                db.execute(
                    'INSERT INTO session_details VALUES(?,?,0,0,?,?)',
                    (row['digest'], secrets.token_hex(12), '旧版登录会话', ''),
                )

    def session_created(self, token, agent='', ip='', db=None):
        if db is None:
            with self.ledger.connect() as connection:
                return self.session_created(token, agent, ip, db=connection)
        now = int(time.time())
        agent = ''.join(c for c in agent[:240] if c.isprintable())
        db.execute(
            'INSERT INTO session_details VALUES(?,?,?,?,?,?)',
            (
                hashlib.sha256(token.encode()).hexdigest(),
                secrets.token_hex(12),
                now,
                now,
                agent,
                ip[:64],
            ),
        )

    def sessions(self, account, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.ledger.connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    """SELECT d.public_id AS id,d.agent,d.ip,d.created,d.seen,s.expires,
                (s.digest=?) AS current FROM sessions s JOIN session_details d ON d.digest=s.digest
                WHERE s.account_id=? AND s.expires>? ORDER BY current DESC,d.seen DESC""",
                    (digest, account['id'], int(time.time())),
                )
            ]
            recovery = db.execute(
                'SELECT created FROM recovery_codes WHERE account_id=?', (account['id'],)
            ).fetchone()
            email_verified = bool(
                db.execute(
                    'SELECT 1 FROM verified_emails WHERE account_id=?', (account['id'],)
                ).fetchone()
            )
            email = db.execute(
                'SELECT email FROM verified_emails WHERE account_id=?', (account['id'],)
            ).fetchone()
            identity = db.execute(
                'SELECT username,admin FROM accounts WHERE id=?', (account['id'],)
            ).fetchone()
        return {
            'sessions': rows,
            'recovery_created': recovery['created'] if recovery else None,
            'email_verified': email_verified,
            'email': email['email'] if email else '',
            'username': identity['username'],
            'admin': bool(identity['admin']),
        }

    def revoke_session(self, account, target, token):
        with self.ledger.transaction() as db:
            row = db.execute(
                """SELECT s.digest FROM sessions s JOIN session_details d ON d.digest=s.digest
                WHERE d.public_id=? AND s.account_id=?""",
                (text(target, 40), account['id']),
            ).fetchone()
            if not row:
                raise DomainError('会话不存在或已经退出')
            if row['digest'] == hashlib.sha256(token.encode()).hexdigest():
                raise DomainError('当前会话请使用退出登录')
            db.execute('DELETE FROM sessions WHERE digest=?', (row['digest'],))
            self.ledger.audit(db, account['id'], 'session.revoke', target)

    def recovery_generate(self, account):
        code = secrets.token_hex(24).upper()
        with self.ledger.transaction() as db:
            db.execute(
                'INSERT OR REPLACE INTO recovery_codes VALUES(?,?,?)',
                (account['id'], self.ledger.digest(code), int(time.time())),
            )
            self.ledger.audit(db, account['id'], 'recovery.generate', account['id'])
        return {'code': '-'.join(code[i : i + 8] for i in range(0, len(code), 8))}

    def recovery_reset(self, username, code, hashed):
        digest = self.ledger.digest(text(code, 100))
        with self.ledger.transaction() as db:
            row = db.execute(
                """SELECT a.id FROM accounts a JOIN recovery_codes r ON a.id=r.account_id
                JOIN members m ON m.id=a.id WHERE a.username=? AND r.digest=? AND m.disabled=0""",
                (text(username, 254).lower(), digest),
            ).fetchone()
            if not row:
                raise DomainError('用户名或恢复码不正确')
            db.execute('DELETE FROM recovery_codes WHERE account_id=?', (row['id'],))
            db.execute(
                'UPDATE accounts SET password=?,must_change=0 WHERE id=?', (hashed, row['id'])
            )
            db.execute('DELETE FROM sessions WHERE account_id=?', (row['id'],))
            self.ledger.audit(db, row['id'], 'account.recover', row['id'])

    def tickets(self, account, staff=False):
        with self.ledger.connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    """SELECT t.*,a.username,
                    (SELECT COUNT(*) FROM ticket_messages m WHERE m.ticket_id=t.id AND m.staff=1
                    AND m.id>COALESCE((SELECT r.message_id FROM ticket_reads r WHERE r.account_id=t.account_id AND r.ticket_id=t.id),0)) AS unread
                    FROM support_tickets t
                JOIN accounts a ON a.id=t.account_id """
                    + ('' if staff else 'WHERE t.account_id=? ')
                    + 'ORDER BY t.updated DESC LIMIT 100',
                    () if staff else (account['id'],),
                )
            ]
        return {'tickets': rows}

    def ticket_read(self, account, tid, mid):
        if type(mid) is not int:
            raise DomainError('无效消息')
        with self.ledger.transaction() as db:
            if not db.execute(
                'SELECT 1 FROM support_tickets t JOIN ticket_messages m ON m.ticket_id=t.id WHERE t.account_id=? AND t.id=? AND m.id=?',
                (account['id'], tid, mid),
            ).fetchone():
                raise DomainError('工单不存在')
            db.execute(
                'INSERT INTO ticket_reads VALUES(?,?,?) ON CONFLICT(account_id,ticket_id) DO UPDATE SET message_id=MAX(message_id,excluded.message_id)',
                (account['id'], tid, mid),
            )

    def ticket(self, account, ticket_id, staff=False):
        with self.ledger.connect() as db:
            row = db.execute(
                'SELECT * FROM support_tickets WHERE id=? AND (? OR account_id=?)',
                (ticket_id, int(staff), account['id']),
            ).fetchone()
            if not row:
                raise DomainError('工单不存在')
            return {
                'ticket': dict(row),
                'messages': [
                    dict(m)
                    for m in db.execute(
                        """SELECT id,staff,body,created
                FROM ticket_messages WHERE ticket_id=? ORDER BY id LIMIT 200""",
                        (ticket_id,),
                    )
                ],
            }

    def ticket_write(self, account, data, staff=False):
        now = int(time.time())
        with self.ledger.transaction() as db:
            tid = data.get('id')
            if not tid:
                subject, body = text(data.get('subject'), 100), text(data.get('body'), 4000)
                category = data.get('category')
                if category not in ('connection', 'redeem', 'account', 'other'):
                    raise DomainError('请选择问题类型')
                if (
                    db.execute(
                        "SELECT COUNT(*) FROM support_tickets WHERE account_id=? AND status!='closed'",
                        (account['id'],),
                    ).fetchone()[0]
                    >= 5
                ):
                    raise DomainError('最多同时保留 5 个未关闭工单')
                tid = secrets.token_hex(12)
                db.execute(
                    'INSERT INTO support_tickets VALUES(?,?,?,?,?,?,?)',
                    (tid, account['id'], subject, category, 'waiting', now, now),
                )
            else:
                row = db.execute(
                    'SELECT * FROM support_tickets WHERE id=? AND (? OR account_id=?)',
                    (tid, int(staff), account['id']),
                ).fetchone()
                if not row:
                    raise DomainError('工单不存在')
                if data.get('close') is True:
                    db.execute(
                        "UPDATE support_tickets SET status='closed',updated=? WHERE id=?",
                        (now, tid),
                    )
                    self.ledger.audit(db, account['id'], 'ticket.close', tid)
                    return {'id': tid}
                if row['status'] == 'closed':
                    raise DomainError('工单已关闭，请新建工单')
                if (
                    db.execute(
                        'SELECT COUNT(*) FROM ticket_messages WHERE ticket_id=?', (tid,)
                    ).fetchone()[0]
                    >= 200
                ):
                    raise DomainError('该工单消息已达上限，请关闭后新建')
                body = text(data.get('body'), 4000)
                db.execute(
                    'UPDATE support_tickets SET status=?,updated=? WHERE id=?',
                    ('replied' if staff else 'waiting', now, tid),
                )
            message = db.execute(
                'INSERT INTO ticket_messages(ticket_id,account_id,staff,body,created) VALUES(?,?,?,?,?)',
                (tid, account['id'], int(staff), body, now),
            )
            if staff and data.get('id'):
                self.app.ticket_notifications.enqueue(db, row['account_id'], message.lastrowid)
            self.ledger.audit(
                db, account['id'], 'ticket.reply' if data.get('id') else 'ticket.create', tid
            )
        return {'id': tid}

    def preview(self, account_id, code, target=None):
        now = int(time.time())
        with self.ledger.connect() as db:
            card = db.execute(
                'SELECT * FROM cards WHERE digest=?', (self.ledger.digest(text(code, 100)),)
            ).fetchone()
            member = db.execute(
                'SELECT quota,expires FROM members WHERE id=?', (account_id,)
            ).fetchone()
            if not card or card['revoked_at'] or card['redeem_before'] <= now:
                raise DomainError('卡密无效或已过期')
            if card['redeemed_by']:
                raise DomainError('卡密已兑换，请查看兑换记录')
            if self.ledger.package_billing:
                from package_ledger import targets, snapshot
                from cycles import expiry

                state = snapshot(db, account_id, now)
                packages = targets(db, account_id, now)
                parent = next((p for p in packages if p['id'] == target), None)
                if card['kind'] == 'addon' and not packages:
                    raise DomainError('没有有效套餐，请先兑换套餐卡；流量包不能延长有效期')
                if target and not parent:
                    raise DomainError('目标套餐无效或已到期，请重新选择')
                return {
                    'label': card['label'],
                    'quota': card['quota'],
                    'days': card['days'] if card['kind'] == 'base' else 0,
                    'kind': card['kind'],
                    **{k: card[k] for k in ('permanent', 'reset_period', 'reset_interval')},
                    'targets': packages,
                    'package_billing': True,
                    'after_quota': (state['remaining'] if state else 0) + card['quota'],
                    'after_expires': (parent['expires'] if parent else 0)
                    if card['kind'] == 'addon'
                    else expiry(card, now),
                }
            return {
                'label': card['label'],
                'quota': card['quota'],
                'days': card['days'],
                'after_quota': member['quota'] + card['quota'],
                'after_expires': max(now, member['expires']) + card['days'] * 86400,
            }

    def rotate(self, account_id, credentials=False):
        with self.ledger.transaction() as db:
            member = db.execute('SELECT * FROM members WHERE id=?', (account_id,)).fetchone()
            if not member['quota'] or member['revision'] != member['synced_revision']:
                raise DomainError('请先开通订阅并等待节点同步完成')
            db.execute(
                """UPDATE members SET previous_sub_id=sub_id,sub_id=?,revision=revision+1,
                sync_error=NULL WHERE id=?""",
                (secrets.token_hex(24), account_id),
            )
            if credentials:
                db.execute(
                    'UPDATE members SET previous_panel_auth=panel_auth,panel_auth=? WHERE id=?',
                    (secrets.token_hex(24), account_id),
                )
            self.ledger.audit(
                db,
                account_id,
                'subscription.rotate_credentials' if credentials else 'subscription.rotate',
                account_id,
            )
        self.app.wake.set()

    def sample_usage(self, values, now=None):
        now = int(time.time()) if now is None else now
        with self.ledger.transaction() as db:
            for account_id, raw in values.items():
                if type(raw) is not int or raw < 0:
                    continue
                old = db.execute(
                    'SELECT * FROM usage_baselines WHERE account_id=?', (account_id,)
                ).fetchone()
                if old and now <= old['sampled']:
                    continue
                # First reading establishes a baseline, never invents past usage.
                delta = max(0, raw - old['raw']) if old else 0
                partial = (
                    not old
                    or raw < old['raw']
                    or now - old['sampled'] > 900
                    or day(old['sampled']) != day(now)
                )
                db.execute(
                    """INSERT INTO usage_days VALUES(?,?,?,?) ON CONFLICT(account_id,day)
                    DO UPDATE SET bytes=bytes+excluded.bytes,partial=MAX(partial,excluded.partial)""",
                    (account_id, day(now), delta, int(partial)),
                )
                db.execute(
                    'INSERT OR REPLACE INTO usage_baselines VALUES(?,?,?,?)',
                    (account_id, raw, now, old['started'] if old else now),
                )
            db.execute('DELETE FROM usage_days WHERE day<?', (day(now - 400 * 86400),))

    def usage(self, account_id, days=30):
        now = int(time.time())
        with self.ledger.connect() as db:
            baseline = db.execute(
                'SELECT sampled,started FROM usage_baselines WHERE account_id=?', (account_id,)
            ).fetchone()
            records = {
                r['day']: dict(r)
                for r in db.execute(
                    'SELECT day,bytes,partial FROM usage_days WHERE account_id=? AND day>=?',
                    (account_id, day(now - days * 86400)),
                )
            }
        result = []
        for offset in range(days - 1, -1, -1):
            d = day(now - offset * 86400)
            result.append(records.get(d, {'day': d, 'bytes': None, 'partial': True}))
        return {
            'days': result,
            'sampled': baseline['sampled'] if baseline else 0,
            'started': baseline['started'] if baseline else 0,
            'timezone': 'Asia/Shanghai',
        }

    def collect(self):
        now = int(time.time())
        try:
            clients = self.app.panel.request('clients/list')
            by_email = {c['email']: c.get('traffic') for c in clients}
            with self.ledger.connect() as db:
                members = db.execute('SELECT id,panel_email FROM members WHERE quota>0').fetchall()
            values = {}
            for m in members:
                stat = by_email.get(m['panel_email'])
                if stat and all(type(stat.get(k)) is int and stat[k] >= 0 for k in ('up', 'down')):
                    values[m['id']] = stat['up'] + stat['down']
            self.sample_usage(values, now)
        except Exception:
            pass
        try:
            budgets = []
            for row in self.app.panel.request('inbounds/list'):
                if row['id'] not in self.app.panel.inbounds:
                    continue
                budgets.append(
                    {
                        'id': row['id'],
                        'name': self.app.monitor.names.get(row['id'], '节点'),
                        'up': row.get('up'),
                        'down': row.get('down'),
                        'total': row.get('total'),
                        'reset': row.get('trafficReset', 'unknown'),
                        'reset_day': row.get('trafficResetDay'),
                        'enabled': row.get('enable'),
                    }
                )
            with self.ledger.connect() as db:
                db.execute(
                    'INSERT OR REPLACE INTO feature_cache VALUES(?,?,?)',
                    ('budgets', json.dumps(budgets), now),
                )
        except Exception:
            pass
        snapshot = self.app.monitor.snapshot()
        with self.ledger.transaction() as db:
            for node in snapshot['nodes']:
                old = db.execute(
                    'SELECT status FROM monitor_states WHERE node_id=?', (node['id'],)
                ).fetchone()
                if not old or old['status'] != node['status']:
                    db.execute(
                        'INSERT INTO service_events(node_id,name,status,created) VALUES(?,?,?,?)',
                        (node['id'], node['name'], node['status'], now),
                    )
                    db.execute(
                        'INSERT OR REPLACE INTO monitor_states VALUES(?,?)',
                        (node['id'], node['status']),
                    )
            db.execute('DELETE FROM service_events WHERE created<?', (now - 90 * 86400,))

    def loop(self):
        while True:
            try:
                self.collect()
                self.app.ticket_notifications.deliver_pending()
            except Exception as exc:
                print('Feature collector:', type(exc).__name__, flush=True)
            time.sleep(300)

    def service_status(self):
        with self.ledger.connect() as db:
            incidents = [
                dict(r)
                for r in db.execute('SELECT * FROM portal_incidents ORDER BY updated DESC LIMIT 30')
            ]
            events = [
                dict(r)
                for r in db.execute(
                    'SELECT name,status,created FROM service_events ORDER BY id DESC LIMIT 50'
                )
            ]
        return {**self.app.monitor.snapshot(), 'incidents': incidents, 'events': events}

    def incident_save(self, account, data):
        title, body = text(data.get('title'), 100), text(data.get('body'), 4000)
        status = data.get('status')
        if status not in ('investigating', 'maintenance', 'resolved'):
            raise DomainError('请选择事件状态')
        now = int(time.time())
        with self.ledger.transaction() as db:
            iid = data.get('id')
            if iid:
                if not db.execute(
                    'UPDATE portal_incidents SET title=?,body=?,status=?,updated=? WHERE id=?',
                    (title, body, status, now, iid),
                ).rowcount:
                    raise DomainError('事件不存在')
            else:
                iid = secrets.token_hex(12)
                db.execute(
                    'INSERT INTO portal_incidents VALUES(?,?,?,?,?,?)',
                    (iid, title, body, status, now, now),
                )
            self.ledger.audit(db, account['id'], 'incident.save', iid)
        return {'id': iid}

    def operations(self):
        now = int(time.time())
        with self.ledger.connect() as db:
            counts = dict(
                db.execute(
                    """SELECT COUNT(*) AS users,SUM(disabled=0 AND expires>?) AS active,
                SUM(disabled=0 AND expires>? AND expires<=?) AS expiring,
                SUM(revision>synced_revision) AS pending,SUM(sync_error IS NOT NULL) AS sync_errors
                FROM members""",
                    (now, now, now + 7 * 86400),
                ).fetchone()
            )
            counts['waiting_tickets'] = db.execute(
                "SELECT COUNT(*) FROM support_tickets WHERE status='waiting'"
            ).fetchone()[0]
            batches = [
                dict(r)
                for r in db.execute(
                    """SELECT label,created,COUNT(*) AS total,
                SUM(redeemed_at IS NOT NULL) AS redeemed,
                SUM(redeemed_at IS NULL AND revoked_at IS NULL AND redeem_before>?) AS available,
                SUM(revoked_at IS NOT NULL) AS revoked,
                SUM(redeemed_at IS NULL AND revoked_at IS NULL AND redeem_before<=?) AS expired
                FROM cards GROUP BY created,label ORDER BY created DESC LIMIT 30""",
                    (now, now),
                )
            ]
            cache = db.execute(
                "SELECT value,updated FROM feature_cache WHERE key='budgets'"
            ).fetchone()
        backups = Path(self.ledger.path).parent / 'backups'
        files = list(backups.glob('*.db')) if backups.exists() else []
        backup_at = int(max(p.stat().st_mtime for p in files)) if files else None
        user_counts = self.app.users.listing({})['counts']
        counts.update(
            {key: user_counts[key] for key in ('active', 'expiring', 'pending', 'sync_errors')}
        )
        counts['users'] = user_counts['all']
        return {
            'counts': counts,
            'batches': batches,
            'budgets': json.loads(cache['value']) if cache else [],
            'budgets_at': cache['updated'] if cache else 0,
            'backup_at': backup_at,
            'status': self.service_status(),
        }
