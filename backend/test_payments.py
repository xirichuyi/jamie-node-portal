import hashlib
import hmac
import http.client
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from application import App
from errors import DomainError
from http_types import HttpError
from payment_gateway import micros
from routing import authorize
from server import Server
from test_server import FakePanel


class PaymentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = App({'database': str(Path(temp.name) / 'db'), 'origin': 'https://example.test',
                        'package_billing': True, 'payments': {
                            'enabled': True, 'api_key': 'test-key', 'webhook_secret': 'test-webhook',
                            'card_secret': 'test-card-secret', 'wallets': {'binance': '0x' + 'a' * 40},
                        }}, FakePanel())
        card = self.app.ledger.issue('admin', 'Existing', 10, 30, 1, 0)[0]['code']
        self.account = self.app.session(self.app.register_with_card('alice', 'Password-test-123', card))
        self.p = self.app.payments
        self.p.gateway.create = Mock(side_effect=lambda row, url: self.remote(row))
        self.p.gateway.get = Mock()
        self.sql("UPDATE portal_plans SET usdt_micros=1000000,published=1 WHERE id='light'")
        self.key = 'a' * 32

    def sql(self, query, args=()):
        with self.app.ledger.transaction() as db:
            return [dict(r) for r in db.execute(query, args)]

    def remote(self, row, status='pending', **changes):
        return {'id': 'pay_' + row['id'][4:], 'merchant_order_id': row['id'], 'base_amount': '1',
                'pay_amount': '1.0001', 'status': status, 'token': 'USDT', 'network': 'binance',
                'address': '0x' + 'a' * 40, 'tx_hash': '0xtest', 'paid_at': '2026-10-18T08:00:00Z', **changes}

    def create(self, guest=False):
        return self.p.create(None if guest else self.account, 'light', self.key)

    def complete(self, order, **changes):
        self.p.gateway.get.return_value = self.remote(order, 'completed', **changes)
        self.p.sync(order['id'])

    def sign(self, order, **changes):
        event = {'id': 'pay_' + order['id'][4:], 'merchant_order_id': order['id'],
                 'event': 'payment.completed', 'amount': '1', **changes}
        raw = json.dumps(event).encode()
        ts = str(int(time.time()))
        signature = 'sha256=' + hmac.new(b'test-webhook', ts.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        return raw, {'X-Timestamp': ts, 'X-Signature': signature,
                     'X-Webhook-Id': event['id'], 'X-Event': event['event']}

    def test_exact_amounts_and_changed_price_rejected(self):
        self.assertEqual(micros('3.000001'), 3000001)
        for value in ('NaN', 'Infinity', '-1', '0.01', '1.0000001', 3, True, '1e2'):
            with self.assertRaises(DomainError):
                micros(value)
        with self.assertRaises(DomainError):
            self.p.create(self.account, 'light', self.key, 3000000)
        self.assertEqual(self.sql('SELECT * FROM payment_orders'), [])

    def test_duplicate_creation_and_fulfillment_are_atomic(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            orders = list(pool.map(lambda _: self.create(), range(2)))
        self.assertEqual(orders[0]['id'], orders[1]['id'])
        self.p.gateway.create.assert_called_once()
        self.sql("UPDATE portal_plans SET quota_gib=999,name='Changed' WHERE id='light'")
        self.complete(orders[0])
        self.complete(orders[0])
        row = self.p.row(orders[0]['id'])
        self.assertEqual(row['status'], 'fulfilled')
        package = self.sql('SELECT * FROM entitlement_packages WHERE card_id=?', (row['card_id'],))
        self.assertEqual(len(package), 1)
        self.assertEqual(package[0]['granted'], 30 * 1024**3)
        self.assertNotEqual(package[0]['label'], 'Changed')

    def test_fault_keeps_paid_order_without_partial_card_then_retries(self):
        order = self.create()
        before = len(self.sql('SELECT * FROM cards'))
        self.sql("UPDATE billing_accounts SET fault='counter_rollback'")
        self.complete(order)
        self.assertEqual(self.p.row(order['id'])['status'], 'paid')
        self.assertEqual(len(self.sql('SELECT * FROM cards')), before)
        self.sql('UPDATE billing_accounts SET fault=NULL,sampled=?', (int(time.time()),))
        self.p.gateway.get.side_effect = DomainError('gateway temporarily offline')
        self.complete(order)
        self.assertEqual(self.p.row(order['id'])['status'], 'fulfilled')

    def test_gateway_mismatch_never_grants(self):
        order = self.create()
        for mismatch in ({'base_amount': '3'}, {'address': '0x' + 'b' * 40}, {'token': 'USDC'},
                         {'network': 'tron'}, {'merchant_order_id': 'other'}, {'id': 'pay_other123'},
                         {'tx_hash': ''}, {'pay_amount': '0.5'}):
            self.complete(order, **mismatch)
            self.assertIsNone(self.p.row(order['id'])['card_id'])
        self.complete(order)
        self.assertEqual(self.p.row(order['id'])['status'], 'fulfilled')

    def test_guest_claim_uses_secret_and_can_register_once(self):
        order = self.create(guest=True)
        self.complete(order)
        with self.assertRaises(HttpError):
            self.p.get(order['id'], access_key='b' * 32)
        result = self.p.get(order['id'], access_key=self.key)
        self.assertIn('code', result)
        self.assertNotIn('code', self.p.listing(self.account, admin=True)['items'][0])
        token = self.app.register_with_card('buyer', 'Password-test-123', result['code'])
        buyer = self.app.session(token)
        self.assertTrue(self.app.ledger.redeem(buyer['id'], result['code'])['already_redeemed'])
        self.assertEqual(result['code'], self.p.get(order['id'], access_key=self.key)['code'])

    def test_order_ownership_and_admin_authorization(self):
        order = self.create()
        with self.assertRaises(HttpError):
            self.p.get(order['id'], {'id': 'other'})
        with self.assertRaises(HttpError):
            self.p.get(order['id'], access_key=self.key)
        for path in ('/api/orders', '/api/admin/orders'):
            with self.assertRaises(HttpError):
                authorize('GET', path, None)
        with self.assertRaises(HttpError):
            authorize('GET', '/api/admin/orders', {'must_change': False, 'admin': False})

    def test_callback_is_only_a_hint_and_requires_raw_signature(self):
        order = self.create()
        raw, headers = self.sign(order)
        self.p.webhook(raw, headers)
        self.assertEqual(self.p.row(order['id'])['status'], 'pending')
        self.p.gateway.get.return_value = self.remote(order)
        self.p.reconcile()
        self.assertIsNone(self.p.row(order['id'])['card_id'])
        with self.assertRaises(HttpError):
            self.p.webhook(raw + b' ', headers)
        with self.assertRaises(HttpError):
            self.p.webhook(raw, {**headers, 'X-Timestamp': '1000000000'})
        self.complete(order)
        self.p.webhook(raw, headers)
        self.assertEqual(self.p.row(order['id'])['status'], 'fulfilled')

    def test_expired_can_complete_late_and_repeated_events_do_not_revoke(self):
        order = self.create()
        self.p.gateway.get.return_value = self.remote(order, 'expired')
        self.p.sync(order['id'])
        self.assertEqual(self.p.row(order['id'])['status'], 'expired')
        self.complete(order)
        raw, headers = self.sign(order, event='payment.expired')
        self.p.webhook(raw, headers)
        self.assertEqual(self.p.row(order['id'])['status'], 'fulfilled')

    def test_lost_create_response_recovers_same_merchant_order_id(self):
        self.p.gateway.create.side_effect = DomainError('timeout')
        order = self.create()
        self.assertEqual(order['status'], 'creating')
        self.p.gateway.create.side_effect = lambda row, url: self.remote(row)
        self.p.sync(order['id'])
        self.assertEqual(self.p.row(order['id'])['status'], 'pending')
        self.assertEqual(len(self.sql('SELECT * FROM payment_orders')), 1)

    def test_deletion_blocks_pending_and_anonymizes_settled_order(self):
        order = self.create()
        with self.assertRaises(DomainError):
            self.app.account_deletion.request(self.account, self.account['id'], 'alice', 'Password-test-123')
        self.complete(order)
        self.app.account_deletion.request(self.account, self.account['id'], 'alice', 'Password-test-123')
        self.app.account_deletion.purge(self.account['id'])
        row = self.p.row(order['id'])
        self.assertIsNone(row['account_id'])
        self.assertEqual(row['guest'], 0)

    def test_http_callback_exception_does_not_disable_csrf(self):
        server = Server(('127.0.0.1', 0), self.app)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        order = self.create()
        raw, headers = self.sign(order)
        for path, body, hs, expected in [
            ('/api/payments/webhook', raw, headers, 200),
            ('/api/payments/webhook', raw, {}, 403),
            ('/api/checkout', b'{}', {}, 403),
        ]:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1])
            conn.request('POST', path, body, hs)
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, expected)
            conn.close()
