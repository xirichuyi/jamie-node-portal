import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock
from server import App
from test_server import FakePanel
from entitlements import GIB
from errors import DomainError
from cycles import FOREVER, TZ, next_reset
from package_ledger import desired


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = App(
            {
                'database': str(Path(self.temp.name) / 'db'),
                'origin': 'https://example.test',
                'package_billing': True,
            },
            FakePanel(),
        )
        self.ledger = self.app.ledger

    def create(self, **rule):
        code = self.ledger.issue('admin', 'Cycle', 100, 30, 1, 0, **rule)[0]['code']
        token = self.app.register_with_card('alice', 'Secret-password-123', code)
        user = self.app.session(token)
        with self.ledger.connect() as db:
            member = dict(db.execute('SELECT * FROM members WHERE id=?', (user['id'],)).fetchone())
        return user, member

    def test_permanent_monthly_reset_does_not_stack_or_reset_counter(self):
        user, member = self.create(permanent=True, reset_period='monthly')
        uid = user['id']
        p = self.ledger.billing_snapshot(uid)['packages'][0]
        self.assertEqual(p['expires'], FOREVER)
        self.assertEqual(member['expires'], p['next_reset'])
        self.ledger.sample_billing({member['panel_email']: 80 * GIB}, now=p['next_reset'] - 1)
        self.assertEqual(self.ledger.billing_snapshot(uid)['remaining'], 20 * GIB)
        self.ledger.sample_billing({member['panel_email']: 90 * GIB}, now=p['next_reset'])
        state = self.ledger.billing_snapshot(uid, now=p['next_reset'])
        self.assertEqual(state['remaining'], 100 * GIB)
        self.assertEqual(state['raw'], 90 * GIB)
        self.assertEqual(state['consumed'], 90 * GIB)
        self.ledger.sample_billing({member['panel_email']: 95 * GIB}, now=p['next_reset'] + 1)
        self.assertEqual(self.ledger.billing_snapshot(uid)['remaining'], 95 * GIB)
        self.assertEqual(self.app.overview(user)['subscription']['expires'], FOREVER)
        with self.ledger.connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM billing_events WHERE kind='cycle_reset'"
                ).fetchone()[0],
                1,
            )

    def test_missing_sample_does_not_renew_and_missed_periods_do_not_accumulate(self):
        user, member = self.create(permanent=True, reset_period='interval', reset_interval=1)
        p = self.ledger.billing_snapshot(user['id'])['packages'][0]
        self.ledger.sample_billing({}, now=p['next_reset'] + 5 * 86400)
        with self.ledger.connect() as db:
            self.assertLess(
                desired(db, user['id'], p['next_reset'] + 5 * 86400)['expires'],
                p['next_reset'] + 5 * 86400,
            )
        self.ledger.sample_billing(
            {member['panel_email']: 99 * GIB}, now=p['next_reset'] + 5 * 86400
        )
        state = self.ledger.billing_snapshot(user['id'], now=p['next_reset'] + 5 * 86400)
        self.assertEqual(state['remaining'], 100 * GIB)
        self.assertEqual(state['packages'][0]['next_reset'], p['next_reset'] + 6 * 86400)

    def test_addon_expires_at_current_cycle_and_does_not_renew(self):
        user, member = self.create(permanent=True, reset_period='interval', reset_interval=1)
        p = self.ledger.billing_snapshot(user['id'])['packages'][0]
        card = self.ledger.issue('admin', 'Extra', 10, 1, 1, 30, kind='addon')[0]['code']
        self.ledger.redeem(user['id'], card, target=p['id'])
        state = self.ledger.billing_snapshot(user['id'])
        addon = next(x for x in state['packages'] if x['kind'] == 'addon')
        self.assertEqual(addon['expires'], p['next_reset'])
        self.ledger.sample_billing({member['panel_email']: 0}, now=p['next_reset'])
        state = self.ledger.billing_snapshot(user['id'], now=p['next_reset'])
        self.assertEqual(state['remaining'], 100 * GIB)

    def test_addon_cannot_be_redeemed_into_overdue_unsampled_cycle(self):
        user, member = self.create(permanent=True, reset_period='monthly')
        p = self.ledger.billing_snapshot(user['id'])['packages'][0]
        code = self.ledger.issue('admin', 'Extra', 1, 1, 1, 0, kind='addon')[0]['code']
        with self.ledger.transaction() as db:
            db.execute(
                'UPDATE entitlement_packages SET next_reset=? WHERE id=?', (p['created'], p['id'])
            )
        with self.assertRaises(DomainError):
            self.ledger.redeem(user['id'], code, target=p['id'])
        with self.ledger.connect() as db:
            self.assertIsNone(
                db.execute(
                    'SELECT redeemed_at FROM cards WHERE digest=?', (self.ledger.digest(code),)
                ).fetchone()[0]
            )

    def test_calendar_last_day_and_interval_anchor(self):
        rule = {'reset_period': 'monthly'}

        def ts(y, m, d):
            return int(datetime(y, m, d, 16, 23, 45, tzinfo=TZ).timestamp())

        anchor = ts(2028, 1, 31)
        self.assertEqual(next_reset(rule, anchor), ts(2028, 2, 29))
        self.assertEqual(next_reset(rule, ts(2028, 2, 29), anchor), ts(2028, 3, 31))
        self.assertEqual(next_reset(rule, ts(2029, 2, 1), anchor), ts(2029, 2, 28))
        self.assertEqual(next_reset(rule, ts(2029, 2, 28), anchor), ts(2029, 3, 31))
        self.assertEqual(next_reset(rule, ts(2026, 9, 18)), ts(2026, 10, 18))
        self.assertEqual(
            next_reset({'reset_period': 'interval', 'reset_interval': 30}, 100 + 91 * 86400, 100),
            100 + 120 * 86400,
        )

    def test_expired_subscription_never_renews(self):
        user, member = self.create(reset_period='interval', reset_interval=1)
        p = self.ledger.billing_snapshot(user['id'])['packages'][0]
        self.ledger.sample_billing({member['panel_email']: GIB}, now=p['expires'])
        self.assertEqual(self.ledger.billing_snapshot(user['id'], now=p['expires'])['remaining'], 0)

    def test_custom_limits_and_invalid_combinations(self):
        code = self.ledger.issue('admin', 'Large', 9000, 1000, 1, 0, permanent=True)[0]['code']
        self.assertTrue(self.app.card_preview(code)['permanent'])
        for rule in (
            {'reset_period': 'bad'},
            {'reset_period': 'monthly', 'reset_day': 1},
            {'reset_period': 'interval', 'reset_interval': 0},
        ):
            with self.assertRaises(DomainError):
                self.ledger.issue('admin', 'Invalid', 1, 30, 1, 30, **rule)

    def test_panel_style_flexible_issue(self):
        # 0 days = no expiry, fractional GiB, add-ons ignore their own duration.
        spec = self.ledger.card_spec('Pack', 0.5, 0, 1, 0)
        self.assertEqual((spec['quota'], spec['rule']['permanent']), (GIB // 2, 1))
        addon = self.ledger.card_spec('Add', 2, 30, 1, 0, 'addon', permanent=True)
        self.assertEqual(addon['rule']['permanent'], 0)
        with self.assertRaises(DomainError):
            self.ledger.card_spec('Tiny', 0.0001, 30, 1, 0)

    def test_counter_rollback_does_not_grant_cycle(self):
        user, member = self.create(permanent=True, reset_period='interval', reset_interval=1)
        p = self.ledger.billing_snapshot(user['id'])['packages'][0]
        self.ledger.sample_billing({member['panel_email']: GIB}, now=p['next_reset'] - 1)
        self.ledger.sample_billing({member['panel_email']: 0}, now=p['next_reset'])
        self.assertEqual(self.ledger.billing_snapshot(user['id'])['fault'], 'counter_rollback')

    def test_metadata_reports_business_quota_and_permanent_expiry(self):
        user, member = self.create(permanent=True, reset_period='monthly')
        self.ledger.sample_billing({member['panel_email']: 20 * GIB})
        self.assertEqual(
            self.app.subscription_info(member['sub_id']),
            f'upload=0; download={20 * GIB}; total={100 * GIB}; expire=0',
        )
        self.assertIsNone(self.app.subscription_info('unknown-subscription'))
        with self.ledger.transaction() as db:
            db.execute('UPDATE members SET disabled=1 WHERE id=?', (user['id'],))
        from server import HttpError

        with self.assertRaises(HttpError):
            self.app.subscription_info(member['sub_id'])

    def test_saved_plan_rule_is_snapshotted_on_card_and_old_cards_unchanged(self):
        data = self.app.content.read(True)['plans'][0]
        old_code = self.ledger.issue('admin', 'Old', 100, 30, 1, 30)[0]['code']
        self.app.content.save(
            'admin',
            'plan',
            {**data, 'published': True, 'permanent': True, 'reset_period': 'monthly'},
        )
        plan = self.app.content.plan_for_card(data['id'])
        self.assertEqual(plan['reset_period'], 'monthly')
        self.assertEqual(plan['permanent'], 1)
        self.assertEqual(self.app.card_preview(old_code)['reset_period'], 'never')

    def test_local_metadata_http_boundary(self):
        import http.client
        import json
        import threading
        from server import Server

        user, member = self.create(permanent=True, reset_period='monthly')
        server = Server(('127.0.0.1', 0), self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for headers, status in (
                ({}, 200),
                ({'X-Forwarded-For': '203.0.113.1'}, 404),
                ({'X-Real-IP': '127.0.0.1'}, 404),
            ):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1])
                connection.request(
                    'GET', '/internal/subscription-info/' + member['sub_id'], headers=headers
                )
                response = connection.getresponse()
                self.assertEqual(response.status, status)
                body = json.loads(response.read())
                if status == 200:
                    self.assertEqual(set(body), {'usage'})
                    self.assertIn('expire=0', body['usage'])
                connection.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_permanent_nonrecurring_panel_expiry_is_zero(self):
        from panel import Panel

        panel = Panel.__new__(Panel)
        panel.inbounds = [1]
        client = {
            'email': 'test',
            'auth': 'auth',
            'subId': 'sub',
            'totalGB': 100,
            'expiryTime': 0,
            'enable': True,
        }
        panel.get = Mock(return_value={'client': client, 'inboundIds': [1]})
        panel.request = Mock(side_effect=[[{'email': 'test'}], {}])
        panel.apply(
            {
                'panel_email': 'test',
                'panel_auth': 'auth',
                'sub_id': 'sub',
                'quota': 100,
                'expires': FOREVER,
                'disabled': 0,
            }
        )
        sent = panel.request.call_args_list[1].args[1]
        self.assertEqual(sent['expiryTime'], 0)
        self.assertEqual(sent['trafficReset'], 'never')
