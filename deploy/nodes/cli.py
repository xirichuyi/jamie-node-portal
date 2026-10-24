"""Jamie-Node 接入向导：一次录入、自动准备、可重试、明确区分发布与连通。"""

import argparse
import contextlib
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time

from . import manager as node_manager
from . import client_probe

ROOT = Path(__file__).resolve().parent
PREFLIGHT = r'''
set -eu
. /etc/os-release
printf 'os=%s\narch=%s\nuid=%s\n' "$ID" "$(uname -m)" "$(id -u)"
printf 'memory_kib='; awk '/MemTotal:/ {print $2}' /proc/meminfo
printf 'memory_max='; cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max
if command -v ip >/dev/null; then
 ip -6 -o addr show scope global | awk '{print "ipv6=" $4}'
fi
if command -v curl >/dev/null; then
 region=$(curl -fsS --max-time 3 -H 'Authorization: Bearer Oracle' \
  http://169.254.169.254/opc/v2/instance/region 2>/dev/null || true)
 printf 'cloud_region=%s\n' "$region"
fi
if [ -x /usr/local/x-ui/x-ui ] && [ -s /etc/x-ui/install-result.env ] &&
   [ -s /etc/x-ui/tls/node.crt ] && [ -s /etc/x-ui/tls/node.key ]; then
 echo panel=ready
elif [ -e /usr/local/x-ui ] || [ -e /etc/x-ui/x-ui.db ]; then
 echo panel=partial
else
 echo panel=absent
fi
for f in /proc/net/tcp /proc/net/tcp6; do
 [ ! -r "$f" ] || awk '$4=="0A" {print "tcp=" $2}' "$f"
done
for f in /proc/net/udp /proc/net/udp6; do
 [ ! -r "$f" ] || awk 'NR>1 {print "udp=" $2}' "$f"
done
if command -v python3 >/dev/null; then
 python3 - <<'PY'
from pathlib import Path
# Remote inbounds are dynamically injected and need not appear in config.json.
# Identify actual UDP socket owners instead of assuming a persisted startup config.
sockets = {}
for filename in ('/proc/net/udp', '/proc/net/udp6', '/proc/net/tcp', '/proc/net/tcp6'):
 try:
  for line in Path(filename).read_text().splitlines()[1:]:
   fields = line.split()
   sockets[fields[9]] = ('tcp' if '/tcp' in filename else 'udp',
                        int(fields[1].rsplit(':', 1)[1], 16))
 except OSError:
  pass
for process in Path('/proc').glob('[0-9]*'):
 try:
  executable = (process / 'exe').resolve(strict=True)
  if executable.parent != Path('/usr/local/x-ui/bin') or not executable.name.startswith('xray'):
   continue
  for fd in (process / 'fd').iterdir():
   try:
    link = str(fd.readlink())
    if link.startswith('socket:[') and link[8:-1] in sockets:
     transport, port = sockets[link[8:-1]]
     print('managed_' + transport + '=' + str(port))
   except OSError:
    pass
 except OSError:
  pass
PY
fi
'''

OCI_REGIONS = {
    'ca-montreal-1': ('🇨🇦', '加拿大', '蒙特利尔'),
    'ca-toronto-1': ('🇨🇦', '加拿大', '多伦多'),
    'mx-queretaro-1': ('🇲🇽', '墨西哥', '克雷塔罗'),
    'ap-tokyo-1': ('🇯🇵', '日本', '东京'),
    'ap-osaka-1': ('🇯🇵', '日本', '大阪'),
    'ap-singapore-1': ('🇸🇬', '新加坡', ''),
    'eu-frankfurt-1': ('🇩🇪', '德国', '法兰克福'),
    'us-sanjose-1': ('🇺🇸', '美国', '圣何塞'),
}


def location_defaults(cloud_region, catalog):
    location = OCI_REGIONS.get(cloud_region)
    if not location:
        return None, None
    flag, country, city = location
    prefix = f'{flag} {country}' + (f' · {city}' if city else '')
    names = {row['name'] for row in catalog['nodes']}
    number = 1
    # Retired names also reserve their sequence numbers.
    while any(name.startswith(f'{prefix} {number:02d}') for name in names):
        number += 1
    return f'{prefix} {number:02d}', country


