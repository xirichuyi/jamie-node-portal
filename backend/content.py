"""Portal-owned plans, notices, support settings and sanitized node telemetry."""

import copy
import re
import secrets
import threading
import time
from urllib.parse import urlsplit
from errors import DomainError
from cycles import install_rules, rules, MAX_GIB


def text(data, key, maximum, required=True):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise DomainError('请检查文本长度或必填项目：' + key)
    return value.strip()


def integer(data, key, minimum, maximum):
    value = data.get(key)
    if type(value) is not int or not minimum <= value <= maximum:
        raise DomainError('数值超出允许范围：' + key)
    return value


def flag(data, key):
    if type(data.get(key)) is not bool:
        raise DomainError('状态参数不正确：' + key)
    return int(data[key])


class Content:
    def __init__(self, ledger):
        self.ledger = ledger
        with ledger.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS portal_plans (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                    quota_gib INTEGER NOT NULL CHECK(quota_gib>0), days INTEGER NOT NULL CHECK(days>0),
                    price_label TEXT NOT NULL DEFAULT '', badge TEXT NOT NULL DEFAULT '',
                    published INTEGER NOT NULL DEFAULT 0, sort_order INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 1, updated INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portal_notices (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
                    category TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL,
                    updated INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS portal_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), contact_label TEXT NOT NULL,
                    contact_url TEXT NOT NULL, contact_note TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS portal_migrations (version INTEGER PRIMARY KEY);
            """)
            install_rules(db, 'portal_plans')
        with ledger.transaction() as db:
            if not db.execute('SELECT 1 FROM portal_migrations WHERE version=1').fetchone():
                now = int(time.time())
                # Only the pre-existing 100 GiB / 30 day card is published.
                # Other tiers are editable drafts, never invented public offers.
                for pid, name, quota, days, desc, badge, published, order in [
                    ('light', '轻量月卡', 30, 30, '适合轻量浏览与日常信息访问。', '', 0, 0),
                    (
                        'standard',
                        '标准月卡',
                        100,
                        30,
                        '三个地区节点，适合日常使用。',
                        '月度方案',
                        1,
                        1,
                    ),
                    ('extended', '长效季卡', 300, 90, '更长有效期，按需使用总流量。', '', 0, 2),
                ]:
                    db.execute(
                        'INSERT INTO portal_plans(id,name,description,quota_gib,days,price_label,badge,published,sort_order,revision,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                        (pid, name, desc, quota, days, '', badge, published, order, 1, now),
                    )
                db.execute(
                    'INSERT INTO portal_settings VALUES(1,?,?,?,1)',
                    ('联系发卡人', '', '请通过你获取本站地址或卡密的原渠道联系管理员。'),
                )
                db.execute(
                    'INSERT INTO portal_notices VALUES(?,?,?,?,?,?,?,?,?)',
                    (
                        'welcome',
                        '欢迎使用 Jamie-Node',
                        '本站通过卡密开通订阅，暂不提供在线支付。注册登录后，前往「兑换」输入卡密；开通后在首页复制订阅链接或导入客户端。请勿公开分享你的订阅链接。',
                        'info',
                        1,
                        1,
                        now,
                        now,
                        1,
                    ),
                )
                db.execute('INSERT INTO portal_migrations VALUES(1)')
            if not db.execute('SELECT 1 FROM portal_migrations WHERE version=2').fetchone():
                # Update only our untouched seed copy, never an owner's edited notice.
                db.execute(
                    """UPDATE portal_notices SET body=?,updated=?,revision=revision+1
                    WHERE id='welcome' AND revision=1 AND body=?""",
                    (
                        '使用卡密即可开通账号：先验证卡密查看套餐，再设置用户名和密码。有效期从确认开通时开始，开通后按教程导入客户端。已有账号请登录后兑换续费。请勿公开分享卡密或订阅链接。',
                        int(time.time()),
                        '本站通过卡密开通订阅，暂不提供在线支付。注册登录后，前往「兑换」输入卡密；开通后在首页复制订阅链接或导入客户端。请勿公开分享你的订阅链接。',
                    ),
                )
                db.execute('INSERT INTO portal_migrations VALUES(2)')

    def read(self, admin=False):
        with self.ledger.connect() as db:
            plans = [
                dict(r)
                for r in db.execute(
                    'SELECT * FROM portal_plans '
                    + ('' if admin else 'WHERE published=1 ')
                    + 'ORDER BY sort_order,id'
                )
            ]
            notices = [
                dict(r)
                for r in db.execute(
                    'SELECT * FROM portal_notices '
                    + ('' if admin else 'WHERE published=1 ')
                    + 'ORDER BY pinned DESC,created DESC,id LIMIT 100'
                )
            ]
            settings = dict(db.execute('SELECT * FROM portal_settings WHERE id=1').fetchone())
        return {
            'plans': plans,
            'notices': notices,
            'support': settings,
            'package_billing': self.ledger.package_billing,
        }

    def save(self, actor, kind, data):
        now = int(time.time())
        if kind == 'support':
            label = text(data, 'contact_label', 40)
            note = text(data, 'contact_note', 1000, False)
            url = text(data, 'contact_url', 400, False)
            parsed = urlsplit(url)
            if url and not (
                (
                    parsed.scheme == 'https'
                    and parsed.hostname
                    and not parsed.username
                    and not parsed.password
                    and not any(c.isspace() for c in url)
                )
                or re.fullmatch(r'mailto:[A-Za-z0-9_.+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', url)
            ):
                raise DomainError('联系方式只支持 HTTPS 链接或 mailto:邮箱')
            revision = integer(data, 'revision', 1, 1000000000)
            with self.ledger.transaction() as db:
                changed = db.execute(
                    """UPDATE portal_settings SET contact_label=?,contact_url=?,
                    contact_note=?,revision=revision+1 WHERE id=1 AND revision=?""",
                    (label, url, note, revision),
                ).rowcount
                if not changed:
                    raise DomainError('内容已被更新，请刷新后再保存')
                self.ledger.audit(db, actor, 'support.save', '1')
            return '1'
        if kind == 'plan':
            table = 'portal_plans'
            values = {
                'name': text(data, 'name', 60),
                'description': text(data, 'description', 500, False),
                'quota_gib': integer(data, 'quota_gib', 1, MAX_GIB),
                'days': 1 if data.get('permanent') else integer(data, 'days', 1, 365000),
                'price_label': text(data, 'price_label', 40, False),
                'badge': text(data, 'badge', 20, False),
                'published': flag(data, 'published'),
                'sort_order': integer(data, 'sort_order', 0, 999),
            }
            values.update(rules(data))
            if (
                values['permanent'] or values['reset_period'] != 'never'
            ) and not self.ledger.package_billing:
                raise DomainError('请先启用套餐计费')
            if values['price_label'] and re.fullmatch(r'[\d.]+', values['price_label']):
                raise DomainError('价格请同时填写币种，例如 30 元；留空表示咨询管理员')
        elif kind == 'notice':
            table = 'portal_notices'
            category = data.get('category')
            if category not in ('info', 'maintenance', 'update'):
                raise DomainError('公告类型无效')
            values = {
                'title': text(data, 'title', 120),
                'body': text(data, 'body', 4000),
                'category': category,
                'published': flag(data, 'published'),
                'pinned': flag(data, 'pinned'),
            }
        else:
            raise DomainError('未知内容类型')
        values['updated'] = now
        item_id = data.get('id')
        with self.ledger.transaction() as db:
            if item_id:
                revision = integer(data, 'revision', 1, 1000000000)
                changed = db.execute(
                    'UPDATE '
                    + table
                    + ' SET '
                    + ','.join(k + '=?' for k in values)
                    + ',revision=revision+1 WHERE id=? AND revision=?',
                    (*values.values(), item_id, revision),
                ).rowcount
                if not changed:
                    raise DomainError('内容已变更或不存在，请刷新后再编辑')
            else:
                if db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] >= (
                    100 if kind == 'plan' else 1000
                ):
                    raise DomainError('内容数量已达上限')
                item_id = secrets.token_hex(12)
                values.update(id=item_id, revision=1)
                if kind == 'notice':
                    values['created'] = now
                db.execute(
                    'INSERT INTO '
                    + table
                    + ' ('
                    + ','.join(values)
                    + ') VALUES ('
                    + ','.join('?' for _ in values)
                    + ')',
                    tuple(values.values()),
                )
            self.ledger.audit(db, actor, kind + '.save', item_id)
        return item_id

    def plan_for_card(self, plan_id):
        with self.ledger.connect() as db:
            row = db.execute(
                'SELECT * FROM portal_plans WHERE id=? AND published=1', (plan_id,)
            ).fetchone()
        if not row:
            raise DomainError('套餐不存在或尚未上架')
        return dict(row)


class NodeMonitor:
    NAMES = {
        1: '🇯🇵 日本 · 东京 01', 2: '🇸🇬 新加坡 01', 3: '🇲🇾 马来西亚 · 柔佛',
        4: '🇺🇸 美国 · 圣何塞', 5: '🇯🇵 日本 · 东京 02', 6: '🇸🇬 新加坡 02',
    }

    def __init__(self, panel, inbound_ids=None):
        self.panel = panel
        self.names = {i: self.NAMES[i] for i in (inbound_ids if inbound_ids is not None else [1, 2, 3]) if i in self.NAMES}
        self.lock = threading.Lock()
        self.data = {
            'checked_at': 0,
            'nodes': [
                {'id': i, 'name': name, 'status': 'unknown', 'heartbeat': 0, 'latency_ms': None}
                for i, name in self.names.items()
            ],
        }

    def refresh(self):
        now = int(time.time())
        try:
            nodes = {n['id']: n for n in self.panel.request('nodes/list')}
            inbounds = {i['id']: i for i in self.panel.request('inbounds/list')}
            rows = []
            for inbound_id, name in self.names.items():
                inbound = inbounds.get(inbound_id, {})
                node_id = inbound.get('nodeId', inbound_id)
                n = nodes.get(node_id, {})
                heartbeat = n.get('lastHeartbeat', 0)
                fresh = 0 <= now - heartbeat <= 180
                status = 'unknown'
                if n.get('enable') is False or inbound.get('enable') is False:
                    status = 'paused'
                elif n.get('status') == 'offline':
                    status = 'offline'
                elif (
                    fresh and n.get('status') == 'online' and inbound.get('protocol') == 'hysteria'
                ):
                    status = 'pending' if n.get('configDirty') else 'online'
                latency = n.get('latencyMs')
                rows.append(
                    {
                        'id': inbound_id,
                        'name': name,
                        'status': status,
                        'heartbeat': heartbeat,
                        'latency_ms': latency
                        if status == 'online' and type(latency) is int and latency >= 0
                        else None,
                    }
                )
            result = {'checked_at': now, 'nodes': rows}
        except Exception:
            with self.lock:
                result = copy.deepcopy(self.data)
            for row in result['nodes']:
                row.update(status='unknown', latency_ms=None)
        with self.lock:
            self.data = result

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.data)
        if time.time() - result['checked_at'] > 90:
            for row in result['nodes']:
                row.update(status='unknown', latency_ms=None)
        return result

    def run(self):
        while True:
            self.refresh()
            time.sleep(30)
