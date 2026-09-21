"""Support routes; shared access checks run before dispatch."""

from urllib.parse import parse_qs, urlsplit
from errors import DomainError
from http_types import UNHANDLED


def dispatch(ctx):
    app = ctx.app
    path = ctx.path
    data = ctx.data
    account = ctx.account
    write = ctx.write
    if path == '/api/tickets':
        if write:
            app.limit('ticket:' + account['id'], 20, 3600)
            return ctx.reply(200, app.features.ticket_write(account, data))
        tid = parse_qs(urlsplit(ctx.raw_path).query).get('id', [''])[0]
        return ctx.reply(
            200, app.features.ticket(account, tid) if tid else app.features.tickets(account)
        )
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
