"""Self-contained transactional email: inline styles, no remote assets or tracking."""

from html import escape
import re


FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Arial,sans-serif"
SUPPORT = 'xrcy123@gmail.com'
SITE = 'https://sub.chuyi.uk'

# Light design with an opt-in dark palette for clients that honour it (Apple Mail,
# iOS, Outlook.com via data-ogsc). Clients that strip <style> keep the inline light look.
DARK_CSS = """
:root{color-scheme:light dark;supported-color-schemes:light dark}
@media (prefers-color-scheme:dark){
.jn-bg{background-color:#141816!important}
.jn-card{background-color:#1d2320!important;border-color:#2e3833!important}
.jn-text,.jn-title{color:#e7ece8!important}
.jn-muted{color:#a3b0a8!important}
.jn-word span{color:#9fb5a8!important}
.jn-panel{background-color:#24302a!important;border-color:#33433a!important}
.jn-accent{color:#b5d3c2!important}
.jn-rule{border-color:#2e3833!important}
.jn-link{color:#a9c7b6!important}
}
[data-ogsc] .jn-bg{background-color:#141816!important}
[data-ogsc] .jn-card{background-color:#1d2320!important;border-color:#2e3833!important}
[data-ogsc] .jn-text,[data-ogsc] .jn-title{color:#e7ece8!important}
[data-ogsc] .jn-muted{color:#a3b0a8!important}
[data-ogsc] .jn-panel{background-color:#24302a!important}
[data-ogsc] .jn-accent{color:#b5d3c2!important}
@media only screen and (max-width:480px){
.jn-outer{padding:20px 10px!important}
.jn-card{padding:24px 18px!important;border-radius:16px!important}
.jn-title{font-size:22px!important;line-height:30px!important}
}
"""


def layout(*, title, eyebrow, inner, preheader, footer, site=SITE):
    """Shared shell for every Jamie-Node email: table layout, inline styles, one logo image."""
    site = site.rstrip('/')
    t = escape(title)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<meta name="x-apple-disable-message-reformatting"><title>Jamie-Node · {t}</title>
<style>{DARK_CSS}</style></head>
<body class="jn-bg" style="margin:0;padding:0;background-color:#f8f7f4;color:#29332e;font-family:{FONT};-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">{escape(preheader)}&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;</div>
<table role="presentation" class="jn-bg" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f8f7f4;">
<tr><td align="center" class="jn-outer" style="padding:40px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;">
<tr><td style="padding:0 8px 24px;"><table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="padding-right:10px;"><img src="{escape(site, quote=True)}/jamie-node-email-v3.png" width="36" height="36" alt="Jamie-Node" style="display:block;border:0;border-radius:8px;background-color:#ffffff;"></td>
<td class="jn-word jn-text" style="font-size:20px;line-height:28px;font-weight:600;letter-spacing:-0.6px;color:#29332e;">Jamie<span style="color:#64786d;">-Node</span></td>
</tr></table></td></tr>
<tr><td class="jn-card" style="padding:32px 24px;background-color:#ffffff;border:1px solid #dce3de;border-radius:20px;">
<p class="jn-muted" style="margin:0 0 12px;font-size:12px;line-height:18px;letter-spacing:1.5px;color:#6f8177;">{escape(eyebrow)}</p>
<h1 class="jn-title" style="margin:0 0 14px;font-size:26px;line-height:36px;letter-spacing:-0.5px;font-weight:600;color:#29332e;">{t}</h1>
{inner}
</td></tr>
<tr><td class="jn-muted" style="padding:22px 8px 0;font-size:12px;line-height:22px;color:#87918a;">
<a class="jn-link" href="{escape(site, quote=True)}/" style="color:#61786a;text-decoration:none;">Jamie-Node</a><span style="padding:0 10px;color:#bec7c0;">·</span><a class="jn-link" href="mailto:{SUPPORT}" style="color:#61786a;text-decoration:none;">联系支持</a>
<p style="margin:6px 0 0;">{footer}</p>
</td></tr></table></td></tr></table></body></html>"""


def button(label, href):
    """Bulletproof button: padding lives on the cell so Outlook keeps the shape."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:8px;"><tr>'
        '<td bgcolor="#405e50" style="border-radius:10px;background-color:#405e50;padding:12px 22px;">'
        f'<a href="{escape(href, quote=True)}" style="display:inline-block;font-size:15px;line-height:20px;'
        f'font-weight:600;color:#ffffff;text-decoration:none;">{escape(label)} →</a></td></tr></table>'
    )


