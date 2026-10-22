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

def node_rows():
    return {(row['server'], row['port']): row for row in active_nodes()}

def node_names():
    return {key: row['name'] for key, row in node_rows().items()}

# Only two visible, text-only groups. Routing runs from the rules; services that never
# need a manual switch point straight at their outbound instead of owning a group.
PROXY, AUTO, AI = '节点选择', '自动选择', 'AI 服务'
MEDIA = TELEGRAM = FINAL = PROXY
MICROSOFT = APPLE = 'DIRECT'
ADS = 'REJECT'
# AI services refuse many regions; the hidden AI group tests only these regions' nodes.
AI_REGIONS = ('美国', '日本', '新加坡')
DOMESTIC_DOH = ['https://dns.alidns.com/dns-query', 'https://doh.pub/dns-query']
BOOTSTRAP_DNS = ['223.5.5.5', '119.29.29.29']

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
    return [{'name': label, 'type': 'select', 'proxies': [PROXY]}
            for label in (quota, deadline)]

ROCKET_RULES = 'https://testingcf.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Shadowrocket/'

# One routing table for both clients, top to bottom, first match wins:
# (comment, outbound, Clash MetaCubeX sets, Shadowrocket blackmatrix7 lists, shared domain fixes).
# Shadowrocket lists follow blackmatrix7's README: use both X.list and X_Domain.list where both exist.
# geoip/* sets match by IP; only the final CN-IP rule resolves the domain.
ROUTES = [
    ('局域网与私有地址', 'DIRECT', ['geosite/private', 'geoip/private'], ['Lan/Lan'], []),
    ('必须直连：系统更新与游戏下载 CDN，国内有节点，走代理只会更慢、白耗流量', 'DIRECT',
     ['geosite/category-games@cn', 'geosite/steam@cn'], ['SteamCN/SteamCN'],
     ['swcdn.apple.com', 'updates.cdn-apple.com', 'mesu.apple.com', 'appldnld.apple.com', 'oscdn.apple.com',
      'windowsupdate.com', 'delivery.mp.microsoft.com', 'update.microsoft.com', 'steamcontent.com',
      # The foreign collection's 'amazon' keyword would otherwise catch Amazon/AWS China.
      'amazon.cn', 'amazonaws.com.cn']),
    ('国内 AI：直连', 'DIRECT', ['geosite/category-ai-cn'], [],
     ['deepseek.com', 'doubao.com', 'kimi.com', 'moonshot.cn', 'chatglm.cn', 'zhipuai.cn', 'hailuoai.com',
      'yuanbao.tencent.com', 'tongyi.aliyun.com', 'yiyan.baidu.com']),
    ('BT 下载 tracker：直连', 'DIRECT', ['geosite/tracker'], [], []),
    ('广告与追踪：拦截', ADS,
     ['geosite/category-ads-all'], ['AdvertisingLite/AdvertisingLite', 'AdvertisingLite/AdvertisingLite_Domain'], []),
    # Adapted from the hand-maintained list in Johnshall/Shadowrocket-ADBlock-Rules-Forever:
    # LinkedIn and Bing sit inside the Microsoft lists that are otherwise direct.
    ('必须代理：国内能解析、但直连无法正常使用或会被识别为国内的海外服务', PROXY, [], [],
     ['googleapis.cn', 'xn--ngstr-lra8j.com', 'apple.news', 'testflight.apple.com',
      'linkedin.com', 'linkedin.cn', 'licdn.com', 'bing.com', 'location.microsoft.com', 'hoyolab.com',
      'dnsleaktest.com', 'ipleak.net', 'browserleaks.com', 'browserleaks.org']),
    ('海外 AI：OpenAI、Claude、Gemini、Copilot 等，限制地区较多，自动用美国/日本/新加坡节点', AI, ['geosite/category-ai-!cn'],
     ['OpenAI/OpenAI', 'Claude/Claude', 'Gemini/Gemini', 'Copilot/Copilot'],
     ['anthropic.com', 'claude.ai', 'claudeusercontent.com', 'clau.de', 'openai.com', 'chatgpt.com',
      'oaistatic.com', 'oaiusercontent.com', 'gemini.google.com', 'copilot.microsoft.com', 'perplexity.ai',
      'x.ai', 'grok.com', 'cursor.com', 'cursor.sh', 'cursorapi.com', 'openrouter.ai', 'poe.com',
      'huggingface.co', 'character.ai', 'midjourney.com']),
    ('流媒体：代理', MEDIA,
     ['geosite/youtube', 'geosite/netflix', 'geosite/disney', 'geosite/spotify', 'geosite/tiktok', 'geoip/netflix'],
     ['YouTube/YouTube', 'Netflix/Netflix', 'Disney/Disney', 'Spotify/Spotify', 'TikTok/TikTok'], []),
    ('Telegram：代理', TELEGRAM, ['geosite/telegram', 'geoip/telegram'], ['Telegram/Telegram'], []),
    ('常用海外服务：代理', PROXY, ['geosite/github', 'geosite/google', 'geoip/google'],
     ['GitHub/GitHub', 'Google/Google', 'Twitter/Twitter', 'Facebook/Facebook', 'Instagram/Instagram',
      'Whatsapp/Whatsapp', 'Discord/Discord', 'Reddit/Reddit', 'Wikipedia/Wikipedia', 'Docker/Docker',
      'PayPal/PayPal', 'Steam/Steam'], []),
    ('微软：国内可直连', MICROSOFT, ['geosite/onedrive', 'geosite/microsoft'], ['Microsoft/Microsoft'], []),
    ('苹果：iCloud、App Store 等国内可直连', APPLE, ['geosite/apple'], ['Apple/Apple', 'Apple/Apple_Domain'], []),
    ('其他海外网站：代理', PROXY, ['geosite/geolocation-!cn'], ['Global/Global', 'Global/Global_Domain'], []),
    ('国内网站：直连', 'DIRECT', ['geosite/cn'], ['ChinaMax/ChinaMax', 'ChinaMax/ChinaMax_Domain'], []),
]

