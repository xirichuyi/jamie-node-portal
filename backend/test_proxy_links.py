import base64
import unittest

from probe import outbound, outbound_endpoint
from proxy_links import decode_links, parse_link


VLESS = ('vless://11111111-2222-4333-8444-555555555555@8.8.4.4:21227'
         '?type=tcp&security=reality&pbk=' + 'a' * 43
         + '&sid=0123456789abcdef&sni=www.example.com&fp=chrome&encryption=none')
WSS_HOST = '8080-agqvokiqj7tgcg6m56ddlqduxm.instabox.tech'
WSS = ('vless://11111111-2222-4333-8444-555555555555@' + WSS_HOST
       + ':443?security=tls&type=ws&path=%2Fnode&host=' + WSS_HOST + '&sni=' + WSS_HOST)


class ProxyLinkTests(unittest.TestCase):
    def test_websocket_tls_outbound_and_downgrade_rejection(self):
        config = outbound(WSS, {(WSS_HOST, 443): 'Instabox'})
        stream = config['streamSettings']
        self.assertEqual(stream['network'], 'ws')
        self.assertEqual(stream['wsSettings'], {'path': '/node', 'headers': {'Host': WSS_HOST}})
        self.assertFalse(stream['tlsSettings']['allowInsecure'])
        self.assertEqual(stream['tlsSettings']['alpn'], ['http/1.1'])
        for bad in (WSS.replace('security=tls', 'security=none'), WSS + '&allowInsecure=1',
                    WSS + '&flow=xtls-rprx-vision', WSS.replace('%2Fnode', '%2Fnode%0D%0A')):
            with self.subTest(link=bad), self.assertRaises(ValueError):
                parse_link(bad)

    def test_reality_is_converted_without_disabling_verification(self):
        config = outbound(VLESS, {('8.8.4.4', 21227): 'test'})
        self.assertEqual(outbound_endpoint(config), ('8.8.4.4', 21227))
        self.assertEqual(config['streamSettings']['security'], 'reality')
        self.assertNotIn('allowInsecure', config['streamSettings']['realitySettings'])
        self.assertEqual(config['settings']['vnext'][0]['users'][0]['encryption'], 'none')
        self.assertEqual(decode_links(base64.b64encode(VLESS.encode())), [VLESS])

    def test_reality_downgrades_missing_keys_and_bad_ids_are_rejected(self):
        for link in (VLESS.replace('security=reality', 'security=none'),
                     VLESS.replace('type=tcp', 'type=ws'),
                     VLESS.replace('a' * 43, 'short'), VLESS.replace('sid=0123456789abcdef', 'sid=xyz'),
                     VLESS.replace('11111111-2222-4333-8444-555555555555', 'password'),
                     VLESS + '&security=none', VLESS + '&flow=unknown'):
            with self.subTest(link=link), self.assertRaises(ValueError):
                parse_link(link)

    def test_hy2_still_requires_a_certificate_pin(self):
        with self.assertRaises(ValueError):
            parse_link('hy2://password@8.8.4.4:443?insecure=1')


if __name__ == '__main__':
    unittest.main()
