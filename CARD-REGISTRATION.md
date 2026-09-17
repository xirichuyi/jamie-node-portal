# Two-step card activation

Current billing update: only base cards can register; add-on cards are rejected
by both preview and registration. Base registration creates one independent
package atomically. Logged-in add-on redemption requires an owned, unexpired
target package. See PACKAGE-BILLING.md; the original release notes below describe
the registration rollout, not the subsequent balance migration.

The default anonymous home opens activation. `#/register` and `#/login` are stable entry routes. Authentication screens have no dock.

1. `POST /api/register/preview` validates the card and returns only its label, quota and duration. No account, reservation, expiry countdown or redemption is created. Rate-limited and same-origin protected.
2. `POST /api/register` requires the card plus username/password. The card is revalidated inside `BEGIN IMMEDIATE`. Member, account, entitlement, card binding, audit and secure login session commit together. No empty public registration remains. Internal bootstrap/test account provisioning stays separate and is not an HTTP endpoint.
3. The existing revision/outbox worker prepares the proxy subscription independently. A panel failure keeps the account logged in, displays preparation state and retries the same absolute entitlement. No repeated quota grants.
4. The browser proceeds to the device guide, with an optional recovery-code setup link. The guide does not tell pending subscribers to register again. Login remains available for subsequent visits; renewal uses the existing authenticated redemption flow.

Idempotency: retrying a redeemed card requires its owning username and the current valid password; no extra quota/duration is added. Wrong credentials/disabled accounts cannot replay it to obtain a session. The card alone is never a login credential. Expired/revoked/unavailable cards and username conflicts create nothing. Passwords/cards remain in transient form state only, never browser storage or URLs.

Only the exact untouched default welcome notice is updated to explain the new flow (content migration 2). User-edited announcements are preserved. No existing accounts are deleted or migrated, and the admin interface, plans, prices, credentials and traffic caps are not changed.

Validation: backend registration tests cover preview non-mutation, activation-time expiry, secure session, invalid fields/cards, expiry/revocation after preview, session-write rollback, username conflicts, replay, concurrent same/different users, disabled-account denial and panel retry. Frontend tests cover initial card-only screen, separate login, entitlement summary and auth dock policy alongside existing regressions. Browser/physical client interaction testing was not requested and is not claimed.
