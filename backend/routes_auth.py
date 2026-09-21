"""Auth routes; shared access checks run before dispatch."""

from errors import DomainError
from http_types import HttpError, UNHANDLED
from validation import text
from passwords import hash_password, verify_password


def dispatch(ctx):
    app = ctx.app
    path = ctx.path
    ip = ctx.ip
    data = ctx.data
    write = ctx.write
    if not write and path == '/api/content':
        return ctx.reply(200, app.content.read())
    if write and path == '/api/register/preview':
        app.limit('card-preview:' + ip, 10, 900)
        return ctx.reply(200, app.card_preview(data.get('code')))
    if write and path == '/api/email/code':
        return ctx.reply(
            200,
            app.email_auth.request(data.get('email'), data.get('purpose'), ip, data.get('code')),
        )
    if write and path == '/api/email/reset':
        app.limit('email-reset:' + ip, 10, 900)
        app.email_auth.reset(data.get('email'), data.get('email_code'), data.get('new_password'))
        return ctx.reply(200, {'ok': True})
    if write and path == '/api/recover':
        app.limit('recover:' + ip, 5, 900)
        username = text(data.get('username'), 254).lower()
        app.limit('recover-user:' + username, 5, 900)
        with app.password_lock:
            hashed = hash_password(data.get('new_password'))
        app.features.recovery_reset(username, data.get('code'), hashed)
        return ctx.reply(200, {'ok': True})
    if write and path in ('/api/login', '/api/register'):
        username = str(data.get('username', '')).strip().lower()
        if len(username) > 254:
            raise DomainError('账号格式不正确')
        try:
            app.limit('auth:' + ip, 15, 900)
            app.limit('username:' + username, 20, 900)
        except HttpError:
            if path == '/api/login':
                app.operations.login_event(username, 'rate_limited')
            raise
        password = data.get('password', '')
        if path == '/api/register':
            if not app.email_auth.enabled:
                raise HttpError(503, '邮箱验证服务暂不可用，请稍后注册')
            app.limit('register:' + ip, 5, 3600)
            token = app.register_with_card(
                username,
                password,
                data.get('code'),
                ctx.headers.get('User-Agent', ''),
                ip,
                email_code=data.get('email_code'),
            )
            return ctx.reply(200, {'ok': True}, token)
        else:
            with app.ledger.connect() as db:
                account = db.execute(
                    """SELECT a.*,m.disabled FROM accounts a JOIN members m
                    ON a.id=m.id WHERE username=?""",
                    (username,),
                ).fetchone()
            with app.password_lock:
                valid = verify_password(
                    password, account['password'] if account else app.dummy_hash
                )
            if not valid or not account or account['disabled']:
                app.operations.login_event(
                    username,
                    'unknown_user'
                    if not account
                    else 'disabled'
                    if account['disabled']
                    else 'wrong_password',
                )
                raise HttpError(401, '邮箱或密码不正确，或账号已停用')
            account_id = account['id']
            app.operations.login_event(username, 'success')
        return ctx.reply(
            200,
            {'ok': True},
            app.new_session(account_id, ctx.headers.get('User-Agent', ''), ip),
        )
    return UNHANDLED
