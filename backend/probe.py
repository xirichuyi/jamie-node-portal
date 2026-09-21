"""Dedicated-account HY2 end-to-end probe; never uses customers' credentials.

Only fixed public 204 endpoints are requested. Access logs and payload recording
are disabled. The probe's SOCKS listener binds exclusively to loopback.
"""

import base64
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

NODES = {
    '161.33.217.26': ('日本', 8443),
    '168.107.64.69': ('新加坡', 8443),
    '149.118.144.221': ('马来西亚', 9443),
    '192.9.148.252': ('美国 · 圣何塞', 8443),
    '140.245.88.56': ('日本 · 东京 02', 8443),
    '168.138.190.68': ('新加坡 02', 8443),
}


def outbound(uri):
    u = urllib.parse.urlsplit(uri)
    q = urllib.parse.parse_qs(u.query)
    if (
        u.scheme not in ('hy2', 'hysteria2')
        or u.hostname not in NODES
        or u.port != NODES[u.hostname][1]
    ):
        raise ValueError('Unexpected probe node')
    pin = q.get('pinSHA256', [''])[0].replace(':', '')
    if not re.fullmatch('[a-fA-F0-9]{64}', pin):
        raise ValueError('Missing certificate pin')
    return {
        'protocol': 'hysteria',
        'settings': {'version': 2, 'address': u.hostname, 'port': u.port},
        'streamSettings': {
            'network': 'hysteria',
            'security': 'tls',
            'hysteriaSettings': {'version': 2, 'auth': urllib.parse.unquote(u.username or '')},
            'tlsSettings': {
                'serverName': q.get('sni', [u.hostname])[0],
                'alpn': ['h3'],
                'pinnedPeerCertSha256': pin,
                'allowInsecure': False,
            },
        },
    }


def test_outbound(config, core, directory):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    config_path = Path(directory) / 'probe.json'
    config_path.write_text(
        json.dumps(
            {
                'log': {'access': 'none', 'error': 'none', 'loglevel': 'none'},
                'inbounds': [
                    {
                        'listen': '127.0.0.1',
                        'port': port,
                        'protocol': 'socks',
                        'settings': {'auth': 'noauth', 'udp': False},
                    }
                ],
                'outbounds': [config],
            }
        )
    )
    process = subprocess.Popen(
        [core, 'run', '-c', str(config_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        for _ in range(30):
            if process.poll() is not None:
                raise RuntimeError('Probe core exited')
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('Probe core did not start')
        started = time.monotonic()
        result = subprocess.run(
            [
                'curl',
                '--silent',
                '--socks5-hostname',
                f'127.0.0.1:{port}',
                '--max-time',
                '12',
                '--output',
                '/dev/null',
                '--write-out',
                '%{http_code}',
                'https://www.gstatic.com/generate_204',
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {
            'ok': result.returncode == 0 and result.stdout == '204',
            'latency_ms': round((time.monotonic() - started) * 1000),
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run(root=Path('/var/lib/jamie-portal'), core='/usr/local/x-ui/bin/xray-linux-amd64'):
    os.umask(0o077)
    result = {
        'checked_at': int(time.time()),
        'source': 'Noether',
        'nodes': [],
        'subscription_ok': False,
    }
    try:
        identity = json.loads((root / 'probe-identity.json').read_text())
        url = 'https://sub.chuyi.uk/sub/' + identity['sub_id']
        req = urllib.request.Request(url, headers={'User-Agent': 'Shadowrocket/Probe'})
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read(1024 * 1024)
            if response.headers.get('profile-title') != 'Jamie-Node' or not response.headers.get(
                'subscription-userinfo'
            ):
                raise ValueError('Missing subscription metadata')
        lines = base64.b64decode(raw, validate=True).decode().splitlines()
        configs = [outbound(line.strip()) for line in lines if line.strip()]
        if {c['settings']['address'] for c in configs} != set(NODES) or len(configs) != len(NODES):
            raise ValueError('Unexpected node inventory')
        result['subscription_ok'] = True
        for config in configs:
            host = config['settings']['address']
            item = {'name': NODES[host][0], 'server': host, 'ok': False, 'latency_ms': None}
            try:
                with tempfile.TemporaryDirectory(prefix='probe-', dir=root) as temp:
                    item.update(test_outbound(config, core, temp))
            except Exception:
                item['error'] = '探测未完成'
            result['nodes'].append(item)
    except Exception:
        result['error'] = '探测订阅读取或校验失败'
    path = root / 'connectivity.json'
    temporary = root / 'connectivity.tmp'
    temporary.write_text(json.dumps(result, ensure_ascii=False))
    os.replace(temporary, path)
    print(
        json.dumps(
            {
                'subscription_ok': result['subscription_ok'],
                'nodes': [{'name': n['name'], 'ok': n['ok']} for n in result['nodes']],
            }
        )
    )
    return result


if __name__ == '__main__':
    run()
