"""Read-only target status; unrelated offline nodes never gate onboarding."""

import base64
import json
from pathlib import Path
import sqlite3
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, '/opt/jamie-portal/current/backend')
from node_catalog import load_catalog
from panel import Panel


def run(target):
    if target.get('owner'):
        panel = Panel(json.loads(Path('/etc/jamie-portal.json').read_text()))
        owners = [n['id'] for n in panel.request('nodes/list')
                  if n['address'] == target['management_ip'] and n['port'] == target['management_port']]
        return {'owner_ids': owners}
    catalog = load_catalog()
    row = next((n for n in catalog['nodes']
                if (n['server'], n['port']) == (target['ip'], target['port'])), None)
    result = {'published': bool(row and row['enabled']), 'subscription_present': False}
    if not row:
        return result
    result['name'] = row['name']
    panel = Panel(json.loads(Path('/etc/jamie-portal.json').read_text()))
    nodes = panel.request('nodes/list')
    node = next((n for n in nodes if n['id'] == row['node_id']), {})
    result['management_online'] = node.get('status') == 'online'
    result['configuration_clean'] = not node.get('configDirty', True) and not node.get('lastError')
    with sqlite3.connect('file:/var/lib/jamie-portal/portal.db?mode=ro', uri=True) as db:
        signature = db.execute('SELECT signature FROM node_catalog_state WHERE id=1').fetchone()
        result['catalog_observed'] = bool(signature and row['inbound_id'] in json.loads(signature[0]))
        counts = db.execute('SELECT COUNT(*), COALESCE(SUM(revision>synced_revision),0), '
                            'COALESCE(SUM(sync_error IS NOT NULL),0) FROM members WHERE deleting=0').fetchone()
        result.update(members=counts[0], sync_pending=counts[1], sync_errors=counts[2])
        expected = {entry[0] for entry in db.execute(
            'SELECT panel_email FROM members WHERE deleting=0 AND (quota>0 OR synced_revision>0)')}
    inbound = panel.request('inbounds/get/' + str(row['inbound_id']))
    settings = inbound['settings']
    settings = json.loads(settings) if isinstance(settings, str) else settings
    bound = {client['email'] for client in settings.get('clients', [])}
    result.update(node_members_expected=len(expected), node_members_bound=len(expected & bound))
    offline_ids = {entry['id'] for entry in nodes if entry.get('status') != 'online'}
    result['other_offline_nodes'] = [entry['name'] for entry in catalog['nodes']
                                    if entry['enabled'] and entry['node_id'] != row['node_id']
                                    and entry['node_id'] in offline_ids]
    # Dedicated monitor only; never fetch a customer subscription for acceptance.
    try:
        identity = json.loads(Path('/var/lib/jamie-portal/probe-identity.json').read_text())
        url = catalog['service']['origin'].rstrip('/') + '/sub/' + identity['sub_id']
        request = urllib.request.Request(url, headers={'User-Agent': 'Shadowrocket/Onboarding'})
        with urllib.request.urlopen(request, timeout=15) as response:
            lines = base64.b64decode(response.read(1024 * 1024), validate=True).decode().splitlines()
        endpoints = {(u.hostname, u.port) for u in map(urllib.parse.urlsplit, lines)}
        result['subscription_present'] = (target['ip'], target['port']) in endpoints
    except Exception:
        result['subscription_error'] = 'monitor_subscription_unavailable'
    try:
        probe = json.loads(Path('/var/lib/jamie-portal/connectivity.json').read_text())
        entry = next(n for n in probe['nodes'] if n['server'] == target['ip'] and n['name'] == row['name'])
        result.update(connectivity_ok=entry['ok'], connectivity_checked_at=probe['checked_at'])
    except (OSError, ValueError, KeyError, StopIteration):
        result['connectivity_ok'] = None
    return result


if __name__ == '__main__':
    try:
        print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status_error': type(exc).__name__}))
        raise SystemExit(1) from None
