import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from server import App
from errors import DomainError
from passwords import verify_password


class EmailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = App(
            {
                'database': str(Path(self.temp.name) / 'test.db'),
                'mail': {'api_key': 'test-secret', 'from': 'test@example.com'},
            },
            Mock(),
        )
        self.app.email_auth.send = Mock()
        self.card = self.app.ledger.issue('test-admin', 'Test', 1, 30, 1, 30)[0]['code']
        self.email = 'person@example.com'

    def request(self, purpose='register'):
        self.app.email_auth.request(self.email, purpose, 'test-ip', self.card)
        return self.app.email_auth.send.call_args.args[2]

    def register(self, code):
        return self.app.register_with_card(
            self.email, 'Good-password-123', self.card, email_code=code
        )

    def test_verified_registration_atomic_and_replay(self):
        otp = self.request()
        with self.app.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0], 0)
            self.assertNotIn(otp, db.execute('SELECT digest FROM email_challenges').fetchone()[0])
        token = self.register(otp)
        self.assertEqual(self.app.session(token)['username'], self.email)
        self.assertTrue(
            self.app.features.sessions(self.app.session(token), token)['email_verified']
        )
        with self.assertRaises(DomainError):
            self.register(otp)
        with self.app.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM verified_emails').fetchone()[0], 1)

    def test_email_change_requires_both_challenges_and_revokes_sessions(self):
        token = self.register(self.request())
        account = self.app.session(token)
        with self.app.ledger.transaction() as db:
            db.execute('DELETE FROM rate_limits')
        self.app.email_auth.request(None, 'change_old', 'change-ip', owner=account)
        old_code = self.app.email_auth.send.call_args.args[2]
        self.app.email_auth.request('new@example.com', 'change_new', 'change-ip', owner=account)
        new_code = self.app.email_auth.send.call_args.args[2]
        with self.assertRaises(DomainError):
            self.app.email_auth.change(account, 'new@example.com', new_code, 'invalid')
        self.app.email_auth.change(account, 'new@example.com', new_code, old_code)
        self.assertIsNone(self.app.session(token))
        with self.app.ledger.connect() as db:
            self.assertEqual(
                db.execute('SELECT username FROM accounts WHERE id=?', (account['id'],)).fetchone()[
                    0
                ],
                'new@example.com',
            )
            self.assertEqual(
                db.execute(
                    'SELECT email FROM verified_emails WHERE account_id=?', (account['id'],)
                ).fetchone()[0],
                'new@example.com',
            )
        with self.assertRaises(DomainError):
            self.app.email_auth.change(account, 'new@example.com', new_code, old_code)

    def test_email_change_challenge_bound_to_owner(self):
        token = self.register(self.request())
        account = self.app.session(token)
        other_id = self.app.register('another_user', 'Good-password-123')
        other = self.app.session(self.app.new_session(other_id))
        self.app.email_auth.request('new@example.com', 'change_new', 'change-ip', owner=account)
        code = self.app.email_auth.send.call_args.args[2]
        with self.assertRaises(DomainError):
            self.app.email_auth.change(other, 'new@example.com', code, None)

    def test_public_change_challenge_rejected(self):
        with self.assertRaises(DomainError):
            self.app.email_auth.request('new@example.com', 'change_new', 'test-ip')

    def test_wrong_codes_persist_attempt_limit(self):
        otp = self.request()
        wrong = '000000' if otp != '000000' else '111111'
        for _ in range(5):
            with self.assertRaises(DomainError):
                self.register(wrong)
        with self.assertRaises(DomainError):
            self.register(otp)
        self.assertIsNotNone(self.app.card_preview(self.card))

    def test_card_failure_rolls_back_consumption(self):
        otp = self.request()
        with self.assertRaises(DomainError):
            self.app.register_with_card(self.email, 'Good-password-123', 'bad', email_code=otp)
        self.register(otp)

    def test_expired_code_and_delivery_failure(self):
        otp = self.request()
        with self.app.ledger.connect() as db:
            db.execute('UPDATE email_challenges SET expires=0')
        with self.assertRaises(DomainError):
            self.register(otp)
        self.email = 'another@example.com'
        self.app.email_auth.send.side_effect = DomainError('delivery failure')
        with self.assertRaises(DomainError):
            self.request()
        with self.app.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT ready FROM email_challenges').fetchone()[0], 0)

    def test_reset_revokes_sessions_and_is_single_use(self):
        token = self.register(self.request())
        with self.app.ledger.connect() as db:
            db.execute('DELETE FROM rate_limits')
        otp = self.request('reset')
        self.app.email_auth.reset(self.email, otp, 'Changed-password-123')
        self.assertIsNone(self.app.session(token))
        with self.app.ledger.connect() as db:
            row = db.execute('SELECT password FROM accounts').fetchone()
            self.assertTrue(verify_password('Changed-password-123', row['password']))
        with self.assertRaises(DomainError):
            self.app.email_auth.reset(self.email, otp, 'Another-password-123')

    def test_purpose_separation_and_unknown_reset(self):
        otp = self.request()
        with self.assertRaises(DomainError):
            self.app.email_auth.reset(self.email, otp, 'Changed-password-123')
        with self.app.ledger.connect() as db:
            db.execute('DELETE FROM rate_limits')
        self.app.email_auth.send.reset_mock()
        self.app.email_auth.request(self.email, 'reset', 'test-ip')
        self.app.email_auth.send.assert_not_called()

    def test_concurrent_confirmation_consumes_card_once(self):
        otp = self.request()

        def attempt():
            try:
                self.register(otp)
                return True
            except DomainError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(lambda _: attempt(), range(2))), 1)
        with self.app.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM verified_emails').fetchone()[0], 1)

    def test_cooldown_and_required_proof(self):
        from server import HttpError

        with self.assertRaises(DomainError):
            self.register(None)
        self.request()
        with self.assertRaises(HttpError):
            self.request()
        self.app.email_auth.send.assert_called_once()
