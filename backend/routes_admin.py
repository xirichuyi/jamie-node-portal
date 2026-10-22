"""Admin routes; shared access checks run before dispatch."""

import secrets
import time
from urllib.parse import parse_qs, urlsplit
from errors import DomainError
from http_types import UNHANDLED
from validation import text
from passwords import hash_password
from routes_support import ticket_request
import mail_history
from email_auth import email_address
from email_templates import service_email


def card_plan(app, data):
    """A saved plan when plan_id is given, otherwise the custom fields in the request."""
    return app.content.plan_for_card(data['plan_id']) if data.get('plan_id') else data


def grant_spec(app, data):
    """One internal card for an administrator grant, from a saved or custom plan."""
    plan = card_plan(app, data)
    return app.ledger.card_spec(
        plan.get('name', plan.get('label')),
        plan['quota_gib'],
        plan.get('days', 1),
        1,
        0,
        plan.get('kind', 'base'),
        permanent=plan.get('permanent', False),
        reset_period=plan.get('reset_period', 'never'),
        reset_interval=plan.get('reset_interval', 30),
        note=data.get('note'),
    )


def dispatch(ctx):
    if not ctx.write:
        return handle(ctx)
    # Any admin write may change listing rows; drop the cache on both sides of it.
    ctx.app.users.invalidate()
    try:
        return handle(ctx)
    finally:
        ctx.app.users.invalidate()


