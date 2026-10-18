"""Administrative mail metadata. Never retain verification codes or message bodies."""

import time
from errors import DomainError


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS mail_deliveries (
        delivery_key TEXT PRIMARY KEY, recipient TEXT NOT NULL, subject TEXT NOT NULL,
        created INTEGER NOT NULL, updated INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL, provider_id TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT ''
    )''')


def record(app, key, email, subject, status, provider_id='', error=''):
    now = int(time.time())
    with app.ledger.transaction() as db:
        db.execute('DELETE FROM mail_deliveries WHERE updated<?', (now - 90 * 86400,))
        db.execute('''INSERT INTO mail_deliveries
            (delivery_key,recipient,subject,created,updated,attempts,status,provider_id,error)
            VALUES(?,?,?,?,?,1,?,?,?) ON CONFLICT(delivery_key) DO UPDATE SET
            updated=excluded.updated,attempts=mail_deliveries.attempts+?,status=excluded.status,
            provider_id=excluded.provider_id,error=excluded.error''',
                   (key, email, subject, now, now, status, provider_id, error, int(status == 'sending')))


def listing(app, query):
    try:
        page = max(1, min(100000, int(query.get('page', ['1'])[0])))
    except (ValueError, TypeError):
        raise DomainError('无效页码') from None
    status = query.get('status', [''])[0]
    if status not in ('', 'pending', 'sent', 'failed', 'cancelled', 'sending'):
        raise DomainError('无效邮件状态')
    # Queues preserve earlier reminders; delivery metadata enriches new sends.
    union = '''WITH mail AS (
        SELECT 'subscription-'||q.event_key id,q.recipient,
            CASE q.kind WHEN 'traffic_email' THEN '流量提醒' ELSE '套餐到期提醒' END subject,
            q.created,q.attempts,q.next_attempt,q.status,
            COALESCE(d.updated,0) updated,COALESCE(d.provider_id,'') provider_id,COALESCE(d.error,'') error,
            COALESCE(a.username,'') account
        FROM subscription_mail_queue q LEFT JOIN mail_deliveries d ON d.delivery_key='subscription-'||q.event_key
        LEFT JOIN accounts a ON a.id=q.account_id
        UNION ALL
        SELECT 'ticket-reply-'||q.message_id,COALESCE(d.recipient,''),'工单回复提醒',
            q.created,q.attempts,q.next_attempt,q.status,
            COALESCE(d.updated,0),COALESCE(d.provider_id,''),COALESCE(d.error,''),COALESCE(a.username,'')
        FROM ticket_mail_queue q LEFT JOIN mail_deliveries d ON d.delivery_key='ticket-reply-'||q.message_id
        LEFT JOIN accounts a ON a.id=q.account_id
        UNION ALL
        SELECT d.delivery_key,d.recipient,d.subject,d.created,d.attempts,0,d.status,d.updated,d.provider_id,d.error,''
        FROM mail_deliveries d WHERE NOT EXISTS
            (SELECT 1 FROM subscription_mail_queue q WHERE d.delivery_key='subscription-'||q.event_key)
            AND NOT EXISTS (SELECT 1 FROM ticket_mail_queue q WHERE d.delivery_key='ticket-reply-'||q.message_id)
        ) '''
    where = ' WHERE status=?' if status else ''
    params = (status,) if status else ()
    with app.ledger.connect() as db:
        total = db.execute(union + 'SELECT count(*) FROM mail' + where, params).fetchone()[0]
        rows = db.execute(union + 'SELECT * FROM mail' + where + ' ORDER BY created DESC,id LIMIT 30 OFFSET ?',
                          (*params, (page - 1) * 30)).fetchall()
    return {'items': [dict(r) for r in rows], 'page': page, 'pages': max(1, (total + 29) // 30), 'total': total,
            'available': app.email_auth.enabled}
