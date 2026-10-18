"""Private USDTPay API client and exact USDT amounts."""

import json
import re
import urllib.error
import urllib.request
from decimal import Decimal

from errors import DomainError


def micros(value, allow_zero=False):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,7}(?:\.\d{1,6})?', value):
        raise DomainError('USDT 金额格式不正确，最多 6 位小数')
    amount = int(Decimal(value) * 1000000)
    if (amount == 0 and allow_zero) or 100000 <= amount <= 1000000000000:
        return amount
    raise DomainError('USDT 金额应在 0.1 至 1000000 之间')


def amount_text(value):
    return format(Decimal(value) / 1000000, 'f')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the merchant credential to another origin.


class Gateway:
    origin = 'https://pay.chuyi.uk'

    def __init__(self, config):
        self.config = config

    def request(self, path, data=None):
        request = urllib.request.Request(
            self.origin + '/v1/' + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Authorization': 'Bearer ' + self.config['api_key'],
                     'Content-Type': 'application/json', 'User-Agent': 'Jamie-Node-Payments/1'},
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=10) as response:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError('Oversize response')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError('Invalid response')
                return result
        except (OSError, ValueError):
            raise DomainError('支付服务暂未确认结果，请稍后刷新订单，不要重复付款') from None

    def get(self, payment_id):
        if not isinstance(payment_id, str) or not re.fullmatch(r'pay_[A-Za-z0-9_-]{8,80}', payment_id):
            raise DomainError('支付订单编号不正确')
        return self.request('payments/' + payment_id)

    def create(self, order, return_url):
        return self.request('payments', {'merchant_order_id': order['id'],
                                        'amount': amount_text(order['amount']),
                                        'success_url': return_url, 'cancel_url': return_url})
