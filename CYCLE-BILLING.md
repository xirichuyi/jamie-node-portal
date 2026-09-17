# Recurring allowances

Admin custom cards and saved plans support finite days or permanent service,
with no reset, monthly anniversary renewal, or an explicit N-day interval.
Monthly renewal is anchored to the package's redemption timestamp in Asia/Shanghai,
including its time of day. Jan 31 → Feb 28/29 → Mar 31. The original anchor never
drifts. Card redemption deadline is separate; zero means no redemption deadline.

Existing cards/packages/plans retain `never` and finite duration defaults. Editing
a saved plan only affects newly issued cards. Each redeemed base card remains an
independent package, consistent with existing accounting, not a replacement or
extension of other packages. Add-ons inherit the current cycle boundary (or the
base expiry if sooner) and never renew or move the anchor.

The portal owns renewal. Panel counters stay cumulative and native resets remain
off. Access is capped at the earliest package expiry or cycle boundary. The worker
samples cumulative traffic, allocates the pre-boundary delta, then restores the
current allowance once and advances the boundary. Missed cycles never accumulate.
No successful sample or counter rollback means no renewal. At a boundary, service
may briefly wait for the worker/sample/panel sync; unavailable nodes retry.
Established connections remain subject to the node's enforcement behavior.

Internal forever timestamp is translated to panel expiry zero when no cycle
boundary is needed. A local-only token-scoped metadata route supplies the adapter
with business quota and expiry, avoiding cumulative enforcement totals and cycle
cutoffs in the user's subscription display. No account names or secrets are
returned. The adapter fails closed if this metadata service is unavailable.

Verification uses isolated databases, simulated clocks and mocked panel writes;
no real user's balance is reset for testing. Keep portal and adapter backups
together: rollback the adapter metadata integration before reverting to a portal
version that lacks `/internal/subscription-info/`. Do not roll back cycle-aware
accounting after issuing recurring cards without an explicit data migration.