def matching_nodes(catalog, ip, allocation=None, saved_port=None):
    rows = [row for row in catalog['nodes'] if row['server'] == ip]
    if allocation:
        ports = set()
        for value in allocation:
            if value:
                ports.update(port_pool(value))
        if ports:
            return [row for row in rows if row['port'] in ports]
    if saved_port:
        return [row for row in rows if row['port'] == saved_port]
    return rows


def port_pool(value):
    ports = set()
    for part in value.split(','):
        bounds = part.strip().split('-')
        if len(bounds) not in (1, 2):
            raise ValueError('端口请用 21226,21227 或 21226-21227')
        start, end = int(bounds[0]), int(bounds[-1])
        if not 1024 <= start <= end <= 65535 or end - start > 100:
            raise ValueError('端口必须在 1024–65535，每段最多 101 个')
        ports.update(range(start, end + 1))
    return sorted(ports)


def inspect(text):
    facts = {'tcp': set(), 'udp': set(), 'managed_udp': set(), 'managed_tcp': set(), 'ipv6': []}
    for line in text.splitlines():
        key, _, value = line.partition('=')
        if key in ('tcp', 'udp'):
            facts[key].add(int(value.rsplit(':', 1)[1], 16))
        elif key == 'ipv6':
            address = ipaddress.ip_interface(value).ip
            if address.is_global:
                facts['ipv6'].append(str(address))
        elif key in ('managed_udp', 'managed_tcp'):
            facts[key].add(int(value))
        elif key:
            facts[key] = value
    if facts.get('uid') != '0':
        raise ValueError('需要 root SSH 账号')
    if facts.get('os') not in ('alpine', 'debian', 'ubuntu'):
        raise ValueError('自动安装支持 Alpine、Debian、Ubuntu')
    if facts.get('arch') not in ('aarch64', 'arm64', 'x86_64', 'amd64'):
        raise ValueError('自动接入目前支持 ARM64 和 AMD64')
    memory = int(facts['memory_kib']) * 1024
    if facts.get('memory_max', 'max').isdigit():
        memory = min(memory, int(facts['memory_max']))
    facts['memory_mib'] = memory // 1024**2
    if facts['memory_mib'] < 128:
        raise ValueError('内存不足 128 MiB，暂不自动安装')
    if facts.get('panel') == 'partial':
        raise ValueError('发现已有或未完成的 x-ui 安装；保留现场，请检查安装日志，不会覆盖重装')
    return facts


def choose_port(pool, occupied, existing=None):
    if existing is not None:
        if existing not in pool:
            raise ValueError('已有节点端口不在指定范围内；请保留原端口，迁移需单独操作')
        return existing
    for port in pool:
        if port not in occupied:
            return port
    raise ValueError('提供的端口都被占用；请提供另一个已分配端口')


def transport_for(requested, existing, saved, ssh_port):
    previous = (existing or {}).get('protocol', 'hysteria') if existing else saved.get('protocol')
    if previous:
        if requested != 'auto' and requested != previous:
            raise ValueError('已有节点/重试参数的协议不同；协议迁移需单独操作')
        return previous
    return requested if requested != 'auto' else ('vless' if ssh_port != 22 else 'hysteria')


def prompt(label, default, automatic):
    if automatic:
        if default is None:
            raise ValueError('缺少参数：' + label)
        return default
    value = input(label + (f' [{default}]' if default is not None else '') + ': ').strip()
    if value:
        return value
    if default is None:
        raise ValueError('必须填写：' + label)
    return default


