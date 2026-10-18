import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError

from application import App
from errors import DomainError
from http_types import HttpError
from routing import authorize
import mail_history


class MailHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = App({'database': str(Path(temp.name) / 'db'),
                        'mail': {'api_key': 'test-key', 'from': 'test@example.test'}}, Mock())

    def test_delivery_metadata_and_retry_do_not_store_body(self):
        content = {'subject': '验证邮箱', 'text': 'Secret OTP 765432', 'html': '<p>765432</p>'}
        with patch('email_auth.urllib.request.urlopen', side_effect=URLError('private details')):
            with self.assertRaises(DomainError):
                self.app.email_auth.deliver('alice@example.test', content, 'email-challenge-test')
        row = mail_history.listing(self.app, {})['items'][0]
        self.assertEqual((row['status'], row['attempts']), ('failed', 1))
        self.assertNotIn('private details', row['error'])
        with patch('email_auth.urllib.request.urlopen', return_value=io.BytesIO(b'{"id":"provider-test"}')):
            self.app.email_auth.deliver('alice@example.test', content, 'email-challenge-test')
        result = mail_history.listing(self.app, {})
        self.assertEqual(result['total'], 1)
        row = result['items'][0]
        self.assertEqual((row['status'], row['attempts'], row['provider_id']), ('sent', 2, 'provider-test'))
        self.assertNotIn('765432', str(result))
        self.assertEqual(mail_history.listing(self.app, {'status': ['failed']})['total'], 0)

    def test_pagination_validation_and_admin_access(self):
        for i in range(31):
            mail_history.record(self.app, str(i), 'a@example.test', 'Test', 'sent')
        self.assertEqual(len(mail_history.listing(self.app, {})['items']), 30)
        self.assertEqual(len(mail_history.listing(self.app, {'page': ['2']})['items']), 1)
        for query in ({'page': ['bad']}, {'status': ['invalid']}):
            with self.assertRaises(DomainError):
                mail_history.listing(self.app, query)
        for account in (None, {'must_change': False, 'admin': False}):
            with self.assertRaises(HttpError):
                authorize('GET', '/api/admin/mail-history', account)
        authorize('GET', '/api/admin/mail-history', {'must_change': False, 'admin': True})
