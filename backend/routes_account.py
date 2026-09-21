"""Account routes; shared access checks run before dispatch."""

import hashlib
from errors import DomainError
from http_types import UNHANDLED
from passwords import hash_password, verify_password


def dispatch(ctx):
    app = ctx.app
    path = ctx.path
    ip = ctx.ip
    data = ctx.data
    account = ctx.account
    token = ctx.token
    write = ctx.write
    if write and path == '/api/logout':
        with app.ledger.connect() as db:
            db.execute(
                'DELETE FROM sessions WHERE digest=?',
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
        return ctx.reply(200, {'ok': True}, '')
    if write and path == '/api/password':
        app.limit('password:' + account['id'], 5, 900)
        with app.password_lock:
            if not verify_password(data.get('old_password'), account['password']):
                raise DomainError('当前密码不正确')
            hashed = hash_password(data.get('new_password'))
        with app.ledger.transaction() as db:
            db.execute(
                'UPDATE accounts SET password=?,must_change=0 WHERE id=?',
                (hashed, account['id']),
            )
            db.execute('DELETE FROM sessions WHERE account_id=?', (account['id'],))
            app.ledger.audit(db, account['id'], 'account.password', account['id'])
        return ctx.reply(
            200,
            {'ok': True},
            app.new_session(account['id'], ctx.headers.get('User-Agent', ''), ip),
        )
    if not write and path == '/api/sessions':
        return ctx.reply(200, app.features.sessions(account, token))
    if write and path == '/api/account/delete':
        return ctx.reply(
            202,
            app.account_deletion.request(
                account, account['id'], data.get('confirmation'), data.get('password')
            ),
            '',
        )
    if write and path == '/api/account/email/code':
        app.reauthenticate(account, data.get('password'))
        if data.get('purpose') not in ('change_old', 'change_new'):
            raise DomainError('无效验证码用途')
        return ctx.reply(
            200,
            app.email_auth.request(data.get('email'), data.get('purpose'), ip, owner=account),
        )
    if write and path == '/api/account/email':
        app.reauthenticate(account, data.get('password'))
        app.email_auth.change(
            account, data.get('email'), data.get('new_code'), data.get('old_code')
        )
        return ctx.reply(
            200,
            {'ok': True},
            app.new_session(account['id'], ctx.headers.get('User-Agent', ''), ip),
        )
    if write and path == '/api/sessions/revoke':
        app.limit('sessions:' + account['id'], 20, 600)
        app.features.revoke_session(account, data.get('id'), token)
        return ctx.reply(200, {'ok': True})
    if write and path == '/api/recovery-code':
        app.reauthenticate(account, data.get('password'))
        return ctx.reply(200, app.features.recovery_generate(account))
    return UNHANDLED
