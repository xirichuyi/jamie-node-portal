"""Admin-only user workspace; never return subscription credentials."""

import threading
import time
from errors import DomainError
from package_ledger import summaries, snapshot

SCOPES = (
    'all',
    'active',
    'expiring',
    'expired',
    'exhausted',
    'disabled',
    'pending',
    'sync_errors',
    'unknown',
    'unopened',
)
SORT_FIELDS = (
    'username',
    'created',
    'expires',
    'remaining',
    'used',
    'last_web_seen',
    'last_proxy_activity',
)


def subscription_state(member, now):
    if not member['quota']:
        return 'unopened'
    if member['expires'] <= now:
        return 'expired'
    if member['used'] is None:
        return 'unknown'
    if member['used'] >= member['quota']:
        return 'exhausted'
    return 'active'


class UserWorkspace:
    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.sample = None
        with self.app.ledger.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS user_traffic_activity (
                member_id TEXT PRIMARY KEY REFERENCES members(id),
                raw INTEGER NOT NULL, sampled INTEGER NOT NULL, changed INTEGER,
                counter_reset INTEGER NOT NULL DEFAULT 0)""")

    def traffic(self):
        with self.lock:
            now = time.time()
            if self.sample and now - self.sample['at'] < 15:
                return self.sample
            try:
                rows = self.app.panel.request('clients/list')
                values = {}
                for row in rows:
                    stat = row.get('traffic')
                    values[row['email']] = (
                        (stat.get('up', 0) + stat.get('down', 0)) if stat else None
                    )
                with self.app.ledger.transaction() as db:
                    previous_by_id = {
                        r['member_id']: r for r in db.execute('SELECT * FROM user_traffic_activity')
                    }
                    updates = []
                    for member in db.execute('SELECT id,panel_email FROM members').fetchall():
                        raw = values.get(member['panel_email'])
                        if type(raw) is not int or raw < 0:
                            continue
                        previous = previous_by_id.get(member['id'])
                        changed = previous['changed'] if previous else None
                        # A long gap proves only that usage occurred sometime in
                        # the gap, not that this user is currently online.
                        if previous and raw > previous['raw'] and now - previous['sampled'] <= 60:
                            changed = int(now)
                        reset = int(
                            bool(previous and (previous['counter_reset'] or raw < previous['raw']))
                        )
                        updates.append((member['id'], raw, int(now), changed, reset))
                    db.executemany(
                        """INSERT INTO user_traffic_activity VALUES(?,?,?,?,?)
                        ON CONFLICT(member_id) DO UPDATE SET raw=excluded.raw,
                        sampled=excluded.sampled,changed=excluded.changed,counter_reset=excluded.counter_reset""",
                        updates,
                    )
                self.sample = {'at': int(now), 'values': values, 'error': None}
            except Exception:
                self.sample = {
                    'at': int(now),
                    'values': {},
                    'error': '暂时无法读取节点用量，订阅状态可能待确认',
                }
            return self.sample

    def members(self, uid=None):
        """Read compact summaries; only detail() loads a user's package history."""
        sample = self.traffic()
        now = int(time.time())
        with self.app.ledger.connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    """SELECT a.id,a.username,a.admin,a.must_change,
                m.quota,m.expires,m.disabled,m.deleting,m.revision,m.synced_revision,m.sync_error,m.created,
                m.last_sync_attempt,m.last_synced_at,m.panel_email,
                (SELECT MAX(d.seen) FROM sessions s JOIN session_details d ON d.digest=s.digest
                    WHERE s.account_id=m.id) AS last_web_seen,
                (SELECT changed FROM user_traffic_activity WHERE member_id=m.id) AS last_proxy_activity,
                COALESCE((SELECT counter_reset FROM user_traffic_activity WHERE member_id=m.id),0) AS counter_reset,
                (SELECT label FROM cards WHERE redeemed_by=m.id AND kind='base' ORDER BY redeemed_at DESC,id DESC LIMIT 1) AS plan_name
                FROM accounts a JOIN members m ON m.id=a.id """
                    + ('WHERE a.id=? ' if uid is not None else '')
                    + 'ORDER BY m.created DESC,m.id',
                    (uid,) if uid is not None else (),
                )
            ]
            billing_by_id = summaries(db, now, uid) if self.app.ledger.package_billing else {}
        for row in rows:
            row['used'] = sample['values'].get(row.pop('panel_email'))
            row['remaining'] = None if row['used'] is None else max(0, row['quota'] - row['used'])
            billing = billing_by_id.get(row['id'])
            if billing:
                row['expires'] = billing['next_expiry'] or billing['last_expiry']
                row['quota'] = billing['quota']
                row['used'] = billing['used']
                row['remaining'] = billing['remaining']
                row['billing_fault'] = billing['fault']
                # Keep historical entitlement visible as expired, not unopened.
                if not billing['active_count'] and billing['package_count']:
                    row['quota'] = billing['historical_quota']
                    row['used'] = row['quota']
                if billing['fault']:
                    row['used'] = None
            row['subscription_state'] = subscription_state(row, now)
            row['sync_state'] = (
                'error'
                if row['sync_error']
                else 'pending'
                if row['revision'] > row['synced_revision']
                else 'synced'
            )
            row['primary_state'] = 'disabled' if row['disabled'] else row['subscription_state']
            row['proxy_activity'] = (
                'unknown'
                if sample['error'] or row['used'] is None
                else 'recent'
                if row['last_proxy_activity'] and now - row['last_proxy_activity'] <= 60
                else 'unconfirmed'
            )
        return rows, sample

    def listing(self, query):
        keyword = query.get('q', [''])[0].strip().lower()
        scope = query.get('scope', ['all'])[0]
        if len(keyword) > 32 or scope not in SCOPES:
            raise DomainError('筛选条件不正确')
        sort = query.get('sort', ['created'])[0]
        direction = query.get('direction', ['desc'])[0]
        if sort not in SORT_FIELDS or direction not in ('asc', 'desc'):
            raise DomainError('排序条件不正确')
        try:
            page = max(1, int(query.get('page', ['1'])[0]))
        except ValueError:
            raise DomainError('页码不正确') from None
        rows, sample = self.members()
        rows = [m for m in rows if keyword in m['username'].lower()]
        now = int(time.time())

        def matches(m, key):
            if key == 'all':
                return True
            if key == 'expiring':
                return m['primary_state'] == 'active' and m['expires'] <= now + 7 * 86400
            if key == 'pending':
                return m['revision'] > m['synced_revision']
            if key == 'sync_errors':
                return m['sync_state'] == 'error'
            return m['primary_state'] == key

        counts = {key: sum(matches(m, key) for m in rows) for key in SCOPES}
        selected = [m for m in rows if matches(m, scope)]
        # Stable ties and unknown values last in BOTH directions, before paging.
        selected.sort(key=lambda m: m['id'])
        known = [m for m in selected if m[sort] is not None]
        unknown = [m for m in selected if m[sort] is None]
        known.sort(key=lambda m: m[sort], reverse=direction == 'desc')
        selected = known + unknown
        pages = max(1, (len(selected) + 24) // 25)
        page = min(page, pages)
        return {
            'members': selected[(page - 1) * 25 : page * 25],
            'total': len(selected),
            'page': page,
            'pages': pages,
            'counts': counts,
            'checked_at': sample['at'],
            'usage_error': sample['error'],
        }

    def detail(self, uid):
        rows, sample = self.members(uid)
        member = next((m for m in rows if m['id'] == uid), None)
        if not member:
            raise DomainError('用户不存在')
        with self.app.ledger.connect() as db:
            if self.app.ledger.package_billing:
                billing = snapshot(db, uid, int(time.time()))
                if billing:
                    member['packages'] = billing['packages']
            history = [
                dict(r)
                for r in db.execute(
                    """SELECT label,quota,days,kind,redeemed_at,permanent,reset_period,reset_interval FROM cards
                WHERE redeemed_by=? ORDER BY redeemed_at DESC,id DESC LIMIT 50""",
                    (uid,),
                )
            ]
            audit = [
                dict(r)
                for r in db.execute(
                    """SELECT a.action,a.created,COALESCE(u.username,'系统') AS actor
                FROM audit a LEFT JOIN accounts u ON u.id=a.actor WHERE a.actor=? OR a.target=?
                ORDER BY a.id DESC LIMIT 50""",
                    (uid, uid),
                )
            ]
            sessions = db.execute(
                'SELECT COUNT(*) FROM sessions WHERE account_id=? AND expires>?',
                (uid, int(time.time())),
            ).fetchone()[0]
            seen = db.execute(
                """SELECT MAX(d.seen) FROM sessions s JOIN session_details d ON s.digest=d.digest
                WHERE s.account_id=?""",
                (uid,),
            ).fetchone()[0]
        return {
            'member': member,
            'history': history,
            'audit': audit,
            'sessions': sessions,
            'last_seen': seen,
            'checked_at': sample['at'],
            'usage_error': sample['error'],
        }