# Process names as reported on Windows, macOS, Linux and Android.
DIRECT_PROCESSES = ['qbittorrent', 'qbittorrent.exe', 'qBittorrent', 'Transmission', 'transmission-daemon',
    'transmission-qt.exe', 'aria2c', 'aria2c.exe', 'Motrix', 'Motrix.exe', 'Thunder', 'Thunder.exe',
    'DownloadServer.exe', 'BitComet.exe', 'uTorrent.exe', 'BitTorrent.exe', 'Folx',
    'tailscale', 'tailscaled', 'tailscale.exe', 'tailscaled.exe', 'zerotier-one', 'zerotier-one.exe',
    'frpc', 'frpc.exe', 'com.xunlei.downloadprovider', 'org.proninyaroslav.libretorrent',
    'com.xunlei.downloadprovider.pad']

def set_name(source):
    kind, name = source.split('/')
    return name + ('_ip' if kind == 'geoip' else '')

def rule_providers():
    return {set_name(source): {'type': 'http', 'behavior': 'ipcidr' if source.startswith('geoip/') else 'domain',
            'format': 'mrs', 'path': './rules/Jamie-Node-' + set_name(source) + '.mrs', 'interval': 86400,
            'proxy': PROXY,
            'url': 'https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/' + source + '.mrs'}
            for source in [x for route in ROUTES for x in route[2]] + ['geoip/cn']}

def routing_sections(service, client):
    """[(comment, rules)] for 'clash' or 'shadowrocket', ending with the CN-IP and final rules."""
    sections = [('本站与 DNS：直连，保证随时能更新订阅', service_rules(service))]
    if client == 'clash':
        sections.append(('下载与组网软件按程序名直连（BT 走代理既慢又耗流量；组网工具避免绕回代理）',
                         [f'PROCESS-NAME,{name},DIRECT' for name in DIRECT_PROCESSES]))
    for comment, outbound, sets, lists, domains in ROUTES:
        rules = [f'DOMAIN-SUFFIX,{d},{outbound}' for d in domains]
        if client == 'clash':
            rules += [f'RULE-SET,{set_name(x)},{outbound}' + (',no-resolve' if x.startswith('geoip/') else '')
                      for x in sets]
        else:
            # blackmatrix7: X.list holds typed rules (RULE-SET); X_Domain.list is a plain domain set.
            rules += [('DOMAIN-SET' if x.endswith('_Domain') else 'RULE-SET') + f',{ROCKET_RULES}{x}.list,{outbound}'
                      for x in lists]
        if rules:
            sections.append((comment, rules))
    sections.append(('国内 IP：解析域名后判断，未收录的国内网站也能直连',
                     ['RULE-SET,cn_ip,DIRECT' if client == 'clash' else 'GEOIP,CN,DIRECT']))
    sections.append(('以上都没匹配：走代理', [('MATCH,' if client == 'clash' else 'FINAL,') + FINAL]))
    return sections

def service_rules(service):
    hosts = (urllib.parse.urlsplit(service['origin']).hostname, service['panel_host'])
    return ([f'DOMAIN,{host},DIRECT' for host in hosts]
            + [f"IP-CIDR,{service['master_ip']}/32,DIRECT,no-resolve"]
            + [f'IP-CIDR,{ip}/32,DIRECT,no-resolve' for ip in BOOTSTRAP_DNS]
            + ['DOMAIN,dns.alidns.com,DIRECT', 'DOMAIN,doh.pub,DIRECT'])

