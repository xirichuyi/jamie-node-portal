# Task-first layout revision

## Delivered changes

- Home uses separate new/active/inactive subscription journeys. No empty quota
  dashboard for new members. Active users see quota + import; mobile puts the
  connection action first. Usage is secondary; node details are collapsed.
- Plans use natural-width cards rather than a stretched split-layout single
  card. One redemption action in the page heading. Current membership appears
  once; contact/get-card access remains with the plan, no repeated sidebar.
- Device guide supports Windows/macOS/iOS/Android/Linux with installation,
  import and verification steps. Auto-detection can be overridden. Manual
  fallback instructions and official downloads remain available.
- Account groups subscription, support and security. One administrator entry
  opens the management workspace. Connection keeps advanced/security controls
  out of the homepage, available on the subscription page.
- Operations, issuance/users and tickets share navigation. Metric buttons link
  to user filters or support tickets. Admin page has section jumps, username
  search and active/expiring/pending/error filters; CMS settings are collapsed.
- Shared form, button, spacing and responsive styles apply to secondary pages.
  Mobile tickets use list/detail navigation with a back action, rather than
  placing the entire conversation below the ticket list.
  Existing backend, identities, quotas and subscription formats are unchanged.

## Verification scope

- Live browser: plans card sizing, single redemption action, device guide.
- Local browser fixtures: active/new/expired homepage; account groups; tutorial
  next-step transition; operations layout. 390px overflow checks for home,
  plans, guide, account, subscription, operations, tickets, sessions.
  Dark account layout and mobile ticket form opening were also checked.
- Fixtures are explicitly labelled sample data; writes are rejected. They are
  available only through the local Vite `layout-review.html` entry, not included
  in the production build. No production login/credentials bypass is added.
- Production browser was not authenticated. Authenticated visuals were checked
  with fixtures, not a real administrator session. Native mobile-client launch
  and physical phone testing were not performed in this layout revision.
- SSR journey tests, navigation tests, TypeScript build and backend tests pass.

Run local review with the normal dev server and visit `/layout-review.html`.
Do not deploy the development server or the fixture entry to production.
