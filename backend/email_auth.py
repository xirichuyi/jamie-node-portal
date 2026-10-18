"""Email challenges; no passwords, card codes or plaintext OTPs are persisted here."""

import hashlib
import hmac
import json
import re
import secrets
import time
import urllib.error
import urllib.request

from errors import DomainError
from passwords import hash_password
from email_templates import verification_email


def email_address(value):
    if not isinstance(value, str):
        raise DomainError('请输入有效邮箱地址')
    value = value.strip().lower()
    if (
        len(value) > 254
        or not re.fullmatch(
            r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}",
            value,
        )
        or '..' in value
    ):
        raise DomainError('请输入有效邮箱地址')
    return value


class EmailAuth:
    def __init__(self, app):
        self.app = app
        self.config = app.config.get('mail', {})
        self.enabled = bool(self.config.get('api_key') and self.config.get('from'))
        with app.ledger.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS email_challenges (
                    email TEXT NOT NULL, purpose TEXT NOT NULL, id TEXT NOT NULL,
                    digest TEXT NOT NULL, expires INTEGER NOT NULL, attempts INTEGER NOT NULL,
                    ready INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(email,purpose)
                );
                CREATE TABLE IF NOT EXISTS verified_emails (
                    account_id TEXT PRIMARY KEY REFERENCES accounts(id),
                    email TEXT NOT NULL UNIQUE, verified_at INTEGER NOT NULL
                );
            """)
            if self.enabled:
                db.execute(
                    """UPDATE portal_notices SET body=?,updated=?,revision=revision+1
                    WHERE id='welcome' AND body=?""",
                    (
                        '使用卡密即可开通账号：先验证卡密查看套餐，再填写邮箱和密码，完成邮箱验证后确认开通。有效期从开通成功时开始。开通后按教程导入客户端；已有账号请登录后兑换续费。请勿公开分享验证码、卡密或订阅链接。',
                        int(time.time()),
                        '使用卡密即可开通账号：先验证卡密查看套餐，再设置用户名和密码。有效期从确认开通时开始，开通后按教程导入客户端。已有账号请登录后兑换续费。请勿公开分享卡密或订阅链接。',
                    ),
                )

    def digest(self, email, purpose, challenge, code):
        return hmac.new(
            self.config['api_key'].encode(),
            json.dumps([email, purpose, challenge, code]).encode(),
            hashlib.sha256,
        ).hexdigest()

    def send(self, email, purpose, code, challenge):
        self.deliver(
            email,
            verification_email('change' if purpose.startswith('change_') else purpose, code),
            'email-challenge-' + challenge,
        )

    def deliver(self, email, content, key):
        payload = {
            'from': self.config['from'],
            'to': [email],
            **content,
        }
        if self.config.get('reply_to'):
            payload['reply_to'] = self.config['reply_to']
        request = urllib.request.Request(
            'https://api.resend.com/emails',
            data=json.dumps(payload).encode(),
            method='POST',
            headers={
                'Authorization': 'Bearer ' + self.config['api_key'],
                'Content-Type': 'application/json',
                'User-Agent': 'Jamie-Node/1.0',
                'Idempotency-Key': key,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if not json.load(response).get('id'):
                    raise ValueError('Missing delivery id')
        except (OSError, ValueError):
            raise DomainError('邮件暂时无法发送，请稍后重试') from None

    def change_purpose(self, account, purpose):
        fingerprint = hashlib.sha256(
            (account['username'] + account['password']).encode()
        ).hexdigest()[:20]
        return purpose + ':' + account['id'] + ':' + fingerprint

    def request(self, email, purpose, ip, card=None, owner=None):
        if not self.enabled:
            raise DomainError('邮件服务暂未开放')
        if purpose not in ('register', 'reset', 'change_old', 'change_new'):
            raise DomainError('无效验证码用途')
        changing = purpose.startswith('change_')
        if changing:
            if not owner:
                raise DomainError('请先登录并验证身份')
            if purpose == 'change_old':
                with self.app.ledger.connect() as db:
                    old = db.execute(
                        'SELECT email FROM verified_emails WHERE account_id=?', (owner['id'],)
                    ).fetchone()
                if not old:
                    raise DomainError('尚未绑定邮箱')
                email = old['email']
        email = email_address(email)
        app = self.app
        app.limit('mail-ip:' + ip, 5, 3600)
        app.limit('mail-cooldown:' + email, 1, 60)
        app.limit('mail-address:' + email, 5, 86400)
        if purpose == 'register':
            app.card_preview(card)
        with app.ledger.connect() as db:
            account = db.execute('SELECT id FROM accounts WHERE username=?', (email,)).fetchone()
            verified = db.execute(
                'SELECT account_id FROM verified_emails WHERE email=?', (email,)
            ).fetchone()
        # Uniform response: do not disclose whether a mailbox has an account.
        if (purpose == 'register' and account) or (purpose == 'reset' and not verified):
            return {'ok': True, 'retry_after': 60}
        if purpose == 'change_new' and (account or verified):
            raise DomainError('该邮箱无法用于换绑，请使用其他邮箱')
        if changing:
            purpose = self.change_purpose(owner, purpose)
        app.limit('mail-global', 90, 86400)
        code, challenge = f'{secrets.randbelow(1000000):06d}', secrets.token_hex(24)
        with app.ledger.transaction() as db:
            db.execute('DELETE FROM email_challenges WHERE expires<?', (int(time.time()),))
            db.execute(
                'INSERT OR REPLACE INTO email_challenges VALUES(?,?,?,?,?,0,0)',
                (
                    email,
                    purpose,
                    challenge,
                    self.digest(email, purpose, challenge, code),
                    int(time.time()) + 600,
                ),
            )
        self.send(email, purpose, code, challenge)
        with app.ledger.transaction() as db:
            db.execute('UPDATE email_challenges SET ready=1 WHERE id=?', (challenge,))
        return {'ok': True, 'retry_after': 60}

    def change(self, account, email, new_code, old_code):
        if not self.enabled:
            raise DomainError('邮件服务暂未开放')
        email = email_address(email)
        with self.app.ledger.connect() as db:
            old = db.execute(
                'SELECT email FROM verified_emails WHERE account_id=?', (account['id'],)
            ).fetchone()
        old_challenge = (
            self.check(old['email'], self.change_purpose(account, 'change_old'), old_code)
            if old
            else None
        )
        challenge = self.check(email, self.change_purpose(account, 'change_new'), new_code)
        with self.app.account_lifecycle_lock, self.app.ledger.transaction() as db:
            current = db.execute(
                'SELECT a.username,a.password,m.disabled FROM accounts a JOIN members m ON m.id=a.id WHERE a.id=?',
                (account['id'],),
            ).fetchone()
            if (
                not current
                or current['disabled']
                or current['username'] != account['username']
                or current['password'] != account['password']
            ):
                raise DomainError('账号状态已变化，请重新登录')
            if (
                db.execute('SELECT 1 FROM accounts WHERE username=?', (email,)).fetchone()
                or db.execute('SELECT 1 FROM verified_emails WHERE email=?', (email,)).fetchone()
            ):
                raise DomainError('该邮箱无法用于换绑，请使用其他邮箱')
            if old_challenge:
                self.consume(db, old_challenge)
            self.consume(db, challenge)
            db.execute('UPDATE accounts SET username=? WHERE id=?', (email, account['id']))
            db.execute(
                'INSERT OR REPLACE INTO verified_emails VALUES(?,?,?)',
                (account['id'], email, int(time.time())),
            )
            db.execute('DELETE FROM sessions WHERE account_id=?', (account['id'],))
            db.execute('DELETE FROM recovery_codes WHERE account_id=?', (account['id'],))
            self.app.ledger.audit(db, account['id'], 'account.email_changed', account['id'])
            db.execute(
                "UPDATE ticket_mail_queue SET status='cancelled' WHERE account_id=? AND status='pending'",
                (account['id'],),
            )
            db.execute(
                "UPDATE subscription_mail_queue SET status='cancelled' WHERE account_id=? AND status='pending'",
                (account['id'],),
            )

    def check(self, email, purpose, code):
        email = email_address(email)
        if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
            raise DomainError('请输入 6 位邮箱验证码')
        valid, challenge = False, None
        with self.app.ledger.transaction() as db:
            row = db.execute(
                'SELECT * FROM email_challenges WHERE email=? AND purpose=?', (email, purpose)
            ).fetchone()
            if row and row['ready'] and row['expires'] > int(time.time()) and row['attempts'] < 5:
                db.execute(
                    'UPDATE email_challenges SET attempts=attempts+1 WHERE id=?', (row['id'],)
                )
                valid = hmac.compare_digest(
                    row['digest'], self.digest(email, purpose, row['id'], code)
                )
                challenge = row['id']
        if not valid:
            raise DomainError('验证码错误、已过期或尝试次数过多，请重新获取')
        return challenge

    def consume(self, db, challenge):
        # Same transaction as account/card changes: concurrent replays cannot succeed.
        result = db.execute(
            'DELETE FROM email_challenges WHERE id=? AND ready=1 AND expires>?',
            (challenge, int(time.time())),
        )
        if result.rowcount != 1:
            raise DomainError('验证码已使用或过期，请重新获取')

    def reset(self, email, code, password):
        email = email_address(email)
        challenge = self.check(email, 'reset', code)
        with self.app.password_lock:
            hashed = hash_password(password)
        with self.app.ledger.transaction() as db:
            account = db.execute(
                'SELECT account_id FROM verified_emails WHERE email=?', (email,)
            ).fetchone()
            if not account:
                raise DomainError('无法重设密码，请联系管理员')
            uid = account['account_id']
            self.consume(db, challenge)
            db.execute('UPDATE accounts SET password=?,must_change=0 WHERE id=?', (hashed, uid))
            db.execute('DELETE FROM sessions WHERE account_id=?', (uid,))
            db.execute('DELETE FROM recovery_codes WHERE account_id=?', (uid,))
            self.app.ledger.audit(db, uid, 'account.email_password_reset', uid)
