"""One command to prepare and register a node; credentials only travel over SSH stdin."""

import argparse
import base64
from decimal import Decimal
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def ssh(host, command, data=None):
    result = subprocess.run(
        [
            'ssh',
            '-o',
            'BatchMode=yes',
            '-o',
            'StrictHostKeyChecking=yes',
            '-o',
            'ConnectTimeout=12',
            host,
            command,
        ],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
    )
    if result.returncode:
        raise RuntimeError('SSH operation failed on ' + host + '; no credentials printed')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'add'])
    parser.add_argument('--master', default='Noether')
    parser.add_argument(
        '--master-ip', help='Public master address; defaults to SSH config HostName'
    )
    parser.add_argument('--ssh', dest='host')
    parser.add_argument('--ip')
    parser.add_argument('--management-port', type=int)
    parser.add_argument('--port', type=int, default=8443)
    parser.add_argument('--name', help='Public flag + region + optional number, no machine name')
    parser.add_argument('--region')
    parser.add_argument(
        '--quota-group', help='OCI account identifier, NOT simply one limit per machine'
    )
    parser.add_argument('--quota-tb', type=Decimal)
    parser.add_argument('--group-limit-tb', type=Decimal)
    parser.add_argument(
        '--prepare', action='store_true', help='Install on a new Debian node before registration'
    )
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.master):
        parser.error('Invalid master alias')
    if args.action == 'list':
        catalog = json.loads(ssh(args.master, 'cat /etc/jamie-node-catalog.json'))
        for row in catalog['nodes']:
            print(
                f'{row["inbound_id"]:>3}  {row["name"]}  {row["server"]}:{row["port"]}  {row["quota_bytes"] / 10**12:g} TB  {row["quota_group"]}'
            )
        return
    if not all(
        [
            args.host,
            args.ip,
            args.management_port,
            args.name,
            args.region,
            args.quota_group,
            args.quota_tb,
        ]
    ):
        parser.error(
            'add requires --ssh --ip --management-port --name --region --quota-group --quota-tb'
        )
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.host):
        parser.error('Invalid SSH alias')
    ip = ipaddress.ip_address(args.ip)
    if ip.version != 4 or not ip.is_global:
        parser.error('Expected a public IPv4 address')
    if not 1024 <= args.port <= 65535 or not 1024 <= args.management_port <= 65535:
        parser.error('Invalid port')
    if (
        not args.quota_tb.is_finite()
        or args.quota_tb <= 0
        or (
            args.group_limit_tb is not None
            and (not args.group_limit_tb.is_finite() or args.group_limit_tb <= 0)
        )
    ):
        parser.error('Quota must be positive')
    # Reject oversubscribed groups before installing anything on the remote host.
    sys.path.insert(0, str(ROOT.parent / 'backend'))
    from node_catalog import validate_catalog

    catalog = json.loads(ssh(args.master, 'cat /etc/jamie-node-catalog.json'))
    candidate = json.loads(json.dumps(catalog))
    existing = next(
        (n for n in candidate['nodes'] if (n['server'], n['port']) == (args.ip, args.port)), None
    )
    row = {
        'server': args.ip,
        'port': args.port,
        'name': args.name,
        'region': args.region,
        'quota_group': args.quota_group,
        'quota_bytes': int(args.quota_tb * 10**12),
        'enabled': True,
        'node_id': existing['node_id'] if existing else 2147483647,
        'inbound_id': existing['inbound_id']
        if existing
        else max([n['inbound_id'] for n in candidate['nodes']] + [0]) + 1,
    }
    candidate['nodes'] = [n for n in candidate['nodes'] if n['inbound_id'] != row['inbound_id']] + [
        row
    ]
    if args.group_limit_tb is not None:
        limit = int(args.group_limit_tb * 10**12)
        if (
            args.quota_group in candidate['quota_groups']
            and candidate['quota_groups'][args.quota_group] != limit
        ):
            parser.error('Cannot change an existing group limit during node registration')
        candidate['quota_groups'][args.quota_group] = limit
    validate_catalog(candidate)
    if args.prepare:
        ssh_config = subprocess.run(
            ['ssh', '-G', args.master], capture_output=True, text=True, check=True
        ).stdout
        master_ip = args.master_ip or next(
            line.split(maxsplit=1)[1]
            for line in ssh_config.splitlines()
            if line.startswith('hostname ')
        )
        master_ip = str(ipaddress.IPv4Address(master_ip))
        ssh(
            args.host,
            f'bash -s -- {args.ip} {args.management_port} {master_ip}',
            (ROOT / 'prepare_small_node.sh').read_bytes(),
        )
    # This maintenance helper is bundled here, rather than depending on another checkout.
    ssh(args.host, 'python3 -', (ROOT / 'node_settings.py').read_bytes())
    env = {}
    for line in ssh(args.host, 'cat /etc/x-ui/install-result.env').decode().splitlines():
        key, value = line.split('=', 1)
        env[key] = shlex.split(value)[0] if value else ''
    if int(env['XUI_PANEL_PORT']) != args.management_port:
        raise ValueError('Management port differs from installed node; no registration performed')
    der = ssh(args.host, 'openssl x509 -in /etc/x-ui/tls/node.crt -outform DER')
    digest = hashlib.sha256(der).digest()
    params = {
        **row,
        'management_port': args.management_port,
        'token': env['XUI_API_TOKEN'],
        'base': '/' + env['XUI_WEB_BASE_PATH'].strip('/') + '/',
        'pin': digest.hex(),
        'xray_pin': base64.b64encode(digest).decode(),
        'group_limit': int(args.group_limit_tb * 10**12) if args.group_limit_tb else None,
    }
    command = 'python3 -c ' + shlex.quote((ROOT / 'node_register.py').read_text())
    print(ssh(args.master, command, json.dumps(params).encode()).decode())


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
