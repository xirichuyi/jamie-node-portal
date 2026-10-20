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

### Quick onboarding

Run `npm run node:add` in this checkout. The wizard asks for the public IPv4,
SSH port, allocated TCP/UDP ports, display name and region. OpenSSH handles the
password/key and first host-key confirmation; no password is stored by the wizard.
The master defaults to the existing `Noether` SSH alias. For an existing node:

```sh
npm run node:add -- --ssh ck46
npm run node:add -- --ssh ck46 --check --yes
```

For a new NAT node, parameters can also be supplied directly:

```sh
npm run node:add -- --host PUBLIC_IPV4 --ssh-port SSH_PORT \
  --ports 21225-21229 \
  --name '🇯🇵 日本 · 东京 04' --region 日本
```

Supplied/saved parameters are used without repeated confirmation even in
password-login mode (do not add `--yes` just to skip redundant prompts).
The preflight also reads the non-secret OCI region metadata. Known regions
provide country/city names and the next unused display number, so `--name` and
`--region` can be omitted. Explicit names take precedence; unknown/unavailable
metadata still requires a name and region rather than guessing from GeoIP.

`--ports` is the provider's allocated range; the wizard excludes the SSH port,
then chooses separate management and proxy TCP ports. Split allocations can still
use `--tcp-ports` and `--udp-ports`. Inventory matching uses the supplied allocation
or saved proxy port, so separate NAT containers sharing a public IP are not merged.
New endpoints with a non-22 SSH port default
to VLESS REALITY TCP, avoiding the failed-HY2/manual-migration cycle seen with
128 MiB NAT containers. Use `--protocol vless` for TCP on a dedicated host or
`--protocol hysteria` when UDP is deliberately requested. Auto mode preserves
existing catalog protocols and saved retry profiles; it does not migrate them.
NAT allocations must be provided explicitly; the wizard never assumes public
48180/8443 forwarding for a fresh NAT host.

New TCP installations use Xray 26.6.27, verified against the official SHA256
digest, with the prior binary backed up privately. A fresh-install marker allows
retrying an interrupted core download. Existing unmarked installations with a
different core are rejected rather than automatically downgraded. Registration
creates REALITY keys once and probes with a temporary, matching VLESS UUID before
publishing; failed probes preserve installation/inbound state but do not publish.
Retries reuse keys, inbound IDs and counters. No staged catalog or manual TCP
migration script is needed for new TCP nodes.

Passwords are entered directly into OpenSSH, never passed in flags or saved.
An authentication failure is not an installation failure: confirm the root
username/password with the provider before retrying. Do not repeatedly install
or change firewall settings to troubleshoot rejected SSH credentials.

The wizard reads the inventory before connecting to the target (retired nodes are
rejected), checks root access, OS/architecture, cgroup memory and occupied ports,
and chooses unused ports only from the supplied allocation. For dedicated servers,
default management/proxy ports are 48180/TCP and 8443/UDP; NAT allocations must be
entered explicitly. It bootstraps dependencies on new Alpine/Debian/Ubuntu hosts,
reuses a complete existing installation and refuses to overwrite partial installs.
The final step checks publication, the dedicated monitor's subscription, catalog
observation, this node's member binding coverage and aggregate member-sync progress;
it also names other active offline nodes, excluding retired nodes. Complete local
binding coverage is not a claim that global entitlement synchronization completed.
It refreshes the normal probe and
reports the latest timestamped connectivity result separately. Pending sync is not
reported as completed. If Clash Verge is installed locally, it also runs isolated
Mihomo verification for the selected node after publication; a local failure is
reported separately from the master's pre-publication probe, without modifying the
OS proxy or withdrawing an otherwise working endpoint. Recheck with
`python3 deploy/verify_clients.py --node PUBLIC_IPV4`.
Cloud/NAT forwarding cannot be provisioned by this tool.

