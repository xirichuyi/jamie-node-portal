"""Target-only client checks and SSH probe handoff. No customer identities or logs."""

import base64
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request


def core_path():
    installed = Path('/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo')
    return str(installed) if installed.exists() else shutil.which('mihomo')


def physical_interface(server):
    if ':' not in server or not shutil.which('route') or os.uname().sysname != 'Darwin':
        return None
    result = subprocess.run(['route', '-n', 'get', '-inet6', 'default'],
                            capture_output=True, text=True, timeout=5)
    return next((line.split(':', 1)[1].strip() for line in result.stdout.splitlines()
                 if line.strip().startswith('interface:')), None)


def proxy_from_outbound(config):
    stream = config['streamSettings']
    if config['protocol'] == 'hysteria':
        endpoint = config['settings']
        tls = stream['tlsSettings']
        return dict(name='onboarding', type='hysteria2', server=endpoint['address'],
                    port=endpoint['port'], password=stream['hysteriaSettings']['auth'],
                    sni=tls['serverName'], fingerprint=tls['pinnedPeerCertSha256'],
                    alpn=['h3'], **{'skip-cert-verify': False})
    endpoint = config['settings']['vnext'][0]
    user = endpoint['users'][0]
    proxy = dict(name='onboarding', type='vless', server=endpoint['address'],
                 port=endpoint['port'], uuid=user['id'], tls=True,
                 network=stream['network'], **{'skip-cert-verify': False})
    if stream['security'] == 'reality':
        tls = stream['realitySettings']
        proxy.update(servername=tls['serverName'], **{
            'client-fingerprint': tls['fingerprint'],
            'reality-opts': {'public-key': tls['publicKey'], 'short-id': tls['shortId']}})
    else:
        tls = stream['tlsSettings']
        proxy.update(servername=tls['serverName'], alpn=tls.get('alpn', []),
                     **{'client-fingerprint': tls['fingerprint'], 'ws-opts': stream['wsSettings']})
    if user.get('flow'):
        proxy['flow'] = user['flow']
    return proxy


def test(config, interface=None, url='https://www.gstatic.com/generate_204'):
    core = core_path()
    if not core:
        raise RuntimeError('本机未安装 Mihomo；请安装 Clash Verge/Mihomo 或选择 --probe-origin master')
    proxy = proxy_from_outbound(config)
    interface = interface or physical_interface(proxy['server'])
    if interface:
        proxy['interface-name'] = interface
    with tempfile.TemporaryDirectory(prefix='jamie-node-test-') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        path = Path(directory) / 'config.json'
        path.write_text(json.dumps({'mixed-port': port, 'allow-lan': False, 'ipv6': True,
                                   'mode': 'rule', 'log-level': 'silent', 'proxies': [proxy],
                                   'rules': ['MATCH,onboarding']}))
        path.chmod(0o600)
        process = subprocess.Popen([core, '-d', directory, '-f', str(path)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(40):
                if process.poll() is not None:
                    return {'ok': False, 'error': 'client_start_failed'}
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1):
                        break
                except OSError:
                    time.sleep(.1)
            started = time.monotonic()
            result = subprocess.run(['curl', '-q', '-sS', '--socks5-hostname',
                                     f'127.0.0.1:{port}', '--noproxy', '', '--max-time', '15',
                                     '-o', '/dev/null', '-w', '%{http_code}', url],
                                    capture_output=True, text=True, timeout=20)
            return {'ok': result.returncode == 0 and result.stdout == '204',
                    'latency_ms': round((time.monotonic() - started) * 1000)}
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def register(command, source, params, interface=None):
    """Run the existing registrar, answering its probe over private subprocess pipes."""
    import shlex

    wrapper = '''
import sys,json,fcntl,os
os.umask(0o077)
ns={'__name__':'node_registration'}
exec(SOURCE,ns)
params=json.loads(sys.stdin.readline())
def local_probe(config,*args):
 print(json.dumps({'probe':config}),flush=True)
 return json.loads(sys.stdin.readline())
ns['test_outbound']=local_probe
with open('/run/lock/jamie-node-register.lock','w') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 try: print(json.dumps({'result':ns['run'](params)}),flush=True)
 except Exception as exc:
  print(json.dumps({'error':type(exc).__name__}),flush=True)
  raise SystemExit(1)
'''.replace('SOURCE', repr(source))
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([*command, 'python3 -u -c ' + shlex.quote(wrapper)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=errors, text=True)
        answer = None
        try:
            process.stdin.write(json.dumps(params) + '\n')
            process.stdin.flush()
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                if not select.select([process.stdout], [], [], 30)[0]:
                    if process.poll() is not None:
                        break
                    continue
                line = process.stdout.readline()
                if not line:
                    break
                message = json.loads(line)
                if 'probe' in message:
                    result = test(message['probe'], interface)
                    print('本机目标节点实连：' + ('通过' if result['ok'] else '未通过'), flush=True)
                    process.stdin.write(json.dumps(result) + '\n')
                    process.stdin.flush()
                elif 'result' in message:
                    answer = message['result']
                else:
                    raise RuntimeError('节点注册失败；保留安装与私密备份，未强制发布')
            if answer is None or process.wait(timeout=10):
                raise RuntimeError('节点注册未完成；请用相同命令重试')
            return answer
        finally:
            process.stdin.close()
            if process.poll() is None:
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
            process.stdout.close()


def check_subscription(remote, profile, interface=None):
    """Load only the dedicated monitor and test just the requested endpoint."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
    from probe import outbound
    from proxy_links import parse_link

    identity = json.loads(remote('cat /var/lib/jamie-portal/probe-identity.json'))
    catalog = json.loads(remote('cat /etc/jamie-node-catalog.json'))
    url = catalog['service']['origin'].rstrip('/') + '/sub/' + identity['sub_id']
    request = urllib.request.Request(url, headers={'User-Agent': 'Shadowrocket/Onboarding'})
    with urllib.request.urlopen(request, timeout=25) as response:
        lines = base64.b64decode(response.read(), validate=True).decode().splitlines()
    endpoint = (profile['ip'], profile['port'])
    for line in lines:
        link = parse_link(line)
        if (link['server'], link['port']) == endpoint:
            return test(outbound(line, {endpoint: profile['name']}), interface,
                        catalog['service']['probe_url'])
    raise RuntimeError('订阅尚未包含目标节点')
