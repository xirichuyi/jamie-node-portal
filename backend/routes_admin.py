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


def card_plan(app, data):
    """A saved plan when plan_id is given, otherwise the custom fields in the request."""
    return app.content.plan_for_card(data['plan_id']) if data.get('plan_id') else data


def dispatch(ctx):
    app = ctx.app
    path = ctx.path
    data = ctx.data
    account = ctx.account
    write = ctx.write
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
    if write and path in ('/api/admin/user-sessions', '/api/admin/user-sync'):
        app.limit('user-action:' + account['id'], 20, 600)
        uid = text(data.get('id'), 64)
        with app.ledger.transaction() as db:
            target = db.execute(
                'SELECT a.admin,m.* FROM accounts a JOIN members m ON m.id=a.id WHERE a.id=?',
                (uid,),
            ).fetchone()
            if not target or target['admin']:
                raise DomainError('只能操作普通用户')
            if target['deleting']:
                raise DomainError('账号删除处理中，不能修改状态')
            if path.endswith('user-sessions'):
                db.execute('DELETE FROM sessions WHERE account_id=?', (uid,))
                app.ledger.audit(db, account['id'], 'account.revoke_sessions', uid)
            else:
                if target['revision'] <= target['synced_revision']:
                    return ctx.reply(200, {'pending': False})
                app.ledger.audit(db, account['id'], 'account.retry_sync', uid)
        if path.endswith('user-sync'):
            app.wake.set()
        return ctx.reply(200, {'ok': True, 'pending': path.endswith('user-sync')})
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
        plan = card_plan(app, data)
        spec = app.ledger.card_spec(
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
    if not write and path == '/api/admin/badges':
        return ctx.reply(200, app.users.badges())
    if not write and path == '/api/admin/audit':
        return ctx.reply(200, app.users.audit_log(parse_qs(urlsplit(ctx.raw_path).query)))
    if write and path == '/api/admin/revoke':
        app.ledger.revoke(account['id'], data['id'])
        return ctx.reply(200, {'ok': True})
    if write and path == '/api/admin/member':
        member_id = data['id']
        if member_id == account['id']:
            raise DomainError('不能停用自己的管理员账号')
        if type(data.get('disabled')) is not bool:
            raise DomainError('无效状态')
        with app.ledger.transaction() as db:
            target = db.execute('SELECT * FROM accounts WHERE id=?', (member_id,)).fetchone()
            if not target or target['admin']:
                raise DomainError('只能操作普通用户')
            state = db.execute(
                'SELECT disabled,deleting FROM members WHERE id=?', (member_id,)
            ).fetchone()
            if state['deleting']:
                raise DomainError('账号删除处理中，不能修改状态')
            state = state['disabled']
            if 'expected_disabled' in data and (
                type(data['expected_disabled']) is not bool
                or data['expected_disabled'] != bool(state)
            ):
                raise DomainError('用户状态已改变，请刷新详情后重试')
            db.execute(
                """UPDATE members SET disabled=?,
                sync_error=NULL,revision=revision+CASE WHEN quota>0 AND disabled!=? THEN 1 ELSE 0 END WHERE id=?""",
                (int(data['disabled']), int(data['disabled']), member_id),
            )
            db.execute('DELETE FROM sessions WHERE account_id=?', (member_id,))
            app.ledger.audit(
                db,
                account['id'],
                'account.disable' if data['disabled'] else 'account.enable',
                member_id,
            )
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
    if not write and path in ('/api/admin/overview', '/api/admin/cards-overview'):
        with app.ledger.connect() as db:
            cards = [
                dict(r)
                for r in db.execute("""SELECT c.id,c.suffix,c.label,c.quota,c.days,c.permanent,c.reset_period,c.reset_interval,
                c.redeem_before,c.created,c.redeemed_at,c.revoked_at,a.username AS redeemed_by
                FROM cards c LEFT JOIN accounts a ON a.id=c.redeemed_by ORDER BY c.created DESC,c.id LIMIT 500""")
            ]
            members = (
                [
                    dict(r)
                    for r in db.execute("""SELECT a.id,a.username,a.admin,m.quota,m.expires,m.panel_email,
                m.disabled,m.revision,m.synced_revision,m.sync_error FROM accounts a JOIN members m
                ON a.id=m.id ORDER BY m.created DESC LIMIT 500""")
                ]
                if path.endswith('/overview')
                else []
            )
            audit = [
                dict(r)
                for r in db.execute("""SELECT a.action,a.target,a.created,
                COALESCE(u.username,a.actor) AS actor FROM audit a LEFT JOIN accounts u
                ON u.id=a.actor ORDER BY a.id DESC LIMIT 100""")
            ]
        if path.endswith('/cards-overview'):
            return ctx.reply(200, {'cards': cards, 'audit': audit})
        traffic = {}
        try:
            traffic = {c['email']: c.get('traffic') for c in app.panel.request('clients/list')}
        except Exception:
            pass
        for member in members:
            stat = traffic.get(member.pop('panel_email'))
            member['used'] = (stat.get('up', 0) + stat.get('down', 0)) if stat else None
        return ctx.reply(200, {'cards': cards, 'members': members, 'audit': audit})
    return UNHANDLED
