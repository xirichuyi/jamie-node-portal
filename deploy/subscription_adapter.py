#!/usr/bin/env python3
"""Private, fixed-upstream HY2 -> Mihomo subscription adapter. No admin token."""
import base64
import http.server
import html
import json
import re
import math
import time
from datetime import datetime, timezone, timedelta
import urllib.error
import urllib.parse
import urllib.request
import yaml
import sys
sys.path.insert(0, '/opt/jamie-portal/current/backend')
from node_catalog import active_nodes, service_settings
from proxy_links import decode_links, parse_link

def node_names():
    return {(row['server'], row['port']): row['name'] for row in active_nodes()}

def account_groups(usage):
    fields = {}
    for part in (usage or '').split(';'):
        key, sep, value = part.strip().partition('=')
        if sep and value.strip().isdigit():
            fields[key] = int(value.strip())
    if all(k in fields for k in ('total', 'upload', 'download')):
        total = fields['total']
        left = max(0, total - fields['upload'] - fields['download'])
        quota = ('剩余流量：不限量' if total == 0 else
                 f'剩余流量：{left / 1024**3:.2f} GiB / {total / 1024**3:.2f} GiB')
    else:
        quota = '剩余流量：暂无数据'
    expiry = fields.get('expire')
    if expiry is None or expiry == 0:
        deadline = '有效期：未提供到期时间' if expiry is None else '有效期：长期有效'
    else:
        date = datetime.fromtimestamp(expiry, timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
        days = max(0, math.ceil((expiry - time.time()) / 86400))
        deadline = f'到期：{date}（剩余 {days} 天）' if expiry > time.time() else f'已到期：{date}'
    # Display-only groups, never referenced by routing rules or node selection.
    return [{'name': label, 'type': 'select', 'proxies': ['Jamie-Node']}
            for label in (quota, deadline)]

def rule_providers():
    sources = {'private_domain': ('domain', 'geosite/private'),
               'cn_domain': ('domain', 'geosite/cn'),
               'proxy_domain': ('domain', 'geosite/geolocation-!cn'),
               'cn_ip': ('ipcidr', 'geoip/cn')}
    return {name: {'type': 'http', 'behavior': behavior, 'format': 'mrs',
            'path': './rules/Jamie-Node-' + name + '.mrs', 'interval': 86400,
            'proxy': 'Jamie-Node',
            'url': 'https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/' + source + '.mrs'}
            for name, (behavior, source) in sources.items()}

def convert(body, usage=None):
    regions = node_names()
    service = service_settings()
    direct_rules = [f"DOMAIN,{host},DIRECT" for host in (urllib.parse.urlsplit(service['origin']).hostname, service['panel_host'], service['master_ip'])]
    direct_rules.append(f"IP-CIDR,{service['master_ip']}/32,DIRECT,no-resolve")
    proxies = []
    for index, line in enumerate(decode_links(body), 1):
        u = urllib.parse.urlsplit(line.strip())
        name = regions.get((u.hostname, u.port or 443))
        if name is None:
            continue  # Unpublished and retired nodes never leak into subscriptions.
        parsed = parse_link(line)
        q = parsed['query']
        if any(p['name'] == name for p in proxies):
            name += ' ' + str(index)
        p = {'name': name, 'type': parsed['type'], 'server': parsed['server'],
             'port': parsed['port'], 'udp': True, 'skip-cert-verify': False}
        if parsed['type'] == 'vless':
            p.update(uuid=parsed['uuid'], tls=True, network='tcp', servername=parsed['sni'],
                     **{'client-fingerprint': parsed['fingerprint'],
                        'reality-opts': {'public-key': parsed['public_key'], 'short-id': parsed['short_id']}})
            if parsed['flow']:
                p['flow'] = parsed['flow']
        else:
            p.update(password=parsed['password'], sni=parsed['sni'], fingerprint=parsed['pin'])
        if 'alpn' in q:
            p['alpn'] = q['alpn'][0].split(',')
        if 'obfs' in q:
            p['obfs'] = q['obfs'][0]
            p['obfs-password'] = q.get('obfs-password', [''])[0]
        if 'mport' in q:
            p['ports'] = q['mport'][0]
        proxies.append(p)
    if not proxies:
        raise ValueError('No enabled proxies')
    names = [p['name'] for p in proxies]
    return yaml.safe_dump({'mixed-port': 7890, 'allow-lan': False,
        'mode': 'rule', 'log-level': 'info', 'ipv6': False,
        'profile': {'store-selected': True},
        'dns': {'enable': True, 'ipv6': False, 'enhanced-mode': 'fake-ip',
                'fake-ip-range': '198.18.0.1/16',
                'fake-ip-filter': ['*.lan', '*.local', 'localhost', '*.msftconnecttest.com', '*.msftncsi.com'],
                'respect-rules': True,
                'default-nameserver': ['223.5.5.5', '119.29.29.29'],
                'proxy-server-nameserver': ['223.5.5.5', '119.29.29.29'],
                'nameserver': ['https://1.1.1.1/dns-query', 'https://8.8.8.8/dns-query'],
                'nameserver-policy': {'rule-set:cn_domain': ['https://dns.alidns.com/dns-query', 'https://doh.pub/dns-query'],
                                      'rule-set:private_domain': ['system']}},
        'proxies': proxies,
        'proxy-groups': [{'name': 'Jamie-Node', 'type': 'select', 'proxies': ['自动选择'] + names},
            {'name': '自动选择', 'type': 'url-test', 'proxies': names,
             'url': service['probe_url'], 'interval': 300, 'tolerance': 50}] + account_groups(usage),
        'rule-providers': rule_providers(),
        'rules': direct_rules + ['IP-CIDR,223.5.5.5/32,DIRECT,no-resolve',
                  'IP-CIDR,119.29.29.29/32,DIRECT,no-resolve',
                  'DOMAIN,dns.alidns.com,DIRECT', 'DOMAIN,doh.pub,DIRECT',
                  'IP-CIDR,1.1.1.1/32,Jamie-Node,no-resolve',
                  'IP-CIDR,8.8.8.8/32,Jamie-Node,no-resolve',
                  'DOMAIN-SUFFIX,lan,DIRECT', 'DOMAIN-SUFFIX,local,DIRECT',
                  'DOMAIN,localhost,DIRECT',
                  'IP-CIDR,127.0.0.0/8,DIRECT,no-resolve',
                  'IP-CIDR,10.0.0.0/8,DIRECT,no-resolve',
                  'IP-CIDR,172.16.0.0/12,DIRECT,no-resolve',
                  'IP-CIDR,192.168.0.0/16,DIRECT,no-resolve',
                  'IP-CIDR,169.254.0.0/16,DIRECT,no-resolve',
                  'RULE-SET,private_domain,DIRECT',
                  'RULE-SET,proxy_domain,Jamie-Node',
                  'RULE-SET,cn_domain,DIRECT',
                  'RULE-SET,cn_ip,DIRECT,no-resolve', 'MATCH,Jamie-Node']},
        allow_unicode=True, sort_keys=False).encode()

def choose_format(path, query, agent, accept):
    requested = query.get('format', ['auto'])
    if len(requested) != 1 or requested[0] not in ('auto', 'clash', 'shadowrocket', 'base64', 'html'):
        raise ValueError('Unsupported format')
    if requested[0] != 'auto':
        return 'base64' if requested[0] == 'shadowrocket' else requested[0]
    if path.startswith('/clash/'):
        return 'clash'  # Existing subscriptions retain their old behavior.
    ua = agent.lower()
    if 'shadowrocket' in ua:
        return 'base64'
    if any(name in ua for name in ('clash', 'mihomo', 'verge')):
        return 'clash'
    if any(name in ua for name in ('v2rayn', 'v2rayng', 'nekobox', 'hiddify')):
        return 'base64'
    if 'sing-box' in ua or 'surge' in ua:
        raise ValueError('This client requires a separate configuration adapter')
    if 'text/html' in accept.lower() or 'mozilla/' in ua:
        return 'html'
    return 'base64'

def native_subscription(raw):
    regions = node_names()
    links = []
    names = set()
    for index, line in enumerate(decode_links(raw), 1):
        u = urllib.parse.urlsplit(line.strip())
        name = regions.get((u.hostname, u.port or 443))
        if name is None:
            continue
        parse_link(line)
        if name in names:
            name += ' ' + str(index)
        names.add(name)
        links.append(urllib.parse.urlunsplit(u._replace(fragment=urllib.parse.quote(name, safe=''))))
    if not links:
        raise ValueError('Empty subscription')
    return base64.b64encode(('\n'.join(links) + '\n').encode())

def landing_page(sid, usage):
    service = service_settings()
    url = service['origin'].rstrip('/') + '/sub/' + sid
    safe = html.escape(url, quote=True)
    status = ''.join('<p>' + html.escape(g['name']) + '</p>' for g in account_groups(usage))
    return (f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(service['title'])}</title>
<body style="max-width:640px;margin:48px auto;padding:20px;font-family:system-ui;line-height:1.8">
<h1>{html.escape(service['title'])}</h1><p>将下面同一个链接粘贴到客户端的“添加订阅”。请勿公开分享。</p>'''
        + '<input readonly style="width:100%;padding:10px;box-sizing:border-box" value="' + safe + '">'
        + status + '<h2>手动选择格式</h2><ul><li><a href="' + safe + '?format=clash">Clash Verge / Mihomo YAML</a></li>'
        + '<li><a href="' + safe + '?format=shadowrocket">小火箭 / 通用节点订阅</a></li></ul>'
        + '<p>Clash 格式包含分流规则。小火箭通用订阅只更新节点，分流规则使用小火箭当前配置，不会自动覆盖。</p>'
        + '<p>需要支持 HY2 和 VLESS REALITY 的客户端。HY2 节点使用自签证书，客户端必须识别并校验证书指纹 pinSHA256；'
          '不能删除指纹后只开启跳过验证。小火箭手机端证书校验尚待实测。原生 sing-box / Surge 暂未适配。</p>'
        + '<p>数据随订阅更新刷新，不是实时计量。</p></body></html>').encode()

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Subscription tokens must never enter access logs.

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        match = re.fullmatch(r'/(?:clash|sub)/([A-Za-z0-9_-]{16,128})', parsed.path)
        if not match:
            self.send_error(404)
            return
        try:
            fmt = choose_format(parsed.path, urllib.parse.parse_qs(parsed.query),
                                self.headers.get('User-Agent', ''), self.headers.get('Accept', ''))
        except ValueError:
            self.send_error(400, 'Unsupported client or format; use a HY2-capable client or select format manually')
            return
        try:
            service = service_settings()
            req = urllib.request.Request(UPSTREAM + match[1], headers={'User-Agent': 'Private-HY2-Adapter/1'})
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError('Oversized upstream')
                usage = response.headers.get('subscription-userinfo')
                # Portal ledger owns package/cycle metadata; the panel enforces access.
                with urllib.request.urlopen('http://127.0.0.1:18766/internal/subscription-info/' + match[1], timeout=3) as info:
                    portal_usage = json.loads(info.read(4096)).get('usage')
                if portal_usage is not None:
                    usage = portal_usage
                if fmt == 'clash':
                    result = convert(raw, usage)
                elif fmt == 'base64':
                    result = native_subscription(raw)
                else:
                    native_subscription(raw)  # Validate before showing a usable subscription page.
                    result = landing_page(match[1], usage)
            self.send_response(200)
            self.send_header('Content-Type', {'clash': 'application/yaml; charset=utf-8',
                'base64': 'text/plain; charset=utf-8', 'html': 'text/html; charset=utf-8'}[fmt])
            if fmt != 'html':
                self.send_header('Content-Disposition', 'attachment; filename=' + service['title'])
            self.send_header('Vary', 'User-Agent, Accept')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('profile-title', service['title'])
            self.send_header('Cache-Control', 'no-store')
            self.send_header('profile-update-interval', '6')
            self.send_header('profile-web-page-url', service['origin'].rstrip('/') + '/')
            self.send_header('support-url', service['origin'].rstrip('/') + '/#/help')
            if usage:
                self.send_header('subscription-userinfo', usage)
            self.send_header('Content-Length', str(len(result)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(result)
        except urllib.error.HTTPError as e:
            self.send_error(404 if e.code in (400, 401, 403, 404) else 502)
        except (ValueError, UnicodeError):
            self.send_error(422, 'No valid pinned HY2 subscription available')
        except Exception:
            self.send_error(502, 'Subscription temporarily unavailable')

if __name__ == '__main__':
    with open('/etc/xui-clash.json') as f:
        UPSTREAM = json.load(f)['upstream']
    http.server.ThreadingHTTPServer(('127.0.0.1', 18765), Handler).serve_forever()
