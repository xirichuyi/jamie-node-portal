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

Run `npm run node:add` in this checkout. `deploy/onboard.py` is the only public
entry point; implementation and installer assets live together in `deploy/nodes/`.
The wizard asks for the public IP,
SSH port, allocated TCP/UDP ports, display name and region. OpenSSH handles the
password/key and first host-key confirmation; no password is stored by the wizard.
The master defaults to the existing `Noether` SSH alias. For an existing node:

```sh
npm run node:add -- --ssh ck46
npm run node:add -- --ssh ck46 --check --yes
```

Add IPv6 HY2 to an existing managed machine, preserving its other protocol:

```sh
npm run node:add -- --host PUBLIC_IP --add-protocol --protocol hy2 --ipv6
```

The tool discovers the public IPv6 address (use `--endpoint` if more than one),
keeps SSH/management addresses independent, reuses the installed panel, selects a
free protocol port and assigns the next region/city number. Public names never
gain a protocol or IP-family suffix. HY2/reality aliases are accepted. A capped
existing inbound contributes half of its cap by default, or `--quota-tb` selects
the slice. The original group limit and historical counters stay unchanged. Capacity
is reserved before adding the inbound; a failed probe leaves the reduced donor cap
and an unpublished inbound for safe retry with the saved allocation. This is not
an all-or-nothing distributed transaction. Retrying never halves the cap again.
IPv6 registrations use local Mihomo/Clash Verge for a real pre-publication check
by default, so an IPv4-only master does not block the node. `--probe-origin master`
selects the master explicitly; `--interface` selects the local physical interface.
Known subscription adapter layouts are patched narrowly to enable IPv6 connections,
preserving live routing; unknown layouts fail without overwriting them.

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
The final step checks only the target's publication, dedicated monitor subscription,
management readiness and binding coverage. Other offline nodes and global pending
counts are not completion gates and no fleet probe is started. Account synchronization
continues through the normal entitlement worker; pending bindings are reported honestly.
Default synchronization wait is zero; `--wait-seconds N` optionally waits for this
target only. Local Mihomo verification connects only to the selected endpoint, without
modifying the OS proxy. Repeating the same command verifies/reuses the existing node;
`--check` provides read-only status without installation, publication or profile writes.
Cloud/NAT forwarding cannot be provisioned by this tool.

This quick path creates NEW nodes with no aggregate traffic cap, as requested for
small rented nodes; existing capped nodes retain their allocation. Use the advanced
command below or the wizard's `--quota-group`, `--quota-tb`, `--group-limit-tb`
options for new shared-account/capped nodes. User billing always stays enabled.
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
npm run node:add -- list
npm run node:add -- advanced add --ssh SSH_ALIAS --ip PUBLIC_IPV4 \
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

Optional fleet acceptance (not part of node onboarding; unrelated offline nodes
must not block adding a node):

```sh
python3 tools/verify_clients.py
ssh Noether systemctl start jamie-portal-probe.service
```

Client QA launches an isolated Mihomo, does not alter the OS proxy, and cleans up
temporary credentials. Local TUN routing can affect its upstream network path;
the master-side probe is a separate path, not proof of every user's ISP reachability.

## Limits and recovery

### InstaBox published HTTPS ports

InstaBox has IPv4 NAT egress and global IPv6, but raw TCP/UDP ingress was not
reachable in the initial external check. Its official `POST /v1/machines/{id}/ports`
API publishes HTTPS URLs; HTTP and WebSocket echo were both verified. Use VLESS
WebSocket with platform TLS, without relaying customer traffic through Noether.
Do not run the IPv4/REALITY onboarding wizard against these public HTTPS URLs.

`npm run node:add -- instabox` reuses the pinned node preparation and transactional
registration helpers. Set `INSTABOX_API_KEY` privately in the environment, then run
`prepare --names instabox-1` and `register --names instabox-1` after deploying the
WebSocket-capable backend and adapter. Multiple explicitly named machines are
processed sequentially. Preparation refuses partial installs; registration retries
reuse inbound identity, path, counters and customer outbox processing.

