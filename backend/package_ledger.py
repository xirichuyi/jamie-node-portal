"""Independent package accounting. All mutations use the caller's transaction.

Counter rollbacks are quarantined, never interpreted as a free quota reset.
An aggregate sample cannot prove per-node accounting correctness; deployment
must separately verify the panel's cross-node enforcement semantics.
"""

import secrets
from cycles import install_rules, next_reset, expiry
from errors import DomainError


def install(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS billing_rollout (
            id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL CHECK(enabled=1)
        );
        CREATE TABLE IF NOT EXISTS billing_accounts (
            member_id TEXT PRIMARY KEY REFERENCES members(id),
            raw INTEGER NOT NULL CHECK(raw>=0),
            sampled INTEGER NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed>=0),
            unallocated INTEGER NOT NULL DEFAULT 0 CHECK(unallocated>=0),
            fault TEXT,
            last_activity INTEGER
        );
        CREATE TABLE IF NOT EXISTS entitlement_packages (
            id TEXT PRIMARY KEY,
            member_id TEXT NOT NULL REFERENCES members(id),
            card_id TEXT UNIQUE REFERENCES cards(id),
            parent_id TEXT REFERENCES entitlement_packages(id),
            kind TEXT NOT NULL CHECK(kind IN ('base','addon','transition')),
            label TEXT NOT NULL,
            granted INTEGER NOT NULL CHECK(granted>=0),
            spent INTEGER NOT NULL DEFAULT 0 CHECK(spent>=0 AND spent<=granted),
            created INTEGER NOT NULL,
            expires INTEGER NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_packages_member_expiry
            ON entitlement_packages(member_id,expires,id);
        CREATE TABLE IF NOT EXISTS billing_events (
            id INTEGER PRIMARY KEY,
            member_id TEXT NOT NULL REFERENCES members(id),
            package_id TEXT REFERENCES entitlement_packages(id),
            kind TEXT NOT NULL,
            amount INTEGER NOT NULL,
            created INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_billing_events_member
            ON billing_events(member_id,id);
    """)
    install_rules(db, 'entitlement_packages')
    if 'next_reset' not in {
        r['name'] for r in db.execute('PRAGMA table_info(entitlement_packages)')
    }:
        db.execute(
            'ALTER TABLE entitlement_packages ADD COLUMN next_reset INTEGER NOT NULL DEFAULT 0'
        )
    db.execute(
        'CREATE INDEX IF NOT EXISTS idx_package_cycle_due ON entitlement_packages(member_id,next_reset) WHERE next_reset>0 AND revoked=0'
    )


def initialize(db, member, raw, now):
    """One-time, reliable counter snapshot; no invented historical allocations."""
    if type(raw) is not int or raw < 0:
        raise DomainError('流量数据不可用，暂不能切换计费')
    uid = member['id']
    if db.execute('SELECT 1 FROM billing_accounts WHERE member_id=?', (uid,)).fetchone():
        return
    db.execute('INSERT INTO billing_accounts(member_id,raw,sampled) VALUES(?,?,?)', (uid, raw, now))
    if member['quota']:
        pid = secrets.token_hex(16)
        remaining = max(0, member['quota'] - raw)
        db.execute(
            """INSERT INTO entitlement_packages
            (id,member_id,kind,label,granted,created,expires)
            VALUES(?,?,'transition','切换前剩余额度',?,?,?)""",
            (pid, uid, remaining, now, member['expires']),
        )
        event(db, uid, pid, 'transition', remaining, now)


def event(db, uid, pid, kind, amount, now):
    db.execute(
        'INSERT INTO billing_events(member_id,package_id,kind,amount,created) VALUES(?,?,?,?,?)',
        (uid, pid, kind, amount, now),
    )


def sample(db, uid, raw, now):
    if type(raw) is not int or raw < 0:
        raise DomainError('流量数据不可用')
    state = db.execute('SELECT * FROM billing_accounts WHERE member_id=?', (uid,)).fetchone()
    if not state:
        raise DomainError('计费尚未初始化')
    if now < state['sampled']:
        raise DomainError('不能使用早于上次采样的流量数据')
    if state['fault']:
        return
    if raw < state['raw']:
        db.execute("UPDATE billing_accounts SET fault='counter_rollback' WHERE member_id=?", (uid,))
        event(db, uid, None, 'counter_rollback', raw, now)
        return
    delta = raw - state['raw']
    rest = delta
    # Include packages valid at the last sample: bytes observed just after an
    # expiry may have been transmitted before it. Never resurrect their balance.
    rows = (
        db.execute(
            """SELECT id,granted,spent FROM entitlement_packages WHERE member_id=?
        AND revoked=0 AND expires>? AND created<=? AND spent<granted
        ORDER BY CASE WHEN next_reset>0 THEN MIN(expires,next_reset) ELSE expires END,created,id""",
            (uid, state['sampled'], now),
        ).fetchall()
        if delta
        else []
    )
    for p in rows:
        amount = min(rest, p['granted'] - p['spent'])
        if not amount:
            break
        db.execute('UPDATE entitlement_packages SET spent=spent+? WHERE id=?', (amount, p['id']))
        event(db, uid, p['id'], 'consume', amount, now)
        rest -= amount
    db.execute(
        """UPDATE billing_accounts SET raw=?,sampled=?,consumed=consumed+?,
        unallocated=unallocated+?,last_activity=CASE WHEN ?>0 THEN ? ELSE last_activity END
        WHERE member_id=?""",
        (raw, now, delta, rest, delta, now, uid),
    )
    if rest:
        event(db, uid, None, 'overrun', rest, now)
    # Only advance after a fresh cumulative sample. No sample => no free quota.
    # Missed periods do not stack; the current period receives one allowance.
    for row in db.execute(
        'SELECT * FROM entitlement_packages WHERE member_id=? AND revoked=0 AND expires>? AND next_reset>0 AND next_reset<=?',
        (uid, now, now),
    ).fetchall():
        p = dict(row)
        db.execute(
            'UPDATE entitlement_packages SET spent=0,next_reset=? WHERE id=?',
            (next_reset(p, now, p['created']), p['id']),
        )
        event(db, uid, p['id'], 'cycle_reset', p['granted'], now)


def targets(db, uid, now):
    return [
        dict(r)
        for r in db.execute(
            """SELECT id,label,CASE WHEN next_reset>0 THEN MIN(expires,next_reset) ELSE expires END AS expires FROM entitlement_packages
        WHERE member_id=? AND kind IN ('base','transition') AND revoked=0 AND expires>?
        AND (next_reset=0 OR next_reset>?)
        ORDER BY CASE WHEN next_reset>0 THEN MIN(expires,next_reset) ELSE expires END,created,id""",
            (uid, now, now),
        )
    ]


def grant(db, uid, card, now, target=None):
    state = db.execute('SELECT * FROM billing_accounts WHERE member_id=?', (uid,)).fetchone()
    if not state or state['fault']:
        raise DomainError('计费状态待核对，请联系管理员；卡密未消耗')
    kind = card['kind']
    remaining = db.execute(
        'SELECT COALESCE(SUM(granted-spent),0) FROM entitlement_packages WHERE member_id=? AND revoked=0 AND expires>?',
        (uid, now),
    ).fetchone()[0]
    if state['raw'] + remaining + card['quota'] > 2**53 - 1:
        raise DomainError('总额度超过精确计量范围；卡密未消耗')
    parent = None
    if kind == 'addon':
        parent = (
            db.execute(
                """SELECT id,CASE WHEN next_reset>0 THEN MIN(expires,next_reset) ELSE expires END AS expires FROM entitlement_packages
            WHERE id=? AND member_id=? AND kind IN ('base','transition')
            AND revoked=0 AND expires>? AND (next_reset=0 OR next_reset>?)""",
                (target, uid, now, now),
            ).fetchone()
            if isinstance(target, str)
            else None
        )
        if not parent:
            raise DomainError('请选择属于自己的有效套餐；流量包不能延长有效期')
    elif kind != 'base':
        raise DomainError('卡密类型不正确')
    card = {'permanent': 0, 'reset_period': 'never', 'reset_interval': 30, **dict(card)}
    expires = parent['expires'] if parent else expiry(card, now)
    pid = secrets.token_hex(16)
    db.execute(
        """INSERT INTO entitlement_packages
        (id,member_id,card_id,parent_id,kind,label,granted,created,expires)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            pid,
            uid,
            card['id'],
            target if parent else None,
            kind,
            card['label'],
            card['quota'],
            now,
            expires,
        ),
    )
    if not parent:
        db.execute(
            'UPDATE entitlement_packages SET permanent=?,reset_period=?,reset_interval=?,next_reset=? WHERE id=?',
            (
                card['permanent'],
                card['reset_period'],
                card['reset_interval'],
                next_reset(card, now),
                pid,
            ),
        )
    event(db, uid, pid, 'grant', card['quota'], now)
    return pid


