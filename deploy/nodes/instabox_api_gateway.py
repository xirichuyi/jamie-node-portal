"""InstaBox token-only API bridge; never exposes the panel UI."""

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shlex
import ssl
import urllib.error
import urllib.request


def main():
    env = {}
    for line in Path('/etc/x-ui/install-result.env').read_text().splitlines():
        key, value = line.split('=', 1)
        env[key] = shlex.split(value)[0] if value else ''
    prefix = '/' + env['XUI_WEB_BASE_PATH'].strip('/') + '/panel/api/'
    authorization = 'Bearer ' + env['XUI_API_TOKEN']
    context = ssl.create_default_context(cafile='/etc/x-ui/tls/node.crt')
    upstream = 'https://127.0.0.1:' + env['XUI_PANEL_PORT']

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def forward(self):
            self.connection.settimeout(40)
            if (not self.path.startswith(prefix)
                    or not hmac.compare_digest(self.headers.get('Authorization', ''), authorization)):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > 16 * 1024 * 1024 or self.headers.get('Transfer-Encoding'):
                    self.send_error(413)
                    return
                body = self.rfile.read(length) if self.command == 'POST' else None
                request = urllib.request.Request(upstream + self.path, data=body,
                    method=self.command, headers={'Authorization': authorization,
                                                  'Content-Type': self.headers.get('Content-Type', 'application/json')})
                try:
                    response = urllib.request.urlopen(request, context=context, timeout=30)
                except urllib.error.HTTPError as exc:
                    response = exc
                with response:
                    payload = response.read(16 * 1024 * 1024 + 1)
                    if len(payload) > 16 * 1024 * 1024:
                        raise ValueError('Response too large')
                    self.send_response(response.code)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
            except (OSError, ValueError):
                self.send_error(502)

    ThreadingHTTPServer(('0.0.0.0', 48181), Handler).serve_forever()


if __name__ == '__main__':
    main()
