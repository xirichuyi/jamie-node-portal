# Operations completion · 2026-09-17

## Backend optimization · 2026-09-17 11:08 UTC

Release `/opt/jamie-portal/releases/20260917T110854Z`; previous release retained.
Batch balance projections and target-only user detail eliminate per-user DB
connections/history loads from lists. Indexed expiry cleanup, batched activity
updates, zero-delta allocation short circuit and no-write recent session checks.
Extracted password/error modules, formatted backend/tests and added reproducible
synthetic benchmarks plus query-budget regression tests. See BACKEND-REVIEW.md
for measurements and explicitly remaining work. 67 backend / 35 frontend checks,
static checks and build passed; live safe and funded QA checks passed and removed
their own temporary records. Billing rollout remains enabled, no policy change.

## Package billing release · 2026-09-17 10:37 UTC

- Deployed `/opt/jamie-portal/releases/20260917T103747Z` and activated the
  transactional independent-package accounting gate after acceptance.
- Migrated all 16 funded accounts to transition packages preserving observed
  remaining quota and original expiration; no counter reset, credential rotation
  or price changes. Migration snapshot is private under `/root/codex-backups`.
- Independent base cards, owned target selection for add-ons, no add-on registration,
  earliest-expiry allocation, expiry cap recalculation, counter rollback quarantine,
  explicit exhaustion disable and fair outbox retries are active.
- User/staff package details and card-kind history are exposed. Custom issuance
  supports add-on cards without inventing an add-on price or public plan.
- User sorting is global before pagination, unknown values last; traffic activity
  is explicitly distinguished from website session activity and true online state.
- 59 backend / 35 frontend checks, type check and build passed. Live unfunded
  smoke check and owned temporary funded registration/add-on/duplicate/permission
  checks passed. Every temporary account, card, panel identity and test ledger
  was removed. Existing users were not used for acceptance tests.
- Independent quota probe: first 30-second accounting window did not observe
  traffic; extended repeat observed it and all three nodes denied an exhausted
  QA identity. Invalid-auth negative control also denied. This does NOT certify
  zero overshoot or immediate existing-session termination at high concurrency.
- Final verification: 16 billing accounts / 16 transition packages; zero pending,
  sync errors, billing faults, FK errors or panel-target mismatches. Public policy
  enabled, entry assets match build, health OK, post-cutover backup restore verified.
- See PACKAGE-BILLING.md for remaining boundaries. Notifications/offsite backups,
  admin TOTP, and paid entitlement reversal/refunds are not claimed completed.

## Shipped

- Admin card search: exact full-code hash, eight-character suffix or exact
  username; state filters and server-side pagination (25). Full codes are sent
  in authenticated CSRF-protected POST bodies, not URLs, and never returned.
  Results link directly to the owning user. Revocation requires confirmation.
- Login diagnostics on Cards and Users: account existence, disabled/password
  change state, current username throttle and recent authentication outcomes.
  Generic public errors remain unchanged. Only username/outcome/time are stored,
  seven-day/10,000-row bound; no password, IP, UA or browsing target logging.
  Gateway blocks/network failures before the API are not represented.
- User self-service credential rotation requires password reauthentication and
  the existing rate limit. It rotates both sub ID and HY2 auth, retains old
  identity only for idempotent synchronization, preserves quota/expiry/counters,
  and clears old identity after a verified same-revision sync. Existing active
  connections may persist until closed by the core. No real user was rotated.
- Budget/sync/low-user-quota/readiness warnings; published prices without an
  explicit currency are flagged. New numeric-only price saves are rejected.
  Current administrator-entered prices were not changed.
- Daily and deployment backup verifies SQLite integrity, foreign keys and row
  counts after restoring into a disposable isolated DB. Production is never the
  restore target. This does not claim full VM/panel disaster recovery.
- Dedicated panel-only monitoring identity, 1 GiB cumulative, 365 days, private
  local credentials; no customer identity reuse. Every 15 minutes the existing
  Xray binary establishes HY2 connections with certificate pins, then requests
  a fixed HTTPS 204 endpoint through each node. Loopback SOCKS only, no access
  logs. Backend displays actual probe results separately from panel heartbeat.
- Safari experiment was excluded. The user's confirmed body-portal dock and
  original scrolling behavior are preserved.

## Verified

- 46 backend and 34 frontend checks; TypeScript/build.
- Production temporary unfunded QA accounts verified authorization, card-search
  output, login diagnostics, account controls and recovery; QA removed in finally.
- Current three panel inbound caps are 9,000,000,000,000 bytes each.
- Xray monitor: all three nodes returned successful proxied HTTPS requests.
- Installed Clash Verge Mihomo: YAML validation, all four rule providers loaded,
  three successful proxied HTTPS requests, auto/forced subscription formats.
  The first test tried sending requests before initial rule download completed;
  the corrected acceptance waits for providers before checking data-plane traffic.
- Shadowrocket auto/forced base64, three HY2 URIs, certificate pins and quota
  headers verified. No claim of iOS app-level import/connection validation.
- Online static assets hashed against local build, public health and anonymous
  administrator API rejection checked.

## Explicitly unfinished / requires input

- User instructed **do not stop** old entry. Fermat standalone HY2 :443 uses
  independent password and had 334 connection events in the preceding 24 hours;
  untouched. Gauss standalone VLESS :8448/:10080 also left untouched (not the
  HY2 panel entry).
- Standard plan price and whether the existing season price `30` means CNY await
  confirmation. No invented prices/currency.
- Offsite backup destination and notification delivery credentials/recipient
  not supplied. UI marks these unconfigured; nothing is emailed or sent to TG.
- Whole-VM billing cannot be derived from proxy counters. Read-only current-boot
  NIC snapshots were approximately 54 GB JP, 67 GB SG and 129 GB MY (RX+TX).
  Those are not provider billing-cycle totals; old services and OS traffic are
  outside the panel's 9 TB cap. No hard-stop of entire VMs or legacy services.
- Real iOS Shadowrocket acceptance and full cross-client expiration/renewal
  acceptance require a device/test account workflow. Transaction semantics and
  rotation retries are covered by automated tests, not claimed as device QA.
- Customer destination/access logging remains OFF; it is not part of this scope.

## Commands

Use isolated backend regression tests for account and permission checks.
Obsolete `verify_features.py` and unsafe `verify_live.py` were removed.
`deploy/verify_clients.py` uses only the monitor identity, an isolated installed
Mihomo process and private temporary files; it never changes system proxy settings.
`deploy/provision_probe.py` refuses an existing unowned monitor identity and does
not renew/reset its quota automatically. Monitor expiration is a real limit.
