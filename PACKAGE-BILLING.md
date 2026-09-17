# Package billing rollout

Independent package accounting replaces quota/time stacking only after the
transactional `billing_rollout` marker has been enabled. `package_billing` in
configuration is an additional explicit gate. Never turn off the gate or deploy
a pre-package release after migration: repair forward, or perform a separately
planned full recovery with traffic reconciliation.

## Rules

- Base cards start immediately on redemption, each with its own expiration.
- Add-on cards require an explicitly selected, owned, unexpired base/transition
  package; exhausting a base does not prevent adding traffic before it expires.
- Add-ons inherit the exact expiration and cannot register new accounts.
- Earliest expiry is consumed first. Expired unused allowance is not renewed.
- Existing users receive a single transition package with the observed remaining
  bytes and original expiration; no reconstruction of historical package usage.
- Panel caps remain cumulative raw counter + remaining bytes, not remaining
  bytes alone. Zero allowance explicitly disables the node identity; caps never
  use zero (unlimited). Website login remains available for normal exhaustion.
- Counter rollback freezes billing and node use without restoring allowance.
  It requires operator reconciliation; there is deliberately no blind auto-reset.
- Repeated samples and card retries cannot duplicate charges or grants. Cards,
  packages and their audit events commit in the same SQLite transaction.
- Expiry is sent to nodes as the earliest remaining package boundary. After that
  boundary the worker refreshes the next entitlement; a brief sync gap is possible.

## Acceptance and limits

- Local tests cover independent expiry, add-on ownership, invalid/expired target,
  no add-on registration, exhaustion, counter rollback, concurrent samples,
  transaction rollback, transition migration, and request-path integration.
- The live QA script uses an owned temporary identity and fixed gstatic requests.
  First short accounting window failed to observe traffic within 30 seconds.
  The longer-window repeat observed traffic and confirmed all three nodes deny
  an account after shared quota exhaustion, including nodes it had not used.
  Both temporary identities were removed. Invalid-auth negative control denied.
- This is not proof of zero overshoot under simultaneous high-speed sessions.
  Panel statistics and synchronization are asynchronous. Cross-expiry allocation
  is based on observed counter deltas, not per-request timestamps.
- No destination logging, VM hard stop, legacy-service shutdown, price changes,
  payment integration or new advertised add-on pricing.
- Notifications and offsite backups still need a recipient/destination and secret
  provisioning. Admin TOTP and paid/refunded entitlement reversal are not shipped.

## Cutover

Run all backend/frontend tests, type check and build, deploy with billing gated
off, and run the safe unfunded HTTP smoke test. Verify data-plane quota acceptance
using `deploy/verify_billing_nodes.py`. Then run
`deploy/enable_package_billing.py` via SSH stdin as root on Noether.

Cutover stops portal briefly, verifies a fresh database backup, checks every
funded account against panel quota/expiry and counter baseline, and atomically
creates transition packages plus the rollout marker. Private migration snapshots
stay under `/root/codex-backups`. Node counters are never reset.

Afterward verify package count/balance invariants, pending sync errors, public
health and the package flag; test registration/add-on flows using an isolated
database and dedicated identity, not customer cards. Backups now verify package
tables in addition to accounts/cards.
