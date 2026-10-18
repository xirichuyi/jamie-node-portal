import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from entitlements import Ledger, DomainError
import package_ledger as billing


class PackageLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(str(Path(self.temp.name) / 'billing.db'))
        self.ledger.create_member('alice')
        self.ledger.create_member('bob')
        with self.ledger.connect() as db:
            billing.install(db)
        with self.ledger.transaction() as db:
            for uid in ('alice', 'bob'):
                billing.initialize(
                    db,
                    dict(db.execute('SELECT * FROM members WHERE id=?', (uid,)).fetchone()),
                    0,
                    100,
                )

    def tearDown(self):
        self.temp.cleanup()

    def grant(self, db, quota=100, days=1, kind='base', target=None, uid='alice', now=100):
        # Real card rows are required by the ledger's FK / unique constraints.
        import secrets

        cid = secrets.token_hex(12)
        db.execute(
            """INSERT INTO cards(id,digest,suffix,label,quota,days,redeem_before,created,created_by)
            VALUES(?,?,?,?,?,?,9999999,100,'admin')""",
            (cid, cid, cid, 'test', quota, days),
        )
        return billing.grant(
            db,
            uid,
            {'id': cid, 'kind': kind, 'label': 'test', 'quota': quota, 'days': days},
            now,
            target,
        )

    def test_renewal_queues_after_latest_expiry_and_spends_earliest_first(self):
        with self.ledger.transaction() as db:
            first = self.grant(db, days=1)
            second = self.grant(db, days=2)
            expires = {
                r['id']: r['expires']
                for r in db.execute('SELECT id,expires FROM entitlement_packages')
            }
            # 1 day + 2 days = service until day 3, not overlapping clocks.
            self.assertEqual(expires[first], 100 + 86400)
            self.assertEqual(expires[second], 100 + 3 * 86400)
            billing.sample(db, 'alice', 120, 200)
            state = billing.snapshot(db, 'alice', 200)
            # Queued quota is usable immediately.
            self.assertEqual(state['remaining'], 80)
            spent = {p['id']: p['spent'] for p in state['packages']}
            self.assertEqual(spent[first], 100)
            self.assertEqual(spent[second], 20)
            self.assertEqual(billing.snapshot(db, 'alice', 100 + 2 * 86400)['remaining'], 80)
            self.assertEqual(billing.snapshot(db, 'alice', 100 + 3 * 86400)['remaining'], 0)

    def test_renewal_ignores_expired_permanent_and_other_members(self):
        with self.ledger.transaction() as db:
            self.grant(db, days=1, now=100)
            self.grant(db, days=5, uid='bob', now=100)
            # Previous package already expired: the new one starts now.
            late = self.grant(db, days=2, now=100 + 2 * 86400)
            row = db.execute('SELECT expires FROM entitlement_packages WHERE id=?', (late,)).fetchone()
            self.assertEqual(row[0], 100 + 4 * 86400)
            card = {'id': 'x', 'kind': 'base', 'permanent': 1, 'reset_period': 'never', 'reset_interval': 30, 'days': 1}
            self.assertEqual(billing.base_start(db, 'alice', card, 100 + 2 * 86400), 100 + 2 * 86400)
            db.execute("UPDATE entitlement_packages SET permanent=1,expires=? WHERE id=?", (billing.FOREVER, late))
            dated = {**card, 'permanent': 0}
            # A permanent package never delays dated renewals.
            self.assertEqual(billing.base_start(db, 'alice', dated, 100 + 2 * 86400), 100 + 2 * 86400)

    def test_addon_requires_owned_live_package_and_inherits_exact_expiry(self):
        with self.ledger.transaction() as db:
            first = self.grant(db)
            addon = self.grant(db, kind='addon', target=first, now=200, days=700)
            packages = billing.snapshot(db, 'alice', 200)['packages']
            self.assertEqual(len({p['expires'] for p in packages}), 1)
            self.assertEqual(next(p for p in packages if p['id'] == addon)['parent_id'], first)
            for target, uid, now in [
                (first, 'bob', 200),
                (None, 'alice', 200),
                (first, 'alice', 86500),
            ]:
                with self.assertRaises(DomainError):
                    self.grant(db, kind='addon', target=target, uid=uid, now=now)

    def test_rollback_quarantines_never_restores_consumed_balance(self):
        with self.ledger.transaction() as db:
            self.grant(db)
            billing.sample(db, 'alice', 60, 200)
            billing.sample(db, 'alice', 0, 201)
            billing.sample(db, 'alice', 70, 202)
            state = billing.snapshot(db, 'alice', 202)
            self.assertEqual(state['remaining'], 40)
            self.assertEqual(state['fault'], 'counter_rollback')
            self.assertTrue(billing.desired(db, 'alice', 202)['billing_blocked'])
            with self.assertRaises(DomainError):
                self.grant(db, now=202)

    def test_expiry_and_exhaustion_never_produce_unlimited_panel_cap(self):
        with self.ledger.transaction() as db:
            self.assertGreater(billing.desired(db, 'alice', 100)['quota'], 0)
            self.assertTrue(billing.desired(db, 'alice', 100)['billing_blocked'])
            self.grant(db)
            billing.sample(db, 'alice', 101, 200)
            self.assertTrue(billing.desired(db, 'alice', 200)['billing_blocked'])
            self.assertEqual(billing.snapshot(db, 'alice', 200)['unallocated'], 1)

    def test_transition_preserves_only_remaining_and_original_expiry_once(self):
        self.ledger.create_member('legacy')
        with self.ledger.transaction() as db:
            db.execute('UPDATE members SET quota=1000,expires=500 WHERE id="legacy"')
            member = dict(db.execute('SELECT * FROM members WHERE id="legacy"').fetchone())
            billing.initialize(db, member, 250, 100)
            billing.initialize(db, member, 0, 100)
            s = billing.snapshot(db, 'legacy', 100)
            self.assertEqual(s['remaining'], 750)
            self.assertEqual(s['next_expiry'], 500)
            self.assertEqual(len(s['packages']), 1)
            self.assertEqual(billing.snapshot(db, 'legacy', 500)['remaining'], 0)

    def test_repeated_and_concurrent_samples_cannot_double_charge(self):
        with self.ledger.transaction() as db:
            self.grant(db)

        def sample(_):
            with self.ledger.transaction() as db:
                billing.sample(db, 'alice', 40, 200)

        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            list(pool.map(sample, range(8)))
        with self.ledger.connect() as db:
            self.assertEqual(billing.snapshot(db, 'alice', 200)['remaining'], 60)

    def test_transaction_failure_rolls_back_grant_and_audit(self):
        try:
            with self.ledger.transaction() as db:
                self.grant(db)
                raise RuntimeError('interrupted redemption')
        except RuntimeError:
            pass
        with self.ledger.connect() as db:
            self.assertEqual(billing.snapshot(db, 'alice', 100)['packages'], [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM billing_events').fetchone()[0], 0)
