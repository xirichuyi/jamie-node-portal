"""Email administrators when customers open or reply to tickets; durable, bounded retries."""

import time

from email_templates import service_email
from errors import DomainError


class StaffNotifications:
    def __init__(self, app):
        self.app = app
        with app.ledger.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS staff_mail_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), ticket_email INTEGER NOT NULL DEFAULT 1
                );
                INSERT OR IGNORE INTO staff_mail_settings(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS staff_mail_queue (
                    message_id INTEGER PRIMARY KEY REFERENCES ticket_messages(id),
                    created INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending'
                );
            """)

    def recipients(self, db):
        """Administrators' verified addresses, else the configured support mailbox."""
        rows = [
            r[0]
            for r in db.execute(
                """SELECT v.email FROM verified_emails v JOIN accounts a ON a.id=v.account_id
                JOIN members m ON m.id=a.id WHERE a.admin=1 AND m.disabled=0 ORDER BY v.email"""
            )
        ]
        fallback = self.app.email_auth.config.get('reply_to')
        return rows or ([fallback] if isinstance(fallback, str) and fallback else [])

    def settings(self, enabled=None):
        with self.app.ledger.transaction() as db:
            if enabled is not None:
                if type(enabled) is not bool:
                    raise DomainError('无效提醒设置')
                db.execute('UPDATE staff_mail_settings SET ticket_email=? WHERE id=1', (int(enabled),))
                if not enabled:
                    db.execute("UPDATE staff_mail_queue SET status='cancelled' WHERE status='pending'")
            on = bool(db.execute('SELECT ticket_email FROM staff_mail_settings WHERE id=1').fetchone()[0])
            recipients = self.recipients(db)
        return {
            'ticket_email': on,
            'available': self.app.email_auth.enabled and bool(recipients),
            'recipients': recipients,
        }

    def enqueue(self, db, message_id):
        if db.execute('SELECT ticket_email FROM staff_mail_settings WHERE id=1').fetchone()[0]:
            db.execute(
                'INSERT OR IGNORE INTO staff_mail_queue(message_id,created) VALUES(?,?)',
                (message_id, int(time.time())),
            )

    def deliver_pending(self, now=None):
        if not self.app.email_auth.enabled:
            return
        now = int(time.time()) if now is None else now
        with self.app.ledger.transaction() as db:
            db.execute("DELETE FROM staff_mail_queue WHERE status!='pending' AND created<?", (now - 30 * 86400,))
            pending = db.execute(
                """SELECT * FROM staff_mail_queue WHERE status='pending' AND next_attempt<=?
                ORDER BY message_id LIMIT 5""",
                (now,),
            ).fetchall()
        for item in pending:
            with self.app.ledger.transaction() as db:
                row = db.execute(
                    """SELECT t.id,t.subject,t.status,t.category,a.username,m.body,
                    (SELECT COUNT(*) FROM ticket_messages x WHERE x.ticket_id=t.id) AS messages,
                    EXISTS(SELECT 1 FROM ticket_messages s WHERE s.ticket_id=t.id AND s.staff=1
                        AND s.id>m.id) AS answered,
                    EXISTS(SELECT 1 FROM staff_mail_queue q JOIN ticket_messages n ON n.id=q.message_id
                        WHERE n.ticket_id=t.id AND q.message_id>m.id AND q.status='pending') AS newer
                    FROM ticket_messages m JOIN support_tickets t ON t.id=m.ticket_id
                    JOIN accounts a ON a.id=t.account_id WHERE m.id=?""",
                    (item['message_id'],),
                ).fetchone()
                enabled = db.execute('SELECT ticket_email FROM staff_mail_settings WHERE id=1').fetchone()[0]
                recipients = self.recipients(db)
                # Already answered, closed, superseded by a newer message, or stale: skip.
                if (
                    not row
                    or not enabled
                    or not recipients
                    or row['answered']
                    or row['newer']
                    or row['status'] == 'closed'
                    or now - item['created'] > 23 * 3600
                    or item['attempts'] >= 5
                ):
                    status = 'failed' if item['attempts'] >= 5 else 'cancelled'
                    db.execute('UPDATE staff_mail_queue SET status=? WHERE message_id=?', (status, item['message_id']))
                    continue
                db.execute(
                    'UPDATE staff_mail_queue SET attempts=attempts+1,next_attempt=? WHERE message_id=?',
                    (now + min(3600, 300 * 2 ** item['attempts']), item['message_id']),
                )
            new = row['messages'] <= 1
            excerpt = row['body'] if len(row['body']) <= 500 else row['body'][:500] + '…'
            content = service_email(
                ('新工单：' if new else '工单有新回复：') + row['subject'],
                f'用户 {row["username"]} {"提交了新工单" if new else "回复了工单"}「{row["subject"]}」。\n\n{excerpt}',
                self.app.config['origin'],
                action=('去处理工单', '/#/admin_tickets'),
                footer='这是发给管理员的工单提醒，可在后台「工单」页关闭。',
            )
            sent = True
            for address in recipients:
                try:
                    self.app.email_auth.deliver(
                        address, content, f'staff-ticket-{item["message_id"]}-{address}'
                    )
                except DomainError:
                    sent = False
            if sent or item['attempts'] >= 4:
                with self.app.ledger.transaction() as db:
                    db.execute(
                        'UPDATE staff_mail_queue SET status=? WHERE message_id=?',
                        ('sent' if sent else 'failed', item['message_id']),
                    )
