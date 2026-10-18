"""Master-side transactional publication. Input contains private node credentials."""

import copy
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.parse

sys.path.insert(0, '/opt/jamie-portal/current/backend')
from node_catalog import CATALOG_PATH, load_catalog, validate_catalog
from panel import Panel
from probe import outbound, test_outbound


def run(params):
    catalog = load_catalog()
    panel = Panel(json.loads(Path('/etc/jamie-portal.json').read_text()))
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
    if params.get('group_limit') is not None:
        old = candidate['quota_groups'].get(row['quota_group'])
        if old is not None and old != params['group_limit']:
            raise ValueError('Existing group limit cannot be changed during node registration')
        candidate['quota_groups'][row['quota_group']] = params['group_limit']
    validate_catalog(candidate)  # Quota/name checks happen before any panel mutation.
    backup = Path('/root/codex-backups') / ('node-register-' + str(time.time_ns()))
    backup.mkdir(mode=0o700)
    shutil.copy2(CATALOG_PATH, backup / 'catalog.json')
    with sqlite3.connect('/etc/x-ui/x-ui.db') as src, sqlite3.connect(backup / 'panel.db') as dst:
        src.backup(dst)
    nodes = panel.request('nodes/list')
    node = next(
        (
            n
            for n in nodes
            if n['address'] == params['server'] and n['port'] == params['management_port']
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
                'address': params['server'],
                'port': params['management_port'],
                'basePath': params['base'],
                'apiToken': params['token'],
                'enable': True,
                'allowPrivateAddress': False,
                'tlsVerifyMode': 'pin',
                'pinnedCertSha256': params['pin'],
                'inboundSyncMode': 'all',
            },
        )
        node = next(
            n
            for n in panel.request('nodes/list')
            if n['address'] == params['server'] and n['port'] == params['management_port']
        )
    tag = 'managed-hy2-' + params['server'].replace('.', '-') + '-' + str(params['port'])
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
                'port': params['port'],
                'protocol': 'hysteria',
                'tag': tag,
                'settings': json.dumps({'version': 2, 'clients': []}),
                'streamSettings': json.dumps(stream),
                'sniffing': template['sniffing'],
            },
        )
        inbound = next(n for n in panel.request('inbounds/list') if n['tag'] == tag)
    if inbound['nodeId'] != node['id'] or inbound['port'] != params['port']:
        raise RuntimeError('Existing inbound does not belong to the requested node')
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
    try:
        panel.request(
            'clients/add',
            {
                'client': {
                    'email': email,
                    'auth': auth,
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
        uri = f'hysteria2://{auth}@{params["server"]}:{params["port"]}?sni={params["server"]}&pinSHA256={params["pin"]}'
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
    identity = json.loads(Path('/var/lib/jamie-portal/probe-identity.json').read_text())
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
