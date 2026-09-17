# Borderless UI experiment

Baseline commit: `55b9d46`, tag `ui-before-borderless`.
Branch: `ui/borderless`. Local repository only; no remote push.

The experiment is isolated to `portal/exchange.css`, imported by the production and local-review entries. The `exchange-layout` class is limited to customer views. It removes surface fills, round containers, shadows and backdrop filters; maintains control borders, focus indicators, dialogs and the dock; uses shared rules, columns and list spacing. No backend or billing changes.

To undo after checking for unrelated local changes, revert the experiment commit and redeploy. Do not reset the whole worktree or database. The production deploy also retains the previous release directory for rollback.
