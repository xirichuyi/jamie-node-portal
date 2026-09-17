import datetime
import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path


def verify_restore(source, directory):
    with closing(sqlite3.connect('file:' + str(source) + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup integrity check failed')
        with tempfile.TemporaryDirectory(prefix='restore-check-', dir=directory) as work:
            restored = sqlite3.connect(str(Path(work) / 'restored.db'))
            try:
                db.backup(restored)
                if (
                    restored.execute('PRAGMA integrity_check').fetchone()[0] != 'ok'
                    or restored.execute('PRAGMA foreign_key_check').fetchone()
                ):
                    raise RuntimeError('Restored database validation failed')
                counts = {}
                tables = (
                    'accounts',
                    'members',
                    'cards',
                    'audit',
                    'billing_accounts',
                    'entitlement_packages',
                    'billing_events',
                )
                for table in tables:
                    if not db.execute(
                        'SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (table,)
                    ).fetchone():
                        continue
                    count = restored.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                    if count != db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]:
                        raise RuntimeError('Restored row count mismatch')
                    counts[table] = count
                if restored.execute(
                    'SELECT COUNT(*) FROM accounts a LEFT JOIN members m ON m.id=a.id WHERE m.id IS NULL'
                ).fetchone()[0]:
                    raise RuntimeError('Restored account relationship check failed')
                return counts
            finally:
                restored.close()


def run(root):
    os.umask(0o077)
    root = Path(root)
    backups = root / 'backups'
    backups.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = backups / (stamp + '.db')
    with closing(
        sqlite3.connect('file:' + str(root / 'portal.db') + '?mode=ro', uri=True)
    ) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
    counts = verify_restore(target, backups)
    result = {
        'verified_at': int(time.time()),
        'restore_verified': True,
        'file': target.name,
        'counts': counts,
        'scope': 'isolated_sqlite_restore',
        'offsite': False,
    }
    temporary = backups / ('verification-' + stamp + '.tmp')
    temporary.write_text(json.dumps(result))
    os.replace(temporary, backups / 'verification.json')
    print('Portal backup and isolated database restore verified')
    return result


if __name__ == '__main__':
    run('/var/lib/jamie-portal')
