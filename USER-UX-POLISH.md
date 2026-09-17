# User experience polish · 2026-09-17

Scope: user-facing flows only; existing visual direction and admin interface retained.

- Authentication, registration, recovery and forced-password-change screens hide the bottom dock. Auth screens no longer reserve dock-sized bottom padding.
- Login/registration offer an accessible password visibility toggle; visibility resets on route, auth-mode or account changes.
- Account page offers a dismissible recovery setup reminder, only after the sessions API confirms no recovery code exists. Only dismissal preference is stored in session storage, not recovery codes.
- Account page shows the count of **replied**, not purportedly unread, tickets. User ticket lists/details refresh every 30 seconds while visible and on tab return. Admin polling remains disabled.
- Ticket drafts remain in page memory across internal navigation, scoped to the signed-in username. They clear on submission/account change and do not survive a page reload; nothing is written to browser storage.
- Tutorial device/step preferences survive internal navigation/reload in the same browser session. Storage denial and corrupt values fall back safely.
- Navigation remembers per-page scroll position for this page session, including delayed content. User scroll/key interaction cancels delayed restoration.
- Home remaining-quota bar now matches its label. Unknown usage/enablement displays status pending confirmation. Subscription status refreshes on return to the browser tab.
- Exact local expiration date/time and sub-day countdown are displayed; the countdown updates every 30 seconds.
- Redemption preview shows estimated remaining quota separately from total entitlement; unavailable usage is never treated as zero, except an account with no prior quota. Success instructions follow actual pending/URL state.
- Copy subscription feedback appears temporarily inside the action rather than inserting a success paragraph.
- Blank/numeric-only price labels display “价格请咨询管理员”; currency is not invented and stored catalog data is unchanged.
- User-approved public contacts verified from the live blog home bundle: `mailto:xrcy123@gmail.com` and `https://t.me/xrcy97`. Both appear in login/help and directly in recovery without authentication. Custom configured contact links remain additive. No private contact information used.

Validation: 23 frontend tests, 23 backend tests, TypeScript check and production build pass. Includes dock route policy, minute/hour expiry, quota estimates, invalid tutorial storage, unknown subscription status, resumed draft rendering, contact fallback and existing journeys/API behavior. No new browser/physical-device QA in this pass; do not describe static rendering tests as interactive browser verification.

Pending owner input: currency for the numeric-only seasonal price (currently shown as “价格请咨询管理员”). No payment, proxy credentials, traffic ceilings, server resources or administrator settings changed.