This quick path creates NEW nodes with no aggregate traffic cap, as requested for
small rented nodes; existing capped nodes retain their allocation. Use the advanced
command below for new shared-account/capped nodes. User billing always stays enabled.
Without `--publish-unverified`, a failed new-node probe still blocks publication.
The flag is never saved as a default. Already-published endpoints retain publication
and are checked without recreating their inbounds or credentials.

Non-secret parameters are saved under `~/.config/jamie-node/nodes/` (mode 0600).
Rerun with the same SSH alias or host/port to reuse them. `--yes` uses supplied/saved
values without prompts and requires established SSH trust and key/agent login.
`--check` performs read-only remote checks and does not save a profile. A failed
installation is preserved for diagnosis, not blindly rerun. Password-only retries
may require entering the password again; each run multiplexes its SSH connection.

### Advanced registration

From this checkout:

```sh
python3 deploy/node_manager.py list
python3 deploy/node_manager.py add --ssh SSH_ALIAS --ip PUBLIC_IPV4 \
  --management-port 48180 --port 8443 --name '🇯🇵 日本 · 东京 03' \
  --region 日本 --quota-group ACCOUNT_KEY --quota-tb 0.5 --prepare
```

The advanced command also accepts `--protocol vless`; unlike the wizard it does
not infer NAT transport from SSH port. For existing nodes, omission preserves the
catalog protocol, and an explicitly conflicting protocol is rejected.

