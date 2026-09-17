# Email authentication

Sender: `Jamie-Node <noreply@notify.chuyi.uk>` (Resend).
Credentials live only in the private server configuration, `mail` object.

New registrations validate a base card, request a mailbox code, then submit
email + password + card + code. Mailbox addresses are trimmed and lowercased;
the existing username field stores the email without changing account IDs.
Only the final successful transaction consumes the code/card and starts the
package. A failed card/account transaction rolls back code consumption too.
After a lost success response, use email/password login; a used code cannot replay.

Old username accounts remain usable and retain recovery-code/admin-assisted
recovery; this release does not silently claim or bind an email for them.
Verified email accounts can reset passwords by mailbox code. Reset revokes all
website sessions and existing recovery codes, but never re-enables disabled users.

Codes expire in 10 minutes and allow 5 checks. Stored codes are HMAC digests,
with fresh random challenge IDs and no plaintext passwords/card storage.
Sending is limited to once/minute/mailbox, 5/day/mailbox, 5/hour/IP and
90/day/site (conservative default). Registration email requires a valid base
card. Unknown reset addresses and existing signup addresses get a uniform
acknowledgement without sending. Request timestamps and delivery side effects
can still differ; this is not a guarantee against all account enumeration.
Delivery uses a 15-second timeout and provider idempotency keys; no automatic
retry, no SMTP fallback. Domain/API success does not guarantee inbox delivery.

Additive tables: `email_challenges`, `verified_emails`. Mail is enabled only when
server configuration has both `mail.api_key` and `mail.from`. The new frontend
expects email registration enabled in production. No third-party dependencies.
The public registration endpoint fails closed if mail configuration is missing;
it never falls back to username-only registration. Internal legacy fixture and
administrator bootstrap helpers remain separate from the public endpoint.

HTML templates live in `backend/email_templates.py`, paired with plain text.
Warm-white/sage colors match the portal; layout uses inline styles and tables,
with no third-party images, scripts or web fonts. The static brand icon is hosted
on the portal, without per-recipient tracking parameters; the wordmark remains
readable when remote images are blocked. Both signup and reset are covered.

Not included: old-account email binding/change, scheduled subscription emails,
delivery webhooks/queue, CAPTCHA, or changes to subscription billing rules.
