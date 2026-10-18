"""Checkout access rules, separate from the signed server-to-server callback."""

from urllib.parse import parse_qs, urlsplit
from http_types import UNHANDLED
from errors import DomainError


def dispatch(ctx):
    app, path, data = ctx.app, ctx.path, ctx.data
    if ctx.write and path in ('/api/orders', '/api/checkout'):
        guest = path == '/api/checkout'
        app.limit('checkout:' + (ctx.ip if guest else ctx.account['id']), 10, 600)
        plan_id = data.get('plan_id')
        if not isinstance(plan_id, str) or len(plan_id) > 64:
            raise DomainError('请选择套餐')
        if type(data.get('expected_amount')) is not int:
            raise DomainError('请刷新页面确认套餐价格')
        return ctx.reply(200, app.payments.create(None if guest else ctx.account, plan_id, data.get('request_key'), data['expected_amount']))
    if ctx.write and path == '/api/checkout/status':
        app.limit('checkout-read:' + ctx.ip, 120, 60)
        oid = data.get('id')
        if not isinstance(oid, str) or len(oid) > 64:
            raise DomainError('订单编号不正确')
        return ctx.reply(200, app.payments.get(oid, access_key=data.get('access_key')))
    if not ctx.write and path == '/api/orders':
        query = parse_qs(urlsplit(ctx.raw_path).query)
        return ctx.reply(200, app.payments.listing(ctx.account, query.get('page', ['1'])[0]))
    return UNHANDLED
