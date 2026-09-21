# Admin workspace and notice entry · 2026-09-17

## Delivered surface

- Separate Overview / Users / Cards / Tickets / Notices & Plans navigation. The user-facing dock is hidden in administration; a return-to-user-site action remains. `#/admin` continues as the cards page.
- `#/admin_users`: server-side search over all accounts, 25-row pagination, status counts and filters. No destructive actions are placed on rows. Overview counts use the same state classification.
- `#/admin_users?user=ID`: accessible Sheet detail; full width on mobile. URL/history supports closing/back without losing the mounted list/search state. Current account, subscription and synchronization statuses are displayed independently.
- Remaining/total entitlement, exact expiration, registration time, sampled usage time, current website sessions, latest session activity, real synchronization attempt/success times. No timestamps are fabricated for pre-release historical syncs.
- Redemption/audit records (latest 50 each) are collapsed by default so account actions remain accessible. Unknown usage is not zero or “active”. Traffic fetch errors are explicit; bounded 15-second server cache avoids hammering the panel.
- Confirmed actions: disable/restore, reset password, revoke website sessions, retry existing pending synchronization. Password display is scoped to the selected user, copy includes username, and closing removes the plaintext from UI state. No delete/quota-edit/reset-usage controls.
- Disable is immediately effective for website sessions; node propagation is separately pending. Restore never extends quota/expiry. Retry wakes the existing absolute-entitlement worker and does not grant quota or bump entitlement revisions. Stale disable/restore confirmations are rejected.
- Cards use a lightweight overview endpoint, independent of live user traffic. User detail data excludes panel auth, subscription URLs, password hashes, session tokens and card plaintext.

## Announcements

- Public top-of-page entry on login, activation, tutorials and user pages. The newest unread/important title is immediately discoverable without logging in.
- One unread pinned announcement opens on entry. Acknowledgement is a device-local preference keyed by announcement ID + revision, not a server/account read receipt. On subsequent entry an edited revision can remind again; the in-page indicator marks updates immediately after successful refresh.
- Announcement content refreshes every 60 seconds while visible and on tab return. Latest-response guarding prevents an older concurrent request replacing newer content. Only published notices render; withdrawal takes effect on the next successful refresh. Offline users cannot receive updates until reconnected.
- Plaintext rendering, scrollable complete notice dialog, persistent All Notices route. Unpinned notices do not force a dialog. Publishing UI distinguishes drafts from published notices and explains pinned first-entry reminders.

## Data / validation

Additive columns `members.last_sync_attempt` and `members.last_synced_at`, default 0; audit actor/target indexes. Existing members, credentials, quotas, counters and plans are preserved.

Automated checks cover >500-user search/pagination, state classification, unknown/failing traffic, detail isolation, timestamps, role restrictions, stale actions, publication/revision/withdrawal, separate routes and public announcement rendering. Existing entitlement/authentication regressions remain in the suite. Static rendering tests are not interactive browser or physical-device QA.

Account operations are verified by isolated backend tests. Live subscription checks use the dedicated monitoring identity through `deploy/verify_clients.py`. Obsolete bootstrap/account smoke scripts have been removed; do not recover them from Git for routine production checks.
