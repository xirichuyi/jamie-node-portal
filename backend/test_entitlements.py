import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from entitlements import DomainError, GIB, Ledger


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(str(Path(self.temp.name) / 'test.db'))
        self.ledger.create_member('alice')
        self.ledger.create_member('bob')

    def tearDown(self):
        self.temp.cleanup()

    def code(self):
        return self.ledger.issue('admin', '标准卡', 100, 30, 1, 90)[0]

    def member(self):
        with self.ledger.connect() as db:
            return dict(db.execute('SELECT * FROM members WHERE id="alice"').fetchone())

    def test_retry_does_not_double_credit(self):
        code = self.code()['code']
        self.ledger.redeem('alice', code, now=1000)
        self.ledger.redeem('alice', code, now=2000)
        self.assertEqual(self.member()['quota'], 100 * GIB)
        self.assertEqual(self.member()['expires'], 1000 + 30 * 86400)

    def test_concurrent_redemption_only_one_owner(self):
        code = self.code()['code']

        def redeem(user):
            try:
                self.ledger.redeem(user, code)
                return True
            except DomainError:
                return False

        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(redeem, ['alice', 'bob'])), 1)

    def test_stacking_extends_and_adds(self):
        self.ledger.redeem('alice', self.code()['code'], now=1000)
        self.ledger.redeem('alice', self.code()['code'], now=2000)
        self.assertEqual(self.member()['quota'], 200 * GIB)
        self.assertEqual(self.member()['expires'], 1000 + 60 * 86400)

    def test_revoked_cannot_redeem(self):
        card = self.code()
        self.ledger.revoke('admin', card['id'])
        with self.assertRaises(DomainError):
            self.ledger.redeem('alice', card['code'])

    def test_partial_panel_failure_retry_absolute_target(self):
        targets = []

        class Panel:
            def apply(self, state):
                targets.append((state['quota'], state['expires']))
                if len(targets) == 1:
                    raise TimeoutError('after partial commit')

        self.ledger.redeem('alice', self.code()['code'])
        self.assertFalse(self.ledger.sync_member('alice', Panel()))
        self.assertEqual(self.ledger.pending(), ['alice'])
        self.assertTrue(self.ledger.sync_member('alice', Panel()))
        self.assertEqual(targets[0], targets[1])
        self.assertEqual(self.ledger.pending(), [])

    def test_new_redemption_during_sync_remains_pending(self):
        ledger = self.ledger
        new_code = self.code()['code']

        class Panel:
            def apply(self, state):
                ledger.redeem('alice', new_code)

        ledger.redeem('alice', self.code()['code'])
        ledger.sync_member('alice', Panel())
        self.assertEqual(ledger.pending(), ['alice'])
        self.assertEqual(self.member()['revision'], 2)
        self.assertEqual(self.member()['synced_revision'], 1)

    def test_plaintext_codes_not_persisted(self):
        card = self.code()
        with self.ledger.connect() as db:
            rows = str([dict(r) for r in db.execute('SELECT * FROM cards').fetchall()])
            self.assertNotIn(card['code'], rows)


if __name__ == '__main__':
    unittest.main()
