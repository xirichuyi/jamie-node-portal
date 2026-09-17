#!/usr/bin/env python3
"""Jamie-Node portal: stdlib-only, loopback HTTP behind nginx TLS."""

import argparse
import hashlib
import http.cookies
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from entitlements import Ledger
from errors import DomainError
from panel import Panel
from content import Content, NodeMonitor
from features import Features, text
from admin_users import UserWorkspace
from operations import Operations
from passwords import PASSWORD_COST as PASSWORD_COST
from passwords import hash_password, verify_password
from email_auth import EmailAuth, email_address
from ticket_notifications import TicketNotifications
from account_deletion import AccountDeletion

COOKIE = '__Host-jamie_session'


class HttpError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class App:
    def __init__(self, config, panel=None):
        self.config = config
        self.ledger = Ledger(config['database'])
        self.ledger.package_billing = self.ledger.package_billing or bool(
            config.get('package_billing', False)
        )
        self.panel = panel or Panel(config)
        self.content = Content(self.ledger)
        self.monitor = NodeMonitor(self.panel)
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
                db.execute(
                    """INSERT INTO members(id,panel_email,panel_auth,sub_id,created)
                    VALUES(?,?,?,?,?)""",
                    (
                        member_id,
                        'jn_' + secrets.token_hex(12),
                        secrets.token_hex(24),
                        secrets.token_hex(24),
                        int(time.time()),
                    ),
                )
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
            return {key: card[key] for key in ('label', 'quota', 'days')}

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
                    db.execute(
                        """INSERT INTO members
                        (id,panel_email,panel_auth,sub_id,quota,expires,revision,created)
                        VALUES(?,?,?,?,?,?,1,?)""",
                        (
                            uid,
                            'jn_' + secrets.token_hex(12),
                            secrets.token_hex(24),
                            secrets.token_hex(24),
                            card['quota'],
                            now + card['days'] * 86400,
                            now,
                        ),
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
                    """SELECT label,quota,days,kind,redeemed_at
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
        if member['revision']:
            try:
                current = self.panel.get(member['panel_email'])
                used = current['usedTraffic']
                panel_enabled = current['client']['enable']
            except Exception:
                error = '暂时无法读取节点用量，请稍后刷新'
        billing = self.ledger.billing_snapshot(account['id'])
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
                'expires': member['expires'],
                'billing': billing,
                'pending': member['revision'] > member['synced_revision'],
                'sync_error': member['sync_error'],
                'usage_error': error,
                'enabled': panel_enabled,
                'rotating': bool(member['previous_sub_id']),
                'plan_name': base_plan['label'] if base_plan else None,
                'url': self.config['origin'] + '/sub/' + member['sub_id']
                if member['synced_revision'] > 0
                and not member['disabled']
                and not member['previous_sub_id']
                else None,
            },
            'history': history,
            'nodes': ['🇯🇵 日本 · 东京', '🇸🇬 新加坡', '🇲🇾 马来西亚 · 柔佛'],
        }

    def sync_loop(self):
        while True:
            try:
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

    def refresh_billing(self):
        values = {}
        with self.ledger.billing_lock:
            try:
                for row in self.panel.request('clients/list'):
                    stat = row.get('traffic')
                    if stat and type(stat.get('up')) is int and type(stat.get('down')) is int:
                        values[row['email']] = stat['up'] + stat['down']
            except Exception:
                pass  # Expiration processing still runs when sampling is down.
            self.ledger.sample_billing(values)


class Handler(BaseHTTPRequestHandler):
    server_version = 'JamieNode'
    sys_version = ''

    def log_message(self, *_args):
        pass  # No passwords, card codes, cookies, or subscription URLs in logs.

    def reply(self, status, data, token=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if token is not None:
            self.send_header(
                'Set-Cookie',
                f'{COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={604800 if token else 0}',
            )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.handle_api(False)

    def do_POST(self):
        self.handle_api(True)

    def handle_api(self, write):
        try:
            self.route(write)
        except HttpError as exc:
            self.reply(exc.status, {'error': exc.message})
        except DomainError as exc:
            self.reply(400, {'error': str(exc)})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.reply(400, {'error': '请求参数不正确'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            print('API error:', type(exc).__name__, flush=True)
            self.reply(503, {'error': '服务暂时不可用，请稍后重试'})

    def route(self, write):
        app = self.server.app
        path = urlsplit(self.path).path
        ip = self.headers.get('X-Real-IP', self.client_address[0])
        if not write and path == '/api/health':
            return self.reply(200, {'ok': True})
        app.limit('request:' + ip, 240, 60)
        if not write and path == '/api/content':
            return self.reply(200, app.content.read())
        data = {}
        if write:
            if (
                self.headers.get('Origin') != app.config['origin']
                or self.headers.get('X-Jamie-Request') != '1'
                or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'
            ):
                raise HttpError(403, '请求来源校验失败，请刷新页面')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                raise HttpError(413, '请求过大')
            self.connection.settimeout(10)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise HttpError(400, '请求格式不正确')
        if write and path == '/api/register/preview':
            app.limit('card-preview:' + ip, 10, 900)
            return self.reply(200, app.card_preview(data.get('code')))
        if write and path == '/api/email/code':
            return self.reply(
                200,
                app.email_auth.request(
                    data.get('email'), data.get('purpose'), ip, data.get('code')
                ),
            )
        if write and path == '/api/email/reset':
            app.limit('email-reset:' + ip, 10, 900)
            app.email_auth.reset(
                data.get('email'), data.get('email_code'), data.get('new_password')
            )
            return self.reply(200, {'ok': True})
        if write and path == '/api/recover':
            app.limit('recover:' + ip, 5, 900)
            username = text(data.get('username'), 254).lower()
            app.limit('recover-user:' + username, 5, 900)
            with app.password_lock:
                hashed = hash_password(data.get('new_password'))
            app.features.recovery_reset(username, data.get('code'), hashed)
            return self.reply(200, {'ok': True})
        if write and path in ('/api/login', '/api/register'):
            username = str(data.get('username', '')).strip().lower()
            if len(username) > 254:
                raise DomainError('账号格式不正确')
            try:
                app.limit('auth:' + ip, 15, 900)
                app.limit('username:' + username, 20, 900)
            except HttpError:
                if path == '/api/login':
                    app.operations.login_event(username, 'rate_limited')
                raise
            password = data.get('password', '')
            if path == '/api/register':
                if not app.email_auth.enabled:
                    raise HttpError(503, '邮箱验证服务暂不可用，请稍后注册')
                app.limit('register:' + ip, 5, 3600)
                token = app.register_with_card(
                    username,
                    password,
                    data.get('code'),
                    self.headers.get('User-Agent', ''),
                    ip,
                    email_code=data.get('email_code'),
                )
                return self.reply(200, {'ok': True}, token)
            else:
                with app.ledger.connect() as db:
                    account = db.execute(
                        """SELECT a.*,m.disabled FROM accounts a JOIN members m
                        ON a.id=m.id WHERE username=?""",
                        (username,),
                    ).fetchone()
                with app.password_lock:
                    valid = verify_password(
                        password, account['password'] if account else app.dummy_hash
                    )
                if not valid or not account or account['disabled']:
                    app.operations.login_event(
                        username,
                        'unknown_user'
                        if not account
                        else 'disabled'
                        if account['disabled']
                        else 'wrong_password',
                    )
                    raise HttpError(401, '邮箱或密码不正确，或账号已停用')
                account_id = account['id']
                app.operations.login_event(username, 'success')
            return self.reply(
                200,
                {'ok': True},
                app.new_session(account_id, self.headers.get('User-Agent', ''), ip),
            )
        cookies = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
        token = cookies[COOKIE].value if COOKIE in cookies else ''
        account = app.session(token)
        if not account:
            raise HttpError(401, '请先登录')
        if write and path == '/api/logout':
            with app.ledger.connect() as db:
                db.execute(
                    'DELETE FROM sessions WHERE digest=?',
                    (hashlib.sha256(token.encode()).hexdigest(),),
                )
            return self.reply(200, {'ok': True}, '')
        if write and path == '/api/password':
            app.limit('password:' + account['id'], 5, 900)
            with app.password_lock:
                if not verify_password(data.get('old_password'), account['password']):
                    raise DomainError('当前密码不正确')
                hashed = hash_password(data.get('new_password'))
            with app.ledger.transaction() as db:
                db.execute(
                    'UPDATE accounts SET password=?,must_change=0 WHERE id=?',
                    (hashed, account['id']),
                )
                db.execute('DELETE FROM sessions WHERE account_id=?', (account['id'],))
                app.ledger.audit(db, account['id'], 'account.password', account['id'])
            return self.reply(
                200,
                {'ok': True},
                app.new_session(account['id'], self.headers.get('User-Agent', ''), ip),
            )
        if not write and path == '/api/me':
            return self.reply(200, app.overview(account))
        if not write and path == '/api/nodes':
            return self.reply(200, app.monitor.snapshot())
        if account['must_change']:
            raise HttpError(403, '请先修改初始密码')
        if not write and path == '/api/usage':
            return self.reply(200, app.features.usage(account['id']))
        if not write and path == '/api/service-status':
            return self.reply(200, app.features.service_status())
        if not write and path == '/api/sessions':
            return self.reply(200, app.features.sessions(account, token))
        if write and path == '/api/account/delete':
            return self.reply(
                202,
                app.account_deletion.request(
                    account, account['id'], data.get('confirmation'), data.get('password')
                ),
                '',
            )
        if write and path == '/api/account/email/code':
            app.reauthenticate(account, data.get('password'))
            if data.get('purpose') not in ('change_old', 'change_new'):
                raise DomainError('无效验证码用途')
            return self.reply(
                200,
                app.email_auth.request(data.get('email'), data.get('purpose'), ip, owner=account),
            )
        if write and path == '/api/account/email':
            app.reauthenticate(account, data.get('password'))
            app.email_auth.change(
                account, data.get('email'), data.get('new_code'), data.get('old_code')
            )
            return self.reply(
                200,
                {'ok': True},
                app.new_session(account['id'], self.headers.get('User-Agent', ''), ip),
            )
        if write and path == '/api/sessions/revoke':
            app.limit('sessions:' + account['id'], 20, 600)
            app.features.revoke_session(account, data.get('id'), token)
            return self.reply(200, {'ok': True})
        if write and path == '/api/recovery-code':
            app.reauthenticate(account, data.get('password'))
            return self.reply(200, app.features.recovery_generate(account))
        if write and path in ('/api/subscription/reset', '/api/subscription/reset-credentials'):
            app.reauthenticate(account, data.get('password'))
            app.limit('rotate:' + account['id'], 3, 86400)
            app.features.rotate(account['id'], credentials=path.endswith('reset-credentials'))
            return self.reply(200, {'ok': True})
        if write and path == '/api/redeem/preview':
            app.limit('redeem:' + account['id'], 10, 600)
            with app.ledger.billing_lock:
                if app.ledger.package_billing:
                    app.refresh_billing()
                return self.reply(
                    200, app.features.preview(account['id'], data.get('code'), data.get('target'))
                )
        if path == '/api/tickets':
            if write:
                app.limit('ticket:' + account['id'], 20, 3600)
                return self.reply(200, app.features.ticket_write(account, data))
            tid = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
            return self.reply(
                200, app.features.ticket(account, tid) if tid else app.features.tickets(account)
            )
        if path == '/api/notifications':
            if write and type(data.get('ticket_email')) is not bool:
                raise DomainError('无效提醒设置')
            return self.reply(
                200,
                app.ticket_notifications.preferences(
                    account, data.get('ticket_email') if write else None
                ),
            )
        if write and path == '/api/tickets/read':
            app.features.ticket_read(account, data.get('id'), data.get('message_id'))
            return self.reply(200, {'ok': True})
        if write and path == '/api/redeem':
            app.limit('redeem:' + account['id'], 10, 600)
            code = data.get('code', '')
            if not isinstance(code, str) or len(code) > 100:
                raise DomainError('卡密格式不正确')
            with app.ledger.billing_lock:
                if app.ledger.package_billing:
                    app.refresh_billing()
                result = app.ledger.redeem(account['id'], code, target=data.get('target'))
            app.wake.set()
            return self.reply(200, result)
        if path.startswith('/api/admin/'):
            if not account['admin']:
                raise HttpError(403, '仅管理员可访问')
            if write and path == '/api/admin/user-delete':
                return self.reply(
                    202,
                    app.account_deletion.request(
                        account,
                        text(data.get('id'), 64),
                        data.get('confirmation'),
                        data.get('password'),
                    ),
                )
            if write and path in ('/api/admin/card-search', '/api/admin/login-diagnosis'):
                app.limit('diagnostics:' + account['id'], 60, 60)
                return self.reply(
                    200,
                    app.operations.cards(data)
                    if path.endswith('card-search')
                    else app.operations.login_diagnosis(data),
                )
            if not write and path == '/api/admin/readiness':
                return self.reply(200, app.operations.readiness())
            if not write and path == '/api/admin/users':
                return self.reply(200, app.users.listing(parse_qs(urlsplit(self.path).query)))
            if not write and path == '/api/admin/user':
                return self.reply(
                    200, app.users.detail(parse_qs(urlsplit(self.path).query).get('id', [''])[0])
                )
            if write and path in ('/api/admin/user-sessions', '/api/admin/user-sync'):
                app.limit('user-action:' + account['id'], 20, 600)
                uid = text(data.get('id'), 64)
                with app.ledger.transaction() as db:
                    target = db.execute(
                        'SELECT a.admin,m.* FROM accounts a JOIN members m ON m.id=a.id WHERE a.id=?',
                        (uid,),
                    ).fetchone()
                    if not target or target['admin']:
                        raise DomainError('只能操作普通用户')
                    if target['deleting']:
                        raise DomainError('账号删除处理中，不能修改状态')
                    if path.endswith('user-sessions'):
                        db.execute('DELETE FROM sessions WHERE account_id=?', (uid,))
                        app.ledger.audit(db, account['id'], 'account.revoke_sessions', uid)
                    else:
                        if target['revision'] <= target['synced_revision']:
                            return self.reply(200, {'pending': False})
                        app.ledger.audit(db, account['id'], 'account.retry_sync', uid)
                if path.endswith('user-sync'):
                    app.wake.set()
                return self.reply(200, {'ok': True, 'pending': path.endswith('user-sync')})
            if not write and path == '/api/admin/operations':
                return self.reply(200, app.features.operations())
            if write and path == '/api/admin/incident':
                app.limit('incident:' + account['id'], 30, 600)
                return self.reply(200, app.features.incident_save(account, data))
            if path == '/api/admin/tickets':
                if write:
                    app.limit('ticket:' + account['id'], 60, 3600)
                    return self.reply(200, app.features.ticket_write(account, data, True))
                tid = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
                return self.reply(
                    200,
                    app.features.ticket(account, tid, True)
                    if tid
                    else app.features.tickets(account, True),
                )
            if not write and path == '/api/admin/content':
                return self.reply(200, app.content.read(admin=True))
            if write and path in ('/api/admin/plan', '/api/admin/notice', '/api/admin/support'):
                app.limit('content:' + account['id'], 60, 60)
                item_id = app.content.save(account['id'], path.rsplit('/', 1)[-1], data)
                return self.reply(200, {'ok': True, 'id': item_id})
            if write and path == '/api/admin/cards':
                app.limit('issue:' + account['id'], 10, 60)
                plan = app.content.plan_for_card(data['plan_id']) if data.get('plan_id') else data
                codes = app.ledger.issue(
                    account['id'],
                    plan.get('name', plan.get('label')),
                    plan['quota_gib'],
                    plan.get('days', 1),
                    data['count'],
                    data['valid_days'],
                    kind=plan.get('kind', 'base'),
                )
                return self.reply(200, {'codes': codes})
            if write and path == '/api/admin/revoke':
                app.ledger.revoke(account['id'], data['id'])
                return self.reply(200, {'ok': True})
            if write and path == '/api/admin/member':
                member_id = data['id']
                if member_id == account['id']:
                    raise DomainError('不能停用自己的管理员账号')
                if type(data.get('disabled')) is not bool:
                    raise DomainError('无效状态')
                with app.ledger.transaction() as db:
                    target = db.execute(
                        'SELECT * FROM accounts WHERE id=?', (member_id,)
                    ).fetchone()
                    if not target or target['admin']:
                        raise DomainError('只能操作普通用户')
                    state = db.execute(
                        'SELECT disabled,deleting FROM members WHERE id=?', (member_id,)
                    ).fetchone()
                    if state['deleting']:
                        raise DomainError('账号删除处理中，不能修改状态')
                    state = state['disabled']
                    if 'expected_disabled' in data and (
                        type(data['expected_disabled']) is not bool
                        or data['expected_disabled'] != bool(state)
                    ):
                        raise DomainError('用户状态已改变，请刷新详情后重试')
                    db.execute(
                        """UPDATE members SET disabled=?,
                        sync_error=NULL,revision=revision+CASE WHEN quota>0 AND disabled!=? THEN 1 ELSE 0 END WHERE id=?""",
                        (int(data['disabled']), int(data['disabled']), member_id),
                    )
                    db.execute('DELETE FROM sessions WHERE account_id=?', (member_id,))
                    app.ledger.audit(
                        db,
                        account['id'],
                        'account.disable' if data['disabled'] else 'account.enable',
                        member_id,
                    )
                app.wake.set()
                return self.reply(200, {'ok': True})
            if write and path == '/api/admin/reset-password':
                app.limit('reset-password:' + account['id'], 20, 600)
                new_password = secrets.token_urlsafe(15)
                with app.password_lock:
                    hashed = hash_password(new_password)
                with app.ledger.transaction() as db:
                    target = db.execute(
                        'SELECT a.*,m.deleting FROM accounts a JOIN members m ON m.id=a.id WHERE a.id=? AND a.admin=0', (data['id'],)
                    ).fetchone()
                    if not target:
                        raise DomainError('用户不存在')
                    if target['deleting']:
                        raise DomainError('账号正在删除，不能重置密码')
                    db.execute(
                        'UPDATE accounts SET password=?,must_change=1 WHERE id=?',
                        (hashed, data['id']),
                    )
                    db.execute('DELETE FROM sessions WHERE account_id=?', (data['id'],))
                    db.execute('DELETE FROM recovery_codes WHERE account_id=?', (data['id'],))
                    app.ledger.audit(db, account['id'], 'account.reset_password', data['id'])
                return self.reply(200, {'password': new_password})
            if not write and path in ('/api/admin/overview', '/api/admin/cards-overview'):
                with app.ledger.connect() as db:
                    cards = [
                        dict(r)
                        for r in db.execute("""SELECT c.id,c.suffix,c.label,c.quota,c.days,
                        c.redeem_before,c.created,c.redeemed_at,c.revoked_at,a.username AS redeemed_by
                        FROM cards c LEFT JOIN accounts a ON a.id=c.redeemed_by ORDER BY c.created DESC,c.id LIMIT 500""")
                    ]
                    members = (
                        [
                            dict(r)
                            for r in db.execute("""SELECT a.id,a.username,a.admin,m.quota,m.expires,m.panel_email,
                        m.disabled,m.revision,m.synced_revision,m.sync_error FROM accounts a JOIN members m
                        ON a.id=m.id ORDER BY m.created DESC LIMIT 500""")
                        ]
                        if path.endswith('/overview')
                        else []
                    )
                    audit = [
                        dict(r)
                        for r in db.execute("""SELECT a.action,a.target,a.created,
                        COALESCE(u.username,a.actor) AS actor FROM audit a LEFT JOIN accounts u
                        ON u.id=a.actor ORDER BY a.id DESC LIMIT 100""")
                    ]
                if path.endswith('/cards-overview'):
                    return self.reply(200, {'cards': cards, 'audit': audit})
                traffic = {}
                try:
                    traffic = {
                        c['email']: c.get('traffic') for c in app.panel.request('clients/list')
                    }
                except Exception:
                    pass
                for member in members:
                    stat = traffic.get(member.pop('panel_email'))
                    member['used'] = (stat.get('up', 0) + stat.get('down', 0)) if stat else None
                return self.reply(200, {'cards': cards, 'members': members, 'audit': audit})
        raise HttpError(404, '页面不存在')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app):
        self.app = app
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        super().process_request(request, address)

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/jamie-portal.json')
    parser.add_argument('--bootstrap-admin', action='store_true')
    parser.add_argument('--backup')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    app = App(config)
    if args.backup:
        with app.ledger.connect() as src:
            dst = sqlite3.connect(args.backup)
            src.backup(dst)
            dst.close()
        return
    if args.bootstrap_admin:
        with app.ledger.connect() as db:
            if db.execute('SELECT 1 FROM accounts WHERE admin=1').fetchone():
                raise SystemExit('Admin already exists; no changes made')
        password = secrets.token_urlsafe(20)
        app.register('jamie', password, admin=True)
        print(json.dumps({'username': 'jamie', 'password': password}))
        return
    threading.Thread(target=app.sync_loop, daemon=True).start()
    threading.Thread(target=app.monitor.run, daemon=True).start()
    threading.Thread(target=app.features.loop, daemon=True).start()
    Server(('127.0.0.1', config.get('port', 18766)), app).serve_forever()


if __name__ == '__main__':
    main()