Each machine publishes 8080 for VLESS WebSocket and 48181 for management. The latter
is an API-only bridge that requires the node's bearer token before forwarding to
the local pinned-TLS panel on 48180. It does not expose the panel UI or subscription.
Direct 48180 retains the existing loopback/master-source firewall. Platform-facing
TLS uses public CA verification, not a pin to the provider's rotating certificate.
The catalog accepts the provider's exact port-machine hostname format; arbitrary
DNS names cannot bypass the existing public-address validation.

No lifecycle settings are changed and no artificial keepalive jobs are installed.
Paused machines interrupt connections. Free-machine availability and provider
traffic allowances must not be represented as a permanent service guarantee.
Node aggregate quotas are separate from unchanged customer package billing.

On 2026-10-23, `instabox-1` through `instabox-5` were registered as node/inbound
15 through 19. All five passed the master Xray probe and an isolated workstation
Mihomo request using the dedicated monitoring subscription. Observed IPv4 exits
were 35.90.59.10, 35.90.32.199, and 54.191.15.212 (shared by machines 3–5).
The published catalog names are `🇺🇸 美国 · 俄勒冈 01` through `05`, mapped
in order to platform machines `instabox-1` through `instabox-5`. AWS's published
IP ranges place all three observed exits in `us-west-2` (Oregon). Platform machine
names remain the operational identifiers; preserve the catalog display names
when re-registering. Both Clash and Shadowrocket read these names at runtime.
These are observations, not dedicated-IP or static-IP guarantees. The provider
rewrites HTTP Host on ingress; keep the guest WebSocket host unset and match its
stable path, while clients validate TLS/SNI against the public provider hostname.

The 2026-10-23 checkout predates live portal/routing fixes from 2026-10-22.
The live rollout preserves that production baseline and changes only the three
transport/catalog modules plus the VLESS conversion block in the live adapter.
Do not overwrite those live fixes with this checkout. Full deployment now checks
the server against both local HEAD and working files and rejects unresolved drift.

## Existing node recovery notes

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
Do not rerun preparation over these installed panels; use `npm run node:add -- advanced add`
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

ck26 was added through `npm run node:add` on 2026-10-23 as
`🇮🇱 以色列 · 耶路撒冷 01` (node/inbound 20/20). OCI metadata reports
`il-jerusalem-1`; public IP `82.70.223.52`, SSH `21125 -> 22`, management
TLS `21126`, VLESS REALITY TCP `21127`, within the allocated `21125-21129` range.
It is an Alpine ARM64 container with a 128 MiB cgroup memory limit; host `df`
output does not establish its advertised 512 MiB container disk allowance.
The existing onboarding workflow installed the pinned Xray core and passed the
master probe before publication. All 38 customer bindings are present and node
configuration is clean. Independent workstation Mihomo over the physical interface
passed HTTP 204 and confirmed the IL exit; Clash and Shadowrocket names/endpoints
also passed. Global synchronization still reports 38 pending/errors while the
existing Osaka node is offline; ck26 itself is online and synchronized.
The temporary standalone client check must serialize Unicode names with
`ensure_ascii=False` (or YAML), since Mihomo's YAML reader rejects JSON surrogate
escapes for flag emoji. Reuse the saved host/SSH-port profile without preparation;
aggregate quota is unlimited, with normal customer package billing preserved.

On 2026-10-24, cauchy (`168.138.218.181`) and laplace (`168.110.35.217`)
were added as `🇯🇵 日本 · 东京 04` and `🇯🇵 日本 · 东京 05` (node/inbound
21/21 and 22/22). Both are Debian 12 AMD64, accept the operator's existing
local SSH key as root on port 22, and report OCI `ap-tokyo-1` in the same
compartment. The explicitly requested pair budget is 8 TB: runtime quota group
`oci-tokyo-95272271-pair` has an 8,000,000,000,000-byte limit, with
4,000,000,000,000 bytes allocated to each inbound and `trafficReset=never`.
This is the pair's managed proxy traffic budget, not a whole-account cloud meter
or an automatic monthly reset. Preserve this shared group and both allocations
on retries; do not use `--unlimited` for these nodes.
Both use management TLS TCP 48180 restricted to Noether and VLESS REALITY TCP
8443, with Xray pinned to 26.6.27. Master registration probes and independent
physical-interface Mihomo requests passed, including JP exit-IP checks and
Clash/Shadowrocket metadata. Laplace passed on a registration retry after its
initial probe failed; the retry reused its installed panel and inbound identity.
No frontend/backend deployment or existing customer-counter reset was needed.
Both nodes received all 39 customer bindings through the existing entitlement
worker. Global sync errors can remain while the pre-existing Jerusalem node is
offline; distinguish that fleet-wide state from these two nodes' own readiness.

