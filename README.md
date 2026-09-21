# Jamie-Node portal

## Node operations (2026-09-21)

Node inventory is runtime data, not a Python list. See [NODE-OPERATIONS.md](NODE-OPERATIONS.md)
for the supported onboarding command, shared-account quota rules, retry semantics,
and known operational boundaries. Legacy one-off installers and unsafe old smoke
checks have been removed; Git history retains them for reference only.

Backend tests (including subscription serialization):
`uv run --with pyyaml --no-project python -m unittest discover -s backend -p 'test*.py'`.

## Expanded user center (2026-09-17)

- Public plans, announcements, official client guides, FAQ and contact entry.
- Signed-in home includes quick actions, latest redeemed card name, real node
  management heartbeats and management-link latency (NOT local-client latency
  or proof of proxy end-to-end connectivity). Refresh cache every 30 seconds;
  stale/failed telemetry becomes unknown, never fabricated online status.
- Admin: plan publishing/unpublishing and editing, announcement draft/publish/
  pin, support HTTPS/mailto link. Optimistic revision checks prevent lost edits.
- Plan-based card issuance reads quota/duration from the database, ignores client
  overrides, rejects unpublished plans, and snapshots old issued cards unchanged.
- Standard 100 GiB / 30-day card is initially published. Light and extended tiers
  are drafts pending the owner's choice. No price or contact address is invented.
- New additive SQLite tables `portal_plans`, `portal_notices`, `portal_settings`,
  `portal_migrations`; one-time seed does not reset admin edits on restarts.
- New APIs: public GET `/api/content`; authenticated GET `/api/nodes`; admin
  GET `/api/admin/content` and POST `/api/admin/plan`, `/notice`, `/support`.
- Deployment now backs up SQLite before switching releases and rolls back the
  code symlink if health checks fail. Unsafe bootstrap-era smoke scripts have
  been removed; use the current unit suite and `deploy/verify_clients.py`.

Production: https://sub.chuyi.uk/ — self-hosted on Noether, explicitly selected
by the owner. Do not migrate it to Sites/ChatGPT authentication. The original
Sites scaffold is retained as development dependencies only; its Worker,
Cloudflare database, and authentication helpers are not used or deployed.

## Runtime

- `portal/main.tsx`, `portal/style.css`: static React frontend, blog-inspired
  monochrome palette, light/dark mode, compact working surface and floating dock.
- `vite.portal.config.ts`: local-only compilation into `dist/portal`.
- `backend/server.py`: Python 3.11 stdlib HTTP API, bound only to 127.0.0.1:18766.
- `backend/entitlements.py`: SQLite atomic redemption, retryable absolute state.
- `backend/panel.py`: verified TLS to 3x-ui through loopback, fixed inbound IDs 1/2/3.
- Server data: `/var/lib/jamie-portal/portal.db`, credentials `/etc/jamie-portal.json`.
- Service: `jamie-portal`, 160 MiB memory ceiling, 50% of one CPU, 12 HTTP workers.
- Daily SQLite backups: `jamie-portal-backup.timer`, server state directory
  `backups/`, no automatic pruning. Backups contain private account information.
- Versioned deployments: `/opt/jamie-portal/releases/`, `current` symlink.
- Nginx backup before first activation:
  `/root/codex-backups/jamie-portal-20260916T161535Z/jamie-domains.conf`.

Existing `/sub/` and `/clash/` locations and panel.chuyi.uk are unchanged.
The old clients are not imported or overwritten: portal users have separate
`jn_` identities. Package billing is now enabled: each base card starts an
independently expiring package; an add-on inherits the selected active package's
expiry and never adds days. Expired unused traffic is discarded, earliest expiry
is consumed first, and panel counters are never reset. Existing balances were
preserved as transition packages. See PACKAGE-BILLING.md for acceptance and
asynchronous-metering limits. Redeem-deadline and package duration are distinct.
The existing per-inbound 9 TB settings are unchanged; they are not hard
machine-wide bandwidth caps.

## Security and operations

Passwords: salted PBKDF2-SHA256, 600,000 rounds. Server-held session hashes;
Secure, HttpOnly, SameSite=Strict cookies. Origin + JSON + custom header checks
on mutations, rate limits, server-side admin authorization, parameterized SQL.
Card plaintext is returned only once and stored as SHA-256 digest, with 128 bits
of entropy. Never log cookies, passwords, card plaintext or subscription URLs.
The entire portal DB is private; it contains node credentials for provisioned
members. The panel API credential is accessible only to root and service group.

Administrator username is `jamie`. `private-admin.json` is an ignored, mode-600
handoff file containing the initial password. First sign-in requires changing
it. After the user changes it, this local file no longer reflects their password.
Do not run verification scripts that rotate credentials after handoff.

No automatic public password recovery; admin can reset a user's password after
verifying their identity. Resets invalidate sessions and require password change.
Disabling a user invalidates sessions immediately; node access is eventually
disabled by the retry worker. Pending errors are visible in admin user records.
Admin records show most recent 500 users/cards and 100 audit entries.

## Development and checks

`npm run build`, `npm run check`, `python3 -m unittest discover -s backend -v`.
`python3 deploy/deploy.py` provisions/releases the self-hosted app. Existing
config and admin account are preserved. Inspect server config before changing
API credentials or inbound IDs. Never reset traffic counters during renewal.

`deploy/verify_clients.py` uses the dedicated monitoring identity, not real user
passwords. Unit tests use isolated databases and fake panels. The old
`verify_live.py` and `verify_features.py` scripts were removed as obsolete.

Validated: TypeScript, production static build, 8 unit/integration tests,
production HTTPS login/register, duplicate redemption, non-admin denial, real
panel sync, real usage retrieval, both subscription formats, and QA disable.
No browser visual QA or physical iPhone Shadowrocket connection test was run.
Optional WebMCP read-only summary uses feature detection; browser registration
was not verified because no supported WebMCP validation context was available.

## Rollback

Restore the backed-up nginx config and validate it before reload to remove the
portal entry while retaining old subscription paths. Stop `jamie-portal` only
after the entry is removed. Keep `/var/lib/jamie-portal` intact to preserve
accounts and redeemed codes. For future releases, point `current` back at the
recorded previous release, restart the portal, and check `/api/health`. Schema
changes must remain backward compatible or require a separately planned restore.
