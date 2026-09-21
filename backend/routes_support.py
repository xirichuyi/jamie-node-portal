"""Support routes; shared access checks run before dispatch."""

from urllib.parse import parse_qs, urlsplit
from errors import DomainError
from http_types import UNHANDLED


def ticket_request(ctx, staff=False):
    if ctx.write:
        ctx.app.limit('ticket:' + ctx.account['id'], 60 if staff else 20, 3600)
        result = ctx.app.features.ticket_write(ctx.account, ctx.data, staff)
    else:
        tid = parse_qs(urlsplit(ctx.raw_path).query).get('id', [''])[0]
        features = ctx.app.features
        result = (
            features.ticket(ctx.account, tid, staff)
            if tid
            else features.tickets(ctx.account, staff)
        )
    return ctx.reply(200, result)


def dispatch(ctx):
    app = ctx.app
    path = ctx.path
    data = ctx.data
    account = ctx.account
    write = ctx.write
    if path == '/api/tickets':
        return ticket_request(ctx)
    if path == '/api/notifications':
        if write and type(data.get('ticket_email')) is not bool:
            raise DomainError('无效提醒设置')
        return ctx.reply(
            200,
            app.ticket_notifications.preferences(
                account, data.get('ticket_email') if write else None
            ),
        )
    if write and path == '/api/tickets/read':
        app.features.ticket_read(account, data.get('id'), data.get('message_id'))
        return ctx.reply(200, {'ok': True})
    return UNHANDLED