# Domains that must keep real IPs: LAN discovery, time sync, STUN/P2P, consoles, captive checks.
FAKE_IP_FILTER = ['rule-set:private', '+.lan', '+.local', '+.localdomain', '+.home.arpa',
    '+.msftconnecttest.com', '+.msftncsi.com', 'captive.apple.com', 'time.*.com', 'time.*.gov',
    'time.*.edu.cn', 'time.*.apple.com', 'ntp.*.com', '+.pool.ntp.org', '+.ntp.org.cn',
    'time1.cloud.tencent.com', '+.stun.*.*', '+.stun.*.*.*', '+.stun.*.*.*.*',
    'stun.l.google.com', 'localhost.ptlogin2.qq.com', 'localhost.sec.qq.com', 'localhost.work.weixin.qq.com',
    '+.srv.nintendo.net', '+.stun.playstation.net', 'xbox.*.microsoft.com', '+.xboxlive.com',
    '+.battlenet.com.cn', '+.wotgame.cn', '+.wggames.cn', '+.wowsgame.cn', '+.wargaming.net',
    '+.music.163.com', '+.126.net', 'music.*.com', '+.y.qq.com', 'lens.l.google.com']

def collect_proxies(body):
    rows = node_rows()
    proxies = []
    for index, line in enumerate(decode_links(body), 1):
        u = urllib.parse.urlsplit(line.strip())
        row = rows.get((u.hostname, u.port or 443))
        if row is None:
            continue  # Unpublished and retired nodes never leak into subscriptions.
        name = row['name']
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
    return proxies, {p['name']: (rows.get((p['server'], p['port'])) or {}).get('region') for p in proxies}

class PlainDumper(yaml.SafeDumper):
    """No &anchors/*aliases: some clients' editors show them literally."""
    def ignore_aliases(self, data):
        return True

def convert(body, usage=None, client='clash'):
    """Clash YAML. For Shadowrocket (which imports Clash YAML as a config but cannot read
    mihomo .mrs sets) the same nodes and groups carry its own rule-list URLs instead."""
    service = service_settings()
    proxies, region_of = collect_proxies(body)
    names = [p['name'] for p in proxies]
    probe = {'url': service['probe_url'], 'interval': 300, 'lazy': True, 'timeout': 3000}
    ai_nodes = [n for n in names if region_of[n] in AI_REGIONS] or names
    groups = [
        {'name': PROXY, 'type': 'select', 'proxies': [AUTO, *names, 'DIRECT']},
        dict(name=AUTO, type='url-test', tolerance=50, proxies=names, **probe),
        # Runs in the background: hidden from the Clash panel, never needs a manual pick.
        dict(name=AI, type='url-test', tolerance=50, hidden=True, proxies=ai_nodes, **probe),
    ] + account_groups(usage)
    if client == 'shadowrocket':
        head = yaml.dump({'mode': 'rule', 'ipv6': False,
            'dns': {'enable': True, 'nameserver': DOMESTIC_DOH},
            'proxies': proxies, 'proxy-groups': groups},
            Dumper=PlainDumper, allow_unicode=True, sort_keys=False)
        return (head + rule_lines(service, client)).encode()
    head = yaml.dump({'mixed-port': 7890, 'allow-lan': False,
        'mode': 'rule', 'log-level': 'warning', 'ipv6': False,
        'unified-delay': True, 'tcp-concurrent': True,
        'profile': {'store-selected': True, 'store-fake-ip': True},
        'sniffer': {'enable': True, 'force-dns-mapping': True, 'parse-pure-ip': True,
                    'sniff': {'HTTP': {'ports': [80, '8080-8880'], 'override-destination': True},
                              'TLS': {'ports': [443, 8443]}, 'QUIC': {'ports': [443, 8443]}},
                    'skip-domain': ['Mijia Cloud', '+.push.apple.com', 'dlg.io.mi.com']},
        'dns': {'enable': True, 'ipv6': False, 'enhanced-mode': 'fake-ip',
                'fake-ip-range': '198.18.0.1/16', 'fake-ip-filter': FAKE_IP_FILTER,
                'default-nameserver': BOOTSTRAP_DNS,
                'nameserver': DOMESTIC_DOH,
                'proxy-server-nameserver': DOMESTIC_DOH},
        'proxies': proxies,
        'proxy-groups': groups,
        'rule-providers': rule_providers()},
        Dumper=PlainDumper, allow_unicode=True, sort_keys=False)
    return (head + rule_lines(service, client)).encode()

