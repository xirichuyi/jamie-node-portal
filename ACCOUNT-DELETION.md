# Account deletion

User: My account → Email & account security → Delete account.
Admin: Users → User detail → Account actions → Delete account.

Both actions require the acting account's password and an exact target username confirmation. Ordinary users can only delete themselves. Administrator accounts are protected. These endpoints enqueue erasure and return 202, not a false completed result.

Request immediately disables website access, revokes sessions, cancels queued mail and marks the member deleting. The sync worker retries deletion; regular provisioning skips deleting members. Panel ownership is checked using the current/previous subscription ID and auth secret. The client is disabled through the existing node-aware update path before calling `clients/del/{email}?keepTraffic=0`. Local ownership is retained on error for safe retry. Existing established connections remain subject to node kernel teardown behavior.

After panel removal is verified, an atomic transaction removes account/session/email/recovery/preference data, owner tickets and replies, usage/activity records, packages and billing events, redeemed cards, linked audits and current-name login events. Removed cards cannot be redeemed again. Other accounts and unredeemed inventory are untouched. Pending deletion remains visible in management and cannot be re-enabled. No real customer was deleted for testing.

Scope is logical removal from live portal and managed panel data. Old backups, prior email-provider logs, historical renamed-login identifiers no longer linked to the account, and already-delivered email are not automatically erased. Restoring an old backup requires reconciling deletions before restarting provisioning; this release does not rewrite shared backups or claim forensic disk erasure.

Tests use isolated SQLite and a fake panel: ownership/confirmation/password guards, administrator protection, session revocation, per-account isolation, card replay rejection, package/add-on foreign keys, node failures/retries, provisioning prevention and HTTP/CSRF authorization. Real panel deletion was not exercised against customer data.