def call(config, host, command, data=None):
    result = subprocess.run(
        ['ssh', '-F', str(config), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
         '-o', 'ConnectTimeout=12', host, command], input=data, capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError(f'{host} 操作失败；凭据与私密日志未输出')
    return result.stdout


def save_profile(path, profile):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def report(status):
    print('管理连接：' + ('在线' if status.get('management_online') else '尚未确认在线'))
    print('订阅发布：' + ('已发布' if status.get('published') else '未发布'))
    print('订阅内容：' + ('已包含节点' if status.get('subscription_present') else '尚未确认'))
    if 'node_members_expected' in status:
        print(f'本节点用户绑定：{status["node_members_bound"]}/{status["node_members_expected"]}')
        if status['node_members_bound'] != status['node_members_expected']:
            print('剩余账号由后台继续同步；不等待或处理其他离线节点。')
    online = status.get('connectivity_ok')
    print('最近代理探测：' + ('通过' if online is True else '未通过' if online is False else '暂无结果'))
    if status.get('connectivity_checked_at'):
        print('探测时间：' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(status['connectivity_checked_at'])))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument('--ssh', help='已有 SSH 别名，如 ck46')
    target.add_argument('--host', help='没有 SSH 别名时填写公网 IPv4/IPv6')
    parser.add_argument('--ssh-port', type=int, default=22)
    parser.add_argument('--user', default='root')
    parser.add_argument('--master', default='Noether')
    parser.add_argument('--tcp-ports', help='服务商分配的 TCP 端口，如 21226-21227')
    parser.add_argument('--udp-ports', help='服务商分配的 UDP 端口，如 21228-21229')
    parser.add_argument('--ports', help='NAT 分配端口范围；TCP/UDP 共用时只需填一次，自动排除 SSH 端口')
    parser.add_argument('--protocol', choices=['auto', 'vless', 'reality', 'hysteria', 'hy2'], default='auto',
                        help='新 NAT 节点默认 VLESS TCP；已有节点保留原协议')
    parser.add_argument('--ipv6', action='store_true', help='自动发现公网 IPv6 并作为客户端入口')
    parser.add_argument('--endpoint', help='明确指定客户端公网 IP；SSH 管理地址保持独立')
    parser.add_argument('--add-protocol', action='store_true', help='增加入口，保留已有协议和账号')
    parser.add_argument('--probe-origin', choices=['auto', 'master', 'local'], default='auto')
    parser.add_argument('--interface', help='本机验证使用的物理网卡')
    parser.add_argument('--wait-seconds', type=int, default=0, help='可选：等待本节点账号绑定；默认后台同步')
    parser.add_argument('--quota-group', help='共享流量组；已有机器默认沿用')
    parser.add_argument('--quota-tb', help='新入口额度 TB；追加协议默认分配原入口的一半')
    parser.add_argument('--group-limit-tb', help='新建共享流量组的总额度 TB')
    parser.add_argument('--name')
    parser.add_argument('--region')
    parser.add_argument('--publish-unverified', action='store_true', help='代理测试失败时仍明确要求发布')
    parser.add_argument('--yes', action='store_true', help='使用参数/已保存配置，无交互运行')
    parser.add_argument('--check', action='store_true', help='只读检查，不安装、不注册、不发布')
    args = parser.parse_args(argv)
    args.protocol = {'hy2': 'hysteria', 'reality': 'vless'}.get(args.protocol, args.protocol)
    if not args.ssh and not args.host:
        args.host = prompt('公网 IP', None, args.yes)
        args.ssh_port = int(prompt('SSH 端口', '22', args.yes))
    for alias in (args.ssh, args.master, args.user):
        if alias and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', alias):
            raise ValueError('SSH 名称/用户名格式不正确')
    if not 1 <= args.ssh_port <= 65535:
        raise ValueError('SSH 端口不正确')
    if args.host:
        ip = str(ipaddress.ip_address(args.host))
        if not ipaddress.ip_address(ip).is_global:
            raise ValueError('请使用公网 IP')
    else:
        resolved = subprocess.run(['ssh', '-G', args.ssh], capture_output=True, text=True, check=True)
        ip = next(line.split(maxsplit=1)[1] for line in resolved.stdout.splitlines() if line.startswith('hostname '))
        ip = str(ipaddress.ip_address(ip))
        args.ssh_port = int(next(line.split()[1] for line in resolved.stdout.splitlines()
                                 if line.startswith('port ')))
    if not ipaddress.ip_address(ip).is_global:
        raise ValueError('节点必须使用公网 IP')
    if args.wait_seconds < 0 or args.wait_seconds > 600:
        raise ValueError('等待时间必须为 0–600 秒')
    profile_key = f'{args.master}:{args.ssh or ip}:{args.ssh_port}'
    if args.add_protocol or args.ipv6 or args.endpoint:
        family = args.endpoint or ('v6' if args.ipv6 else 'v4')
        profile_key += f':{args.protocol}:{family}'
    key = hashlib.sha256(profile_key.encode()).hexdigest()[:16]
    profile_path = Path.home() / '.config/jamie-node/nodes' / (key + '.json')
    saved = json.loads(profile_path.read_text()) if profile_path.exists() else {}
    stage = '连接'
    # macOS TMPDIR paths can exceed the Unix socket path limit with OpenSSH %C.
    with tempfile.TemporaryDirectory(prefix='jamie-onboard-', dir='/tmp') as directory:
        config = Path(directory) / 'ssh.conf'
        host = args.ssh or 'jamie-onboard-target'
        text = ''
        if args.host:
            text += f'Host {host}\n HostName {ip}\n Port {args.ssh_port}\n User {args.user}\n'
        text += f'Host *\n ControlMaster auto\n ControlPersist 600\n ControlPath {directory}/%C\n'
        text += f'Include "{Path.home() / ".ssh/config"}"\n'
        config.write_text(text)
        config.chmod(0o600)
        try:
            # OpenSSH handles password input and host-key trust directly; never store a password.
            def login_to(endpoint):
                login = subprocess.run(['ssh', '-F', str(config), '-o', 'ConnectTimeout=12',
                                        '-o', 'BatchMode=' + ('yes' if args.yes else 'no'),
                                        '-o', 'StrictHostKeyChecking=' + ('yes' if args.yes else 'ask'),
                                        endpoint, 'true'])
                if login.returncode:
                    raise RuntimeError('SSH 登录失败：' + endpoint +
                                       '；请核对用户名/密码、密钥和主机指纹；--yes 仅支持已有密钥/连接')
            login_to(args.master)
            catalog = json.loads(call(config, args.master, 'cat /etc/jamie-node-catalog.json'))
            if ip == catalog['service']['master_ip']:
                raise ValueError('目标是主控机器，不能用新节点向导安装')
            existing_rows = matching_nodes(
                catalog, ip, [args.ports, args.tcp_ports, args.udp_ports], saved.get('port'))
            if any(not n['enabled'] for n in existing_rows):
                raise ValueError('该节点已停用；请先确认机器归属，不能自动连接已退役节点')
            if len(existing_rows) > 1:
                raise ValueError('该 IP 已有多个入口，请指定 --ports 选择端口')
            existing = existing_rows[0] if existing_rows else None
            original = existing
            login_to(host)
            stage = '预检查'
            print('[1/4] 检查系统、内存、端口和已有安装', flush=True)
            facts = inspect(call(config, host, 'sh -s', PREFLIGHT.encode()).decode())
            if existing and facts['panel'] != 'ready':
                raise ValueError('目录已有节点但机器安装不完整，不会自动重装或替换凭据')
            installed_port = None
            if facts['panel'] == 'ready':
                # Read just the non-secret management port, never the rest of the env file.
                value = call(config, host, "sed -n 's/^XUI_PANEL_PORT=//p' /etc/x-ui/install-result.env").decode().strip()
                installed_port = int(shlex.split(value)[0])
            if installed_port and (args.add_protocol or args.ipv6 or args.endpoint) and original is None:
                command = 'python3 -c ' + shlex.quote((ROOT / 'status.py').read_text())
                owner = json.loads(call(config, args.master, command, json.dumps({
                    'owner': True, 'management_ip': ip, 'management_port': installed_port}).encode()))
                owned = [n for n in catalog['nodes'] if n.get('node_id') in owner['owner_ids']]
                if any(not n['enabled'] for n in owned):
                    raise ValueError('该管理端包含已停用入口；不能自动重新接入')
                original = next(iter(owned), None)
            endpoint = args.endpoint or saved.get('ip') or ip
            if args.ipv6 and not args.endpoint:
                addresses = facts['ipv6']
                if endpoint not in addresses:
                    if len(addresses) != 1:
                        raise ValueError('未发现唯一公网 IPv6；请用 --endpoint 指定已配置的地址')
                    endpoint = addresses[0]
            endpoint = str(ipaddress.ip_address(endpoint))
            if not ipaddress.ip_address(endpoint).is_global:
                raise ValueError('客户端入口必须是公网 IP')
            if args.ipv6 and ':' not in endpoint:
                raise ValueError('--ipv6 需要公网 IPv6 地址')
            if ':' in endpoint and endpoint not in facts['ipv6'] and endpoint != ip:
                raise ValueError('指定 IPv6 未出现在机器网卡上')
            if args.add_protocol and args.protocol == 'auto':
                raise ValueError('追加协议请指定 --protocol hysteria 或 vless')
            if args.add_protocol or endpoint != ip:
                candidates = [n for n in matching_nodes(catalog, endpoint,
                              [args.ports, args.tcp_ports, args.udp_ports], saved.get('port'))
                              if args.protocol == 'auto' or n.get('protocol', 'hysteria') == args.protocol]
                if len(candidates) > 1:
                    candidates = [n for n in candidates if n['port'] == saved.get('port')]
                if len(candidates) > 1:
                    raise ValueError('该地址协议已有多个入口；请指定端口')
                existing = candidates[0] if candidates else None
                if existing and not existing['enabled']:
                    raise ValueError('目标入口已停用，不会自动重新启用')
            automatic = args.yes or args.check
            protocol = transport_for(args.protocol, existing, saved, args.ssh_port)
            tcp_default = args.tcp_ports or args.ports or saved.get('tcp_ports')
            if not tcp_default and args.ssh_port == 22:
                tcp_default = str(installed_port or 48180) + (',8443-8453' if protocol == 'vless' else '')
            if not tcp_default and installed_port and existing and protocol == 'vless':
                tcp_default = f'{installed_port},{existing["port"]}'
            if not tcp_default and installed_port:
                tcp_default = str(installed_port)
            tcp = port_pool(prompt('可用 TCP 端口', tcp_default, automatic or bool(tcp_default)))
            tcp = [port for port in tcp if port != args.ssh_port]
            management_port = choose_port(tcp, facts['tcp'], installed_port)
            is_tcp = protocol == 'vless'
            previous_port = existing['port'] if existing else saved.get('port') if facts['panel'] == 'ready' else None
            udp = []
            if is_tcp:
                pool = [port for port in tcp if port != management_port]
                port = choose_port(pool, facts['tcp'], previous_port)
                if port in facts['tcp'] and port not in facts['managed_tcp']:
                    raise ValueError('TCP 端口被其他服务占用，不能覆盖')
            else:
                udp_default = args.udp_ports or args.ports or saved.get('udp_ports')
                if not udp_default and existing:
                    udp_default = str(existing['port'])
                if not udp_default and args.ssh_port == 22:
                    udp_default = str(existing['port']) if existing else '8443-8453'
                udp = port_pool(prompt('可用 UDP 端口', udp_default, automatic or bool(udp_default)))
                occupied = facts['udp'] | (facts['tcp'] if args.add_protocol and not existing else set())
                port = choose_port(udp, occupied, previous_port)
            if not is_tcp and port in facts['udp'] and port not in facts['managed_udp']:
                raise ValueError('选定 UDP 端口被其他服务占用，不能覆盖；请换一个已分配端口')
            detected_name, detected_region = location_defaults(facts.get('cloud_region'), catalog)
            name_default = args.name or (existing or {}).get('name') or saved.get('name') or detected_name
            region_default = args.region or (existing or {}).get('region') or saved.get('region') or detected_region
            name = prompt('节点显示名称', name_default or ('待命名' if args.check else None),
                          automatic or bool(name_default))
            region = prompt('地区', region_default or ('待填写' if args.check else None),
                            automatic or bool(region_default))
            profile = dict(ip=endpoint, management_ip=ip, port=port, management_port=management_port, name=name, region=region,
                           protocol=protocol,
                           tcp_ports=','.join(map(str, tcp)), udp_ports=','.join(map(str, udp)))
            transport = 'VLESS TCP' if is_tcp else 'HY2 UDP'
            print(f'{facts["os"]} / {facts["arch"]} / {facts["memory_mib"]} MiB；管理 TCP {management_port}，{transport} {port}')
            options = ['add', '--ssh', host, '--ssh-config', str(config), '--master', args.master,
                       '--ip', endpoint, '--management-ip', ip, '--management-port', str(management_port), '--port', str(port),
                       '--name', name, '--region', region]
            options += ['--protocol', protocol]
            options += ['--probe-origin', args.probe_origin]
            if args.interface:
                options += ['--interface', args.interface]
            if existing and existing['quota_bytes']:
                from decimal import Decimal
                options += ['--quota-group', existing['quota_group'], '--quota-tb', str(Decimal(existing['quota_bytes']) / 10**12)]
            elif original and original['quota_bytes'] and (args.add_protocol or endpoint != ip):
                from decimal import Decimal
                allocation = saved.get('quota_bytes')
                if allocation is None:
                    allocation = int(Decimal(args.quota_tb) * 10**12) if args.quota_tb else original['quota_bytes'] // 2
                original_bytes = saved.get('split_original_bytes', original['quota_bytes'])
                donor_id = saved.get('split_from_id', original['inbound_id'])
                if not 0 < allocation < original_bytes:
                    raise ValueError('追加额度必须小于原入口总额度')
                options += ['--quota-group', original['quota_group'], '--quota-tb', str(Decimal(allocation) / 10**12),
                            '--split-from', str(donor_id), '--split-original-bytes', str(original_bytes)]
                profile.update(quota_bytes=allocation, split_from_id=donor_id, split_original_bytes=original_bytes)
            elif args.quota_tb:
                options += ['--quota-group', args.quota_group or ('account-' + ip.replace(':', '-')), '--quota-tb', args.quota_tb]
                if args.group_limit_tb:
                    options += ['--group-limit-tb', args.group_limit_tb]
            else:
                options += ['--quota-group', (existing or {}).get('quota_group', 'unlimited-' + ip.replace('.', '-')), '--unlimited']
                print('节点总流量：不设上限；用户套餐保持原规则')
            if args.publish_unverified:
                options.append('--publish-unverified')
            status_command = 'python3 -c ' + shlex.quote((ROOT / 'status.py').read_text())
            def status():
                return json.loads(call(config, args.master, status_command, json.dumps(profile).encode()))
            if args.check:
                report(status())
                return
            save_profile(profile_path, profile)
            stage = '准备节点'
            print('[2/4] ' + ('复用已有安装' if facts['panel'] == 'ready' else '安装节点组件'), flush=True)
            if facts['panel'] == 'absent':
                bootstrap = ('apk add --no-cache bash' if facts['os'] == 'alpine' else
                             'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y bash python3 nftables curl openssl')
                call(config, host, bootstrap)
                options += ['--prepare', '--master-ip', catalog['service']['master_ip'],
                            '--memory-mib', str(min(320, max(128, facts['memory_mib'] * 3 // 4)))]
            stage = '注册与发布'
            print('[3/4] ' + ('目录已发布，检查现有配置' if existing and existing['enabled'] else '注册、连通性测试与订阅发布'), flush=True)
            if not existing or (name, region) != (existing['name'], existing['region']):
                node_manager.main(options)
            stage = '验证同步'
            print('[4/4] 只检查本次入口；旧节点离线不阻塞完成', flush=True)
            deadline = time.monotonic() + args.wait_seconds
            while True:
                result = status()
                node_bound = (result.get('node_members_expected') is not None and
                              result.get('node_members_bound') == result['node_members_expected'] and
                              result.get('configuration_clean') and result.get('management_online'))
                if result.get('subscription_present') and node_bound:
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(5)
            report(result)
            if client_probe.core_path():
                checked = client_probe.check_subscription(
                    lambda command: call(config, args.master, command), profile, args.interface)
                print('本机目标节点验证：' + ('通过' if checked['ok'] else '未通过'))
                if not checked['ok']:
                    raise RuntimeError('本机目标节点实连未通过；现有发布状态保留，未修改其他节点')
            else:
                print('本机独立 Mihomo 验证：跳过（未安装 Clash Verge）；不能据此断言本机链路可用')
            print('参数已保存；以后用相同 --ssh 或 --host/--ssh-port 重试，加 --check 可只读检查。')
        except (RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            # Error messages here are explicitly sanitized; subprocess output remains private.
            print(f'停止阶段：{stage}；已完成的安装/注册不会删除或重装。', flush=True)
            raise RuntimeError(str(exc) if isinstance(exc, (RuntimeError, ValueError)) else 'SSH 执行超时或失败') from None
        finally:
            for endpoint in (host, args.master):
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    subprocess.run(['ssh', '-F', str(config), '-O', 'exit', endpoint],
                                   capture_output=True, timeout=5)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print('接入未完成：' + str(error))
        raise SystemExit(1) from None
