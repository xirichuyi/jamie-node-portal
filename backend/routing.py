"""Shared access policy and five small domain dispatchers; no routing framework."""

from http_types import HttpError, UNHANDLED
import routes_auth
import routes_account
import routes_subscription
import routes_support
import routes_admin
import routes_payments

PUBLIC = {('GET', '/api/content')} | {
    ('POST', '/api/' + name)
    for name in ('register/preview', 'email/code', 'email/reset', 'recover', 'login', 'register', 'checkout', 'checkout/status')
}
PASSWORD_CHANGE_ALLOWED = {
    ('POST', '/api/logout'),
    ('POST', '/api/password'),
    ('GET', '/api/me'),
    ('GET', '/api/nodes'),
}


def authorize(method, path, account):
    if (method, path) in PUBLIC:
        return
    if not account:
        raise HttpError(401, '请先登录')
    if account['must_change'] and (method, path) not in PASSWORD_CHANGE_ALLOWED:
        raise HttpError(403, '请先修改初始密码')
    if path.startswith('/api/admin/') and not account['admin']:
        raise HttpError(403, '仅管理员可访问')


def dispatch(ctx):
    method = 'POST' if ctx.write else 'GET'
    authorize(method, ctx.path, ctx.account)
    groups = (
        (routes_auth, routes_payments)
        if (method, ctx.path) in PUBLIC
        else (routes_admin,)
        if ctx.path.startswith('/api/admin/')
        else (routes_account, routes_subscription, routes_support, routes_payments)
    )
    for group in groups:
        result = group.dispatch(ctx)
        if result is not UNHANDLED:
            return result
    raise HttpError(404, '页面不存在')
