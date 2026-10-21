import json
import tempfile
import time
import unittest
from pathlib import Path
from content import Content, NodeMonitor
from entitlements import Ledger, DomainError


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(str(Path(self.temp.name) / 'db.sqlite'))
        self.content = Content(self.ledger)

    def tearDown(self):
        self.temp.cleanup()

    def test_seed_and_restart_preserve_user_edits(self):
        self.assertEqual(len(self.content.read()['plans']), 1)
        self.assertEqual(len(self.content.read(True)['plans']), 3)
        p = self.content.read()['plans'][0]
        p.update(name='My edited plan', published=True)
        self.content.save('admin', 'plan', p)
        Content(self.ledger)
        self.assertEqual(self.content.read()['plans'][0]['name'], 'My edited plan')
        with self.assertRaises(DomainError):
            self.content.save('admin', 'plan', p)

    def test_zero_day_plan_is_an_unlimited_traffic_pack(self):
        self.ledger.package_billing = True
        plan = self.content.read(True)['plans'][0]
        plan.update(name='不限时流量包', days=0, quota_gib=0.5, permanent=False, published=True)
        self.content.save('admin', 'plan', plan)
        saved = self.content.plan_for_card(plan['id'])
        self.assertEqual((saved['permanent'], saved['quota_gib']), (1, 0.5))

    def test_publish_hide_and_card_entitlement_snapshot(self):
        plan = self.content.read(True)['plans'][0]
        with self.assertRaises(DomainError):
            self.content.plan_for_card(plan['id'])
        plan['published'] = True
        self.content.save('admin', 'plan', plan)
        before = self.content.plan_for_card(plan['id'])
        code = self.ledger.issue(
            'admin', before['name'], before['quota_gib'], before['days'], 1, 90
        )[0]
        before.update(quota_gib=999, published=False)
        self.content.save('admin', 'plan', before)
        with self.ledger.connect() as db:
            row = db.execute('SELECT quota FROM cards WHERE id=?', (code['id'],)).fetchone()
            self.assertEqual(row['quota'], plan['quota_gib'] * 1024**3)
        with self.assertRaises(DomainError):
            self.content.plan_for_card(plan['id'])

    def test_notice_draft_not_public_and_plaintext_body(self):
        item = {
            'title': 'Draft',
            'body': '<script>alert(1)</script>',
            'category': 'maintenance',
            'published': False,
            'pinned': False,
        }
        item_id = self.content.save('admin', 'notice', item)
        self.assertNotIn(item_id, [n['id'] for n in self.content.read()['notices']])
        saved = next(n for n in self.content.read(True)['notices'] if n['id'] == item_id)
        saved.update(published=True, pinned=True)
        self.content.save('admin', 'notice', saved)
        self.assertEqual(
            next(n for n in self.content.read()['notices'] if n['id'] == item_id)['body'],
            item['body'],
        )
        published = next(n for n in self.content.read(True)['notices'] if n['id'] == item_id)
        self.assertGreater(published['revision'], saved['revision'])
        published['published'] = False
        published['pinned'] = bool(published['pinned'])
        self.content.save('admin', 'notice', published)
        self.assertNotIn(item_id, [n['id'] for n in self.content.read()['notices']])

    def test_support_rejects_unsafe_links(self):
        data = self.content.read()['support']
        for url in [
            'javascript:alert(1)',
            'http://example.com',
            'https://user:pass@example.com',
            'mailto:a@b.com?body=bad',
        ]:
            with self.assertRaises(DomainError):
                self.content.save('admin', 'support', {**data, 'contact_url': url})
        self.content.save('admin', 'support', {**data, 'contact_url': 'https://t.me/example'})
        self.assertEqual(self.content.read()['support']['contact_url'], 'https://t.me/example')

    def test_invalid_numeric_values(self):
        data = self.content.read(True)['plans'][0]
        for value in [0, -1, 8388608, True, '100']:
            with self.assertRaises(DomainError):
                self.content.save('admin', 'plan', {**data, 'quota_gib': value, 'published': False})
        with self.assertRaises(DomainError):
            self.content.save('admin', 'plan', {**data, 'price_label': '30', 'published': False})


class MonitoringTests(unittest.TestCase):
    def test_expansion_maps_inbound_to_remote_node(self):
        class Panel:
            def request(self, path):
                if path == 'nodes/list':
                    return [{'id': 40, 'enable': True, 'status': 'online',
                             'lastHeartbeat': int(time.time()), 'latencyMs': 10}]
                return [{'id': 4, 'nodeId': 40, 'enable': True, 'protocol': 'hysteria'}]

        monitor = NodeMonitor(Panel(), names={4: '🇺🇸 美国 · 圣何塞'})
        monitor.refresh()
        rows = monitor.snapshot()['nodes']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'online')
        self.assertEqual(rows[0]['name'], '🇺🇸 美国 · 圣何塞')
        self.assertEqual(rows[0]['id'], 4)

    def test_sanitizes_stale_and_failure(self):
        class Panel:
            fail = False

            def request(self, path):
                if self.fail:
                    raise TimeoutError()
                if path == 'nodes/list':
                    return [
                        {
                            'id': i,
                            'name': 'private-host',
                            'address': 'secret-address',
                            'apiToken': 'TOPSECRET',
                            'status': 'online',
                            'enable': True,
                            'lastHeartbeat': int(time.time()) - (1000 if i == 2 else 0),
                            'latencyMs': 25,
                            'configDirty': i == 3,
                        }
                        for i in (1, 2, 3)
                    ]
                return [{'id': i, 'enable': True, 'protocol': 'hysteria'} for i in (1, 2, 3)]

        panel = Panel()
        monitor = NodeMonitor(panel, names={1: '日本', 2: '新加坡', 3: '马来西亚'})
        monitor.refresh()
        data = monitor.snapshot()
        self.assertEqual([n['status'] for n in data['nodes']], ['online', 'unknown', 'pending'])
        self.assertNotIn('TOPSECRET', json.dumps(data))
        self.assertNotIn('secret-address', json.dumps(data))
        self.assertNotIn('private-host', json.dumps(data))
        panel.fail = True
        monitor.refresh()
        self.assertTrue(all(n['status'] == 'unknown' for n in monitor.snapshot()['nodes']))
        self.assertTrue(all(n['latency_ms'] is None for n in monitor.snapshot()['nodes']))


if __name__ == '__main__':
    unittest.main()
