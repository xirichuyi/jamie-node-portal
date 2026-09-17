"""Portal-owned renewal rules; panel traffic counters remain cumulative."""

import calendar
from datetime import datetime, timedelta, timezone
from errors import DomainError

FOREVER = 253402185600  # Internal sentinel; translated to no expiry at the panel boundary.
MAX_GIB = 8388607  # Keep byte counts within JavaScript's exact integer range.
TZ = timezone(timedelta(hours=8))


def install_rules(db, table):
    columns = {r['name'] for r in db.execute('PRAGMA table_info(' + table + ')')}
    for name, definition in (
        ('permanent', 'INTEGER NOT NULL DEFAULT 0'),
        ('reset_period', "TEXT NOT NULL DEFAULT 'never'"),
        ('reset_interval', 'INTEGER NOT NULL DEFAULT 30'),
    ):
        if name not in columns:
            db.execute('ALTER TABLE ' + table + ' ADD COLUMN ' + name + ' ' + definition)


def rules(data):
    permanent = data.get('permanent', False)
    period = data.get('reset_period', 'never')
    interval = data.get('reset_interval', 30)
    if type(permanent) not in (bool, int) or permanent not in (0, 1):
        raise DomainError('请选择订阅期限')
    if period not in ('never', 'monthly', 'interval'):
        raise DomainError('请选择流量重置周期')
    if 'reset_day' in data:
        raise DomainError('重置日由开通时间确定，不能指定固定日期')
    if type(interval) is not int or not 1 <= interval <= 365000:
        raise DomainError('重置间隔应为正整数天')
    return dict(permanent=int(permanent), reset_period=period, reset_interval=interval)


def next_reset(rule, now, anchor=None):
    if rule['reset_period'] == 'never':
        return 0
    if rule['reset_period'] == 'interval':
        step = rule['reset_interval'] * 86400
        anchor = now if anchor is None else anchor
        return anchor + ((now - anchor) // step + 1) * step
    start = datetime.fromtimestamp(now if anchor is None else anchor, TZ)
    date = datetime.fromtimestamp(now, TZ)
    year, month = date.year, date.month
    for _ in range(2):
        day = min(start.day, calendar.monthrange(year, month)[1])
        candidate = int(start.replace(year=year, month=month, day=day).timestamp())
        if candidate > now:
            return candidate
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    raise ValueError('No monthly boundary')


def expiry(card, now):
    return FOREVER if card['permanent'] else now + card['days'] * 86400