Later on 2026-10-24, IPv6 Hysteria2 was added alongside REALITY on these same
managed nodes. Inbounds 23/24 use UDP 8444, advertised respectively as
`[2603:c021:8027:deee:0:a60d:af9f:f896]:8444` and
`[2603:c021:8027:deee:0:be05:2bcc:a8e0]:8444`, named
`🇯🇵 日本 · 东京 06` and `🇯🇵 日本 · 东京 07`.
Management continues over the existing restricted IPv4 endpoints. The four
inbounds 21–24 now have 2 TB each; their shared group remains exactly 8 TB.
Existing REALITY counters and identities were retained, with `trafficReset=never`.
Do not reapply the earlier 4 TB REALITY allocations while the HY2 allocations exist.
No extra panel or standalone Hysteria service was installed; the existing Xray
26.6.27 serves both protocols, with certificate pins retained in subscriptions.
Pre-publication tests used temporary dedicated identities and workstation Mihomo
bound to the physical IPv6 interface. Noether has no global IPv6 route, so its
periodic probe cannot validate these IPv6 endpoints; do not interpret that probe's
failure as a workstation connectivity result or silently substitute an IPv4 test.
The live adapter's existing routing baseline was retained, enabling IPv6 transport
when an IPv6 endpoint is present (Clash and Shadowrocket configurations). The
unified-tool commit was rebased onto the current GitHub main branch, incorporating
the newer routing and admin changes instead of overwriting them.
Private pre-change backups are under
`/root/codex-backups/tokyo-hy2-v6-1792823066` on Noether.
Both entries received all 39 customer bindings. Independent workstation tests of
their real subscriptions completed 10 MB downloads at 27.4/24.7 Mbps respectively;
these are point-in-time results. Both retained REALITY entries also passed.

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

Node implementation and maintenance helpers live together in `deploy/nodes/`.
Normal additions, including extra protocols, use `npm run node:add` only.
Two exceptional maintenance helpers run as root on Noether with the deployed
backend at `/opt/jamie-portal/current/backend`; they are not automatically deployed
or run during onboarding:

- `provision_probe.py` initializes or verifies the dedicated monitoring identity.
  Existing identity ownership must match; it does not rotate customer credentials.
- `switch_node_tcp.py INBOUND_ID PORT` converts an existing IPv4 inbound in place
  to REALITY. This is a manual transport migration, not the additive protocol flow.
  It keeps private backups and probes before catalog publication; a failed probe
  can leave the panel changed and requires inspection of that backup.

Completed metadata patches (`update_client_metadata.py`, `update_cycle_metadata.py`),
the initial catalog and billing migrations (`migrate_node_catalog.py`,
`enable_package_billing.py`), and obsolete live bootstrap acceptance scripts
(`verify_billing_nodes.py`, `verify_package_flow.py`) have been removed.
The latter assumed HY2-only fleet configuration or registration without email
verification; current billing and registration regression tests use isolated data
in `backend/test_*.py`. Earlier retired scripts (`attach_sanjose.py`,
`expand_nodes.py`, `prepare_sanjose.sh`, `verify_live.py`, `verify_features.py`)
also remain in Git history only. Do not rerun historical migrations.

## Quality checks and remaining work

Tests cover dynamic 1/7/12-node output, unpublished endpoint filtering, duplicate
names/endpoints, private addresses, shared quota overflow, runtime reload, and
idempotent persistent sync scheduling. Existing account/billing tests also run.

This is not a claim of zero bugs. HTTP transport and five domain route groups are
now separated, with shared authorization before dispatch and regression tests.
Remaining architecture work includes strengthening deployment rollback around later nginx
failures, and adding operator UI for inventory lifecycle. Existing readiness
monitoring distinguishes management heartbeat from actual data-plane probes.
