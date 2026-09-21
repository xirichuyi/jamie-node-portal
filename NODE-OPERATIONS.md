# Dynamic node operations

See [README.md](README.md) for deployment, billing invariants and private-data handling.

## One inventory

`/etc/jamie-node-catalog.json` on the master is the credential-free source of truth.
It records inbound/node IDs, public endpoint, display name, region, account quota
group, allocated bytes, and publication state. It is validated and atomically
replaced, not edited in Python source. SSH/panel/API credentials never go in it.

Consumers load it at runtime:

- Subscription adapter: the current account's real upstream nodes, intersected
  with published catalog endpoints; both Clash and Shadowrocket use the same names.
- Portal node status and admin budgets: names from the catalog, node association
  from the actual inbound's `nodeId` (IDs need not match).
- Portal entitlement worker: new inventory IDs atomically enqueue member revisions
  in the existing database outbox. Billing serialization, retries, and absolute
  entitlements remain the single customer-write path.
- Dedicated connectivity probe and client acceptance script: expected endpoints
  from the catalog, not a fixed count or IP list.

The catalog's `service` object holds `origin`, `panel_host`, `master_ip`, `title`,
and `probe_url`. Subscription metadata, landing links, site/master direct-routing
exceptions and probes read these values; do not edit Python when changing them.
`origin` must also match the portal's private configuration and nginx/DNS setup;
changing this catalog alone does not migrate a domain or provision a certificate.
`title` is the subscription profile/download name. The existing `Jamie-Node`
proxy-group key stays stable to preserve client selections and rule references.
DNS and routing policy defaults, API paths and security checks are deliberate
code-level policy, not per-server inventory or credentials.

The adapter source is now versioned at `deploy/subscription_adapter.py` and shipped
with backend releases, preserving the cycle-billing metadata integration.

## Supported operator workflow

From this checkout:

```sh
python3 deploy/node_manager.py list
python3 deploy/node_manager.py add --ssh SSH_ALIAS --ip PUBLIC_IPV4 \
  --management-port 48180 --port 8443 --name '🇯🇵 日本 · 东京 03' \
  --region 日本 --quota-group ACCOUNT_KEY --quota-tb 0.5 --prepare
```

Use a real OCI account key, not a new group for every server. An existing group
must have unallocated capacity. Registering an existing endpoint with a lower
`--quota-tb` reallocates its slice without resetting counters; then add the new
node. The slice cannot be lower than traffic already counted. New account groups
require an explicit `--group-limit-tb` (normally 9 under the current owner's policy).
This command does not silently increase an existing group limit.

`--prepare` is for NEW root-access Debian nodes without an existing x-ui install.
Management is source-restricted to the master, TLS certificates are pinned,
and the node subscription endpoint is disabled. Small-node service limits are
320 MiB memory and 50% of one CPU; override using `--memory-mib` and `--cpu-percent`
when preparing a new node. These flags do not resize existing deployed nodes.
Existing software and firewall rules are not removed.
The master's SSH HostName must be a public IPv4 literal, or supply `--master-ip`.
The master defaults to `Noether`; select another SSH alias with `--master`.
Cloud security rules must permit the management connection and chosen UDP port;
the tool cannot change OCI cloud rules without OCI authorization.

For already-prepared nodes, omit `--prepare`. Registration is retryable: it reuses
the existing endpoint/inbound, preserves credentials, and does not reset traffic.
An exclusive master-side lock prevents concurrent registration jobs.

Before publishing, registration verifies quota/name uniqueness and uses a short-
lived dedicated account to make a real HY2 request. The test identity is removed.
A failed connectivity test does not publish the endpoint. Prepared panel resources
may remain for diagnosis/retry; it is NOT an all-or-nothing distributed transaction.
If preparation itself was interrupted, inspect the private installation log before
retrying; never rerun a destructive install over an existing panel.

After publication, customer synchronization runs through the portal outbox, usually
starting within 15 seconds. Offline nodes remain pending and retry; no customer
quota, expiry, subscription token, or password is regenerated. Panel-only custom
identities are intentionally not bulk-modified by future onboarding. The dedicated
monitor is explicitly extended after verifying ownership.

Acceptance:

```sh
python3 deploy/verify_clients.py
ssh Noether systemctl start jamie-portal-probe.service
```

Client QA launches an isolated Mihomo, does not alter the OS proxy, and cleans up
temporary credentials. Local TUN routing can affect its upstream network path;
the master-side probe is a separate path, not proof of every user's ISP reachability.

## Limits and recovery

The group budget sums managed VPN inbound allowances. Tokyo and Singapore each
currently use 8 TB + 1 TB slices. Other group allocations are 9 TB. Counters remain
`never` reset; this is not a reconstructed OCI monthly billing counter and excludes
unrelated applications. Do not claim a whole-account monthly billing hard cap.
Do not reset counters or change shared-account grouping without a billing baseline.

Backups are private under `/root/codex-backups/node-register-*`. Restore a catalog
only after checking matching panel IDs/limits; blindly restoring a database can
overwrite newer purchases. Code rollback and live entitlement rollback are separate.
The catalog supports publication state, but a complete node retirement/draining UI
and automatic OCI billing integration are not implemented by this change.

The one-time `migrate_node_catalog.py` contains the historical six-node migration;
it refuses to overwrite an existing catalog. Retired `attach_sanjose.py`,
`expand_nodes.py`, `prepare_sanjose.sh`, `verify_live.py`, and `verify_features.py`
have been removed; their historical implementations remain in Git only.

## Quality checks and remaining work

Tests cover dynamic 1/7/12-node output, unpublished endpoint filtering, duplicate
names/endpoints, private addresses, shared quota overflow, runtime reload, and
idempotent persistent sync scheduling. Existing account/billing tests also run.

This is not a claim of zero bugs. HTTP transport and five domain route groups are
now separated, with shared authorization before dispatch and regression tests.
Remaining architecture work includes strengthening deployment rollback around later nginx
failures, and adding operator UI for inventory lifecycle. Existing readiness
monitoring distinguishes management heartbeat from actual data-plane probes.
