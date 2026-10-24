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
from . import client_probe

ROOT = Path(__file__).resolve().parent
SSH_OPTIONS = []


def ssh(host, command, data=None):
    result = subprocess.run(
        [
            'ssh',
            *SSH_OPTIONS,
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
        if b'Node connectivity failed; not published' in result.stderr:
            raise RuntimeError('Node connectivity failed; not published')
        raise RuntimeError('SSH operation failed on ' + host + '; no credentials printed')
    return result.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'add'])
    parser.add_argument('--master', default='Noether')
    parser.add_argument('--ssh-config', help='Optional SSH configuration used by onboarding')
    parser.add_argument(
        '--master-ip', help='Public master address; defaults to SSH config HostName'
    )
    parser.add_argument('--ssh', dest='host')
    parser.add_argument('--ip')
    parser.add_argument('--management-ip', help='Management address, separate from the public endpoint')
    parser.add_argument('--probe-origin', choices=['auto', 'master', 'local'], default='auto')
    parser.add_argument('--interface', help='Physical interface for the local verification client')
    parser.add_argument('--split-from', type=int, help='Existing inbound contributing part of its cap')
    parser.add_argument('--split-original-bytes', type=int)
    parser.add_argument('--management-port', type=int)
    parser.add_argument('--port', type=int, default=8443)
    parser.add_argument('--protocol', choices=['hysteria', 'vless'],
                        help='New-node transport; existing nodes retain their protocol')
    parser.add_argument('--memory-mib', type=int, default=320)
    parser.add_argument('--cpu-percent', type=int, default=50)
    parser.add_argument('--name', help='Public flag + region + optional number, no machine name')
    parser.add_argument('--region')
    parser.add_argument(
        '--quota-group', help='OCI account identifier, NOT simply one limit per machine'
    )
    parser.add_argument('--quota-tb', type=Decimal)
    parser.add_argument('--unlimited', action='store_true', help='No node aggregate traffic cap; user allowances remain enforced')
    parser.add_argument('--publish-unverified', action='store_true', help='Explicitly publish even if the data-plane probe fails; monitoring stays enabled')
    parser.add_argument('--group-limit-tb', type=Decimal)
    parser.add_argument(
        '--prepare', action='store_true', help='Install on a new Debian or Alpine node before registration'
    )
    args = parser.parse_args(argv)
    global SSH_OPTIONS
    SSH_OPTIONS = ['-F', args.ssh_config] if args.ssh_config else []
    if not 128 <= args.memory_mib <= 65536 or not 10 <= args.cpu_percent <= 6400:
        parser.error('Invalid resource limits')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.master):
        parser.error('Invalid master alias')
    if args.action == 'list':
        catalog = json.loads(ssh(args.master, 'cat /etc/jamie-node-catalog.json'))
        for row in catalog['nodes']:
            quota = f'{row["quota_bytes"] / 10**12:g} TB' if row['quota_bytes'] else 'unlimited'
            print(
                f'{row["inbound_id"]:>3}  {row["name"]}  {row["server"]}:{row["port"]}  {quota}  {row["quota_group"]}'
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
            args.quota_tb or args.unlimited,
        ]
    ):
        parser.error(
            'add requires --ssh --ip --management-port --name --region --quota-group and --quota-tb or --unlimited'
        )
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.host):
        parser.error('Invalid SSH alias')
    ip = ipaddress.ip_address(args.ip)
    if not ip.is_global:
        parser.error('Expected a public IPv4 or IPv6 address')
    args.ip = str(ip)
    management_ip = str(ipaddress.ip_address(args.management_ip or args.ip))
    if not ipaddress.ip_address(management_ip).is_global:
        parser.error('Expected a public management address')
    local_probe = args.probe_origin == 'local' or (args.probe_origin == 'auto' and ip.version == 6)
    if local_probe and not client_probe.core_path():
        parser.error('IPv6/local verification requires Mihomo or Clash Verge on this computer')
    if not 1024 <= args.port <= 65535 or not 1024 <= args.management_port <= 65535:
        parser.error('Invalid port')
    if args.unlimited:
        if args.quota_tb is not None or args.group_limit_tb is not None:
            parser.error('--unlimited cannot be combined with quota limits')
        args.quota_tb = Decimal(0)
        args.group_limit_tb = Decimal(0)
    if not args.unlimited and (
        not args.quota_tb.is_finite()
        or args.quota_tb <= 0
        or (
            args.group_limit_tb is not None
            and (not args.group_limit_tb.is_finite() or args.group_limit_tb <= 0)
        )
    ):
        parser.error('Quota must be positive')
    # Reject oversubscribed groups before installing anything on the remote host.
    sys.path.insert(0, str(ROOT.parent.parent / 'backend'))
    from node_catalog import validate_catalog

    catalog = json.loads(ssh(args.master, 'cat /etc/jamie-node-catalog.json'))
    candidate = json.loads(json.dumps(catalog))
    existing = next(
        (n for n in candidate['nodes'] if (n['server'], n['port']) == (args.ip, args.port)), None
    )
    protocol = args.protocol or (existing or {}).get('protocol', 'hysteria')
    if existing and protocol != existing.get('protocol', 'hysteria'):
        parser.error('Transport migration is a separate operation; existing protocol is preserved')
    row = {
        'server': args.ip,
        'port': args.port,
        'name': args.name,
        'region': args.region,
        'quota_group': args.quota_group,
        'quota_bytes': int(args.quota_tb * 10**12),
        'enabled': True,
        'protocol': protocol,
        'node_id': existing['node_id'] if existing else 2147483647,
        'inbound_id': existing['inbound_id']
        if existing
        else max([n['inbound_id'] for n in candidate['nodes']] + [0]) + 1,
    }
    candidate['nodes'] = [n for n in candidate['nodes'] if n['inbound_id'] != row['inbound_id']] + [
        row
    ]
    if args.split_from and not existing:
        donor = next(n for n in candidate['nodes'] if n['inbound_id'] == args.split_from)
        remaining = args.split_original_bytes - row['quota_bytes'] if args.split_original_bytes else 0
        if remaining <= 0 or donor['quota_group'] != row['quota_group'] or donor['quota_bytes'] not in (args.split_original_bytes, remaining):
            parser.error('Invalid or changed shared allocation; no quota changed')
        donor['quota_bytes'] = remaining
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
            ['ssh', *SSH_OPTIONS, '-G', args.master], capture_output=True, text=True, check=True
        ).stdout
        master_ip = args.master_ip or next(
            line.split(maxsplit=1)[1]
            for line in ssh_config.splitlines()
            if line.startswith('hostname ')
        )
        master_ip = str(ipaddress.IPv4Address(master_ip))
        alpine = ssh(args.host, 'test -f /etc/alpine-release && echo alpine || echo other').strip() == b'alpine'
        script = 'prepare_alpine_node.sh' if alpine else 'prepare_small_node.sh'
        ssh(
            args.host,
            f'bash -s -- {management_ip} {args.management_port} {master_ip} {args.memory_mib} {args.cpu_percent}',
            (ROOT / script).read_bytes(),
        )
        if protocol == 'vless':
            ssh(args.host, 'touch /etc/x-ui/jamie-new-tcp-core')
    if protocol == 'vless' and not existing:
        # Only installations marked freshly prepared may change core version.
        ssh(args.host, 'python3 -', (ROOT / 'prepare_tcp_core.py').read_bytes())
    # This maintenance helper is bundled here, rather than depending on another checkout.
    ssh(args.host, 'python3 -', (ROOT / 'settings.py').read_bytes())
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
        'management_server': management_ip,
        'management_port': args.management_port,
        'token': env['XUI_API_TOKEN'],
        'base': '/' + env['XUI_WEB_BASE_PATH'].strip('/') + '/',
        'pin': digest.hex(),
        'xray_pin': base64.b64encode(digest).decode(),
        'group_limit': int(args.group_limit_tb * 10**12) if args.group_limit_tb is not None else None,
        'publish_unverified': args.publish_unverified,
        'split_from_id': args.split_from,
        'split_original_bytes': args.split_original_bytes,
    }
    if ip.version == 6:
        ssh(args.master, 'python3 -', (ROOT / 'subscriptions.py').read_bytes())
    source = (ROOT / 'register.py').read_text()
    if local_probe:
        command = ['ssh', *SSH_OPTIONS, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', 'ConnectTimeout=12', args.master]
        result = client_probe.register(command, source, params, args.interface)
    else:
        command = 'python3 -c ' + shlex.quote(source)
        result = json.loads(ssh(args.master, command, json.dumps(params).encode()))
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