def service_email(title, message, origin, *, action=None, details=(), footer=None, eyebrow='服务通知',
                  manage=('管理邮件提醒', '/#/sessions')):
    """Branded notification; message paragraphs are separated by blank lines, details are (label, value)."""
    origin = origin.rstrip('/')
    manage_label, manage = manage[0], origin + manage[1]
    label, path = action or ('打开 Jamie-Node', '/')
    link = origin + path
    footer = footer or '可在「邮箱与账号安全」关闭这类邮件提醒。'
    paragraphs = [p.strip() for p in str(message).split('\n\n') if p.strip()]
    rows = [(str(k), str(v)) for k, v in details]
    text = '\n\n'.join(
        [f'Jamie-Node · {title}', *paragraphs]
        + (['\n'.join(f'{k}：{v}' for k, v in rows)] if rows else [])
        + [f'{label}：{link}', f'{footer}\n{manage_label}：{manage}\n需要帮助：{SUPPORT}']
    )
    body = ''.join(
        '<p class="jn-text" style="margin:0 0 14px;font-size:15px;line-height:25px;color:#4f5b55;">'
        f'{escape(p).replace(chr(10), "<br>")}</p>'
        for p in paragraphs
    )
    table = ''
    if rows:
        cells = ''.join(
            f'<tr><td class="jn-muted jn-rule" style="padding:10px 0;font-size:13px;line-height:20px;color:#7b847f;'
            f'white-space:nowrap;vertical-align:top;border-top:1px solid #e3e8e4;">{escape(k)}</td>'
            f'<td class="jn-text jn-rule" style="padding:10px 0 10px 16px;font-size:14px;line-height:20px;color:#29332e;'
            f'font-weight:600;text-align:right;border-top:1px solid #e3e8e4;">{escape(v)}</td></tr>'
            for k, v in rows
        )
        table = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="margin:4px 0 20px;border-bottom:1px solid #e3e8e4;" class="jn-rule">{cells}</table>'
        )
    preheader = paragraphs[0] if paragraphs else title
    html = layout(
        title=title,
        eyebrow=eyebrow,
        inner=body + table + button(label, link),
        preheader=preheader[:90],
        footer=(
            f'{escape(footer)}<br><a class="jn-link" href="{escape(manage, quote=True)}" '
            f'style="color:#61786a;">{escape(manage_label)}</a>'
        ),
        site=origin,
    )
    return {'subject': 'Jamie-Node · ' + title, 'text': text, 'html': html}


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
    text = f'Jamie-Node · {title}\n\n{instruction}\n\n{code}\n\n验证码 10 分钟内有效，仅可使用一次。\n请勿向任何人透露验证码。如果不是你本人操作，请忽略这封邮件。\n\n需要帮助：xrcy123@gmail.com\nhttps://sub.chuyi.uk/'
    safe_code = escape(code)
    inner = f"""<p class="jn-muted" style="margin:0 0 26px;font-size:15px;line-height:25px;color:#738078;">{escape(intro)}<br>{escape(instruction)}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" class="jn-panel" style="padding:22px 12px;background-color:#edf2ee;border:1px solid #dce5de;border-radius:12px;">
<div class="jn-accent" style="font-family:ui-monospace,SFMono-Regular,Consolas,'Courier New',monospace;font-size:34px;line-height:44px;font-weight:600;letter-spacing:6px;color:#405e50;white-space:nowrap;">{safe_code}</div>
<p class="jn-muted" style="margin:8px 0 0;font-size:12px;line-height:20px;color:#687c70;">10 分钟内有效 · 仅可使用一次</p>
</td></tr></table>
<p class="jn-muted" style="margin:26px 0 0;font-size:13px;line-height:23px;color:#7b847f;">请勿向任何人透露验证码。<br>如果不是你本人操作，忽略这封邮件即可。</p>"""
    html = layout(
        title=title,
        eyebrow='账号安全 · ' + ('邮箱换绑' if purpose == 'change' else '邮箱验证' if signup else '密码找回'),
        inner=inner,
        # The code itself is never placed in the inbox preview.
        preheader=f'{title}，验证码 10 分钟内有效。请勿向他人透露。',
        footer='这是一封账号安全邮件，无需回复验证码。',
    )
    return {'subject': 'Jamie-Node · ' + title, 'text': text, 'html': html}
