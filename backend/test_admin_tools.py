import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from server import App
from entitlements import DomainError, GIB
from test_server import FakePanel


class AdminToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.panel = FakePanel()
        self.panel.request = Mock(return_value=[])
        self.app = App(
            {
                'database': str(Path(self.temp.name) / 'db'),
                'origin': 'https://sub.chuyi.uk',
                'package_billing': True,
            },
            self.panel,
        )
        self.admin = self.app.register('boss', 'Admin-password-12345', True)
        self.uid = self.app.register('alice', 'User-password-12345')

    def tearDown(self):
        self.temp.cleanup()

    def spec(self, **overrides):
        values = {'label': '补偿', 'quota_gib': 10, 'days': 7, 'count': 1, 'valid_days': 0}
        values.update(overrides)
        return self.app.ledger.card_spec(**values)

    def test_grant_uses_card_path_and_is_visible_in_history_and_audit(self):
        self.app.ledger.grant(self.admin, self.uid, self.spec())
        detail = self.app.users.detail(self.uid)
        self.assertEqual(detail['member']['quota'], 10 * GIB)
        self.assertEqual(detail['history'][0]['label'], '补偿')
        self.assertTrue(detail['history'][0]['granted'])
        actions = [r['action'] for r in detail['audit']]
        self.assertIn('account.grant', actions)
        with self.app.ledger.connect() as db:
            card = db.execute('SELECT * FROM cards WHERE redeemed_by=?', (self.uid,)).fetchone()
            self.assertEqual(card['created_by'], self.admin)
            self.assertGreater(
                db.execute('SELECT revision FROM members WHERE id=?', (self.uid,)).fetchone()[0], 0
            )

    def test_grant_addon_requires_live_target_and_rolls_back_card(self):
        with self.assertRaises(DomainError):
            self.app.ledger.grant(self.admin, self.uid, self.spec(kind='addon'), 'missing')
        with self.app.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cards').fetchone()[0], 0)
        self.app.ledger.grant(self.admin, self.uid, self.spec())
        package = self.app.users.detail(self.uid)['member']['packages'][0]
        # A fresh billing sample is required before topping up an opened account.
        with self.app.ledger.transaction() as db:
            db.execute('UPDATE billing_accounts SET sampled=? WHERE member_id=?', (int(time.time()), self.uid))
        self.app.ledger.grant(self.admin, self.uid, self.spec(kind='addon', quota_gib=5), package['id'])
        detail = self.app.users.detail(self.uid)
        self.assertEqual(detail['member']['quota'], 15 * GIB)

    def test_grant_refuses_disabled_or_deleting_accounts(self):
        with self.app.ledger.connect() as db:
            db.execute('UPDATE members SET disabled=1 WHERE id=?', (self.uid,))
        with self.assertRaises(DomainError):
            self.app.ledger.grant(self.admin, self.uid, self.spec())
        with self.assertRaises(DomainError):
            self.app.ledger.grant(self.admin, 'nobody', self.spec())

    def test_revoke_batch_only_touches_unused_cards_of_that_batch(self):
        codes = self.app.ledger.issue(self.admin, '月卡', 10, 30, 3, 30)
        other = self.app.ledger.issue(self.admin, '季卡', 10, 90, 1, 30)
        self.app.ledger.redeem(self.uid, codes[0]['code'])
        with self.app.ledger.connect() as db:
            created = db.execute("SELECT created FROM cards WHERE label='月卡'").fetchone()[0]
        self.assertEqual(self.app.ledger.revoke_batch(self.admin, '月卡', created), 2)
        with self.app.ledger.connect() as db:
            rows = {r['id']: r for r in db.execute('SELECT * FROM cards')}
        self.assertIsNone(rows[codes[0]['id']]['revoked_at'])
        self.assertIsNotNone(rows[codes[1]['id']]['revoked_at'])
        self.assertIsNone(rows[other[0]['id']]['revoked_at'])
        self.assertEqual(self.app.ledger.revoke_batch(self.admin, '月卡', created), 0)

    def test_notes_are_saved_cleared_and_audited(self):
        self.app.users.save_note(self.admin, self.uid, '  老客户，优先处理  ')
        note = self.app.users.detail(self.uid)['note']
        self.assertEqual(note['body'], '老客户，优先处理')
        self.assertEqual(note['updated_by'], 'boss')
        self.app.users.save_note(self.admin, self.uid, '')
        self.assertIsNone(self.app.users.detail(self.uid)['note'])
        with self.assertRaises(DomainError):
            self.app.users.save_note(self.admin, self.uid, 'x' * 2001)

    def test_audit_log_filters_and_pages(self):
        self.app.ledger.issue(self.admin, '月卡', 10, 30, 3, 30)
        result = self.app.users.audit_log({'action': ['card.issue']})
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['items'][0]['actor'], 'boss')
        self.assertEqual(result['items'][0]['card_label'], '月卡')
        prefix = self.app.users.audit_log({'action': ['account.']})
        self.assertEqual(prefix['total'], 2)
        by_user = self.app.users.audit_log({'q': ['alice']})
        self.assertEqual(by_user['items'][0]['target_user'], 'alice')
        with self.assertRaises(DomainError):
            self.app.users.audit_log({'page': ['x']})

    def test_badges_trend_and_export(self):
        badges = self.app.users.badges()
        self.assertEqual(set(badges), {'tickets', 'sync_errors', 'pending', 'orders'})
        trend = self.app.users.trend()
        self.assertEqual(len(trend), 14)
        self.assertEqual(trend[-1]['registered'], 2)
        exported = self.app.users.listing({'export': ['1']})
        self.assertEqual(exported['total'], 2)
        self.assertNotIn('pages', exported)
        encoded = json.dumps(exported)
        for secret in ['panel_email', 'panel_auth', 'sub_id', 'password', 'digest']:
            self.assertNotIn(secret, encoded)

    def test_search_covers_email_note_and_plan_but_hides_note_body(self):
        with self.app.ledger.transaction() as db:
            db.execute(
                'INSERT INTO verified_emails VALUES(?,?,?)', (self.uid, 'alice.w@mail.test', 1)
            )
        self.app.users.save_note(self.admin, self.uid, '老客户 VIP')
        self.app.ledger.grant(self.admin, self.uid, self.spec(label='季卡'))
        for keyword in ('MAIL.TEST', 'vip', '季卡'):
            result = self.app.users.listing({'q': [keyword]})
            self.assertEqual([m['id'] for m in result['members']], [self.uid], keyword)
            self.assertNotIn('note_body', result['members'][0])
        self.assertEqual(self.app.users.listing({'q': ['x' * 64]})['total'], 0)
        self.assertNotIn('note_body', self.app.users.detail(self.uid)['member'])
        self.assertEqual(self.app.users.detail(self.uid)['member']['email'], 'alice.w@mail.test')

    def test_listing_cache_is_dropped_by_admin_writes(self):
        self.assertEqual(self.app.users.listing({})['counts']['disabled'], 0)
        self.app.users.set_disabled(self.admin, self.uid, True)
        self.app.users.invalidate()
        self.assertEqual(self.app.users.listing({})['counts']['disabled'], 1)

    def test_overview_counts_do_not_call_the_panel(self):
        self.panel.request.reset_mock()
        self.app.users.sample = None
        self.app.users.invalidate()
        self.app.features.operations()
        self.panel.request.assert_not_called()

    def test_pending_badge_ignores_fresh_sync_and_counts_stale(self):
        with self.app.ledger.transaction() as db:
            db.execute('UPDATE members SET revision=synced_revision+1 WHERE id=?', (self.uid,))
        self.assertEqual(self.app.users.badges()['pending'], 0)
        self.app.users.pending_since[self.uid] -= 301
        self.assertEqual(self.app.users.badges()['pending'], 1)
        with self.app.ledger.transaction() as db:
            db.execute('UPDATE members SET synced_revision=revision WHERE id=?', (self.uid,))
        self.assertEqual(self.app.users.badges()['pending'], 0)
        self.assertEqual(self.app.users.pending_since, {})

    def test_bulk_actions_report_each_user(self):
        bob = self.app.register('bob', 'User-password-12345')
        result = self.app.users.bulk(
            self.admin, {'action': 'disable', 'ids': [self.uid, bob, self.admin, 'nobody']}
        )
        self.assertEqual(result['ok'], 2)
        self.assertEqual([r['ok'] for r in result['results']], [True, True, False, False])
        self.assertEqual(self.app.users.listing({})['counts']['disabled'], 2)
        self.app.users.bulk(self.admin, {'action': 'enable', 'ids': [self.uid, bob]})
        granted = self.app.users.bulk(
            self.admin, {'action': 'grant', 'ids': [self.uid, bob], 'spec': self.spec()}
        )
        self.assertEqual(granted['ok'], 2)
        self.assertEqual(self.app.users.detail(bob)['member']['quota'], 10 * GIB)
        with self.assertRaises(DomainError):
            self.app.users.bulk(
                self.admin, {'action': 'grant', 'ids': [bob], 'spec': self.spec(kind='addon')}
            )
        for bad in ({'action': 'delete', 'ids': [bob]}, {'action': 'sync', 'ids': []},
                    {'action': 'sync', 'ids': ['x'] * 101}):
            with self.assertRaises(DomainError):
                self.app.users.bulk(self.admin, bad)

    def test_staff_tickets_filter_search_and_page_on_server(self):
        with self.app.ledger.transaction() as db:
            for i in range(35):
                db.execute(
                    'INSERT INTO support_tickets VALUES(?,?,?,?,?,?,?)',
                    (f't{i}', self.uid, f'旧问题 {i}', 'other', 'waiting', i, i),
                )
        result = self.app.features.tickets(None, True, {})
        self.assertEqual(result['counts']['waiting'], 35)
        self.assertEqual((len(result['tickets']), result['pages']), (30, 2))
        # Longest-waiting first: the oldest inserted tickets lead the queue.
        self.assertEqual(result['tickets'][0]['id'], 't0')
        self.assertEqual(len(self.app.features.tickets(None, True, {'page': ['2']})['tickets']), 5)
        self.assertEqual(self.app.features.tickets(None, True, {'q': ['旧问题 1']})['total'], 11)
        self.assertEqual(self.app.features.tickets(None, True, {'q': ['ALICE']})['total'], 35)
        self.assertEqual(self.app.features.tickets(None, True, {'status': ['closed']})['total'], 0)
        with self.assertRaises(DomainError):
            self.app.features.tickets(None, True, {'status': ['bogus']})

    def test_card_notes_show_who_received_and_who_redeemed(self):
        codes = self.app.ledger.issue(self.admin, '月卡', 10, 30, 2, 30, note='发给 张三 (微信)')
        self.assertEqual(codes[0]['suffix'], codes[0]['code'].replace('-', '')[-8:])
        self.app.ledger.redeem(self.uid, codes[0]['code'])
        self.app.ledger.set_card_note(self.admin, codes[1]['id'], '李四')
        found = self.app.operations.cards({'query': '张三'})['cards']
        self.assertEqual([c['id'] for c in found], [codes[0]['id']])
        self.assertEqual(found[0]['redeemed_by'], 'alice')
        # A customer redeeming in the same second as issuing is not a grant.
        self.assertFalse(found[0]['granted'])
        self.assertEqual(found[0]['issued_by'], 'boss')
        self.assertEqual(self.app.operations.cards({'query': 'ali'})['total'], 1)
        self.assertEqual(self.app.operations.cards({'query': '%'})['total'], 0)
        with self.app.ledger.connect() as db:
            created = db.execute("SELECT created FROM cards WHERE label='月卡'").fetchone()[0]
        batch = self.app.operations.cards({'batch': {'label': '月卡', 'created': created}})
        self.assertEqual({c['note'] for c in batch['cards']}, {'发给 张三 (微信)', '李四'})
        history = self.app.users.detail(self.uid)['history'][0]
        self.assertEqual((history['suffix'], history['note']), (found[0]['suffix'], '发给 张三 (微信)'))
        with self.assertRaises(DomainError):
            self.app.ledger.set_card_note(self.admin, codes[1]['id'], 'x' * 101)
        with self.assertRaises(DomainError):
            self.app.operations.cards({'batch': {'label': '月卡'}})
        encoded = json.dumps(batch)
        for secret in ['digest', codes[1]['code']]:
            self.assertNotIn(secret, encoded)

    def test_parallel_packages_expose_nearest_and_final_expiry(self):
        now = int(time.time())
        self.app.ledger.grant(self.admin, self.uid, self.spec(days=30), now=now)
        with self.app.ledger.transaction() as db:
            db.execute('UPDATE billing_accounts SET sampled=? WHERE member_id=?', (now, self.uid))
        self.app.ledger.grant(self.admin, self.uid, self.spec(days=60), now=now)
        member = self.app.users.detail(self.uid)['member']
        self.assertEqual(member['expires'], now + 30 * 86400)
        # 30-day package then a queued 60-day package: service ends after 90 days.
        self.assertEqual(member['final_expires'], now + 90 * 86400)

    def test_redemption_preview_matches_queued_expiry(self):
        now = int(time.time())
        self.app.ledger.grant(self.admin, self.uid, self.spec(days=30), now=now)
        code = self.app.ledger.issue(self.admin, '季卡', 10, 60, 1, 30)[0]['code']
        preview = self.app.features.preview(self.uid, code)
        self.assertAlmostEqual(preview['after_expires'], now + 90 * 86400, delta=5)
        with self.app.ledger.transaction() as db:
            db.execute('UPDATE billing_accounts SET sampled=? WHERE member_id=?', (int(time.time()), self.uid))
        self.app.ledger.redeem(self.uid, code)
        self.assertEqual(self.app.users.detail(self.uid)['member']['final_expires'], preview['after_expires'])

    def test_card_search_accepts_links_partial_tails_and_names(self):
        code = self.app.ledger.issue(self.admin, '标准月卡', 10, 30, 1, 30, note='张三')[0]['code']
        self.app.ledger.issue(self.admin, '季卡', 10, 90, 1, 30)

        def found(q):
            return self.app.operations.cards({'query': q})['total']

        for query in (code, code.lower(), code.replace('-', ''), ' ' + code + ' ', code[-8:],
                      code[-4:].lower(), '标准月卡', '张三',
                      'https://sub.chuyi.uk/#/redeem?code=' + code):
            self.assertEqual(found(query), 1, query)
        # Only the tail is stored; the head of a code cannot match by design.
        self.assertEqual(found(code[:8]) if code[:8] not in code[-8:] else 0, 0)
        self.assertEqual(found('%'), 0)
        with self.assertRaises(DomainError):
            self.app.operations.cards({'query': 'x' * 301})


if __name__ == '__main__':
    unittest.main()
