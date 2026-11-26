"""Open registration: the card is optional and a card-free account starts empty."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from server import App
from errors import DomainError
from test_server import FakePanel


class OpenRegistrationTests(unittest.TestCase):
    def make(self, **config):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        panel = FakePanel()
        panel.request = Mock(return_value=[])
        return App({'database': str(Path(temp.name) / 'db'), 'origin': 'https://example.test',
                    **config}, panel)

    def counts(self, app):
        with app.ledger.connect() as db:
            return {t: db.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]
                    for t in ('accounts', 'members', 'cards', 'entitlement_packages')}

    def test_card_free_account_is_empty_then_redeems_normally(self):
        for billing in (True, False):
            app = self.make(package_billing=billing)
            for code in (None, '', '   '):
                name = 'user_' + str(len(str(code)))
                token = app.register_with_card(name, 'Secret-password-123', code)
                account = app.session(token)
                self.assertEqual(account['username'], name)
                with app.ledger.connect() as db:
                    member = db.execute('SELECT * FROM members WHERE id=?', (account['id'],)).fetchone()
                self.assertEqual((member['quota'], member['revision']), (0, 0))
                app.overview(account)  # an empty account still renders its home page
            self.assertEqual(self.counts(app)['entitlement_packages'], 0)
            card = app.ledger.issue('admin', 'Test', 1, 30, 1, 30)[0]['code']
            app.ledger.redeem(account['id'], card)
            with app.ledger.connect() as db:
                member = db.execute('SELECT * FROM members WHERE id=?', (account['id'],)).fetchone()
            self.assertGreater(member['quota'], 0)
            self.assertGreater(member['revision'], 0)

    def test_taken_name_and_bad_card_still_rejected(self):
        app = self.make()
        app.register_with_card('alice', 'Secret-password-123', None)
        with self.assertRaises(DomainError):
            app.register_with_card('alice', 'Secret-password-123', None)
        with self.assertRaises(DomainError):
            app.register_with_card('bob', 'Secret-password-123', 'not-a-card')
        with self.assertRaises(DomainError):
            app.register_with_card('bob', 'Secret-password-123', 'x' * 101)
        self.assertEqual(self.counts(app)['accounts'], 1)

    def test_email_verification_still_required_without_card(self):
        app = self.make(mail={'api_key': 'test-secret', 'from': 'test@example.com'})
        app.email_auth.send = Mock()
        with self.assertRaises(DomainError):
            app.register_with_card('person@example.com', 'Good-password-123', None, email_code='000000')
        app.email_auth.request('person@example.com', 'register', 'ip', None)
        otp = app.email_auth.send.call_args.args[2]
        token = app.register_with_card('person@example.com', 'Good-password-123', '', email_code=otp)
        account = app.session(token)
        self.assertTrue(app.features.sessions(account, token)['email_verified'])
        with self.assertRaises(DomainError):  # the code is single use
            app.register_with_card('other@example.com', 'Good-password-123', '', email_code=otp)
        # A card that is supplied is still checked before any mail goes out.
        with self.assertRaises(DomainError):
            app.email_auth.request('third@example.com', 'register', 'ip2', 'bad-card')


class HiddenNodeTests(unittest.TestCase):
    def monitor(self, nodes):
        from content import NodeMonitor

        class Panel:
            fail = False

            def request(self, path):
                if self.fail:
                    raise TimeoutError()
                if path == 'nodes/list':
                    return nodes
                return [{'id': n['id'], 'nodeId': n['id'], 'enable': True, 'protocol': 'hysteria'}
                        for n in nodes] + [{'id': 9, 'enable': True, 'protocol': 'hysteria'}]

        m = NodeMonitor(Panel(), names={1: 'A', 2: 'B', 3: 'C', 9: 'Master'})
        m.endpoints = {1: ('8.8.8.1', 443), 2: ('8.8.8.2', 443), 3: ('8.8.8.3', 443),
                       9: ('8.8.8.9', 443)}
        return m

    def test_offline_and_silent_hosts_hidden_but_panel_failure_hides_nothing(self):
        now = int(time.time())
        m = self.monitor([
            {'id': 1, 'enable': True, 'status': 'online', 'lastHeartbeat': now},
            {'id': 2, 'enable': True, 'status': 'offline', 'lastHeartbeat': now - 600},
            {'id': 3, 'enable': True, 'status': 'online', 'lastHeartbeat': now - 600},
        ])
        m.refresh()
        self.assertEqual([n['name'] for n in m.public_snapshot()['nodes']], ['A', 'Master'])
        self.assertNotIn('reachable', m.public_snapshot()['nodes'][0])
        self.assertEqual(m.hidden_endpoints(), [('8.8.8.2', 443), ('8.8.8.3', 443)])
        self.assertEqual(len(m.snapshot()['nodes']), 4)  # history/admin still see all
        m.panel.fail = True
        m.refresh()
        self.assertEqual(m.hidden_endpoints(), [])
        self.assertEqual(len(m.public_snapshot()['nodes']), 4)


if __name__ == '__main__':
    unittest.main()
