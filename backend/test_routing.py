"""Security contract tests independent of business service implementations."""

import ast
import inspect
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from errors import DomainError
from http_api import Handler
from http_types import HttpError, RequestData
from routing import PUBLIC, PASSWORD_CHANGE_ALLOWED, authorize, dispatch
import routes_auth
import routes_account
import routes_subscription
import routes_support
import routes_admin


class RoutingTests(unittest.TestCase):
    def test_all_endpoint_branches_keep_access_guards(self):
        user = {'admin': False, 'must_change': False}
        forced = {'admin': True, 'must_change': True}
        for module in (
            routes_auth,
            routes_account,
            routes_subscription,
            routes_support,
            routes_admin,
        ):
            for branch in ast.walk(ast.parse(inspect.getsource(module.dispatch))):
                if not isinstance(branch, ast.If):
                    continue
                condition = ast.unparse(branch.test)
                paths = [
                    n.value
                    for n in ast.walk(branch.test)
                    if isinstance(n, ast.Constant)
                    and isinstance(n.value, str)
                    and n.value.startswith('/api/')
                ]
                methods = (
                    ['GET']
                    if 'not write' in condition
                    else ['POST']
                    if 'write' in condition
                    else ['GET', 'POST']
                )
                for path in paths:
                    for method in methods:
                        key = method, path
                        if key in PUBLIC:
                            authorize(method, path, None)
                            continue
                        app = Mock()
                        ctx = SimpleNamespace(
                            app=app, write=method == 'POST', path=path, account=None
                        )
                        with self.assertRaises(HttpError) as error:
                            dispatch(ctx)
                        self.assertEqual(error.exception.status, 401)
                        self.assertEqual(app.mock_calls, [])
                        if path.startswith('/api/admin/'):
                            with self.assertRaises(HttpError) as error:
                                authorize(method, path, user)
                            self.assertEqual(error.exception.status, 403)
                        if key not in PASSWORD_CHANGE_ALLOWED:
                            with self.assertRaises(HttpError) as error:
                                authorize(method, path, forced)
                            self.assertEqual(error.exception.status, 403)

    def test_internal_errors_not_misreported_as_user_input(self):
        handler = Handler.__new__(Handler)
        handler.reply = Mock()
        for error, expected in (
            (KeyError('secret'), 503),
            (TypeError('secret'), 503),
            (ValueError('secret'), 503),
            (DomainError('invalid'), 400),
        ):
            handler.route = Mock(side_effect=error)
            with patch('builtins.print'):
                handler.handle_api(False)
            self.assertEqual(handler.reply.call_args.args[0], expected)
            self.assertNotIn('secret', str(handler.reply.call_args))
        with self.assertRaises(DomainError):
            RequestData()['missing']

    def test_bad_json_and_length_are_validation_errors(self):
        handler = Handler.__new__(Handler)
        handler.connection = Mock()
        app = SimpleNamespace(config={'origin': 'https://example.test'})
        for length, body in [('invalid', b'{}'), ('1', b'{'), ('2', b'[]')]:
            handler.headers = {
                'Origin': app.config['origin'],
                'X-Jamie-Request': '1',
                'Content-Type': 'application/json',
                'Content-Length': length,
            }
            handler.rfile = io.BytesIO(body)
            with self.assertRaises(HttpError) as error:
                handler.read_data(app)
            self.assertEqual(error.exception.status, 400)
