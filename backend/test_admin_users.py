import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from server import App
from entitlements import DomainError
from test_server import FakePanel


class UserWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.panel = FakePanel()
        self.panel.request = Mock(return_value=[])
        self.app = App(
            {'database': str(Path(self.temp.name) / 'db'), 'origin': 'https://sub.chuyi.uk'},
            self.panel,
        )
        self.now = int(time.time())
        self.traffic = []

    def tearDown(self):
        self.temp.cleanup()

    def member(self, uid, quota=100, used=20, expires=None, disabled=0, pending=False, error=None):
        self.app.ledger.create_member(uid)
        with self.app.ledger.connect() as db:
            db.execute(
                'INSERT INTO accounts VALUES(?,?,?,0,0)', (uid, uid, 'test-not-a-real-password')
            )
            db.execute(
                """UPDATE members SET quota=?,expires=?,disabled=?,revision=1,synced_revision=?,sync_error=? WHERE id=?""",
                (
                    quota,
                    self.now + 86400 if expires is None else expires,
                    disabled,
                    0 if pending else 1,
                    error,
                    uid,
                ),
            )
            email = db.execute('SELECT panel_email FROM members WHERE id=?', (uid,)).fetchone()[0]
        if used is not None:
            self.traffic.append({'email': email, 'traffic': {'up': used, 'down': 0}})
        self.panel.request.return_value = self.traffic
        self.app.users.sample = None

    def test_state_and_filters_do_not_call_exhausted_or_unknown_users_active(self):
        self.member('active')
        self.member('empty', used=100)
        self.member('expired', expires=self.now - 1)
        self.member('unknown', used=None)
        self.member('disabled', disabled=1, pending=True)
        self.member('sync_error', pending=True, error='retry')
        self.member('unopened', quota=0, used=None)
        result = self.app.users.listing({})
        self.assertEqual(result['counts']['active'], 2)
        self.assertEqual(result['counts']['exhausted'], 1)
        self.assertEqual(result['counts']['unknown'], 1)
        self.assertEqual(result['counts']['pending'], 2)
        disabled = next(m for m in result['members'] if m['id'] == 'disabled')
        self.assertEqual(disabled['primary_state'], 'disabled')
        self.assertEqual(disabled['sync_state'], 'pending')
        self.assertEqual(
            self.app.users.listing({'scope': ['exhausted']})['members'][0]['id'], 'empty'
        )
        encoded = json.dumps(result)
        for secret in ['panel_email', 'panel_auth', 'sub_id', 'password', 'digest']:
            self.assertNotIn('"' + secret + '"', encoded)

    def test_search_and_pagination_cover_more_than_500_users(self):
        with self.app.ledger.transaction() as db:
            for i in range(530):
                uid = f'user_{i:04}'
                db.execute(
                    'INSERT INTO members(id,panel_email,panel_auth,sub_id,created) VALUES(?,?,?,?,?)',
                    (uid, uid, 'private', uid, i),
                )
                db.execute('INSERT INTO accounts VALUES(?,?,?,0,0)', (uid, uid, 'private'))
        first = self.app.users.listing({})
        self.assertEqual(first['total'], 530)
        self.assertEqual(first['pages'], 22)
        self.assertEqual(len(first['members']), 25)
        last = self.app.users.listing({'page': ['999']})
        self.assertEqual(last['page'], 22)
        self.assertEqual(len(last['members']), 5)
        self.assertEqual(self.app.users.listing({'q': ['USER_0000']})['total'], 1)
        self.assertEqual(self.app.users.listing({'q': ['%']})['total'], 0)
        with self.assertRaises(DomainError):
            self.app.users.listing({'scope': ['bogus']})

    def test_failed_usage_read_is_unknown_not_zero_or_stale_success(self):
        self.member('sample')
        self.assertEqual(self.app.users.detail('sample')['member']['used'], 20)
        self.app.users.sample = None
        self.panel.request.side_effect = RuntimeError('offline')
        detail = self.app.users.detail('sample')
        self.assertIsNone(detail['member']['used'])
        self.assertEqual(detail['member']['primary_state'], 'unknown')
        self.assertTrue(detail['usage_error'])

    def test_detail_contains_only_target_history_and_audit(self):
        self.member('alice')
        self.member('bob')
        with self.app.ledger.transaction() as db:
            self.app.ledger.audit(db, 'admin', 'account.disable', 'alice')
            self.app.ledger.audit(db, 'admin', 'account.disable', 'bob')
        code = self.app.ledger.issue('admin', 'Alice only', 1, 1, 1, 1)[0]['code']
        self.app.ledger.redeem('alice', code)
        detail = self.app.users.detail('alice')
        self.assertEqual(len(detail['history']), 1)
        self.assertEqual(len(detail['audit']), 2)
        self.assertNotIn(code, json.dumps(detail))
        with self.assertRaises(DomainError):
            self.app.users.detail('missing')

    def test_sync_attempt_and_success_times_are_real(self):
        self.member('sync', pending=True)
        self.panel.apply = Mock(side_effect=RuntimeError('offline'))
        self.app.ledger.sync_member('sync', self.panel)
        failed = self.app.users.detail('sync')['member']
        self.assertGreater(failed['last_sync_attempt'], 0)
        self.assertEqual(failed['last_synced_at'], 0)
        self.panel.apply.side_effect = None
        self.app.ledger.sync_member('sync', self.panel)
        success = self.app.users.detail('sync')['member']
        self.assertGreater(success['last_synced_at'], 0)
        self.assertEqual(success['sync_state'], 'synced')

    def test_sorting_before_paging_and_unknown_last(self):
        for i in range(30):
            self.member(f'sort_{i:02}', used=i)
        self.member('unknown_sort', used=None)
        result = self.app.users.listing({'sort': ['used'], 'direction': ['desc']})
        self.assertEqual(result['members'][0]['username'], 'sort_29')
        self.assertEqual(len(result['members']), 25)
        for direction in ('asc', 'desc'):
            page = self.app.users.listing(
                {'sort': ['used'], 'direction': [direction], 'page': ['2']}
            )
            self.assertEqual(page['members'][-1]['username'], 'unknown_sort')
        with self.assertRaises(DomainError):
            self.app.users.listing({'sort': ['password']})
        with self.assertRaises(DomainError):
            self.app.users.listing({'direction': ['bad']})

    def test_activity_does_not_claim_online_from_first_counter_or_long_gap(self):
        self.member('activity', used=20)
        first = self.app.users.detail('activity')['member']
        self.assertEqual(first['proxy_activity'], 'unconfirmed')
        self.traffic[0]['traffic']['up'] = 30
        self.app.users.sample = None
        self.assertEqual(self.app.users.detail('activity')['member']['proxy_activity'], 'recent')
        with self.app.ledger.connect() as db:
            db.execute('UPDATE user_traffic_activity SET sampled=sampled-3600,changed=NULL')
        self.traffic[0]['traffic']['up'] = 40
        self.app.users.sample = None
        self.assertEqual(
            self.app.users.detail('activity')['member']['proxy_activity'], 'unconfirmed'
        )
        self.traffic[0]['traffic']['up'] = 0
        self.app.users.sample = None
        self.assertEqual(self.app.users.detail('activity')['member']['counter_reset'], 1)
