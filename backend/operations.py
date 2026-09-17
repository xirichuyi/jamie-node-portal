"""Administrator diagnostics. No passwords, raw card codes or browsing targets."""

import hashlib
import json
import re
import time
from pathlib import Path
from errors import DomainError
from email_auth import email_address


def valid_login(value):
    if not isinstance(value, str):
        return False
    if re.fullmatch(r'[A-Za-z0-9_]{3,32}', value):
        return True
    try:
        email_address(value)
        return True
    except DomainError:
        return False


class Operations:
    def __init__(self, app):
        self.app = app
        self.ledger = app.ledger
        with self.ledger.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS login_events (
                    id INTEGER PRIMARY KEY, username TEXT NOT NULL,
                    outcome TEXT NOT NULL, created INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_login_events_user_time ON login_events(username,created);
                CREATE INDEX IF NOT EXISTS idx_login_events_time ON login_events(created);
                CREATE INDEX IF NOT EXISTS idx_cards_suffix ON cards(suffix);
            """)

    def login_event(self, username, outcome):
        # No password/IP/UA/card fields. Invalid usernames are not arbitrary text logs.
        username = username.lower() if valid_login(username) else '[invalid]'
        now = int(time.time())
        with self.ledger.connect() as db:
            db.execute(
                'INSERT INTO login_events(username,outcome,created) VALUES(?,?,?)',
                (username, outcome, now),
            )
            db.execute('DELETE FROM login_events WHERE created<?', (now - 7 * 86400,))
            db.execute(
                'DELETE FROM login_events WHERE id <= COALESCE((SELECT id FROM login_events ORDER BY id DESC LIMIT 1 OFFSET 9999),0)-1'
            )

    def cards(self, data):
        query = data.get('query', '')
        if not isinstance(query, str) or len(query) > 100:
            raise DomainError('请输入卡密、8 位尾号或用户名')
        normalized = query.strip().upper().replace('-', '').replace(' ', '')
        scope = data.get('scope', 'all')
        now = int(time.time())
        scopes = {
            'all': '1=1',
            'redeemed': 'c.redeemed_at IS NOT NULL',
            'available': 'c.redeemed_at IS NULL AND c.revoked_at IS NULL AND c.redeem_before>?',
            'expired': 'c.redeemed_at IS NULL AND c.revoked_at IS NULL AND c.redeem_before<=?',
            'revoked': 'c.revoked_at IS NOT NULL',
        }
        if scope not in scopes or type(data.get('page', 1)) is not int:
            raise DomainError('筛选条件不正确')
        where, args = [scopes[scope]], [now] if scope in ('available', 'expired') else []
        if query.strip():
            if re.fullmatch('[A-F0-9]{32}', normalized):
                where.append('c.digest=?')
                args.append(self.ledger.digest(normalized))
            elif re.fullmatch('[A-F0-9]{8}', normalized):
                where.append('(c.suffix=? OR a.username=?)')
                args.extend([normalized, query.strip().lower()])
            else:
                where.append('a.username=?')
                args.append(query.strip().lower())
        clause = ' AND '.join(where)
        join = ' FROM cards c LEFT JOIN accounts a ON a.id=c.redeemed_by WHERE ' + clause
        with self.ledger.connect() as db:
            total = db.execute('SELECT COUNT(*)' + join, args).fetchone()[0]
            pages = max(1, (total + 24) // 25)
            page = min(pages, max(1, data.get('page', 1)))
            rows = [
                dict(r)
                for r in db.execute(
                    """SELECT c.id,c.suffix,c.label,c.quota,c.days,c.kind,c.permanent,c.reset_period,c.reset_interval,
                c.redeem_before,c.created,c.redeemed_at,c.revoked_at,
                a.username AS redeemed_by,a.id AS account_id"""
                    + join
                    + ' ORDER BY c.created DESC,c.id LIMIT 25 OFFSET ?',
                    [*args, (page - 1) * 25],
                )
            ]
        return {'cards': rows, 'total': total, 'page': page, 'pages': pages}

    def login_diagnosis(self, data):
        username = data.get('username', '')
        if not valid_login(username.strip() if isinstance(username, str) else username):
            raise DomainError('请输入完整用户名')
        username = username.strip().lower()
        now = int(time.time())
        with self.ledger.connect() as db:
            account = db.execute(
                'SELECT a.id,a.username,a.must_change,m.disabled FROM accounts a JOIN members m ON m.id=a.id WHERE username=?',
                (username,),
            ).fetchone()
            events = [
                dict(r)
                for r in db.execute(
                    'SELECT outcome,created FROM login_events WHERE username=? AND created>? ORDER BY id DESC LIMIT 50',
                    (username, now - 7 * 86400),
                )
            ]
            limit = db.execute(
                'SELECT count,expires FROM rate_limits WHERE key=?',
                (hashlib.sha256(('username:' + username).encode()).hexdigest(),),
            ).fetchone()
        return {
            'account': dict(account) if account else None,
            'username': username,
            'events': events,
            'limited_until': limit['expires']
            if limit and limit['count'] >= 20 and limit['expires'] > now
            else None,
            'note': '仅记录此功能上线后的登录尝试，保留 7 天；未记录密码。网络故障、网关限流可能没有到达登录服务。',
        }

    def readiness(self):
        now = int(time.time())
        with self.ledger.connect() as db:
            cached = db.execute(
                "SELECT value,updated FROM feature_cache WHERE key='budgets'"
            ).fetchone()
            pending = db.execute(
                'SELECT COUNT(*) FROM members WHERE revision>synced_revision'
            ).fetchone()[0]
            low = db.execute(
                'SELECT COUNT(*) FROM members m JOIN usage_baselines u ON u.account_id=m.id WHERE m.disabled=0 AND m.expires>? AND m.quota>0 AND u.raw>=m.quota*0.9',
                (now,),
            ).fetchone()[0]
            plans = [
                dict(r)
                for r in db.execute('SELECT name,price_label FROM portal_plans WHERE published=1')
            ]
            billing_faults = db.execute(
                'SELECT COUNT(*) FROM billing_accounts WHERE fault IS NOT NULL'
            ).fetchone()[0]
            counter_resets = db.execute(
                'SELECT COUNT(*) FROM user_traffic_activity WHERE counter_reset=1'
            ).fetchone()[0]
            if self.ledger.package_billing:
                low = db.execute(
                    """SELECT COUNT(*) FROM (
                    SELECT p.member_id FROM entitlement_packages p JOIN members m ON m.id=p.member_id
                    WHERE m.disabled=0 AND p.revoked=0 AND p.expires>?
                    GROUP BY p.member_id HAVING SUM(p.spent)>=SUM(p.granted)*0.9
                    AND SUM(p.granted)>0)""",
                    (now,),
                ).fetchone()[0]
        alerts = []
        if billing_faults or counter_resets:
            alerts.append(
                {
                    'level': 'error',
                    'title': '流量计数需核对',
                    'detail': f'{max(billing_faults, counter_resets)} 个账号检测到计数异常；请勿直接清零或重发额度。',
                }
            )
        if not cached or now - cached['updated'] > 900:
            alerts.append(
                {
                    'level': 'error',
                    'title': '节点预算数据未更新',
                    'detail': '请检查面板连接；不把未知用量当作零。',
                }
            )
        elif cached:
            for b in json.loads(cached['value']):
                if (
                    all(type(b.get(k)) is int for k in ('up', 'down', 'total'))
                    and b['total'] > 0
                    and b['up'] + b['down'] >= b['total'] * 0.8
                ):
                    ratio = (b['up'] + b['down']) / b['total']
                    alerts.append(
                        {
                            'level': 'error' if ratio >= 0.9 else 'warning',
                            'title': b['name'] + '流量预算预警',
                            'detail': f'代理累计已用 {ratio:.1%}；请核对服务商计费额度。',
                        }
                    )
        if pending:
            alerts.append(
                {
                    'level': 'warning',
                    'title': '订阅同步待处理',
                    'detail': f'{pending} 个账号等待节点确认。',
                }
            )
        if low:
            alerts.append(
                {
                    'level': 'warning',
                    'title': '用户流量不足',
                    'detail': f'{low} 个有效账号累计用量达到 90%。',
                }
            )
        for p in plans:
            if not p['price_label'] or re.fullmatch(r'[\d.]+', p['price_label'].strip()):
                alerts.append(
                    {
                        'level': 'warning',
                        'title': p['name'] + '价格待确认',
                        'detail': '尚未填写明确价格与币种，用户端显示咨询管理员。',
                    }
                )
        backup = None
        try:
            backup = json.loads(
                (Path(self.ledger.path).parent / 'backups' / 'verification.json').read_text()
            )
        except (OSError, ValueError):
            pass
        if (
            not backup
            or now - backup.get('verified_at', 0) > 36 * 3600
            or not backup.get('restore_verified')
        ):
            alerts.append(
                {
                    'level': 'error',
                    'title': '备份恢复验证待完成',
                    'detail': '需要从备份恢复到隔离数据库并验证，不覆盖线上数据。',
                }
            )
        connectivity = None
        try:
            connectivity = json.loads(
                (Path(self.ledger.path).parent / 'connectivity.json').read_text()
            )
        except (OSError, ValueError):
            pass
        if not connectivity or now - connectivity.get('checked_at', 0) > 1800:
            alerts.append(
                {
                    'level': 'error',
                    'title': '实际连接探测未更新',
                    'detail': '无法确认代理出口是否可用，请检查探测任务。',
                }
            )
        elif not connectivity.get('subscription_ok') or any(
            not n.get('ok') for n in connectivity.get('nodes', [])
        ):
            alerts.append(
                {
                    'level': 'error',
                    'title': '实际代理连接探测失败',
                    'detail': '从监控服务器到节点或测试站点的链路异常；不直接等同于所有用户都无法连接。',
                }
            )
        return {
            'alerts': alerts,
            'backup': backup,
            'external_notifications': False,
            'offsite_backup': False,
            'connectivity': connectivity,
            'checked_at': now,
        }