def snapshot(db, uid, now):
    state = db.execute('SELECT * FROM billing_accounts WHERE member_id=?', (uid,)).fetchone()
    if not state:
        return None
    packages = [
        dict(r)
        for r in db.execute(
            """SELECT id,parent_id,kind,label,granted,spent,
        created,expires,revoked,permanent,reset_period,reset_interval,next_reset FROM entitlement_packages WHERE member_id=?
        ORDER BY CASE WHEN next_reset>0 THEN MIN(expires,next_reset) ELSE expires END,created,id""",
            (uid,),
        )
    ]
    active = []
    for p in packages:
        p['remaining'] = (
            max(0, p['granted'] - p['spent']) if not p['revoked'] and p['expires'] > now else 0
        )
        p['status'] = (
            'revoked'
            if p['revoked']
            else 'expired'
            if p['expires'] <= now
            else 'exhausted'
            if not p['remaining']
            else 'active'
        )
        if p['remaining']:
            active.append(p)
    return {
        'packages': packages,
        'remaining': sum(p['remaining'] for p in active),
        'next_expiry': min((p['expires'] for p in active), default=0),
        'last_expiry': max((p['expires'] for p in packages if not p['revoked']), default=0),
        'consumed': state['consumed'],
        'raw': state['raw'],
        'sampled': state['sampled'],
        'fault': state['fault'],
        'unallocated': state['unallocated'],
        'last_activity': state['last_activity'],
    }


