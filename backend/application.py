"""Application composition and existing account/billing use cases."""

import hashlib
import re
import secrets
import sqlite3
import threading
import time
from entitlements import Ledger
from errors import DomainError
from panel import Panel
from content import Content, NodeMonitor
from features import Features
from admin_users import UserWorkspace
from operations import Operations
from passwords import PASSWORD_COST as PASSWORD_COST
from passwords import hash_password, verify_password
from email_auth import EmailAuth, email_address
from ticket_notifications import TicketNotifications
from subscription_notifications import SubscriptionNotifications
from staff_notifications import StaffNotifications
from receipt_notifications import ReceiptNotifications
from account_deletion import AccountDeletion
from payments import Payments

from http_types import HttpError


class App:
    def __init__(self, config, panel=None):
        self.config = config
        self.ledger = Ledger(config['database'])
        self.ledger.package_billing = self.ledger.package_billing or bool(
            config.get('package_billing', False)
        )
        self.panel = panel or Panel(config)
        # Replaced atomically by the billing sampler; HTTP requests never wait
        # for the panel when the local package ledger is authoritative.
        self.panel_status = (0.0, {})
        self.content = Content(self.ledger)
        self.monitor = NodeMonitor(self.panel, config.get('node_catalog'))
        self.wake = threading.Event()
        self.account_lifecycle_lock = threading.RLock()
        self.password_lock = threading.BoundedSemaphore(2)
        self.dummy_hash = hash_password(secrets.token_urlsafe(24))
        with self.ledger.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY REFERENCES members(id),
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    admin INTEGER NOT NULL DEFAULT 0,
                    must_change INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    expires INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_account ON sessions(account_id);
                CREATE TABLE IF NOT EXISTS rate_limits (
                    key TEXT PRIMARY KEY,
                    count INTEGER NOT NULL,
                    expires INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rate_limits_expires ON rate_limits(expires);
            """)
        self.features = Features(self)
        self.users = UserWorkspace(self)
        self.operations = Operations(self)
        self.email_auth = EmailAuth(self)
        self.ticket_notifications = TicketNotifications(self)
        self.subscription_notifications = SubscriptionNotifications(self)
        self.staff_notifications = StaffNotifications(self)
        self.receipts = ReceiptNotifications(self)
        self.payments = Payments(self)
        self.account_deletion = AccountDeletion(self)

    def limit(self, key, count, window):
        now = int(time.time())
        key = hashlib.sha256(key.encode()).hexdigest()
        with self.ledger.transaction() as db:
            db.execute('DELETE FROM rate_limits WHERE expires<?', (now,))
            row = db.execute('SELECT count FROM rate_limits WHERE key=?', (key,)).fetchone()
            if row and row['count'] >= count:
                raise HttpError(429, '操作过于频繁，请稍后再试')
            db.execute(
                """INSERT INTO rate_limits(key,count,expires) VALUES(?,1,?)
                ON CONFLICT(key) DO UPDATE SET count=count+1""",
                (key, now + window),
            )

    def register(self, username, password, admin=False):
        if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z0-9_]{3,32}', username):
            raise DomainError('用户名为 3–32 位字母、数字或下划线')
        username = username.lower()
        with self.password_lock:
            hashed = hash_password(password)
        member_id = secrets.token_hex(16)
        try:
            with self.ledger.transaction() as db:
                if db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] >= 10000:
                    raise HttpError(503, '暂时无法注册，请联系管理员')
                self.ledger.insert_member(db, member_id)
                db.execute(
                    'INSERT INTO accounts VALUES(?,?,?,?,?)',
                    (member_id, username, hashed, int(admin), int(admin)),
                )
                self.ledger.audit(db, member_id, 'account.register', member_id)
        except sqlite3.IntegrityError:
            raise DomainError('该用户名不可用') from None
        return member_id

    def card_preview(self, code):
        if not isinstance(code, str) or not 1 <= len(code) <= 100:
            raise DomainError('请输入有效卡密')
        with self.ledger.connect() as db:
            card = db.execute(
                'SELECT * FROM cards WHERE digest=?', (self.ledger.digest(code),)
            ).fetchone()
            if (
                not card
                or card['revoked_at']
                or card['redeem_before'] <= int(time.time())
                or card['redeemed_by']
            ):
                raise DomainError('卡密无效、已使用或已过期；已开通过账号请直接登录')
            if card['kind'] != 'base':
                raise DomainError('这是加流量卡，请登录已有账号并选择有效套餐后兑换，不能用于注册')
            return {
                key: card[key]
                for key in ('label', 'quota', 'days', 'permanent', 'reset_period', 'reset_interval')
            }

    def register_with_card(self, username, password, code, agent='', ip='', email_code=None):
        challenge = None
        if self.email_auth.enabled:
            username = email_address(username)
            challenge = self.email_auth.check(username, 'register', email_code)
        elif not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z0-9_]{3,32}', username):
            raise DomainError('用户名为 3–32 位字母、数字或下划线')
        if not isinstance(code, str) or not 1 <= len(code) <= 100:
            raise DomainError('请输入有效卡密')
        username = username.lower()
        with self.password_lock:
            hashed = hash_password(password)
            with self.ledger.transaction() as db:
                now = int(time.time())
                if challenge:
                    self.email_auth.consume(db, challenge)
                card = db.execute(
                    'SELECT * FROM cards WHERE digest=?', (self.ledger.digest(code),)
                ).fetchone()
                if not card or card['revoked_at']:
                    raise DomainError('卡密无效、已使用或已过期')
                if card['kind'] != 'base':
                    raise DomainError('加流量卡不能用于注册，请登录后兑换')
                if card['redeemed_by']:
                    # A lost HTTP response may be retried, but a card alone never
                    # authenticates: require the same account AND its password.
                    account = db.execute(
                        """SELECT a.*,m.disabled FROM accounts a
                        JOIN members m ON m.id=a.id WHERE a.id=? AND a.username=?""",
                        (card['redeemed_by'], username),
                    ).fetchone()
                    if (
                        not account
                        or account['disabled']
                        or not verify_password(password, account['password'])
                    ):
                        raise DomainError('卡密已使用；已开通过账号请直接登录')
                    token = self._new_session(db, account['id'], agent, ip)
                else:
                    if card['redeem_before'] <= now:
                        raise DomainError('卡密已过期')
                    if db.execute(
                        'SELECT 1 FROM accounts WHERE username=?', (username,)
                    ).fetchone():
                        raise DomainError('该用户名不可用，请更换；已有账号请登录后兑换')
                    if db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] >= 10000:
                        raise HttpError(503, '暂时无法开通，请联系管理员')
                    uid = secrets.token_hex(16)
                    self.ledger.insert_member(
                        db,
                        uid,
                        quota=card['quota'],
                        expires=now + card['days'] * 86400,
                        revision=1,
                        now=now,
                    )
                    db.execute('INSERT INTO accounts VALUES(?,?,?,0,0)', (uid, username, hashed))
                    if challenge:
                        db.execute(
                            'INSERT INTO verified_emails VALUES(?,?,?)', (uid, username, now)
                        )
                    if self.ledger.package_billing:
                        from package_ledger import initialize, grant

                        fresh = dict(
                            db.execute('SELECT * FROM members WHERE id=?', (uid,)).fetchone()
                        )
                        fresh['quota'] = 0
                        initialize(db, fresh, 0, now)
                        grant(db, uid, card, now)
                        self.ledger.refresh_desired(db, uid, now)
                    db.execute(
                        'UPDATE cards SET redeemed_by=?,redeemed_at=? WHERE id=?',
                        (uid, now, card['id']),
                    )
                    self.ledger.audit(db, uid, 'account.register', uid)
                    self.ledger.audit(db, uid, 'card.redeem', card['id'])
                    # Include the login session in the same transaction. Any local
                    # database/session failure rolls back the card and account too.
                    token = self._new_session(db, uid, agent, ip)
        self.wake.set()
        return token

    def _new_session(self, db, account_id, agent='', ip=''):
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires<?', (int(time.time()),))
        db.execute(
            'INSERT INTO sessions VALUES(?,?,?)',
            (hashlib.sha256(token.encode()).hexdigest(), account_id, int(time.time()) + 604800),
        )
        self.features.session_created(token, agent, ip, db=db)
        return token

    def new_session(self, account_id, agent='', ip=''):
        with self.ledger.transaction() as db:
            return self._new_session(db, account_id, agent, ip)

    def session(self, token):
        with self.ledger.connect() as db:
            digest = hashlib.sha256(token.encode()).hexdigest()
            account = db.execute(
                """SELECT a.*,m.disabled,d.seen AS session_seen FROM sessions s JOIN accounts a
                ON a.id=s.account_id JOIN members m ON m.id=a.id
                LEFT JOIN session_details d ON d.digest=s.digest
                WHERE s.digest=? AND s.expires>? AND m.disabled=0""",
                (digest, int(time.time())),
            ).fetchone()
            if account and (
                account['session_seen'] is None or account['session_seen'] < int(time.time()) - 60
            ):
                now = int(time.time())
                db.execute(
                    'UPDATE session_details SET seen=? WHERE digest=? AND seen<?',
                    (now, digest, now - 60),
                )
            return account

    def reauthenticate(self, account, password):
        self.limit('reauth:' + account['id'], 5, 900)
        with self.password_lock:
            if not verify_password(password, account['password']):
                raise DomainError('当前密码不正确')

    def overview(self, account):
        with self.ledger.connect() as db:
            member = dict(
                db.execute('SELECT * FROM members WHERE id=?', (account['id'],)).fetchone()
            )
            history = [
                dict(r)
                for r in db.execute(
                    """SELECT label,quota,days,kind,redeemed_at,permanent,reset_period,reset_interval
                FROM cards WHERE redeemed_by=? ORDER BY redeemed_at DESC LIMIT 50""",
                    (account['id'],),
                )
            ]
            base_plan = db.execute(
                """SELECT label FROM cards WHERE redeemed_by=? AND kind='base'
                ORDER BY redeemed_at DESC,id DESC LIMIT 1""",
                (account['id'],),
            ).fetchone()
        used = None
        panel_enabled = None
        error = None
        billing = self.ledger.billing_snapshot(account['id'])
        if self.ledger.package_billing:
            sampled, statuses = self.panel_status
            if time.monotonic() - sampled <= 60:
                panel_enabled = statuses.get(member['panel_email'])
        elif member['revision']:
            try:
                current = self.panel.get(member['panel_email'])
                used = current['usedTraffic']
                panel_enabled = current['client']['enable']
            except Exception:
                error = '暂时无法读取节点用量，请稍后刷新'
        display_quota = member['quota']
        if billing:
            active = [
                p
                for p in billing['packages']
                if p['expires'] > int(time.time()) and not p['revoked']
            ]
            display_quota = sum(p['granted'] for p in active)
            used = sum(p['spent'] for p in active)
            if billing['fault']:
                error = '流量计数异常，已暂停节点权益下发，请联系管理员核对'
            elif int(time.time()) - billing['sampled'] > 60:
                error = '流量采样延迟，显示的是最后确认的账本余额'
        return {
            'user': {
                'username': account['username'],
                'admin': bool(account['admin']),
                'must_change': bool(account['must_change']),
            },
            'subscription': {
                'quota': display_quota,
                'used': used,
                'expires': (billing['next_expiry'] or billing['last_expiry'])
                if billing
                else member['expires'],
                'billing': billing,
                'pending': member['revision'] > member['synced_revision'],
                'sync_error': member['sync_error'],
                'usage_error': error,
                'enabled': panel_enabled,
                'rotating': bool(member['previous_sub_id']),
                'plan_name': base_plan['label'] if base_plan else None,
                'url': self.config['origin'] + '/sub/' + member['sub_id']
                if (
                    member['synced_revision'] > 0
                    or member['ready_revision'] == member['revision'] > 0
                )
                and not member['disabled']
                and not member['previous_sub_id']
                else None,
            },
            'history': history,
            'nodes': list(self.monitor.names.values()),
        }

    def sync_loop(self):
        while True:
            try:
                if self.config.get('node_catalog'):
                    from node_sync import enqueue_catalog

                    try:
                        enqueue_catalog(self.ledger, self.config['node_catalog'])
                    except Exception as exc:
                        print('Catalog sync:', type(exc).__name__, flush=True)
                self.account_deletion.process()
                if self.ledger.package_billing:
                    self.refresh_billing()
                for member_id in self.ledger.pending():
                    with self.ledger.billing_lock:
                        self.ledger.sync_member(member_id, self.panel)
            except Exception as exc:
                print('Sync worker:', type(exc).__name__, flush=True)
            self.wake.wait(15)
            self.wake.clear()

    def subscription_info(self, sub_id):
        """Token-scoped metadata for the local adapter; never account identity."""
        from package_ledger import summaries
        from cycles import FOREVER

        with self.ledger.connect() as db:
            member = db.execute(
                'SELECT id,disabled,deleting,previous_sub_id FROM members WHERE sub_id=?', (sub_id,)
            ).fetchone()
            if not member:
                return None  # Panel-owned monitoring subscriptions keep their metadata.
            if member['disabled'] or member['deleting'] or member['previous_sub_id']:
                raise HttpError(403, 'Subscription unavailable')
            if not self.ledger.package_billing:
                return None
            s = summaries(db, int(time.time()), member['id']).get(member['id'])
            if not s:
                return None
            expires = s['next_expiry'] or s['last_expiry']
            if s['quota']:
                total, used = s['quota'], s['used']
            else:
                total = used = max(1, s['historical_quota'])
            return f'upload=0; download={used}; total={total}; expire={0 if expires >= FOREVER else expires}'

    def refresh_billing(self):
        values = {}
        with self.ledger.billing_lock:
            try:
                rows = self.panel.request('clients/list')
                statuses = {
                    row['email']: row['enable']
                    for row in rows
                    if isinstance(row.get('email'), str) and type(row.get('enable')) is bool
                }
                self.panel_status = (time.monotonic(), statuses)
                for row in rows:
                    stat = row.get('traffic')
                    if stat and type(stat.get('up')) is int and type(stat.get('down')) is int:
                        values[row['email']] = stat['up'] + stat['down']
            except Exception:
                pass  # Expiration processing still runs when sampling is down.
            self.ledger.sample_billing(values)
