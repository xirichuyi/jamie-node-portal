"""Queue catalog changes through the existing entitlement outbox, never a second writer."""

import json
from node_catalog import active_nodes


def enqueue_catalog(ledger, path):
    ids = sorted(n['inbound_id'] for n in active_nodes(path))
    if not ids:
        raise ValueError('Cannot synchronize an empty node fleet')
    signature = json.dumps(ids)
    with ledger.billing_lock, ledger.transaction() as db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS node_catalog_state (id INTEGER PRIMARY KEY CHECK(id=1), signature TEXT NOT NULL)'
        )
        row = db.execute('SELECT signature FROM node_catalog_state WHERE id=1').fetchone()
        if row and row['signature'] == signature:
            return 0
        count = db.execute('UPDATE members SET revision=revision+1 WHERE deleting=0').rowcount
        db.execute('INSERT OR REPLACE INTO node_catalog_state VALUES(1,?)', (signature,))
        ledger.audit(db, 'system', 'nodes.catalog_sync', signature)
    return count
