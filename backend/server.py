#!/usr/bin/env python3
"""Loopback server bootstrap; HTTP policies and business services live separately."""

import argparse
import json
import os
import secrets
import sqlite3
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from application import App as App
from http_api import Handler
from http_types import COOKIE as COOKIE, HttpError as HttpError
from passwords import (
    PASSWORD_COST as PASSWORD_COST,
    hash_password as hash_password,
    verify_password as verify_password,
)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app):
        self.app = app
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        super().process_request(request, address)

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/jamie-portal.json')
    parser.add_argument('--bootstrap-admin', action='store_true')
    parser.add_argument('--backup')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    app = App(config)
    if args.backup:
        with app.ledger.connect() as src:
            dst = sqlite3.connect(args.backup)
            src.backup(dst)
            dst.close()
        return
    if args.bootstrap_admin:
        with app.ledger.connect() as db:
            if db.execute('SELECT 1 FROM accounts WHERE admin=1').fetchone():
                raise SystemExit('Admin already exists; no changes made')
        password = secrets.token_urlsafe(20)
        app.register('jamie', password, admin=True)
        print(json.dumps({'username': 'jamie', 'password': password}))
        return
    threading.Thread(target=app.sync_loop, daemon=True).start()
    threading.Thread(target=app.monitor.run, daemon=True).start()
    threading.Thread(target=app.features.loop, daemon=True).start()
    Server(('127.0.0.1', config.get('port', 18766)), app).serve_forever()


if __name__ == '__main__':
    main()
