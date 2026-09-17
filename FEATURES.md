# Portal self-service release

## Navigation

Four hubs remain Home / Plans / Guide / Account. Secondary pages: usage,
subscription, redemption, tickets, website sessions + recovery, password,
history, notices and service status. Administrators additionally have operations,
ticket replies and the existing issuance/member/content administration.

## Data and safety boundaries

- Usage collection starts with a baseline at rollout. No historical daily data is
  invented. Samples every five minutes, timezone Asia/Shanghai, 30-day view,
  400-day retention. Cross-day intervals, counter resets and gaps are marked
  partial. Homepage remaining quota remains authoritative.
- Subscription QR generation is local. The reset flow verifies the password and
  rotates only the subscription URL, preserving quota/expiry/node credentials.
  Existing imported proxy credentials are NOT revoked. Failed panel updates are
  retried via the ledger; the new URL is hidden until verified.
- Website sessions are not proxy device tracking. Users may revoke their other
  website sessions. Recovery codes are random, hash-only, single-use and shown
  once. Replacing a code invalidates the old code. Recovery logs out all website
  sessions. Administrator password resets invalidate recovery codes too.
- No mail provider is configured. Notifications and ticket replies are on-site;
  users without a saved recovery code must contact the administrator.
- Node budgets show panel inbound proxy counters. All three are configured for
  9 TB decimal, cumulative, no automatic reset. This is not a provider-billed
  whole-VM bandwidth guarantee and excludes traffic outside these inbounds.
- Node status is panel-reported, not end-to-end connectivity testing. Status
  events are collected every five minutes and retained 90 days. Incidents are
  administrator-published. Backup status checks file recency, not restore health.
- Additive SQLite migration only. Deployment takes a database backup before and
  after switching release symlinks. No existing passwords or entitlements reset.

## Verification

Run `python3 -m unittest discover -s backend -v`, `npm run check`,
`node --test portal/navigation.test.mjs portal/features.test.mjs`, `npm run build`.
The SSR checks do not substitute for browser/device visual testing.

`deploy/verify_features.py` runs on Noether via SSH stdin. It creates isolated,
unfunded QA accounts, tests permissions/tickets/sessions/recovery and reads node
budgets. It removes its QA rows in `finally`. It never creates panel clients or
changes real users. Do NOT use the historical `verify_live.py` on established
installations: it resets the initial administrator password.

The existing starter dependency tree still has npm advisories affecting unused
Node server/build dependencies (including vinext/RSC, undici and Vite). Production
serves a static React bundle plus Python, not these Node servers. No bulk forced
dependency upgrade was performed as part of this UI/self-service release.
