"""Self-contained transactional email: inline styles, no remote assets or tracking."""

from html import escape
import re


def verification_email(purpose, code):
    if purpose not in ('register', 'reset', 'change') or not re.fullmatch(r'[0-9]{6}', code):
        raise ValueError('Invalid verification email')
    signup = purpose == 'register'
    title = '验证你的邮箱' if signup else '重设你的密码'
    intro = '只差一步，即可开启你的连接。' if signup else '验证身份后，为账号设置一个新密码。'
    instruction = '请在注册页面输入以下验证码。' if signup else '请在找回密码页面输入以下验证码。'
    if purpose == 'change':
        title, intro, instruction = (
            '更换登录邮箱',
            '你正在更换 Jamie-Node 的登录邮箱。',
            '请在账号安全页面输入以下验证码。非本人操作请立即修改密码并联系支持。',
        )
    safe_code = escape(code)
    text = f'Jamie-Node · {title}\n\n{instruction}\n\n{code}\n\n验证码 10 分钟内有效，仅可使用一次。\n请勿向任何人透露验证码。如果不是你本人操作，请忽略这封邮件。\n\n需要帮助：xrcy123@gmail.com\nhttps://sub.chuyi.uk/'
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><title>Jamie-Node · {title}</title></head>
<body style="margin:0;padding:0;background-color:#f8f7f4;color:#29332e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Arial,sans-serif;-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">{title}，验证码 10 分钟内有效。请勿向他人透露。</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f8f7f4;">
<tr><td align="center" style="padding:40px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;">
<tr><td style="padding:0 8px 24px;"><table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="padding-right:10px;"><img src="https://sub.chuyi.uk/jamie-node-email-v3.png" width="36" height="36" alt="" style="display:block;border:0;border-radius:8px;"></td><td style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;font-size:20px;line-height:28px;font-weight:600;letter-spacing:-0.6px;color:#29332e;">Jamie<span style="color:#64786d;">-Node</span></td></tr></table></td></tr>
<tr><td style="padding:32px 24px;background-color:#ffffff;border:1px solid #dce3de;border-radius:20px;">
<p style="margin:0 0 12px;font-size:12px;line-height:18px;letter-spacing:1.5px;color:#6f8177;">账号安全 · {'邮箱换绑' if purpose == 'change' else '邮箱验证' if signup else '密码找回'}</p>
<h1 style="margin:0 0 12px;font-size:26px;line-height:36px;letter-spacing:-0.5px;font-weight:600;color:#29332e;">{title}</h1>
<p style="margin:0 0 26px;font-size:15px;line-height:25px;color:#738078;">{intro}<br>{instruction}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:22px 12px;background-color:#edf2ee;border:1px solid #dce5de;border-radius:12px;">
<div style="font-family:ui-monospace,SFMono-Regular,Consolas,'Courier New',monospace;font-size:34px;line-height:44px;font-weight:600;letter-spacing:6px;color:#405e50;white-space:nowrap;">{safe_code}</div>
<p style="margin:8px 0 0;font-size:12px;line-height:20px;color:#687c70;">10 分钟内有效 · 仅可使用一次</p>
</td></tr></table>
<p style="margin:26px 0 0;font-size:13px;line-height:23px;color:#7b847f;">请勿向任何人透露验证码。<br>如果不是你本人操作，忽略这封邮件即可。</p>
</td></tr>
<tr><td style="padding:22px 8px 0;font-size:12px;line-height:22px;color:#87918a;">
<a href="https://sub.chuyi.uk/" style="color:#61786a;text-decoration:none;">Jamie-Node</a><span style="padding:0 10px;color:#bec7c0;">·</span><a href="mailto:xrcy123@gmail.com" style="color:#61786a;text-decoration:none;">联系支持</a>
<p style="margin:6px 0 0;">这是一封账号安全邮件，无需回复验证码。</p>
</td></tr></table></td></tr></table></body></html>"""
    return {'subject': 'Jamie-Node · ' + title, 'text': text, 'html': html}
