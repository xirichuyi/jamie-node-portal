"""Retryable account erasure. Remove the panel identity before erasing local ownership."""

import time
from errors import DomainError


class AccountDeletion:
    def __init__(self, app):
        self.app = app
        with app.ledger.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS account_deletions (
                account_id TEXT PRIMARY KEY REFERENCES accounts(id),
                requested INTEGER NOT NULL, next_attempt INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0
            )""")

    def request(self, actor, target_id, confirmation=None, password=None, *, admin_action=False):
        app = self.app
        if admin_action:
            if not actor['admin']:
                raise DomainError('仅管理员可访问')
        else:
            app.reauthenticate(actor, password)
        if actor['id'] != target_id and not actor['admin']:
            raise DomainError('只能注销自己的账号')
        with app.account_lifecycle_lock, app.ledger.billing_lock, app.ledger.transaction() as db:
            current_actor = db.execute(
                'SELECT a.*,m.disabled FROM accounts a JOIN members m ON m.id=a.id WHERE a.id=?',
                (actor['id'],),
            ).fetchone()
            if (
                not current_actor
                or current_actor['disabled']
                or current_actor['password'] != actor['password']
                or (admin_action and not current_actor['admin'])
            ):
                raise DomainError('登录状态已变化，请重新登录')
            target = db.execute('SELECT * FROM accounts WHERE id=?', (target_id,)).fetchone()
            if not target:
                raise DomainError('账号不存在')
            if target['admin']:
                raise DomainError('管理员账号不支持注销或删除')
            if not admin_action and confirmation != target['username']:
                raise DomainError('请输入要删除的完整账号')
            if db.execute("SELECT 1 FROM payment_orders WHERE account_id=? AND status IN ('creating','pending','confirming','paid','review')", (target_id,)).fetchone():
                raise DomainError('还有未完成的支付订单，请先等待付款结果或联系管理员处理')
            db.execute(
                'INSERT OR IGNORE INTO account_deletions(account_id,requested) VALUES(?,?)',
                (target_id, int(time.time())),
            )
            db.execute(
                "UPDATE members SET disabled=1,deleting=1,sync_error='删除处理中',revision=revision+1 WHERE id=?",
                (target_id,),
            )
            db.execute('DELETE FROM sessions WHERE account_id=?', (target_id,))
            db.execute(
                "UPDATE ticket_mail_queue SET status='cancelled' WHERE account_id=? AND status='pending'",
                (target_id,),
            )
            db.execute(
                "UPDATE subscription_mail_queue SET status='cancelled' WHERE account_id=? AND status='pending'",
                (target_id,),
            )
            db.execute(
                "UPDATE receipt_mail_queue SET status='cancelled' WHERE account_id=? AND status='pending'",
                (target_id,),
            )
        app.wake.set()
        return {'pending': True}

    def process(self):
        app = self.app
        with app.ledger.connect() as db:
            ids = [
                r[0]
                for r in db.execute(
                    'SELECT account_id FROM account_deletions WHERE next_attempt<=? ORDER BY requested LIMIT 3',
                    (int(time.time()),),
                )
            ]
        for uid in ids:
            with app.account_lifecycle_lock, app.ledger.billing_lock:
                with app.ledger.connect() as db:
                    member = db.execute(
                        'SELECT * FROM members WHERE id=? AND deleting=1', (uid,)
                    ).fetchone()
                if not member:
                    continue
                try:
                    app.panel.remove(dict(member))
                    self.purge(uid)
                except Exception:
                    with app.ledger.transaction() as db:
                        db.execute(
                            'UPDATE account_deletions SET attempts=attempts+1,next_attempt=? WHERE account_id=?',
                            (int(time.time()) + 60, uid),
                        )
                        db.execute(
                            "UPDATE members SET sync_error='删除处理中：节点或数据清理尚未完成，将自动重试' WHERE id=?",
                            (uid,),
                        )

    def purge(self, uid):
        with self.app.ledger.transaction() as db:
            account = db.execute(
                'SELECT a.username,m.deleting FROM accounts a JOIN members m ON m.id=a.id WHERE a.id=?',
                (uid,),
            ).fetchone()
            if not account or not account['deleting']:
                raise DomainError('账号未进入删除流程')
            db.execute('''DELETE FROM mail_deliveries WHERE recipient=? OR recipient IN
                (SELECT email FROM verified_emails WHERE account_id=?)''', (account['username'], uid))
            db.execute(
                'DELETE FROM email_challenges WHERE email IN (SELECT email FROM verified_emails WHERE account_id=?)',
                (uid,),
            )
            # Ticket children first, including staff replies on the owner's tickets.
            db.execute(
                'DELETE FROM audit WHERE target IN (SELECT id FROM support_tickets WHERE account_id=?) OR target IN (SELECT id FROM entitlement_packages WHERE member_id=?)',
                (uid, uid),
            )
            db.execute(
                'DELETE FROM ticket_mail_queue WHERE account_id=? OR message_id IN (SELECT id FROM ticket_messages WHERE account_id=? OR ticket_id IN (SELECT id FROM support_tickets WHERE account_id=?))',
                (uid, uid, uid),
            )
            db.execute(
                'DELETE FROM staff_mail_queue WHERE message_id IN (SELECT id FROM ticket_messages WHERE account_id=? OR ticket_id IN (SELECT id FROM support_tickets WHERE account_id=?))',
                (uid, uid),
            )
            db.execute(
                'DELETE FROM ticket_reads WHERE account_id=? OR ticket_id IN (SELECT id FROM support_tickets WHERE account_id=?)',
                (uid, uid),
            )
            db.execute(
                'DELETE FROM ticket_messages WHERE account_id=? OR ticket_id IN (SELECT id FROM support_tickets WHERE account_id=?)',
                (uid, uid),
            )
            db.execute('DELETE FROM support_tickets WHERE account_id=?', (uid,))
            db.execute('DELETE FROM billing_events WHERE member_id=?', (uid,))
            db.execute('DELETE FROM entitlement_packages WHERE member_id=?', (uid,))
            db.execute(
                'DELETE FROM audit WHERE actor=? OR target=? OR target IN (SELECT id FROM cards WHERE redeemed_by=?)',
                (uid, uid, uid),
            )
            db.execute(
                'DELETE FROM receipt_mail_queue WHERE account_id=? OR card_id IN (SELECT id FROM cards WHERE redeemed_by=?)',
                (uid, uid),
            )
            # Removing redeemed card digests never makes the original cards redeemable again.
            db.execute('DELETE FROM cards WHERE redeemed_by=?', (uid,))
            db.execute('DELETE FROM login_events WHERE username=?', (account['username'],))
            db.execute(
                'DELETE FROM email_challenges WHERE email=? OR purpose LIKE ? OR purpose LIKE ?',
                (account['username'], 'change_old:' + uid + ':%', 'change_new:' + uid + ':%'),
            )
            for table in (
                'sessions',
                'recovery_codes',
                'verified_emails',
                'notification_preferences',
                'subscription_mail_queue',
                'subscription_mail_preferences',
                'usage_baselines',
                'usage_days',
                'account_deletions',
            ):
                db.execute('DELETE FROM ' + table + ' WHERE account_id=?', (uid,))
            for table in ('billing_accounts', 'user_traffic_activity', 'admin_user_notes'):
                db.execute('DELETE FROM ' + table + ' WHERE member_id=?', (uid,))
            db.execute('UPDATE payment_orders SET account_id=NULL WHERE account_id=?', (uid,))
            db.execute('DELETE FROM accounts WHERE id=?', (uid,))
            db.execute('DELETE FROM members WHERE id=?', (uid,))