def handle(ctx):
    app = ctx.app
    path = ctx.path
    data = ctx.data
    account = ctx.account
    write = ctx.write
    if not write and path == '/api/admin/orders':
        return ctx.reply(200, app.payments.admin_listing(parse_qs(urlsplit(ctx.raw_path).query)))
    if write and path == '/api/admin/order-check':
        app.limit('order-check:' + account['id'], 30, 600)
        return ctx.reply(200, app.payments.admin_check(account['id'], text(data.get('id'), 64)))
    if not write and path == '/api/admin/mail-history':
        return ctx.reply(200, mail_history.listing(app, parse_qs(urlsplit(ctx.raw_path).query)))
    if write and path == '/api/admin/user-delete':
        return ctx.reply(
            202,
            app.account_deletion.request(
                account,
                text(data.get('id'), 64),
                admin_action=True,
            ),
        )
    if write and path in ('/api/admin/card-search', '/api/admin/login-diagnosis'):
        app.limit('diagnostics:' + account['id'], 60, 60)
        return ctx.reply(
            200,
            app.operations.cards(data)
            if path.endswith('card-search')
            else app.operations.login_diagnosis(data),
        )
    if not write and path == '/api/admin/readiness':
        return ctx.reply(200, app.operations.readiness())
    if not write and path == '/api/admin/users':
        return ctx.reply(200, app.users.listing(parse_qs(urlsplit(ctx.raw_path).query)))
    if not write and path == '/api/admin/user':
        return ctx.reply(
            200, app.users.detail(parse_qs(urlsplit(ctx.raw_path).query).get('id', [''])[0])
        )
    if write and path == '/api/admin/user-sessions':
        app.limit('user-action:' + account['id'], 20, 600)
        uid = text(data.get('id'), 64)
        with app.ledger.transaction() as db:
            app.users.target(db, uid)
            db.execute('DELETE FROM sessions WHERE account_id=?', (uid,))
            app.ledger.audit(db, account['id'], 'account.revoke_sessions', uid)
        return ctx.reply(200, {'ok': True, 'pending': False})
    if write and path == '/api/admin/user-sync':
        app.limit('user-action:' + account['id'], 20, 600)
        if not app.users.retry_sync(account['id'], text(data.get('id'), 64)):
            return ctx.reply(200, {'pending': False})
        app.wake.set()
        return ctx.reply(200, {'ok': True, 'pending': True})
    if write and path == '/api/admin/users-bulk':
        app.limit('bulk:' + account['id'], 10, 600)
        if data.get('action') == 'grant':
            data = {**data, 'spec': grant_spec(app, data)}
        return ctx.reply(200, app.users.bulk(account['id'], data))
    if not write and path == '/api/admin/operations':
        return ctx.reply(200, app.features.operations())
    if write and path == '/api/admin/incident':
        app.limit('incident:' + account['id'], 30, 600)
        return ctx.reply(200, app.features.incident_save(account, data))
    if path == '/api/admin/tickets':
        return ticket_request(ctx, staff=True)
    if not write and path == '/api/admin/content':
        return ctx.reply(200, app.content.read(admin=True))
    if write and path in ('/api/admin/plan', '/api/admin/notice', '/api/admin/support'):
        app.limit('content:' + account['id'], 60, 60)
        item_id = app.content.save(account['id'], path.rsplit('/', 1)[-1], data)
        return ctx.reply(200, {'ok': True, 'id': item_id})
    if write and path == '/api/admin/cards':
        app.limit('issue:' + account['id'], 10, 60)
        plan = card_plan(app, data)
        codes = app.ledger.issue(
            account['id'],
            plan.get('name', plan.get('label')),
            plan['quota_gib'],
            plan.get('days', 1),
            data['count'],
            data['valid_days'],
            kind=plan.get('kind', 'base'),
            permanent=plan.get('permanent', False),
            reset_period=plan.get('reset_period', 'never'),
            reset_interval=plan.get('reset_interval', 30),
            note=data.get('note'),
        )
        return ctx.reply(200, {'codes': codes})
    if write and path == '/api/admin/grant':
        app.limit('grant:' + account['id'], 20, 600)
        spec = grant_spec(app, data)
        target = data.get('target') if spec['kind'] == 'addon' else None
        result = app.ledger.grant(account['id'], text(data.get('id'), 64), spec, target)
        app.wake.set()
        return ctx.reply(200, result)
    if write and path == '/api/admin/revoke-batch':
        app.limit('issue:' + account['id'], 10, 60)
        count = app.ledger.revoke_batch(account['id'], data.get('label'), data.get('created'))
        return ctx.reply(200, {'revoked': count})
    if write and path == '/api/admin/card-note':
        app.limit('user-action:' + account['id'], 60, 600)
        app.ledger.set_card_note(account['id'], text(data.get('id'), 64), data.get('note'))
        return ctx.reply(200, {'ok': True})
    if write and path == '/api/admin/user-note':
        app.limit('user-action:' + account['id'], 60, 600)
        app.users.save_note(account['id'], text(data.get('id'), 64), data.get('body', ''))
        return ctx.reply(200, {'ok': True})
    if not write and path == '/api/admin/batches':
        with app.ledger.connect() as db:
            return ctx.reply(200, {'batches': app.features.batches(db, int(time.time()), 100)})
    if path == '/api/admin/staff-alerts':
        if write:
            app.limit('user-action:' + account['id'], 60, 600)
            result = app.staff_notifications.settings(data.get('ticket_email'))
            with app.ledger.transaction() as db:
                app.ledger.audit(db, account['id'], 'staff.alerts', '1')
            return ctx.reply(200, result)
        return ctx.reply(200, app.staff_notifications.settings())
    if write and path == '/api/admin/mail-test':
        app.limit('mail-test:' + account['id'], 5, 600)
        if not app.email_auth.enabled:
            raise DomainError('邮件服务尚未配置')
        to = email_address(data.get('to'))
        app.email_auth.deliver(
            to,
            service_email(
                '测试邮件',
                '这是一封来自 Jamie-Node 后台的测试邮件。收到说明邮件服务配置正常。\n\n'
                '邮件服务接收不代表一定进入收件箱，如果没看到，请检查垃圾邮件文件夹。',
                app.config['origin'],
                footer='由管理员在后台手动发送。',
                eyebrow='系统测试',
            ),
            'mail-test-' + secrets.token_hex(8),
        )
        with app.ledger.transaction() as db:
            app.ledger.audit(db, account['id'], 'mail.test', '1')
        return ctx.reply(200, {'ok': True})
    if not write and path == '/api/admin/badges':
        return ctx.reply(200, app.users.badges())
    if not write and path == '/api/admin/audit':
        return ctx.reply(200, app.users.audit_log(parse_qs(urlsplit(ctx.raw_path).query)))
    if write and path == '/api/admin/revoke':
        app.ledger.revoke(account['id'], data['id'])
        return ctx.reply(200, {'ok': True})
    if write and path == '/api/admin/member':
        member_id = text(data.get('id'), 64)
        if member_id == account['id']:
            raise DomainError('不能停用自己的管理员账号')
        expected = data.get('expected_disabled')
        if type(data.get('disabled')) is not bool or (
            'expected_disabled' in data and type(expected) is not bool
        ):
            raise DomainError('无效状态')
        app.users.set_disabled(account['id'], member_id, data['disabled'], expected)
        app.wake.set()
        return ctx.reply(200, {'ok': True})
    if write and path == '/api/admin/reset-password':
        app.limit('reset-password:' + account['id'], 20, 600)
        new_password = secrets.token_urlsafe(15)
        with app.password_lock:
            hashed = hash_password(new_password)
        with app.ledger.transaction() as db:
            target = db.execute(
                'SELECT a.*,m.deleting FROM accounts a JOIN members m ON m.id=a.id WHERE a.id=? AND a.admin=0',
                (data['id'],),
            ).fetchone()
            if not target:
                raise DomainError('用户不存在')
            if target['deleting']:
                raise DomainError('账号正在删除，不能重置密码')
            db.execute(
                'UPDATE accounts SET password=?,must_change=1 WHERE id=?',
                (hashed, data['id']),
            )
            db.execute('DELETE FROM sessions WHERE account_id=?', (data['id'],))
            db.execute('DELETE FROM recovery_codes WHERE account_id=?', (data['id'],))
            app.ledger.audit(db, account['id'], 'account.reset_password', data['id'])
        return ctx.reply(200, {'password': new_password})
    return UNHANDLED
