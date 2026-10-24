"""Master-side publication; private parameters arrive only over SSH stdin."""

import copy
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid

sys.path.insert(0, '/opt/jamie-portal/current/backend')
from node_catalog import CATALOG_PATH, load_catalog, validate_catalog
from panel import Panel
from probe import outbound, test_outbound

BACKUP_ROOT = '/root/codex-backups'
MONITOR_PATH = '/var/lib/jamie-portal/probe-identity.json'
CONFIG_PATH = '/etc/jamie-portal.json'

def run(params):
    management_server = params.get('management_server', params['server'])
    listener_port = params.get('listener_port', params['port'])
    websocket = params.get('transport') == 'ws'
    if websocket and (params.get('protocol') != 'vless' or not params.get('ws_path', '').startswith('/')):
        raise ValueError('Invalid WebSocket node')
    catalog = load_catalog()
    panel = Panel(json.loads(Path(CONFIG_PATH).read_text()))
    existing = next(
        (
            n
            for n in catalog['nodes']
            if (n['server'], n['port']) == (params['server'], params['port'])
        ),
        None,
    )
    candidate = copy.deepcopy(catalog)
    row = {
        key: params[key]
        for key in ('server', 'port', 'name', 'region', 'quota_group', 'quota_bytes')
    }
    protocol = params.get('protocol', 'hysteria')
    row['protocol'] = protocol
    if websocket:
        row['transport'] = 'ws'
    row.update(
        inbound_id=existing['inbound_id']
        if existing
        else max([n['inbound_id'] for n in catalog['nodes']] + [0]) + 1,
        node_id=existing['node_id'] if existing else 2147483647,
        enabled=True,
    )
    candidate['nodes'] = [n for n in candidate['nodes'] if n['inbound_id'] != row['inbound_id']] + [
        row
    ]
    donor = None
    if params.get('split_from_id') and not existing:
        donor = next(n for n in candidate['nodes'] if n['inbound_id'] == params['split_from_id'])
        original = params['split_original_bytes']
        remaining = original - row['quota_bytes']
        if (remaining <= 0 or not donor['enabled'] or donor['quota_group'] != row['quota_group']
                or donor['quota_bytes'] not in (original, remaining)):
            raise ValueError('Shared allocation changed; refusing to split again')
        donor['quota_bytes'] = remaining
        owner = next((n for n in panel.request('nodes/list')
                      if n['address'] == management_server and n['port'] == params['management_port']), None)
        if not owner or owner['id'] != donor['node_id']:
            raise ValueError('Quota donor belongs to another managed machine')
    if params.get('group_limit') is not None:
        old = candidate['quota_groups'].get(row['quota_group'])
        if old is not None and old != params['group_limit']:
            raise ValueError('Existing group limit cannot be changed during node registration')
        candidate['quota_groups'][row['quota_group']] = params['group_limit']
    validate_catalog(candidate)  # Quota/name checks happen before any panel mutation.
    backup = Path(BACKUP_ROOT) / ('node-register-' + str(time.time_ns()))
    backup.mkdir(mode=0o700)
    shutil.copy2(CATALOG_PATH, backup / 'catalog.json')
    with sqlite3.connect('/etc/x-ui/x-ui.db') as src, sqlite3.connect(backup / 'panel.db') as dst:
        src.backup(dst)
    if donor:
        old = panel.request('inbounds/get/' + str(donor['inbound_id']))
        if old['up'] + old['down'] >= donor['quota_bytes']:
            raise ValueError('Split would put the existing inbound below its consumed traffic')
        if old['total'] not in (params['split_original_bytes'], donor['quota_bytes']):
            raise ValueError('Panel allocation changed')
        update = copy.deepcopy(old)
        update.update(total=donor['quota_bytes'], trafficReset='never')
        for key in ('settings', 'streamSettings', 'sniffing'):
            if isinstance(update[key], dict):
                update[key] = json.dumps(update[key])
        panel.request('inbounds/update/' + str(old['id']), update)
        after = panel.request('inbounds/get/' + str(old['id']))
        if after['total'] != donor['quota_bytes'] or after['up'] < old['up'] or after['down'] < old['down']:
            raise RuntimeError('Allocation verification failed')
        # Reserve capacity before adding the new inbound. On a failed probe the
        # smaller donor remains saved; retries reuse the same reserved amount.
        reserved = copy.deepcopy(catalog)
        for item in reserved['nodes']:
            if item['inbound_id'] == donor['inbound_id']:
                item['quota_bytes'] = donor['quota_bytes']
        validate_catalog(reserved)
        temporary = Path(CATALOG_PATH + '.tmp')
        temporary.write_text(json.dumps(reserved, ensure_ascii=False, indent=2))
        temporary.chmod(0o644)
        temporary.replace(CATALOG_PATH)
    nodes = panel.request('nodes/list')
    node = next(
        (
            n
            for n in nodes
            if n['address'] == management_server and n['port'] == params['management_port']
        ),
        None,
    )
    if not node:
        panel.request(
            'nodes/add',
            {
                'name': 'node-' + params['server'],
                'remark': params['name'],
                'scheme': 'https',
                'address': management_server,
                'port': params['management_port'],
                'basePath': params['base'],
                'apiToken': params['token'],
                'enable': True,
                'allowPrivateAddress': False,
                'tlsVerifyMode': 'verify' if websocket else 'pin',
                'pinnedCertSha256': params['pin'],
                'inboundSyncMode': 'all',
            },
        )
        node = next(
            n
            for n in panel.request('nodes/list')
            if n['address'] == management_server and n['port'] == params['management_port']
        )
    # Keep legacy tag stable for HY2 retries.
    tag = ('managed-vless-' if protocol == 'vless' else 'managed-hy2-') + params['server'].replace('.', '-') + '-' + str(params['port'])
    inbound = (
        panel.request('inbounds/get/' + str(existing['inbound_id']))
        if existing
        else next((n for n in panel.request('inbounds/list') if n['tag'] == tag), None)
    )
    if not inbound:
        template = next(n for n in panel.request('inbounds/list') if n['protocol'] == 'hysteria')
        stream = template['streamSettings']
        if isinstance(stream, str):
            stream = json.loads(stream)
        stream = copy.deepcopy(stream)
        stream['tlsSettings']['serverName'] = params['server']
        stream['tlsSettings']['certificates'] = [
            {
                'certificateFile': '/etc/x-ui/tls/node.crt',
                'keyFile': '/etc/x-ui/tls/node.key',
                'oneTimeLoading': False,
                'usage': 'encipherment',
                'buildChain': False,
            }
        ]
        stream['tlsSettings']['settings']['pinnedPeerCertSha256'] = [params['xray_pin']]
        stream['externalProxy'] = [
            {
                'forceTls': 'same',
                'dest': params['server'],
                'port': params['port'],
                'remark': params['name'],
                'allowInsecure': True,
                'pinnedPeerCertSha256': [params['xray_pin']],
            }
        ]
        settings = {'version': 2, 'clients': []}
        if websocket:
            stream = {
                'network': 'ws', 'security': 'none',
                # The provider rewrites Host before forwarding to the guest.
                # TLS/SNI authenticate the public endpoint; the guest matches the path.
                'wsSettings': {'path': params['ws_path']},
                'externalProxy': [{'forceTls': 'tls', 'dest': params['server'],
                                   'port': params['port'], 'remark': params['name'],
                                   'sni': params['server'], 'fingerprint': 'chrome',
                                   'alpn': ['http/1.1']}]}
            settings = {'clients': [], 'decryption': 'none', 'fallbacks': []}
        elif protocol == 'vless':
            generated = subprocess.run(
                ['/usr/local/x-ui/bin/xray-linux-amd64', 'x25519'],
                capture_output=True, text=True, check=True).stdout
            keys = dict(line.split(': ', 1) for line in generated.splitlines() if ': ' in line)
            public = keys.get('Password (PublicKey)') or keys.get('Password') or keys.get('PublicKey')
            if not public:
                raise RuntimeError('Could not generate REALITY key')
            stream = {
                'network': 'tcp', 'security': 'reality',
                'realitySettings': {
                    'show': False, 'xver': 0, 'minClientVer': '1.0.0',
                    'target': 'www.cloudflare.com:443', 'serverNames': ['www.cloudflare.com'],
                    'privateKey': keys['PrivateKey'], 'shortIds': [secrets.token_hex(8)],
                    'settings': {'publicKey': public, 'fingerprint': 'chrome',
                                 'serverName': 'www.cloudflare.com', 'spiderX': '/'}},
                'tcpSettings': {'acceptProxyProtocol': False, 'header': {'type': 'none'}},
                'externalProxy': [{'forceTls': 'same', 'dest': params['server'],
                                   'port': params['port'], 'remark': params['name']}]}
            settings = {'clients': [], 'decryption': 'none', 'fallbacks': []}
        panel.request(
            'inbounds/add',
            {
                'nodeId': node['id'],
                'up': 0,
                'down': 0,
                'total': params['quota_bytes'],
                'remark': params['name'],
                'enable': True,
                'expiryTime': 0,
                'trafficReset': 'never',
                'trafficResetDay': 1,
                'listen': '',
                'port': listener_port,
                'protocol': protocol,
                'tag': tag,
                'settings': json.dumps(settings),
                'streamSettings': json.dumps(stream),
                'sniffing': template['sniffing'],
            },
        )
        inbound = next(n for n in panel.request('inbounds/list') if n['tag'] == tag)
    if inbound['nodeId'] != node['id'] or inbound['port'] != listener_port:
        raise RuntimeError('Existing inbound does not belong to the requested node')
    if inbound['protocol'] != protocol:
        raise RuntimeError('Existing inbound transport differs; explicit migration required')
    current_stream = inbound['streamSettings']
    current_stream = json.loads(current_stream) if isinstance(current_stream, str) else current_stream
    if (current_stream.get('network') == 'ws') != websocket:
        raise RuntimeError('Existing inbound network differs; explicit migration required')
    row.update(inbound_id=inbound['id'], node_id=node['id'])
    validate_catalog(candidate)
    if inbound['total'] != params['quota_bytes']:
        if params['quota_bytes'] and inbound['up'] + inbound['down'] >= params['quota_bytes']:
            raise ValueError('Quota below already consumed traffic')
        update = copy.deepcopy(inbound)
        update.update(total=params['quota_bytes'], trafficReset='never')
        for key in ('settings', 'streamSettings', 'sniffing'):
            if isinstance(update[key], dict):
                update[key] = json.dumps(update[key])
        panel.request('inbounds/update/' + str(inbound['id']), update)
        after = panel.request('inbounds/get/' + str(inbound['id']))
        if (
            after['up'] < inbound['up']
            or after['down'] < inbound['down']
            or after['total'] != params['quota_bytes']
            or after['trafficReset'] != 'never'
        ):
            raise RuntimeError('Inbound quota update verification failed')

    # Ephemeral probe: failed connectivity blocks publication unless explicitly overridden.
    email = 'onboard_' + secrets.token_hex(8)
    auth = secrets.token_hex(24)
    client_uuid = str(uuid.uuid4())
    try:
        panel.request(
            'clients/add',
            {
                'client': {
                    'email': email,
                    'auth': auth,
                    'id': client_uuid,
                    'subId': secrets.token_hex(24),
                    'enable': True,
                    'totalGB': 10 * 1024**2,
                    'expiryTime': (int(time.time()) + 600) * 1000,
                    'trafficReset': 'never',
                    'trafficResetDay': 1,
                },
                'inboundIds': [inbound['id']],
            },
        )
        host = params['server']
        authority = f'[{host}]' if ':' in host else host
        uri = f'hysteria2://{auth}@{authority}:{params["port"]}?' + urllib.parse.urlencode({
            'sni': host, 'pinSHA256': params['pin']})
        if websocket:
            uri = f'vless://{client_uuid}@{authority}:{params["port"]}?' + urllib.parse.urlencode({
                'security': 'tls', 'type': 'ws', 'encryption': 'none',
                'sni': params['server'], 'host': params['server'], 'fp': 'chrome',
                'path': current_stream['wsSettings']['path'], 'alpn': 'http/1.1'})
        elif protocol == 'vless':
            stream = inbound['streamSettings']
            stream = json.loads(stream) if isinstance(stream, str) else stream
            reality = stream['realitySettings']
            uri = f'vless://{client_uuid}@{authority}:{params["port"]}?' + urllib.parse.urlencode({
                'security': 'reality', 'type': 'tcp', 'encryption': 'none',
                'sni': reality['serverNames'][0], 'fp': 'chrome',
                'pbk': reality['settings']['publicKey'], 'sid': reality['shortIds'][0]})
        config = outbound(uri, {(params['server'], params['port']): params['name']})
        for attempt in range(3):
            with tempfile.TemporaryDirectory(prefix='node-onboard-') as directory:
                result = test_outbound(config, '/usr/local/x-ui/bin/xray-linux-amd64', directory)
            if result['ok']:
                break
            time.sleep(2)
        if not result['ok'] and params.get('publish_unverified') is not True:
            raise RuntimeError('Node connectivity failed; not published')
    finally:
        if any(c['email'] == email for c in panel.request('clients/list')):
            panel.request('clients/del/' + urllib.parse.quote(email) + '?keepTraffic=0', {})

    # Only the dedicated monitor is bound here. Customer bindings go through the
    # portal's existing billing lock + persistent outbox, avoiding concurrent
    # redemption/renewal being overwritten by a second administrative writer.
    identity = json.loads(Path(MONITOR_PATH).read_text())
    current = panel.get(identity['email'])
    if (
        current['client']['auth'] != identity['auth']
        or current['client']['subId'] != identity['sub_id']
    ):
        raise RuntimeError('Probe ownership mismatch')
    panel.attach_existing(identity['email'], [inbound['id']])
    # Atomic public commit. Explicit unverified publication does not alter probe results.
    temporary = Path(CATALOG_PATH + '.tmp')
    temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2))
    temporary.chmod(0o644)
    temporary.replace(CATALOG_PATH)
    return {
        'ok': True,
        'name': row['name'],
        'inbound_id': row['inbound_id'],
        'customer_sync': 'queued by portal worker',
        'connectivity_verified': result['ok'],
        'backup': str(backup),
    }


if __name__ == '__main__':
    os.umask(0o077)
    with open('/run/lock/jamie-node-register.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc) == 'Node connectivity failed; not published':
                print('Node connectivity failed; not published', file=sys.stderr)
                raise SystemExit(1) from None
            print(
                'Node registration failed: '
                + type(exc).__name__
                + '. Inventory not published; retry after checking panel health.',
                file=sys.stderr,
            )
            raise SystemExit(1)
