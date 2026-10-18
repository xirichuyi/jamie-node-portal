"""Redemption receipts: one email per account batch of newly redeemed or granted cards.

Receipts are transactional (not marketing), so they ignore reminder opt-outs but still
require a verified address and an active account. The collector scans recent card
redemptions, so it needs no hook inside the billing transaction.
"""

import datetime
import hashlib
import time

from email_templates import service_email
from errors import DomainError

TZ = datetime.timezone(datetime.timedelta(hours=8))
FOREVER = 253402185600


def when(ts):
    if ts >= FOREVER:
        return '永久有效'
    return datetime.datetime.fromtimestamp(ts, TZ).strftime('%Y-%m-%d %H:%M')


def gib(n):
    return f'{n / 1024**3:.2f}'.rstrip('0').rstrip('.') + ' GiB'


class ReceiptNotifications:
    def __init__(self, app):
        self.app = app
        with app.ledger.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS receipt_mail_queue (
                    card_id TEXT PRIMARY KEY REFERENCES cards(id),
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    created INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS receipt_mail_state (
                    id INTEGER PRIMARY KEY CHECK(id=1), watermark INTEGER NOT NULL
                );
            """)
            # First start covers redemptions since midnight (Beijing time) of that day.
            today = datetime.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            db.execute(
                'INSERT OR IGNORE INTO receipt_mail_state VALUES(1,?)', (int(today.timestamp()),)
            )

    def collect(self, now=None):
        now = int(time.time()) if now is None else now
        with self.app.ledger.transaction() as db:
            watermark = db.execute('SELECT watermark FROM receipt_mail_state WHERE id=1').fetchone()[0]
            # Keep scans small; anything older than two days is no longer worth a receipt.
            since = max(watermark, now - 2 * 86400)
            db.execute(
                """INSERT OR IGNORE INTO receipt_mail_queue(card_id,account_id,created)
                SELECT c.id,c.redeemed_by,? FROM cards c
                WHERE c.redeemed_by IS NOT NULL AND c.redeemed_at>=?
                AND NOT EXISTS(SELECT 1 FROM receipt_mail_queue q WHERE q.card_id=c.id)""",
                (now, since),
            )
            db.execute("DELETE FROM receipt_mail_queue WHERE status!='pending' AND created<?", (now - 30 * 86400,))

    def content(self, db, uid, card_ids, now):
        cards = []
        for cid in card_ids:
            c = db.execute(
                """SELECT c.*,p.expires AS package_expires,p.kind AS package_kind
                FROM cards c LEFT JOIN entitlement_packages p ON p.card_id=c.id WHERE c.id=?""",
                (cid,),
            ).fetchone()
            if c:
                cards.append(c)
        if not cards:
            return None
        paragraphs, details = [], []
        for c in cards:
            granted = bool(c['granted'])
            source = '管理员为你发放了' if granted else '你已成功兑换'
            line = f'{source}「{c["label"]}」：+{gib(c["quota"])}'
            if c['kind'] == 'addon':
                line += '，加到现有套餐，不延长有效期'
                if c['package_expires']:
                    line += f'，随所属套餐于 {when(c["package_expires"])} 到期'
            elif c['package_expires']:
                start = (
                    c['package_expires'] - c['days'] * 86400
                    if not c['permanent'] and c['package_expires'] < FOREVER
                    else c['redeemed_at']
                )
                if start > c['redeemed_at'] + 60:
                    line += f'。该套餐接在现有套餐之后，从 {when(start)} 开始计时，有效期至 {when(c["package_expires"])}'
                else:
                    line += f'，有效期至 {when(c["package_expires"])}'
            paragraphs.append(line + '。')
        if self.app.ledger.package_billing:
            from package_ledger import snapshot

            state = snapshot(db, uid, now)
            if state:
                live = [p for p in state['packages'] if not p['revoked'] and p['expires'] > now]
                dated = [p['expires'] for p in live if p['kind'] in ('base', 'transition')]
                details.append(('当前可用流量', gib(state['remaining'])))
                if dated:
                    details.append(('服务截止', when(max(dated)) + '（北京时间）'))
        paragraphs.append('流量兑换后立即可用。如果客户端还没有导入订阅，登录后在首页一键导入即可。')
        title = '套餐已到账' if any(c['granted'] for c in cards) else '兑换成功'
        return service_email(
            title,
            '\n\n'.join(paragraphs),
            self.app.config['origin'],
            details=details,
            action=('查看我的订阅', '/#/home'),
            footer='这是你兑换或获得套餐后的到账通知。邮件不包含订阅链接，请勿转发卡密。',
            eyebrow='到账通知',
        )

    def deliver_pending(self, now=None):
        if not self.app.email_auth.enabled:
            return
        now = int(time.time()) if now is None else now
        with self.app.account_lifecycle_lock:
            with self.app.ledger.connect() as db:
                accounts = [
                    r[0]
                    for r in db.execute(
                        """SELECT DISTINCT account_id FROM receipt_mail_queue
                        WHERE status='pending' AND next_attempt<=? LIMIT 10""",
                        (now,),
                    )
                ]
            for uid in accounts:
                with self.app.ledger.transaction() as db:
                    items = db.execute(
                        """SELECT * FROM receipt_mail_queue WHERE account_id=? AND status='pending'
                        ORDER BY created,card_id""",
                        (uid,),
                    ).fetchall()
                    ids = [i['card_id'] for i in items]
                    marks = ','.join('?' for _ in ids)
                    recipient = db.execute(
                        """SELECT v.email FROM verified_emails v JOIN members m ON m.id=v.account_id
                        WHERE m.id=? AND m.disabled=0 AND m.deleting=0""",
                        (uid,),
                    ).fetchone()
                    attempts = max(i['attempts'] for i in items)
                    stale = now - min(i['created'] for i in items) > 23 * 3600 or attempts >= 5
                    content = self.content(db, uid, ids, now) if recipient and not stale else None
                    if not content:
                        db.execute(
                            f'UPDATE receipt_mail_queue SET status=? WHERE card_id IN ({marks})',
                            ('failed' if stale and recipient else 'cancelled', *ids),
                        )
                        continue
                    db.execute(
                        f'UPDATE receipt_mail_queue SET attempts=attempts+1,next_attempt=? WHERE card_id IN ({marks})',
                        (now + min(3600, 300 * 2**attempts), *ids),
                    )
                key = 'receipt-' + hashlib.sha256(','.join(sorted(ids)).encode()).hexdigest()[:32]
                try:
                    self.app.email_auth.deliver(recipient['email'], content, key)
                except DomainError:
                    if attempts < 4:
                        continue
                    status = 'failed'
                else:
                    status = 'sent'
                with self.app.ledger.transaction() as db:
                    db.execute(
                        f'UPDATE receipt_mail_queue SET status=? WHERE card_id IN ({marks})',
                        (status, *ids),
                    )

    def run(self):
        self.collect()
        self.deliver_pending()
