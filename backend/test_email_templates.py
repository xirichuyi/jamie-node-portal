import unittest
from email_templates import verification_email


class TemplateTests(unittest.TestCase):
    def test_both_purposes_have_html_and_text(self):
        for purpose in ('register', 'reset', 'change'):
            template = verification_email(purpose, '012345')
            for kind in ('html', 'text'):
                self.assertIn('012345', template[kind])
                self.assertIn('10 分钟', template[kind])
            self.assertIn('max-width:520px', template['html'])
            self.assertNotIn('<script', template['html'])
            self.assertEqual(template['html'].count('<img'), 1)
            self.assertIn('https://sub.chuyi.uk/jamie-node-email-v3.png', template['html'])
        self.assertIn('验证你的邮箱', verification_email('register', '012345')['subject'])
        self.assertIn('重设你的密码', verification_email('reset', '012345')['subject'])

    def test_invalid_input_is_rejected(self):
        for purpose, code in [('other', '012345'), ('register', '<b>bad</b>'), ('reset', '12345')]:
            with self.assertRaises(ValueError):
                verification_email(purpose, code)
