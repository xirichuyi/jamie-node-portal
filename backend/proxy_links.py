"""Validate the supported authenticated transports shared by subscriptions and probes."""

import base64
import re
import urllib.parse
import uuid


def decode_links(body):
    text = body.decode().strip()
    if not text.startswith(('hysteria2://', 'hy2://', 'vless://')):
        text = base64.b64decode(text, validate=True).decode()
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_link(line):
    u = urllib.parse.urlsplit(line)
    q = urllib.parse.parse_qs(u.query)
    if not u.hostname or not u.username or u.scheme not in ('hy2', 'hysteria2', 'vless'):
        raise ValueError('Unsupported proxy link')
    if any(len(v) != 1 for v in q.values()):
        raise ValueError('Ambiguous proxy parameters')
    result = {'uri': u, 'query': q, 'server': u.hostname, 'port': u.port or 443,
              'sni': q.get('sni', [u.hostname])[0]}
    if u.scheme in ('hy2', 'hysteria2'):
        pin = q.get('pinSHA256', [''])[0].replace(':', '').lower()
        if not re.fullmatch('[0-9a-f]{64}', pin):
            raise ValueError('Missing certificate pin')
        result.update(type='hysteria2', pin=pin,
                      password=urllib.parse.unquote(u.username + (':' + u.password if u.password else '')))
    else:
        if q.get('security') != ['reality'] or q.get('type', ['tcp'])[0] not in ('tcp', 'raw'):
            raise ValueError('Only VLESS TCP REALITY is supported')
        public_key = q.get('pbk', [''])[0]
        short_id = q.get('sid', [''])[0]
        if not re.fullmatch('[A-Za-z0-9_-]{43}', public_key):
            raise ValueError('Invalid REALITY public key')
        if not re.fullmatch('(?:[0-9a-fA-F]{2}){1,8}', short_id):
            raise ValueError('Invalid REALITY short ID')
        if q.get('flow', [''])[0] not in ('', 'xtls-rprx-vision'):
            raise ValueError('Unsupported VLESS flow')
        if q.get('encryption', ['none']) != ['none']:
            raise ValueError('Unsupported VLESS encryption')
        result.update(type='vless', uuid=str(uuid.UUID(urllib.parse.unquote(u.username))),
                      public_key=public_key, short_id=short_id,
                      fingerprint=q.get('fp', ['chrome'])[0], flow=q.get('flow', [''])[0])
    return result
