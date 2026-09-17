"""Deterministic query-budget tests, not flaky wall-clock assertions."""

import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

from server import App
from errors import DomainError
from package_ledger import desired, sample, snapshot, summaries


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = App(
            {
                'database': str(Path(self.temp.name) / 'db'),
                'origin': 'https://example.test',
                'package_billing': True,
            },
            Mock(),
        )
        self.now = int(time.time())
        self.app.users.sample = {'at': self.now, 'values': {}, 'error': None}
        with self.app.ledger.transaction() as db:
            for i in range(30):
                uid = f'user_{i}'
                db.execute(
                    """INSERT INTO members(id,panel_email,panel_auth,sub_id,quota,expires,created)
                    VALUES(?,?,?,?,?,?,?)""",
                    (uid, uid, 'test', uid, 1000, self.now + 86400, self.now),
                )
                db.execute('INSERT INTO accounts VALUES(?,?,?,0,0)', (uid, uid, 'not-a-password'))
                db.execute(
                    'INSERT INTO billing_accounts(member_id,raw,sampled) VALUES(?,0,?)',
                    (uid, self.now),
                )
                for j in range(5):
                    db.execute(
                        """INSERT INTO entitlement_packages
                        (id,member_id,kind,label,granted,spent,created,expires,revoked)
                        VALUES(?,?,'base','test',100,?,?,?,?)""",
                        (
                            f'{uid}_{j}',
                            uid,
                            j * 25,
                            self.now - 200,
                            self.now - 100 if j == 0 else self.now + 100,
                            j == 1,
                        ),
                    )
        self.connections = 0
        self.statements = []
        original = self.app.ledger.connect

        @contextmanager
        def counted():
            self.connections += 1
            with original() as db:
                db.set_trace_callback(self.statements.append)
                yield db

        self.app.ledger.connect = counted

    def tearDown(self):
        self.temp.cleanup()

    def test_list_constant_query_budget_and_no_package_history_payload(self):
        result = self.app.users.listing({})
        self.assertEqual(result['total'], 30)
        self.assertEqual(self.connections, 1)
        self.assertEqual(sum(s.startswith('SELECT') for s in self.statements), 2)
        self.assertTrue(all('packages' not in m for m in result['members']))

    def test_detail_only_loads_target_with_constant_connections(self):
        result = self.app.users.detail('user_12')
        self.assertEqual(result['member']['id'], 'user_12')
        self.assertEqual(len(result['member']['packages']), 5)
        self.assertEqual(self.connections, 2)
        self.assertTrue(all(p['id'].startswith('user_12_') for p in result['member']['packages']))

    def test_aggregate_matches_existing_snapshot_and_desired_semantics(self):
        with self.app.ledger.connect() as db:
            for now in (self.now, self.now + 200):
                batch = summaries(db, now)
                for uid, s in batch.items():
                    old = snapshot(db, uid, now)
                    for field in ('remaining', 'next_expiry', 'last_expiry', 'raw', 'fault'):
                        self.assertEqual(s[field], old[field])
                    self.assertEqual(
                        desired(db, uid, now),
                        {
                            'quota': max(1, old['raw'] + old['remaining']),
                            'expires': old['next_expiry'] or old['last_expiry'] or now,
                            'billing_blocked': bool(old['fault']) or not old['remaining'],
                        },
                    )

    def test_idle_counter_sample_does_not_fetch_packages(self):
        with self.app.ledger.transaction() as db:
            sample(db, 'user_1', 0, self.now + 1)
        queries = [sql for sql in self.statements if 'FROM entitlement_packages' in sql]
        self.assertEqual(len(queries), 1)
        self.assertIn('next_reset>0 AND next_reset<=', queries[0])

    def test_recent_session_does_not_acquire_write_transaction(self):
        token = self.app.new_session('user_1')
        self.statements.clear()
        self.assertEqual(self.app.session(token)['id'], 'user_1')
        self.assertFalse(any(sql.startswith(('UPDATE', 'BEGIN')) for sql in self.statements))
        with self.app.ledger.connect() as db:
            db.execute('UPDATE session_details SET seen=seen-120')
        self.statements.clear()
        self.app.session(token)
        self.assertTrue(any(sql.startswith('UPDATE session_details') for sql in self.statements))

    def test_bad_sort_rejected_before_network_or_database_work(self):
        with self.assertRaises(DomainError):
            self.app.users.listing({'sort': ['password']})
        self.assertEqual(self.connections, 0)
        self.app.panel.request.assert_not_called()

    def test_expiry_cleanup_has_indexed_plan(self):
        with self.app.ledger.connect() as db:
            plan = str(
                [
                    tuple(r)
                    for r in db.execute(
                        'EXPLAIN QUERY PLAN DELETE FROM rate_limits WHERE expires<?', (self.now,)
                    )
                ]
            )
        self.assertIn('idx_rate_limits_expires', plan)

    def test_many_addons_do_not_replace_or_hide_base_plan_name(self):
        with self.app.ledger.transaction() as db:
            for i in range(52):
                db.execute(
                    """INSERT INTO cards
                    (id,digest,suffix,label,quota,days,created,created_by,redeem_before,redeemed_by,redeemed_at,kind)
                    VALUES(?,?,?,?,100,1,1,'admin',9999999999,'user_1',?,?)""",
                    (
                        str(i),
                        str(i),
                        str(i),
                        'Original plan' if i == 0 else 'Add-on',
                        self.now + i,
                        'base' if i == 0 else 'addon',
                    ),
                )
        account = {'id': 'user_1', 'username': 'user_1', 'admin': False, 'must_change': False}
        self.assertEqual(self.app.overview(account)['subscription']['plan_name'], 'Original plan')
        self.assertEqual(self.app.users.detail('user_1')['member']['plan_name'], 'Original plan')
