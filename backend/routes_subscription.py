"""Subscription routes; shared access checks run before dispatch."""

from urllib.parse import parse_qs, urlsplit
from errors import DomainError
from http_types import UNHANDLED


def dispatch(ctx):
    app = ctx.app
    path = ctx.path
    data = ctx.data
    account = ctx.account
    write = ctx.write
    if not write and path == '/api/me':
        return ctx.reply(200, app.overview(account))
    if not write and path == '/api/history':
        return ctx.reply(200, {'history': app.redemption_history(account['id'])})
    if not write and path == '/api/nodes':
        return ctx.reply(200, app.monitor.snapshot())
    if not write and path == '/api/usage':
        # The home page shows a week; the detail page asks for the full window.
        week = parse_qs(urlsplit(ctx.raw_path).query).get('days') == ['7']
        return ctx.reply(200, app.features.usage(account['id'], 7 if week else 30))
    if not write and path == '/api/service-status':
        return ctx.reply(200, app.features.service_status())
    if write and path in ('/api/subscription/reset', '/api/subscription/reset-credentials'):
        app.reauthenticate(account, data.get('password'))
        app.limit('rotate:' + account['id'], 3, 86400)
        app.features.rotate(account['id'], credentials=path.endswith('reset-credentials'))
        return ctx.reply(200, {'ok': True})
    if write and path in ('/api/redeem', '/api/redeem/preview'):
        preview = path.endswith('/preview')
        app.limit('redeem:' + account['id'], 10, 600)
        code = data.get('code', '')
        if not preview and (not isinstance(code, str) or len(code) > 100):
            raise DomainError('卡密格式不正确')
        with app.ledger.billing_lock:
            if app.ledger.package_billing:
                app.refresh_billing()
            if preview:
                return ctx.reply(
                    200, app.features.preview(account['id'], data.get('code'), data.get('target'))
                )
            result = app.ledger.redeem(account['id'], code, target=data.get('target'))
        app.wake.set()
        return ctx.reply(200, result)
    return UNHANDLED