def summaries(db, now, uid=None):
    """Single-query aggregate for lists/workers; never materialize package history.

    A specific uid uses the member/expiry index. List callers share one connection
    and query across accounts, instead of opening a connection per member.
    """
    where = 'WHERE b.member_id=:uid' if uid is not None else ''
    rows = db.execute(
        """SELECT b.member_id,b.raw,b.fault,b.sampled,
        COUNT(p.id) AS package_count,
        COALESCE(SUM(p.granted),0) AS historical_quota,
        SUM(CASE WHEN p.revoked=0 AND p.expires>:now THEN 1 ELSE 0 END) AS active_count,
        COALESCE(SUM(CASE WHEN p.revoked=0 AND p.expires>:now THEN p.granted ELSE 0 END),0) AS quota,
        COALESCE(SUM(CASE WHEN p.revoked=0 AND p.expires>:now THEN p.spent ELSE 0 END),0) AS used,
        COALESCE(SUM(CASE WHEN p.revoked=0 AND p.expires>:now THEN p.granted-p.spent ELSE 0 END),0) AS remaining,
        COALESCE(MIN(CASE WHEN p.revoked=0 AND p.expires>:now AND p.granted>p.spent THEN p.expires END),0) AS next_expiry,
        COALESCE(MAX(CASE WHEN p.revoked=0 THEN p.expires END),0) AS last_expiry
        FROM billing_accounts b LEFT JOIN entitlement_packages p ON p.member_id=b.member_id
        """
        + where
        + ' GROUP BY b.member_id',
        {'now': now, 'uid': uid},
    )
    return {row['member_id']: dict(row) for row in rows}


def desired(db, uid, now):
    s = summaries(db, now, uid).get(uid)
    if not s:
        raise DomainError('计费尚未初始化')
    # totalGB=0 means unlimited in the panel; disabled AND positive cap required.
    boundary = db.execute(
        'SELECT MIN(next_reset) FROM entitlement_packages WHERE member_id=? AND revoked=0 AND expires>? AND next_reset>0',
        (uid, now),
    ).fetchone()[0]
    expires = s['next_expiry'] or s['last_expiry'] or now
    return {
        'quota': max(1, s['raw'] + s['remaining']),
        'expires': min(expires, boundary) if boundary else expires,
        'billing_blocked': bool(s['fault']) or not s['remaining'],
    }
