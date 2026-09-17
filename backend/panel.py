"""Loopback-only 3x-ui API client. TLS uses the panel certificate's IP SAN."""

import json
import http.client
import socket
import urllib.request
import urllib.parse


class LoopbackTLS(http.client.HTTPSConnection):
    def connect(self):
        sock = socket.create_connection(('127.0.0.1', self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class LoopbackHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(LoopbackTLS, req, context=self._context)


class Panel:
    def __init__(self, config):
        self.base = config['panel_url'].rstrip('/') + '/panel/api/'
        self.token = config['panel_token']
        self.inbounds = config.get('inbounds', [1, 2, 3])
        # No proxy environment routing for local administrative calls.
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), LoopbackHTTPSHandler()
        )

    def request(self, path, payload=None):
        req = urllib.request.Request(
            self.base + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'},
        )
        with self.opener.open(req, timeout=15) as response:
            result = json.load(response)
        if result.get('success') is not True:
            raise RuntimeError('Panel rejected operation')
        return result.get('obj')

    def get(self, email):
        return self.request('clients/get/' + urllib.parse.quote(email, safe=''))

    def remove(self, member):
        email = member['panel_email']
        if not any(c['email'] == email for c in self.request('clients/list')):
            return
        current = self.get(email)
        if current['client']['subId'] not in {
            member['sub_id'],
            member.get('previous_sub_id'),
        } or current['client']['auth'] not in {
            member['panel_auth'],
            member.get('previous_panel_auth'),
        }:
            raise RuntimeError('Panel identity mismatch')
        self.apply(member)  # Revoke access before removal; pending nodes cause retry.
        result = self.request(
            'clients/del/' + urllib.parse.quote(email, safe='') + '?keepTraffic=0', {}
        )
        if result and result.get('nodePending'):
            raise RuntimeError('Node deletion pending')
        if any(c['email'] == email for c in self.request('clients/list')):
            raise RuntimeError('Panel deletion verification failed')

    def apply(self, member):
        email = member['panel_email']
        enabled = not bool(member['disabled'] or member.get('billing_blocked', False))
        # Listing is used to distinguish absence from a failed read. Never turn
        # a network/auth failure into an attempted create.
        exists = any(c['email'] == email for c in self.request('clients/list'))
        current = self.get(email) if exists else None
        accepted_ids = {member['sub_id']}
        if member.get('previous_sub_id'):
            accepted_ids.add(member['previous_sub_id'])
        accepted_auth = {member['panel_auth']}
        if member.get('previous_panel_auth'):
            accepted_auth.add(member['previous_panel_auth'])
        if current and (
            current['client']['subId'] not in accepted_ids
            or current['client']['auth'] not in accepted_auth
        ):
            raise RuntimeError('Panel identity does not belong to this portal member')
        client = dict(current['client']) if current else {}
        # ClientRecord.id is an integer DB key; Client.id is a UUID string.
        client.pop('id', None)
        if client.get('uuid'):
            client['id'] = client.pop('uuid')
        client.pop('allowedIPs', None)
        client.update(
            email=email,
            auth=member['panel_auth'],
            subId=member['sub_id'],
            totalGB=member['quota'],
            expiryTime=0 if member['expires'] >= 253402185600 else member['expires'] * 1000,
            enable=enabled,
            group='Jamie-Node',
            trafficReset='never',
            trafficResetDay=1,
            reset=0,
            resetDay=0,
            resetMax=0,
        )
        missing = set(self.inbounds) - set(current['inboundIds'] if current else [])
        if missing:
            result = self.request('clients/add', {'client': client, 'inboundIds': sorted(missing)})
            if result and result.get('nodePending'):
                raise RuntimeError('Node update pending')
        if exists:
            result = self.request('clients/update/' + urllib.parse.quote(email, safe=''), client)
            if result and result.get('nodePending'):
                raise RuntimeError('Node update pending')
        verified = self.get(email)
        c = verified['client']
        if (
            c['subId'] != member['sub_id']
            or c['auth'] != member['panel_auth']
            or c['enable'] != enabled
            or c['totalGB'] != member['quota']
            or c['expiryTime']
            != (0 if member['expires'] >= 253402185600 else member['expires'] * 1000)
            or not set(self.inbounds).issubset(verified['inboundIds'])
        ):
            raise RuntimeError('Panel entitlement verification failed')
