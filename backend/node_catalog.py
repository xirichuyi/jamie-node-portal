"""Validated, credential-free node inventory shared by portal and adapter."""

import ipaddress
import json
import re
from urllib.parse import urlsplit
from pathlib import Path

CATALOG_PATH = '/etc/jamie-node-catalog.json'


def validate_catalog(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported node catalog')
    rows = data.get('nodes')
    if not isinstance(rows, list):
        raise ValueError('Invalid node list')
    identifiers, names, endpoints = set(), set(), set()
    groups = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid node')
        for field in ('inbound_id', 'node_id', 'port', 'quota_bytes'):
            if type(row.get(field)) is not int or row[field] <= 0:
                raise ValueError('Invalid node ' + field)
        if row['port'] > 65535 or not ipaddress.ip_address(row['server']).is_global:
            raise ValueError('Expected public node endpoint')
        for field in ('name', 'region', 'quota_group'):
            if (
                not isinstance(row.get(field), str)
                or not row[field].strip()
                or len(row[field]) > 100
            ):
                raise ValueError('Invalid node ' + field)
        if type(row.get('enabled')) is not bool:
            raise ValueError('Invalid node state')
        endpoint = (row['server'], row['port'])
        if row['inbound_id'] in identifiers or row['name'] in names or endpoint in endpoints:
            raise ValueError('Duplicate node identity, name, or endpoint')
        identifiers.add(row['inbound_id'])
        names.add(row['name'])
        endpoints.add(endpoint)
        group = row['quota_group']
        groups[group] = groups.get(group, 0) + row['quota_bytes']
    limits = data.get('quota_groups', {})
    for group, allocated in groups.items():
        limit = limits.get(group)
        if type(limit) is not int or limit <= 0 or allocated > limit:
            raise ValueError('Shared quota exceeded or missing: ' + group)
    return data


def load_catalog(path=CATALOG_PATH):
    return validate_catalog(json.loads(Path(path).read_text()))


def active_nodes(path=CATALOG_PATH):
    return [row for row in load_catalog(path)['nodes'] if row['enabled']]


def service_settings(path=CATALOG_PATH):
    settings = load_catalog(path)['service']
    for key in ('origin', 'probe_url'):
        url = urlsplit(settings[key])
        if (
            url.scheme != 'https'
            or not url.hostname
            or url.username
            or url.password
            or url.fragment
        ):
            raise ValueError('Invalid service URL: ' + key)
    if urlsplit(settings['origin']).path not in ('', '/') or urlsplit(settings['origin']).query:
        raise ValueError('Origin must not contain a path or query')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', settings['title']):
        raise ValueError('Invalid subscription title')
    if not re.fullmatch(r'[A-Za-z0-9.-]+', settings['panel_host']):
        raise ValueError('Invalid panel hostname')
    if not ipaddress.IPv4Address(settings['master_ip']).is_global:
        raise ValueError('Invalid master address')
    return settings
