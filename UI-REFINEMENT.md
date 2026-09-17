# User-facing refinement

Scope: homepage, account hub, authentication, compact support, shared plan copy.
No admin redesign or billing changes. Keep sage/warm-white identity, real SVG logo,
and the body-mounted Safari-safe dock.

- Align homepage cards at the top; connection card fits content instead of an
  artificially stretched empty panel. One full-width mobile import action, with
  copy/QR secondary actions below. Mobile hit areas remain at least 44 px here.
- Shorten supporting copy; keep quota, expiry, card-consumption and safety facts.
  Full usage details retain recording start time; overview has a concise cadence.
- Personal page uses a stable title and wrapping email subtitle, with three
  settings groups. Verified-mailbox users no longer see the misleading missing
  recovery-method prompt. Original username accounts retain that prompt.
- Compact contact areas retain both actual contact links, without repeating a
  paragraph. Form autofill uses theme foreground/background.
- Expired/exhausted copy now distinguishes a new base package from an add-on;
  it does not promise pooled time extensions.

Review fixtures: local-only `/layout-review.html`, with `?mobile&view=account`
for a 390 px iframe and a long example email. Fixtures are not production routes.
Desktop/mobile visual review uses synthetic account/subscription data.
