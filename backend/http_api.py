"""HTTP transport and shared security gates. Endpoint modules cannot bypass gates."""

import http.cookies
import json
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
from errors import DomainError
from http_types import COOKIE, HttpError, RequestContext, RequestData
from routing import PUBLIC, dispatch


class Handler(BaseHTTPRequestHandler):
    server_version = 'JamieNode'
    sys_version = ''

    def log_message(self, *_args):
        pass  # Never log passwords, cookies, card codes, or subscription URLs.

    def reply(self, status, data, token=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if token is not None:
            self.send_header(
                'Set-Cookie',
                f'{COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={604800 if token else 0}',
            )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.handle_api(False)

    def do_POST(self):
        self.handle_api(True)

    def handle_api(self, write):
        try:
            self.route(write)
        except HttpError as exc:
            self.reply(exc.status, {'error': exc.message})
        except DomainError as exc:
            self.reply(400, {'error': str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            # Log only classification; never request data or exception strings.
            print('API error:', type(exc).__name__, flush=True)
            self.reply(503, {'error': '服务暂时不可用，请稍后重试'})

    def read_data(self, app):
        if (
            self.headers.get('Origin') != app.config['origin']
            or self.headers.get('X-Jamie-Request') != '1'
            or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'
        ):
            raise HttpError(403, '请求来源校验失败，请刷新页面')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise HttpError(400, '请求参数不正确') from None
        if not 0 < length <= 16384:
            raise HttpError(413, '请求过大')
        self.connection.settimeout(10)
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            raise HttpError(400, '请求格式不正确') from None
        if not isinstance(data, dict):
            raise HttpError(400, '请求格式不正确')
        return RequestData(data)

    def route(self, write):
        app = self.server.app
        path = urlsplit(self.path).path
        ip = self.headers.get('X-Real-IP', self.client_address[0])
        if not write and path == '/api/health':
            return self.reply(200, {'ok': True})
        app.limit('request:' + ip, 240, 60)
        if not write and path.startswith('/internal/subscription-info/'):
            if self.client_address[0] not in ('127.0.0.1', '::1') or any(
                self.headers.get(h) for h in ('X-Forwarded-For', 'X-Real-IP', 'Forwarded')
            ):
                raise HttpError(404, 'Not found')
            token = path.rsplit('/', 1)[-1]
            if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', token):
                raise HttpError(404, 'Not found')
            return self.reply(200, {'usage': app.subscription_info(token)})
        data = self.read_data(app) if write else RequestData()
        token, account = '', None
        if ('POST' if write else 'GET', path) not in PUBLIC:
            try:
                cookies = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
            except http.cookies.CookieError:
                raise HttpError(401, '请先登录') from None
            token = cookies[COOKIE].value if COOKIE in cookies else ''
            account = app.session(token)
        return dispatch(
            RequestContext(
                app, path, self.path, ip, data, account, token, write, self.headers, self.reply
            )
        )
