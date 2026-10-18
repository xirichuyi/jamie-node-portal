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

    def test_shared_layout_supports_dark_mode_preview_and_outlook_button(self):
        from email_templates import service_email

        for template in (verification_email('register', '012345'),
                         service_email('到账', '第一段\n\n第二段', 'https://sub.chuyi.uk', details=[('流量', '1 GiB')])):
            html = template['html']
            self.assertIn('prefers-color-scheme:dark', html)
            self.assertIn('mso-hide:all', html)  # Inbox preview text.
            self.assertIn('max-width:480px', html)  # Phone adjustments.
            self.assertNotIn('<script', html)
        service = service_email('到账', '第一段\n\n第二段', 'https://sub.chuyi.uk')['html']
        self.assertIn('bgcolor="#405e50"', service)
        preview = verification_email('reset', '987654')['html'].split('mso-hide:all;">')[1][:80]
        self.assertNotIn('987654', preview)  # The code never shows in the inbox list.

    def test_invalid_input_is_rejected(self):
        for purpose, code in [('other', '012345'), ('register', '<b>bad</b>'), ('reset', '12345')]:
            with self.assertRaises(ValueError):
                verification_email(purpose, code)
