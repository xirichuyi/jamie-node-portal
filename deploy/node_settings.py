"""Disable remote-node subscription endpoint; only the master serves users."""

import json
import shlex
import ssl
import urllib.request

env = {}
with open('/etc/x-ui/install-result.env') as source:
    for line in source:
        key, value = line.strip().split('=', 1)
        env[key] = shlex.split(value)[0] if value else ''
context = ssl.create_default_context(cafile='/etc/x-ui/tls/node.crt')
context.check_hostname = False  # Loopback only; trust the node's exact certificate.
base = (
    'https://127.0.0.1:'
    + env['XUI_PANEL_PORT']
    + '/'
    + env['XUI_WEB_BASE_PATH'].strip('/')
    + '/panel/api/'
)


def request(path, data):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(data).encode(),
        headers={
            'Authorization': 'Bearer ' + env['XUI_API_TOKEN'],
            'Content-Type': 'application/json',
        },
    )
    with urllib.request.urlopen(req, context=context, timeout=15) as response:
        result = json.load(response)
    if not result['success']:
        raise RuntimeError('Node settings update failed')
    return result.get('obj')


settings = request('setting/all', {})
settings['subEnable'] = False
request('setting/update', settings)
