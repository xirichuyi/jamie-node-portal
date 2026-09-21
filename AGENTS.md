# Deployment boundary

Read [README.md](README.md) for architecture, business invariants and deployment.
For node changes, also read [NODE-OPERATIONS.md](NODE-OPERATIONS.md).
These three files are the maintained documentation; historical reports live in Git.

The user explicitly chose Noether self-hosting and independent accounts instead
of Sites hosting and ChatGPT login. Public registration requires email verification.
Only `portal/`, shared `components/ui` and `app/globals.css` are used by the
static frontend. `backend/` runs through systemd on Noether. The original
starter Worker and D1 scaffold are not production resources.

Do not print, commit, or publish `private-admin.json`, `/etc/jamie-portal.json`,
or databases/backups. Use local `apply_patch` for source edits. Keep credentials
out of client bundles. Preserve existing subscription adapter and panel config.
Build locally, upload only static output + backend source; no Node runtime is
needed on the server. Run unit tests and type/build checks before deployment.

Nodes and endpoints belong in the validated runtime catalog, not source lists.
Preserve the transactional billing/outbox path; never reset panel traffic counters
or disable package billing to bypass a fault. Do not reuse customer credentials
for tests. Do not rerun historical migrations or bootstrap acceptance scripts.
Update an existing document when behavior changes; do not add per-task reports.