def rule_lines(service, client):
    """YAML rules written by hand so each section keeps its comment in the profile."""
    lines = ['rules:']
    for comment, rules in routing_sections(service, client):
        lines += ['# ' + comment] + ['- ' + json.dumps(re.sub('^FINAL,', 'MATCH,', rule), ensure_ascii=False)
                                     for rule in rules]
    return '\n'.join(lines) + '\n'

def shadowrocket_config(raw, update_url):
    """Routing profile for Shadowrocket; nodes come from the separately imported subscription."""
    service = service_settings()
    _, region_of = collect_proxies(raw)
    probe = 'url=' + service['probe_url'] + ',interval=600,tolerance=50,timeout=5'
    present = [r for r in AI_REGIONS if r in region_of.values()]
    ai_filter = '|'.join(map(re.escape, present)) or '.*'
    every = 'policy-regex-filter=.*'
    lines = [
        '# ' + service['title'] + ' 小火箭分流配置：节点来自订阅，本配置只负责分流。',
        '[General]',
        'bypass-system = true',
        'skip-proxy = 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 100.64.0.0/10, 127.0.0.1, localhost, *.local, captive.apple.com',
        'tun-excluded-routes = 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.0.2.0/24, 192.88.99.0/24, 192.168.0.0/16, 198.51.100.0/24, 203.0.113.0/24, 224.0.0.0/4, 255.255.255.255/32, 239.255.255.250/32',
        'dns-server = ' + ', '.join(DOMESTIC_DOH),
        'fallback-dns-server = system',
        'ipv6 = false',
        'prefer-ipv6 = false',
        'dns-direct-system = false',
        'icmp-auto-reply = true',
        'always-reject-url-rewrite = false',
        'private-ip-answer = true',
        'dns-direct-fallback-proxy = true',
        'udp-policy-not-supported-behaviour = REJECT',
        'update-url = ' + update_url,
        '',
        '[Proxy Group]',
        f'{PROXY} = select,{AUTO},{every}',
        f'{AUTO} = url-test,{probe},{every}',
        f'{AI} = url-test,{probe},policy-regex-filter={ai_filter}',
        '',
        '[Rule]',
        *(line for comment, rules in routing_sections(service, 'shadowrocket') for line in ['# ' + comment, *rules]),
        '',
        '[Host]',
        'localhost = 127.0.0.1',
        '',
        '[URL Rewrite]',
        r'^https?://(www.)?g\.cn https://www.google.com 302',
        r'^https?://(www.)?google\.cn https://www.google.com 302',
    ]
    return ('\n'.join(lines) + '\n').encode()

def choose_format(path, query, agent, accept):
    requested = query.get('format', ['auto'])
    if len(requested) != 1 or requested[0] not in ('auto', 'clash', 'shadowrocket', 'shadowrocket-conf',
                                                   'shadowrocket-yaml', 'base64', 'html'):
        raise ValueError('Unsupported format')
    rocket = 'shadowrocket' in agent.lower()
    if requested[0] != 'auto':
        if requested[0] == 'clash' and rocket:
            return 'rocket-yaml'  # A Clash link added under Shadowrocket's 配置 tab.
        return {'shadowrocket': 'base64', 'shadowrocket-conf': 'conf',
                'shadowrocket-yaml': 'rocket-yaml'}.get(requested[0], requested[0])
    if path.startswith('/clash/'):
        return 'rocket-yaml' if rocket else 'clash'  # Existing subscriptions retain their old behavior.
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
        + '<li><a href="' + safe + '?format=shadowrocket">小火箭 / 通用节点订阅</a></li>'
        + '<li><a href="' + safe + '?format=shadowrocket-conf">小火箭分流配置</a></li></ul>'
        + '<p>Clash 格式自带分流。小火箭需同时导入节点订阅和分流配置，并在「配置」页使用该配置。</p>'
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
                elif fmt == 'rocket-yaml':
                    result = convert(raw, usage, 'shadowrocket')
                elif fmt == 'base64':
                    result = native_subscription(raw)
                elif fmt == 'conf':
                    result = shadowrocket_config(
                        raw, service['origin'].rstrip('/') + '/sub/' + match[1] + '?format=shadowrocket-conf')
                else:
                    native_subscription(raw)  # Validate before showing a usable subscription page.
                    result = landing_page(match[1], usage)
            self.send_response(200)
            self.send_header('Content-Type', {'clash': 'application/yaml; charset=utf-8',
                'rocket-yaml': 'application/yaml; charset=utf-8',
                'base64': 'text/plain; charset=utf-8', 'conf': 'text/plain; charset=utf-8',
                'html': 'text/html; charset=utf-8'}[fmt])
            if fmt != 'html':
                self.send_header('Content-Disposition', 'attachment; filename=' + service['title']
                                 + ('.conf' if fmt == 'conf' else ''))
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
