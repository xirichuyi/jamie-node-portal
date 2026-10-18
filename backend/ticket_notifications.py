"""Default-on support notifications with explicit opt-out and bounded retries."""

import time

from email_templates import service_email
from errors import DomainError


class TicketNotifications:
    def __init__(self, app):
        self.app = app
        with app.ledger.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ticket_reads (
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    ticket_id TEXT NOT NULL REFERENCES support_tickets(id),
                    message_id INTEGER NOT NULL, PRIMARY KEY(account_id,ticket_id)
                );
                CREATE TABLE IF NOT EXISTS notification_preferences (
                    account_id TEXT PRIMARY KEY REFERENCES accounts(id), ticket_email INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS ticket_mail_queue (
                    message_id INTEGER PRIMARY KEY REFERENCES ticket_messages(id),
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    created INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending'
                );
            """)

    def preferences(self, account, enabled=None):
        with self.app.account_lifecycle_lock, self.app.ledger.transaction() as db:
            verified = db.execute(
                'SELECT email FROM verified_emails WHERE account_id=?', (account['id'],)
            ).fetchone()
            if enabled is not None:
                if type(enabled) is not bool:
                    raise DomainError('无效提醒设置')
                if enabled and (not verified or not self.app.email_auth.enabled):
                    raise DomainError('请先绑定邮箱，或稍后再试')
                db.execute(
                    'INSERT OR REPLACE INTO notification_preferences VALUES(?,?)',
                    (account['id'], int(enabled)),
                )
                if not enabled:
                    db.execute(
                        "UPDATE ticket_mail_queue SET status='cancelled' WHERE account_id=? AND status='pending'",
                        (account['id'],),
                    )
            row = db.execute(
                'SELECT ticket_email FROM notification_preferences WHERE account_id=?',
                (account['id'],),
            ).fetchone()
        return {
            'ticket_email': bool(row[0]) if row else True,
            'available': bool(verified and self.app.email_auth.enabled),
        }

    def enqueue(self, db, uid, mid):
        if not db.execute(
            'SELECT 1 FROM notification_preferences WHERE account_id=? AND ticket_email=0', (uid,)
        ).fetchone() and db.execute(
            'SELECT 1 FROM verified_emails WHERE account_id=?', (uid,)
        ).fetchone():
            db.execute(
                'INSERT OR IGNORE INTO ticket_mail_queue(message_id,account_id,created) VALUES(?,?,?)',
                (mid, uid, int(time.time())),
            )

    def deliver_pending(self):
        # Do not send a previously selected reminder after an account deletion starts.
        with self.app.account_lifecycle_lock:
            self._deliver_pending()

    def _deliver_pending(self):
        if not self.app.email_auth.enabled:
            return
        now = int(time.time())
        with self.app.ledger.transaction() as db:
            db.execute(
                "UPDATE ticket_mail_queue SET status='failed' WHERE status='pending' AND attempts>=5"
            )
            db.execute(
                "DELETE FROM ticket_mail_queue WHERE status!='pending' AND created<?",
                (now - 30 * 86400,),
            )
        with self.app.ledger.connect() as db:
            pending = db.execute(
                "SELECT * FROM ticket_mail_queue WHERE status='pending' AND next_attempt<=? ORDER BY message_id LIMIT 5",
                (now,),
            ).fetchall()
        for item in pending:
            with self.app.ledger.transaction() as db:
                recipient = db.execute(
                    """SELECT v.email FROM verified_emails v
                    JOIN accounts a ON a.id=v.account_id
                    JOIN members m ON m.id=a.id
                    LEFT JOIN notification_preferences p ON p.account_id=a.id
                    WHERE a.id=? AND m.disabled=0 AND m.deleting=0 AND COALESCE(p.ticket_email,1)=1""",
                    (item['account_id'],),
                ).fetchone()
                subject = (db.execute(
                    'SELECT t.subject FROM ticket_messages m JOIN support_tickets t ON t.id=m.ticket_id WHERE m.id=?',
                    (item['message_id'],),
                ).fetchone() or ['你的工单'])[0]
                unread = db.execute(
                    """SELECT 1 FROM ticket_messages m LEFT JOIN ticket_reads r
                    ON r.ticket_id=m.ticket_id AND r.account_id=? WHERE m.id=? AND m.id>COALESCE(r.message_id,0)""",
                    (item['account_id'], item['message_id']),
                ).fetchone()
                if not recipient or not unread or now - item['created'] > 86400:
                    db.execute(
                        "UPDATE ticket_mail_queue SET status='cancelled' WHERE message_id=?",
                        (item['message_id'],),
                    )
                    continue
                db.execute(
                    'UPDATE ticket_mail_queue SET attempts=attempts+1,next_attempt=? WHERE message_id=?',
                    (now + min(3600, 300 * 2 ** item['attempts']), item['message_id']),
                )
            content = service_email(
                '工单有新回复',
                f'你的工单「{subject}」收到了管理员回复。\n\n'
                '回复内容请登录后在「我的 → 我的工单」查看；邮件不包含回复正文，避免敏感信息外泄。',
                self.app.config['origin'],
                action=('查看回复', '/#/tickets'),
                footer='你开启了工单回复邮件提醒，可在工单页关闭。',
                eyebrow='工单提醒',
            )
            try:
                self.app.email_auth.deliver(
                    recipient['email'], content, 'ticket-reply-' + str(item['message_id'])
                )
            except DomainError:
                if item['attempts'] >= 4:
                    with self.app.ledger.transaction() as db:
                        db.execute(
                            "UPDATE ticket_mail_queue SET status='failed' WHERE message_id=?",
                            (item['message_id'],),
                        )
            else:
                with self.app.ledger.transaction() as db:
                    db.execute(
                        "UPDATE ticket_mail_queue SET status='sent' WHERE message_id=?",
                        (item['message_id'],),
                    )
