"""Durable checkout, authenticated reconciliation and atomic card/package delivery."""

import hashlib
import hmac
import json
import re
import threading
import time
import secrets

from errors import DomainError
from http_types import HttpError
from payment_gateway import Gateway, micros, amount_text


class Payments:
    def __init__(self, app):
        self.app = app
        self.config = app.config.get('payments', {})
        self.gateway = Gateway(self.config)
        self.lock = threading.RLock()
        self.enabled = bool(self.config.get('enabled') and self.config.get('api_key')
                            and self.config.get('webhook_secret') and self.config.get('card_secret')
                            and self.config.get('wallets') and app.ledger.package_billing)
        with app.ledger.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS payment_orders (
                id TEXT PRIMARY KEY, account_id TEXT REFERENCES accounts(id), guest INTEGER NOT NULL,
                request_digest TEXT NOT NULL UNIQUE, plan_id TEXT NOT NULL, plan TEXT NOT NULL,
                amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'creating',
                gateway_id TEXT UNIQUE, gateway_status TEXT NOT NULL DEFAULT '',
                card_id TEXT, created INTEGER NOT NULL, updated INTEGER NOT NULL,
                checked INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '', tx_hash TEXT NOT NULL DEFAULT '',
                pay_amount TEXT NOT NULL DEFAULT '', network TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_payment_due ON payment_orders(status,checked);
            CREATE INDEX IF NOT EXISTS idx_payment_owner ON payment_orders(account_id,created);
            ''')

    @staticmethod
    def digest(key, owner):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', key):
            raise DomainError('订单请求凭证无效，请重新打开购买页面')
        return hashlib.sha256((str(owner or 'guest') + ':' + key).encode()).hexdigest()

    def row(self, oid):
        with self.app.ledger.connect() as db:
            row = db.execute('SELECT * FROM payment_orders WHERE id=?', (oid,)).fetchone()
        if not row:
            raise HttpError(404, '订单不存在')
        return dict(row)

    def card_code(self, oid):
        raw = hmac.new(self.config['card_secret'].encode(), oid.encode(), hashlib.sha256).hexdigest()[:32].upper()
        return '-'.join(raw[i:i+8] for i in range(0, 32, 8))

    def view(self, row, reveal=False):
        plan = json.loads(row['plan'])
        result = {k: row[k] for k in ('id', 'status', 'gateway_status', 'created', 'updated', 'error',
                                     'tx_hash', 'pay_amount', 'network', 'guest')}
        result.update(label=plan['label'], amount=amount_text(row['amount']),
                      checkout_url=(self.gateway.origin + '/pay/' + row['gateway_id'])
                      if row['gateway_id'] and row['status'] in ('pending', 'confirming') else None)
        if reveal and row['guest'] and row['status'] == 'fulfilled':
            result['code'] = self.card_code(row['id'])
        return result

    def create(self, account, plan_id, key, expected_amount=None):
        if not self.enabled:
            raise DomainError('在线支付尚未开放，请联系管理员')
        owner = account['id'] if account else None
        digest = self.digest(key, owner)
        now = int(time.time())
        with self.lock, self.app.account_lifecycle_lock, self.app.ledger.transaction() as db:
            existing = db.execute('SELECT * FROM payment_orders WHERE request_digest=?', (digest,)).fetchone()
            if existing:
                if existing['plan_id'] != plan_id:
                    raise DomainError('订单对应套餐不同，请刷新后重新选择')
                return self.view(dict(existing), reveal=True)
            if owner:
                member = db.execute('SELECT * FROM members WHERE id=?', (owner,)).fetchone()
                if not member or member['disabled'] or member['deleting']:
                    raise DomainError('账号不可用，不能购买套餐')
                if db.execute("SELECT count(*) FROM payment_orders WHERE account_id=? AND status IN ('creating','pending','confirming','paid','review')", (owner,)).fetchone()[0] >= 3:
                    raise DomainError('请先处理已有的支付订单')
            plan = db.execute('SELECT * FROM portal_plans WHERE id=? AND published=1', (plan_id,)).fetchone()
            if not plan or plan['usdt_micros'] <= 0:
                raise DomainError('此套餐暂未开放在线购买')
            if expected_amount is not None and (type(expected_amount) is not int or expected_amount != plan['usdt_micros']):
                raise DomainError('套餐价格已更新，请刷新页面后重新确认')
            spec = self.app.ledger.card_spec(plan['name'], plan['quota_gib'], plan['days'], 1, 0,
                                             permanent=plan['permanent'], reset_period=plan['reset_period'],
                                             reset_interval=plan['reset_interval'])
            oid = 'sub_' + secrets.token_hex(16)
            db.execute('''INSERT INTO payment_orders
                (id,account_id,guest,request_digest,plan_id,plan,amount,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                       (oid, owner, int(not owner), digest, plan_id, json.dumps(spec), plan['usdt_micros'], now, now))
        # Persist before making any remote request; retry/reload never invents another order.
        self.sync(oid)
        return self.view(self.row(oid), reveal=True)

    def get(self, oid, account=None, access_key=None):
        row = self.row(oid)
        if row['guest']:
            if not hmac.compare_digest(row['request_digest'], self.digest(access_key, None)):
                raise HttpError(404, '订单不存在或领取凭证不正确')
        elif not account or row['account_id'] != account['id']:
            raise HttpError(404, '订单不存在')
        return self.view(row, reveal=True)

    def listing(self, account, page=1):
        try:
            page = max(1, min(100000, int(page)))
        except (ValueError, TypeError):
            raise DomainError('页码无效') from None
        where, params = ' WHERE account_id=?', (account['id'],)
        with self.app.ledger.connect() as db:
            total = db.execute('SELECT count(*) FROM payment_orders' + where, params).fetchone()[0]
            rows = db.execute('SELECT * FROM payment_orders' + where + ' ORDER BY created DESC,id LIMIT 30 OFFSET ?',
                              (*params, (page - 1) * 30)).fetchall()
        items = [self.view(dict(row)) for row in rows]
        return {'items': items, 'total': total, 'page': page, 'pages': max(1, (total + 29) // 30), 'enabled': self.enabled}

    ADMIN_STATUSES = ('creating', 'pending', 'confirming', 'paid', 'review', 'fulfilled', 'expired')

    def admin_listing(self, query):
        """Status filter and search by order id, gateway id, tx hash or username."""
        status = query.get('status', ['all'])[0]
        keyword = query.get('q', [''])[0].strip()
        try:
            page = max(1, min(100000, int(query.get('page', ['1'])[0])))
        except ValueError:
            raise DomainError('页码无效') from None
        if (status != 'all' and status not in self.ADMIN_STATUSES) or len(keyword) > 100:
            raise DomainError('筛选条件不正确')
        where, args = [], []
        if keyword:
            where.append('(o.id=? OR o.gateway_id=? OR lower(o.tx_hash)=? OR a.username=?)')
            args.extend([keyword, keyword, keyword.lower(), keyword.lower()])
        base = ' FROM payment_orders o LEFT JOIN accounts a ON a.id=o.account_id'
        with self.app.ledger.connect() as db:
            counts = dict.fromkeys(('all', *self.ADMIN_STATUSES), 0)
            for row in db.execute(
                'SELECT o.status,count(*)' + base + (' WHERE ' + ' AND '.join(where) if where else '')
                + ' GROUP BY o.status',
                args,
            ):
                counts[row[0]] = row[1]
                counts['all'] += row[1]
            if status != 'all':
                where.append('o.status=?')
                args.append(status)
            clause = (' WHERE ' + ' AND '.join(where)) if where else ''
            total = counts[status]
            pages = max(1, (total + 29) // 30)
            page = min(page, pages)
            rows = db.execute('SELECT o.*,a.username' + base + clause
                              + ' ORDER BY o.created DESC,o.id LIMIT 30 OFFSET ?',
                              (*args, (page - 1) * 30)).fetchall()
        items = []
        for row in rows:
            item = self.view(dict(row))
            item.update(account_id=row['account_id'], username=row['username'], gateway_id=row['gateway_id'],
                        card_id=row['card_id'], checked=row['checked'], attempts=row['attempts'])
            items.append(item)
        return {'items': items, 'total': total, 'page': page, 'pages': pages, 'counts': counts,
                'enabled': self.enabled}

    def admin_check(self, actor, oid):
        """Run the same authenticated lookup as the background collector, right now."""
        if not self.enabled:
            raise DomainError('在线支付尚未开放')
        row = self.row(oid)
        if row['status'] == 'fulfilled':
            raise DomainError('订单已完成，无需查单')
        self.sync(oid)
        with self.app.ledger.transaction() as db:
            self.app.ledger.audit(db, actor, 'payment.check', oid)
        updated = self.row(oid)
        return {'status': updated['status'], 'error': updated['error']}

    def summary(self):
        """Overview revenue at the original plan price; gateway tails are not income."""
        now = int(time.time())
        day = now - (now + 28800) % 86400  # Shanghai midnight
        with self.app.ledger.connect() as db:
            row = db.execute(
                """SELECT COALESCE(SUM(CASE WHEN updated>=? THEN amount END),0) AS today,
                COUNT(CASE WHEN updated>=? THEN 1 END) AS today_count,
                COALESCE(SUM(CASE WHEN updated>=? THEN amount END),0) AS month,
                COUNT(CASE WHEN updated>=? THEN 1 END) AS month_count,
                COALESCE(SUM(amount),0) AS total, COUNT(*) AS total_count
                FROM payment_orders WHERE status='fulfilled'""",
                (day, day, now - 30 * 86400, now - 30 * 86400),
            ).fetchone()
            attention = db.execute(
                "SELECT count(*) FROM payment_orders WHERE status IN ('paid','review')"
            ).fetchone()[0]
        return {
            'enabled': self.enabled,
            'today': amount_text(row['today']),
            'today_count': row['today_count'],
            'month': amount_text(row['month']),
            'month_count': row['month_count'],
            'total': amount_text(row['total']),
            'total_count': row['total_count'],
            'attention': attention,
        }

    def validate(self, row, remote):
        if (remote.get('merchant_order_id') != row['id'] or micros(remote.get('base_amount')) != row['amount']
                or not re.fullmatch(r'pay_[A-Za-z0-9_-]{8,80}', str(remote.get('id', '')))
                or (row['gateway_id'] and row['gateway_id'] != remote['id'])
                or remote.get('token') not in ('USDT', 'USDT-BSC')
                or remote.get('status') not in ('pending', 'confirming', 'completed', 'expired')):
            raise DomainError('支付订单信息不匹配，请联系管理员核对')
        if remote.get('network') or remote.get('address') or remote['status'] == 'completed':
            network = remote.get('network', '')
            address = remote.get('address', '')
            expected = self.config['wallets'].get(network)
            if network in ('binance', 'ethereum', 'polygon'):
                address, expected = address.lower(), (expected or '').lower()
            if not expected or address != expected:
                raise DomainError('收款链或收款地址未通过核对，请联系管理员')
        if remote['status'] == 'completed':
            if not remote.get('tx_hash') or not remote.get('paid_at'):
                raise DomainError('链上到账信息待核对，请联系管理员')
            if micros(remote.get('pay_amount')) < row['amount']:
                raise DomainError('到账金额不足，请联系管理员核对')

    def sync(self, oid):
        if not self.enabled:
            return
        with self.lock:
            row = self.row(oid)
            if row['status'] == 'fulfilled':
                return
            now = int(time.time())
            with self.app.ledger.transaction() as db:
                db.execute('UPDATE payment_orders SET checked=?,attempts=attempts+1 WHERE id=?', (now, oid))
            if row['status'] == 'paid':
                self.fulfill(oid)  # Already authenticated and settled; retry local delivery only.
                return
            try:
                if row['gateway_id']:
                    remote = self.gateway.get(row['gateway_id'])
                elif row['attempts'] < 3 and now - row['created'] <= 120:
                    # Guest receipt credentials stay in the browser, never sent to the gateway.
                    remote = self.gateway.create(row, self.app.config['origin'] + '/#/orders')
                else:
                    raise DomainError('建单结果待核对，请联系管理员，不要重复付款')
                self.validate(row, remote)
            except DomainError as exc:
                with self.app.ledger.transaction() as db:
                    db.execute('UPDATE payment_orders SET error=?,updated=? WHERE id=?', (str(exc), now, oid))
                    if not row['gateway_id'] and (row['attempts'] >= 2 or now - row['created'] > 120):
                        db.execute("UPDATE payment_orders SET status='review' WHERE id=?", (oid,))
                return
            status = {'completed': 'paid'}.get(remote['status'], remote['status'])
            with self.app.ledger.transaction() as db:
                db.execute('''UPDATE payment_orders SET gateway_id=?,gateway_status=?,status=?,error='',
                    tx_hash=?,pay_amount=?,network=?,updated=? WHERE id=?''',
                           (remote['id'], remote['status'], status, remote.get('tx_hash', ''),
                            remote.get('pay_amount', ''), remote.get('network', ''), now, oid))
            if status == 'paid':
                self.fulfill(oid)

    def fulfill(self, oid):
        try:
            with self.app.account_lifecycle_lock, self.app.ledger.billing_lock, self.app.ledger.transaction() as db:
                order = dict(db.execute('SELECT * FROM payment_orders WHERE id=?', (oid,)).fetchone())
                if order['status'] != 'paid' or order['card_id']:
                    return
                member = None
                if not order['guest']:
                    member = db.execute('SELECT * FROM members WHERE id=?', (order['account_id'],)).fetchone()
                    if not member or member['disabled'] or member['deleting']:
                        raise DomainError('已付款，账号状态需管理员处理后到账')
                now = int(time.time())
                card_id, _ = self.app.ledger.insert_card(db, 'payment:' + oid, json.loads(order['plan']), now)
                if member:
                    card = db.execute('SELECT * FROM cards WHERE id=?', (card_id,)).fetchone()
                    self.app.ledger.apply_card(db, member, card, now)
                else:
                    code = self.card_code(oid)
                    db.execute('UPDATE cards SET digest=?,suffix=? WHERE id=?',
                               (self.app.ledger.digest(code), code.replace('-', '')[-8:], card_id))
                self.app.ledger.audit(db, order['account_id'] or 'guest', 'payment.fulfilled', oid)
                db.execute("UPDATE payment_orders SET card_id=?,status='fulfilled',updated=?,error='' WHERE id=?",
                           (card_id, now, oid))
            self.app.wake.set()
        except DomainError:
            with self.app.ledger.transaction() as db:
                db.execute("UPDATE payment_orders SET error='已付款，套餐到账处理中；系统会自动重试，请勿重复付款' WHERE id=?", (oid,))

    def webhook(self, raw, headers):
        if not self.enabled:
            raise HttpError(503, '支付尚未配置')
        ts = headers.get('X-Timestamp', '')
        signature = headers.get('X-Signature', '')
        if not re.fullmatch(r'sha256=[a-f0-9]{64}', signature):
            raise HttpError(403, '回调签名不正确')
        if not re.fullmatch(r'\d{10,12}', ts) or abs(time.time() - int(ts)) > 300:
            raise HttpError(403, '回调已过期')
        expected = 'sha256=' + hmac.new(self.config['webhook_secret'].encode(), ts.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HttpError(403, '回调签名不正确')
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HttpError(400, '回调格式不正确') from None
        if not isinstance(event, dict) or event.get('event') not in ('payment.completed', 'payment.expired'):
            raise HttpError(400, '回调事件不正确')
        with self.lock, self.app.ledger.transaction() as db:
            row = db.execute('SELECT * FROM payment_orders WHERE id=?', (event.get('merchant_order_id'),)).fetchone()
            if not row:
                return {'ok': True, 'ignored': True}
            if (event.get('id') != headers.get('X-Webhook-Id') or event.get('event') != headers.get('X-Event')
                    or not re.fullmatch(r'pay_[A-Za-z0-9_-]{8,80}', str(event.get('id', '')))
                    or micros(event.get('amount')) != row['amount']
                    or (row['gateway_id'] and row['gateway_id'] != event['id'])):
                raise HttpError(400, '回调订单不匹配')
            # A signed callback only schedules an authenticated lookup; never grants by itself.
            if row['status'] != 'fulfilled':
                db.execute("""UPDATE payment_orders SET gateway_id=?,checked=0,
                    status=CASE WHEN created<? THEN 'review' ELSE status END WHERE id=?""",
                           (event['id'], int(time.time()) - 7 * 86400, row['id']))
        return {'ok': True}

    def reconcile(self):
        if not self.enabled:
            return
        now = int(time.time())
        with self.app.ledger.connect() as db:
            rows = db.execute('''SELECT id FROM payment_orders WHERE status!='fulfilled' AND checked<?
                AND (status IN ('paid','review') OR created>?) ORDER BY checked,created LIMIT 10''',
                              (now - 30, now - 7 * 86400)).fetchall()
        for row in rows:
            try:
                self.sync(row['id'])
            except Exception as exc:
                print('Payment reconcile:', type(exc).__name__, flush=True)

    def loop(self):
        while True:
            try:
                self.reconcile()
            except Exception as exc:
                print('Payment collector:', type(exc).__name__, flush=True)
            time.sleep(30)
