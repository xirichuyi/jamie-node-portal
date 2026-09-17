# Deployment boundary

The user explicitly chose Noether self-hosting and independent username/password
accounts instead of Sites hosting and ChatGPT login. Preserve that decision.
Only `portal/`, shared `components/ui` and `app/globals.css` are used by the
static frontend. `backend/` runs through systemd on Noether. The original
starter Worker and D1 scaffold are not production resources.

Do not print, commit, or publish `private-admin.json`, `/etc/jamie-portal.json`,
or databases/backups. Use local `apply_patch` for source edits. Keep credentials
out of client bundles. Preserve existing subscription adapter and panel config.
Build locally, upload only static output + backend source; no Node runtime is
needed on the server. Run unit tests and type/build checks before deployment.
