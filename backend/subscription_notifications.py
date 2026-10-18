"""Durable subscription reminders derived from the package ledger, never panel quotas."""

import hashlib
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from email_templates import service_email
from errors import DomainError
from package_ledger import snapshot


class SubscriptionNotifications:
    fields = ('traffic_email', 'expiry_email')

    def __init__(self, app):
        self.app = app
        with app.ledger.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS subscription_mail_preferences (
                    account_id TEXT PRIMARY KEY REFERENCES accounts(id),
                    traffic_email INTEGER NOT NULL DEFAULT 1,
                    expiry_email INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS subscription_mail_queue (
                    event_key TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    kind TEXT NOT NULL, recipient TEXT NOT NULL,
                    content TEXT NOT NULL, created INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE INDEX IF NOT EXISTS idx_subscription_mail_pending
                    ON subscription_mail_queue(status,next_attempt);
            """)

    def preferences(self, account, changes=None):
        with self.app.account_lifecycle_lock, self.app.ledger.transaction() as db:
            if changes:
                if any(k not in self.fields or type(v) is not bool for k, v in changes.items()):
                    raise DomainError('无效提醒设置')
                db.execute('INSERT OR IGNORE INTO subscription_mail_preferences(account_id) VALUES(?)',
                           (account['id'],))
                for field, enabled in changes.items():
                    db.execute(f'UPDATE subscription_mail_preferences SET {field}=? WHERE account_id=?',
                               (int(enabled), account['id']))
                    if not enabled:
                        db.execute("""UPDATE subscription_mail_queue SET status='cancelled'
                            WHERE account_id=? AND kind=? AND status='pending'""",
                                   (account['id'], field))
            row = db.execute('SELECT * FROM subscription_mail_preferences WHERE account_id=?',
                             (account['id'],)).fetchone()
        return {field: bool(row[field]) if row else True for field in self.fields}

    def events(self, db, uid, now, require_fresh=True):
        state = snapshot(db, uid, now)
        if not state or state['fault']:
            return {}
        packages = [p for p in state['packages'] if not p['revoked'] and p['expires'] > now]
        result = {}
        origin = self.app.config['origin'].rstrip('/')

        def add(kind, identity, title, message):
            key = hashlib.sha256(json.dumps([uid, kind, identity]).encode()).hexdigest()
            result[key] = (kind, service_email(title, message, origin))

        quota = sum(p['granted'] for p in packages)
        if (quota > 0 and (not require_fresh or 0 <= now - state['sampled'] <= 120)
                and state['remaining'] * 10 <= quota
                and not any(p['next_reset'] and p['next_reset'] <= now for p in packages)):
            identity = sorted((p['id'], p['next_reset'], p['granted']) for p in packages)
            remaining = state['remaining'] / 1024**3
            add('traffic_email', identity, '可用流量即将耗尽' if remaining else '可用流量已耗尽',
                f'当前有效套餐合计剩余 {remaining:.2f} GiB，已不超过总额度的 10%。'
                '请登录查看用量，按需兑换流量包或续费。周期套餐以页面显示的重置时间为准。')
        # Renewals queue after each other, so only the package that ends service matters.
        base = [p for p in packages if p['kind'] in ('base', 'transition')]
        if base and not any(p['permanent'] for p in base):
            last = max(base, key=lambda p: p['expires'])
            if last['expires'] - now <= 3 * 86400:
                date = datetime.fromtimestamp(last['expires'], ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
                add('expiry_email', [last['id'], last['expires']], '服务即将到期',
                    f'你的「{last["label"]}」套餐将于 {date}（北京时间）到期，之后没有其他有效套餐，'
                    '届时连接将暂停。续费后新套餐会接在当前套餐之后计时，不会浪费剩余天数。')
        return result

    def collect(self, now=None):
        if not self.app.ledger.package_billing or not self.app.email_auth.enabled:
            return
        now = int(time.time()) if now is None else now
        with self.app.ledger.transaction() as db:
            accounts = db.execute("""SELECT a.id,v.email,
                COALESCE(p.traffic_email,1) traffic_email,COALESCE(p.expiry_email,1) expiry_email
                FROM accounts a JOIN members m ON m.id=a.id
                JOIN verified_emails v ON v.account_id=a.id
                LEFT JOIN subscription_mail_preferences p ON p.account_id=a.id
                WHERE m.disabled=0 AND m.deleting=0""").fetchall()
            for account in accounts:
                for key, (kind, content) in self.events(db, account['id'], now).items():
                    if account[kind]:
                        db.execute("""INSERT OR IGNORE INTO subscription_mail_queue
                            (event_key,account_id,kind,recipient,content,created) VALUES(?,?,?,?,?,?)""",
                                   (key, account['id'], kind, account['email'], json.dumps(content), now))

    def deliver_pending(self, now=None):
        if not self.app.email_auth.enabled or not self.app.ledger.package_billing:
            return
        now = int(time.time()) if now is None else now
        # Serialize against deletion, email changes, preferences and other deliveries.
        with self.app.account_lifecycle_lock:
            with self.app.ledger.connect() as db:
                pending = db.execute("""SELECT * FROM subscription_mail_queue
                    WHERE status='pending' AND next_attempt<=? ORDER BY created,event_key LIMIT 10""",
                                     (now,)).fetchall()
            for item in pending:
                with self.app.ledger.transaction() as db:
                    recipient = db.execute("""SELECT v.email FROM verified_emails v
                        JOIN members m ON m.id=v.account_id
                        LEFT JOIN subscription_mail_preferences p ON p.account_id=m.id
                        WHERE m.id=? AND m.disabled=0 AND m.deleting=0
                        AND CASE WHEN ?='traffic_email' THEN COALESCE(p.traffic_email,1)
                            ELSE COALESCE(p.expiry_email,1) END=1""",
                                           (item['account_id'], item['kind'])).fetchone()
                    expired = now - item['created'] >= 23 * 3600 or item['attempts'] >= 5
                    valid = (recipient and recipient['email'] == item['recipient'] and
                             item['event_key'] in self.events(db, item['account_id'], now, require_fresh=False))
                    if expired or not valid:
                        db.execute('UPDATE subscription_mail_queue SET status=? WHERE event_key=?',
                                   ('failed' if expired else 'cancelled', item['event_key']))
                        continue
                    if item['kind'] == 'traffic_email':
                        sampled = db.execute('SELECT sampled FROM billing_accounts WHERE member_id=?',
                                             (item['account_id'],)).fetchone()[0]
                        if not 0 <= now - sampled <= 120:
                            db.execute('UPDATE subscription_mail_queue SET next_attempt=? WHERE event_key=?',
                                       (now + 300, item['event_key']))
                            continue  # Wait for a fresh sample; keep the event eligible for retry.
                    db.execute("""UPDATE subscription_mail_queue SET attempts=attempts+1,
                        next_attempt=? WHERE event_key=?""",
                               (now + min(3600, 300 * 2 ** item['attempts']), item['event_key']))
                try:
                    self.app.email_auth.deliver(item['recipient'], json.loads(item['content']),
                                                'subscription-' + item['event_key'])
                except DomainError:
                    if item['attempts'] < 4:
                        continue
                    status = 'failed'
                else:
                    status = 'sent'
                with self.app.ledger.transaction() as db:
                    db.execute('UPDATE subscription_mail_queue SET status=? WHERE event_key=?',
                               (status, item['event_key']))

    def run(self):
        self.collect()
        self.deliver_pending()