Use a real OCI account key, not a new group for every server. An existing group
must have unallocated capacity. Registering an existing endpoint with a lower
`--quota-tb` reallocates its slice without resetting counters; then add the new
node. The slice cannot be lower than traffic already counted. New account groups
require an explicit `--group-limit-tb` (normally 9 under the current owner's policy).
This command does not silently increase an existing group limit.

`--prepare` is for NEW root-access Debian or Alpine nodes without an existing x-ui install.
Alpine requires bash before invoking the helper, uses OpenRC and a dedicated nft
table, and sets Go GC/heap targets (24 MiB per Go process, not a hard RSS limit).
The Debian memory/CPU flags do not impose cgroup limits on Alpine. Verify actual
RSS, cgroup pressure, OOM counters, and connectivity before publication.
Management is source-restricted to the master, TLS certificates are pinned,
and the node subscription endpoint is disabled. Small-node service limits are
320 MiB memory and 50% of one CPU; override using `--memory-mib` and `--cpu-percent`
when preparing a new node. These flags do not resize existing deployed nodes.
Existing software and firewall rules are not removed.
For nodes whose aggregate traffic is intentionally uncapped, use `--unlimited`
instead of `--quota-tb`, with a separate quota group. Both catalog allocation and
group limit are explicitly zero; limited and unlimited nodes cannot share a group.
Only the node aggregate cap is removed. Customer package accounting, expiration,
and disable operations remain unchanged. Never convert an existing limited group
to unlimited to bypass its cap.
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
may be explicitly published by the operator with `--publish-unverified` when
unverified availability is accepted. This still runs the probe, reports its real
result, and preserves monitoring and customer billing/sync. It does not certify
the endpoint as working. The default remains to block publication on probe failure.
Prepared panel resources may remain for diagnosis/retry; this is not an
all-or-nothing distributed transaction.
If preparation itself was interrupted, inspect the private installation log before
retrying; never rerun a destructive install over an existing panel.

After publication, customer synchronization runs through the portal outbox, usually
starting within 15 seconds. Offline nodes remain pending and retry; no customer
quota, expiry, subscription token, or password is regenerated. Panel-only custom
identities are intentionally not bulk-modified by future onboarding. The dedicated
monitor is explicitly extended after verifying ownership.

First-time subscriptions become available once at least one active node is enabled,
online, running, freshly reported and configuration-clean after the master identity
and entitlement are verified. `ready_revision` does not advance `synced_revision`:
remaining nodes keep retrying. Credential rotation remains blocked until full sync.
Retries avoid rewriting unchanged master entitlements so reconciliation can finish.

Acceptance:

```sh
python3 deploy/verify_clients.py
ssh Noether systemctl start jamie-portal-probe.service
```

Client QA launches an isolated Mihomo, does not alter the OS proxy, and cleans up
temporary credentials. Local TUN routing can affect its upstream network path;
the master-side probe is a separate path, not proof of every user's ISP reachability.

## Limits and recovery

Frankfurt onboarding (2026-10-18): Nezha UUIDs
confirmed `euler` = `130.61.20.99`, `riemann` = `92.5.101.54`, and
`leibniz` = `141.147.45.180`; root SSH accepts the operator's existing local key.
OCI metadata places all three in the same compartment in `eu-frankfurt-1`.
The shared `德国` group is 9 TB, allocated 7/1/1 TB respectively.
Published node/inbound IDs are 10/10, 11/11 and 12/12, named
`🇩🇪 德国 · 法兰克福 01`, `02` and `03`. Each passed the registration proxy probe.
Management uses 48180/TCP restricted to Noether (`138.2.82.194`), with 8443/UDP
for HY2. OCI NSG `jamie-node-frankfurt` is attached to these three VNICs; it permits
48180/TCP only from the master and 8443/UDP from clients. Existing security-list
rules are preserved. Future nodes in this VCN can reuse this NSG and ports.
Do not rerun preparation over these installed panels; use `node_manager.py add`
without `--prepare` for registration updates. Root SSH uses the existing local
key; no private SSH key was uploaded to these nodes.
All 35 members completed outbox synchronization with zero pending/errors; the
dedicated master probe and isolated local Mihomo passed all three endpoints.
Clash/Shadowrocket metadata and formats passed. Point-in-time workstation
Cloudflare downloads were only 0.46/0.94/0.50 Mbps, each timing out at 45 seconds
before completing 10 MB. Direct 3 MB downloads on the nodes completed at about
237/182/147 Mbps respectively. This suggests the slow path is specific to the
end-to-end proxy route, not evidence of a general server download limit; do not
advertise these nodes as high-speed based on connectivity alone.

The Alpine `ck46` node (`158.101.142.111`, SSH alias `ck46`) has management
TLS on TCP 21226 and managed VLESS + REALITY on TCP 21227. Public UDP failed
while an SSH relay into the HY2 listener worked, so the node was migrated to TCP.
Do not rerun `--prepare` or the HY2 registration command on this machine.
The existing-node wizard recognizes its catalog protocol and preserves TCP.

Management connectivity alone does not prove this node is usable. Registration
keeps it out of subscriptions until the probe passes unless the operator explicitly
uses `--publish-unverified`; this override was requested for ck46.
ck46 was originally published as `🇯🇵 日本 · 东京 03` (node/inbound 7), with aggregate
traffic uncapped. The TCP migration preserves the inbound ID, member bindings and
counters, and verifies a dedicated monitoring account's proxy request before
publishing. Both the panel Host advertisement and the catalog must use TCP 21227;
changing only the inbound leaves the old advertised port in subscriptions.
Subscriptions and probes support mixed pinned HY2 and VLESS REALITY nodes.
New member provisioning and credential rotation also populate/rotate the VLESS UUID.
ck46 pins Xray 26.6.27: 26.9.9 passed Xray probes but rejected installed Mihomo
1.19.13 even with an explicit REALITY minimum client version. The official 26.6.27
ARM64 archive checksum was verified before replacement; both master Xray and local
Mihomo now pass actual proxy requests. Do not auto-upgrade this core without both
checks. The previous binary is privately backed up on ck46. Standalone HY2 is
stopped and removed from OpenRC startup; its configuration is retained.

2026-10-14: unreachable ck46 was replaced by ck20 for `🇯🇵 日本 · 东京 03`.
Current node/inbound IDs are 8/8; public address `150.230.221.141`, SSH mapping
`21095 -> 22`, management TLS `21096`, VLESS REALITY TCP `21097`.
No local SSH alias is required. This Alpine ARM64 NAT container has a 128 MiB
cgroup memory limit; host-level `free`/`df` output is not its resource allocation.
Management is restricted to Noether and loopback. Xray remains pinned to 26.6.27.
Master Xray and isolated local Mihomo proxy checks passed before publication.
Node 7 is disabled and excluded from subscriptions; its bindings and historical
traffic remain for accounting. Node 8 uses the normal entitlement outbox, retains
customer package billing, and has no aggregate node cap (`ck20-unlimited`).
Private pre-switch backups are in `/root/codex-backups/replace-tokyo03-355_1zh9`
on Noether. Do not restore those databases over later customer transactions.

ck28 was added on 2026-10-14 as `🇯🇵 日本 · 大阪 01` (node/inbound 9/9):
public IP `217.142.245.51`, SSH `21135 -> 22`, management TLS `21136`,
VLESS REALITY TCP `21137`. It is another 128 MiB Alpine ARM64 NAT container.
The onboarding script's HY2 probe failed and correctly withheld publication;
the existing TCP migration helper was then used against a staged catalog, with
Xray 26.6.27 and independent Mihomo validation before publishing. UDP packet
reachability alone did not establish HY2 usability. Keep its TCP transport when
rerunning the wizard; the saved host/port profile supports `--check` without aliases.
Its aggregate node quota is unlimited; customer package billing remains enabled.
Two 20 MB proxy downloads measured 36.85–41.57 Mbps from the operator workstation;
these are point-in-time end-to-end measurements, not a guaranteed line rate.

ck24 was added on 2026-10-20 as `🇲🇽 墨西哥 · 克雷塔罗 01` (node/inbound 13/13).
OCI metadata reports `mx-queretaro-1`; public IP `159.54.136.182`, SSH
`21115 -> 22`, management TLS `21116`, VLESS REALITY TCP `21117`.
It is a 128 MiB Alpine ARM64 NAT container. The initial HY2 probe failed and
withheld publication. The existing TCP migration helper was used with a staged
catalog; master Xray and isolated local Mihomo requests both passed before the
live catalog was updated. Xray is pinned to 26.6.27, with the official archive's
SHA256 verified; the prior binary is privately backed up on the node.
Keep its TCP transport and do not rerun preparation. The host/port onboarding
profile is saved locally. Aggregate traffic is unlimited (`ck24-unlimited`);
customer entitlements continue through the normal billing/outbox path.

ck42 was added through `npm run node:add` on 2026-10-20 as
`🇨🇦 加拿大 · 蒙特利尔 01` (node/inbound 14/14). OCI metadata reports
`ca-montreal-1`; public IP `147.15.146.142`, SSH `21205 -> 22`,
management TLS `21206`, VLESS REALITY TCP `21207`.
This 128 MiB Alpine ARM64 NAT container used the direct TCP onboarding path,
including the verified Xray 26.6.27 pin and a successful pre-publication proxy
probe. The final isolated local Mihomo check also passed, and all 36 customer
identities were bound. Global sync remained pending while Osaka was offline;
this is distinct from ck42's own healthy configuration and connectivity.
No manual transport migration or staged catalog was needed.
Its aggregate quota group is `unlimited-147-15-146-142`; customer billing remains
enabled. Reuse its saved host/SSH-port profile and do not rerun preparation.

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

For a sold/retired machine: stop its master-side tunnel, back up the catalog and
databases, disable the node through the panel API, then atomically set catalog
`enabled=false`. Never reconnect to a sold machine or bypass changed SSH host keys.
Keep historical bindings/counters for billing; do not delete inbounds to clear a warning.
Customer updates target active inbound IDs only. Retired nodes are excluded from
publication and sync completion. This cannot erase credentials on the sold machine;
credential rotation is a separate operation requiring client subscription updates.

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
