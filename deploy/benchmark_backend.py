"""Local synthetic benchmark only. Never reads production data or uses network."""

import json
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))
from server import App


def run():
    with tempfile.TemporaryDirectory(prefix='jamie-benchmark-') as directory:
        app = App(
            {
                'database': str(Path(directory) / 'benchmark.db'),
                'origin': 'https://example.test',
                'package_billing': True,
            },
            object(),
        )
        now = int(time.time())
        with app.ledger.transaction() as db:
            for i in range(500):
                uid = f'benchmark_{i:04}'
                db.execute(
                    """INSERT INTO members(id,panel_email,panel_auth,sub_id,quota,expires,
                    revision,synced_revision,created) VALUES(?,?,?,?,?,?,1,1,?)""",
                    (uid, uid, 'not-a-credential', uid, 1000, now + 86400, now - i),
                )
                db.execute('INSERT INTO accounts VALUES(?,?,?,0,0)', (uid, uid, 'not-a-password'))
                db.execute(
                    'INSERT INTO billing_accounts(member_id,raw,sampled) VALUES(?,0,?)', (uid, now)
                )
                for j in range(20):
                    db.execute(
                        """INSERT INTO entitlement_packages
                        (id,member_id,kind,label,granted,spent,created,expires)
                        VALUES(?,?,'base','Synthetic',100,20,?,?)""",
                        (f'{uid}_{j}', uid, now - 100000, now - 100 if j < 10 else now + 86400 + j),
                    )
        app.users.sample = {
            'at': int(time.time()),
            'values': {f'benchmark_{i:04}': 0 for i in range(500)},
            'error': None,
        }
        original = app.ledger.connect
        counters = {'connections': 0, 'selects': 0}

        @contextmanager
        def counted():
            counters['connections'] += 1
            with original() as db:

                def trace(sql):
                    if sql.lstrip().upper().startswith(('SELECT', 'WITH')):
                        counters['selects'] += 1

                db.set_trace_callback(trace)
                yield db

        app.ledger.connect = counted
        result = {}
        for name, fn in [
            ('listing', lambda: app.users.listing({})),
            ('detail', lambda: app.users.detail('benchmark_0250')),
        ]:
            timings = []
            for _ in range(5):
                counters.update(connections=0, selects=0)
                start = time.perf_counter()
                value = fn()
                timings.append((time.perf_counter() - start) * 1000)
            result[name] = {
                'median_ms': round(statistics.median(timings), 2),
                **counters,
                'response_bytes': len(json.dumps(value).encode()),
            }
        print(json.dumps({'users': 500, 'packages': 10000, 'results': result}))


if __name__ == '__main__':
    run()
