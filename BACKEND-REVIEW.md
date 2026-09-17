# Backend performance and maintenance review — 2026-09-17

Published: `/opt/jamie-portal/releases/20260917T110854Z`, previous package-billing
release retained. 67 backend tests, 35 frontend tests, Ruff checks, TypeScript and
build passed. Production health, owned unfunded smoke checks and temporary funded
registration/add-on/idempotency/authorization acceptance passed. QA data and its
panel identity were removed; no customer balance reset or billing policy change.

## Implemented

- Admin listings use one connection and two reads with package billing enabled,
  instead of opening another connection and loading history for every user.
  Package history is now returned only for the selected user's detail.
- User detail filters by the requested ID, not a full-population Python search.
- Panel entitlement calculation uses SQL aggregates rather than constructing
  and traversing every historical package object each synchronization cycle.
- Unchanged traffic samples do not read package allocation rows. Sampling time
  is still persisted; billing safety and expiry handling are not cached away.
- Activity persistence loads previous values in one query and batches updates.
- Recent website sessions avoid unnecessary SQLite write transactions; the
  conditional minute-level last-seen update and session revocation still work.
- Added owner/redemption ordering and rate-limit expiry indexes. User ticket
  queries use an explicit owner predicate so the existing owner index is usable.
- Corrected base-plan labels being overwritten by the latest add-on, including
  when the base card falls outside the last 50 redemption-history rows.
- Extracted `errors.py` and `passwords.py`, breaking the package-ledger/domain-error
  import cycle. Password cost remains 600,000 PBKDF2 rounds; no auth weakening.
- Formatted Python source/tests, removed unused imports, added pinned local Ruff
  checks via pyproject.toml and deterministic query-budget regression tests.

## Reproducible local benchmark

`python3 deploy/benchmark_backend.py` creates disposable synthetic data: 500 users,
10,000 packages, cached panel telemetry, median of five calls. No network or
production database access. This measures backend work, not end-to-end web latency.

| Request | Before median | After median | DB connections | SELECTs |
| --- | ---: | ---: | ---: | ---: |
| User list | 198.60 ms | 6.14 ms | 501 → 1 | 1,001 → 2 |
| Single user detail | 201.22 ms | 1.04 ms | 502 → 2 | 1,005 → 8 |

Synthetic list response shrank from 119,485 to 13,385 bytes. Detail still includes
the requested user's packages and retained its 4,888-byte benchmark response.
Wall-clock results vary by machine; tests assert query budgets and accounting
equivalence, not fragile millisecond thresholds.

Read-only production sample before release: portal RSS/cgroup memory approximately
20 MiB, database 320 KiB, 19 website accounts, 250 billing events, no pending sync
or billing faults, 42 GiB filesystem free. No production stress test was run.

## Module boundaries

- `server.py`: HTTP routing, application composition, session/request orchestration.
- `passwords.py`, `errors.py`: independent security primitives / safe domain errors.
- `entitlements.py`: transactional redemption, migration gate and synchronization outbox.
- `package_ledger.py`: package accounting, balance snapshots and aggregate projections.
- `panel.py`: 3x-ui transport and verified absolute entitlement writes.
- `admin_users.py`, `operations.py`: user workspace and operator diagnostics.
- `content.py`, `features.py`: catalog/notices, support/self-service and collectors.
- `backup.py`, `probe.py`: isolated restore verification and fixed-endpoint health checks.

Runtime remains Python standard library. Ruff is only an isolated local developer
tool: `uvx --from ruff==0.11.13 ruff check backend deploy/benchmark_backend.py` and
`uvx --from ruff==0.11.13 ruff format --check backend deploy/benchmark_backend.py`.

## Remaining work, not claimed fixed

1. Counter-rollback quarantine has no reviewed operator reconciliation UI.
   Never clear spent bytes or auto-reset a fault to restore connectivity.
2. Admin second factor and audited paid-entitlement reversal/refund workflows.
3. Notification recipient/credentials and offsite-backup destination remain absent.
4. Per-VM provider billing is not enforced by proxy-only 9 TB inbound caps; the
   owner-requested legacy entry remains active outside unified accounting.
5. Existing-session termination/high-concurrency overshoot still needs dedicated
   data-plane acceptance. Statistics and boundary allocation remain asynchronous.
6. Overview still reads the panel synchronously; synchronization and redemption
   share a billing lock. A panel outage can increase latency. A future per-user
   job isolation design needs ordering/idempotency tests before changing locks.
7. Lists now aggregate cheaply but still sort the compact user set in Python.
   SQL keyset pagination becomes worthwhile only with materially larger datasets.
8. Billing event/backup retention needs an archival policy; no audit history or
   private backup was deleted during this optimization.
9. server.py and features.py still mix several use cases. Further route/service
   extraction is sensible but should preserve their tested authorization boundary.
10. Frontend initial JS remains approximately 509 kB uncompressed; this backend
    release does not claim browser load-time or Core Web Vitals improvements.
