"""Run on master: switch one existing IPv4 inbound to REALITY, probe before publishing."""

import copy
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid

sys.path.insert(0, '/opt/jamie-portal/current/backend')
from panel import Panel
from probe import outbound, test_outbound
from node_catalog import validate_catalog


def main(inbound_id, port):
    os.umask(0o077)
    panel = Panel(json.loads(Path('/etc/jamie-portal.json').read_text()))
    path = Path('/etc/jamie-node-catalog.json')
    catalog = json.loads(path.read_text())
    row = next(n for n in catalog['nodes'] if n['inbound_id'] == inbound_id)
    old = panel.request(f'inbounds/get/{inbound_id}')
    backup = Path(tempfile.mkdtemp(prefix='node-transport-', dir='/root'))
    (backup / 'inbound.json').write_text(json.dumps(old))
    (backup / 'catalog.json').write_text(json.dumps(catalog))
    hosts = panel.request(f'hosts/byInbound/{inbound_id}')
    assert all(h['inboundIds'] == [inbound_id] for h in hosts)
    (backup / 'hosts.json').write_text(json.dumps(hosts))
    clients = {c['email']: c for c in panel.request('clients/list')}
    for client in clients.values():
        if not client.get('uuid'):
            client['uuid'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'jamie-node:' + client['auth']))
    settings = json.loads(old['settings']) if isinstance(old['settings'], str) else old['settings']
    members = settings['clients']
    for member in members:
        member['id'] = clients[member['email']]['uuid']
    generated = subprocess.run(
        ['/usr/local/x-ui/bin/xray-linux-amd64', 'x25519'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    keys = dict(line.split(': ', 1) for line in generated.splitlines() if ': ' in line)
    private = keys['PrivateKey']
    public = keys.get('Password (PublicKey)') or keys.get('Password') or keys.get('PublicKey')
    assert public
    sid = secrets.token_hex(8)
    stream = {
        'network': 'tcp',
        'security': 'reality',
        'realitySettings': {
            'show': False,
            'xver': 0,
            'minClientVer': '1.0.0',
            'target': 'www.cloudflare.com:443',
            'serverNames': ['www.cloudflare.com'],
            'privateKey': private,
            'shortIds': [sid],
            'settings': {
                'publicKey': public,
                'fingerprint': 'chrome',
                'serverName': 'www.cloudflare.com',
                'spiderX': '/',
            },
        },
        'tcpSettings': {'acceptProxyProtocol': False, 'header': {'type': 'none'}},
        'externalProxy': [
            {'forceTls': 'same', 'dest': row['server'], 'port': port, 'remark': row['name']}
        ],
    }
    update = copy.deepcopy(old)
    update.update(
        protocol='vless',
        port=port,
        listen='0.0.0.0',
        settings=json.dumps({'clients': members, 'decryption': 'none', 'fallbacks': []}),
        streamSettings=json.dumps(stream),
    )
    panel.request(f'inbounds/update/{inbound_id}', update)
    identity = json.loads(Path('/var/lib/jamie-portal/probe-identity.json').read_text())
    monitor = clients[identity['email']]['uuid']
    uri = f'vless://{monitor}@{row["server"]}:{port}?' + urllib.parse.urlencode(
        {
            'security': 'reality',
            'type': 'tcp',
            'encryption': 'none',
            'sni': 'www.cloudflare.com',
            'fp': 'chrome',
            'pbk': public,
            'sid': sid,
        }
    )
    config = outbound(uri, {(row['server'], port)})
    for attempt in range(4):
        time.sleep(3)
        with tempfile.TemporaryDirectory() as temp:
            result = test_outbound(config, '/usr/local/x-ui/bin/xray-linux-amd64', temp)
        if result['ok']:
            break
    else:
        raise RuntimeError(
            'TCP proxy test failed; catalog unchanged; private backup: ' + str(backup)
        )
    after = panel.request(f'inbounds/get/{inbound_id}')
    assert after['up'] >= old['up'] and after['down'] >= old['down']
    after_settings = (
        json.loads(after['settings']) if isinstance(after['settings'], str) else after['settings']
    )
    assert len(after_settings['clients']) == len(members)
    for host in hosts:
        host.update(
            hosts=[f'{row["server"]}:{port}'],
            port=port,
            pinnedPeerCertSha256=[],
            allowInsecure=False,
        )
        panel.request('hosts/update/' + host['groupId'], host)
    row.update(port=port, protocol='vless')
    validate_catalog(catalog)
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
    temporary.chmod(path.stat().st_mode & 0o777)
    os.chown(temporary, path.stat().st_uid, path.stat().st_gid)
    os.replace(temporary, path)
    print(
        json.dumps(
            {
                'published': True,
                'protocol': 'vless',
                'port': port,
                'clients_preserved': len(members),
                'proxy_test': result,
            }
        )
    )


if __name__ == '__main__':
    main(int(sys.argv[1]), int(sys.argv[2]))
