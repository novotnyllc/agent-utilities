---
name: onedrive-fileprovider-repair
description: "macOS OneDrive File Provider diagnosis and bounded FPCK repair for a real ~/Documents/Codex directory. Use for high fileproviderd, suggestd, or OneDrive CPU; provider churn; File Provider reconciliation errors; or a safe fileproviderctl repair that must preserve Documents backup and keep Codex running."
---

# OneDrive File Provider Repair

Keep this narrowly scoped to a real OneDrive-backed `~/Documents/Codex` directory. Diagnose first; repair only with explicit approval.

## Guardrails

- Keep `~/Documents/Codex` a real directory. Do not replace it with a symlink, move it, mount over it, or disable Documents backup.
- Do not quit Codex. The only restart path touches OneDrive and `fileproviderd` after fresh FPCK evidence.
- Do not reset, delete, reinstall, or edit provider storage without separate, explicit approval.
- Keep reports sanitized: no raw File Provider reports, paths, account names, hostnames, PIDs, or item IDs in chat.

## Diagnose

Run the helper twice a few seconds apart. It is read-only and prints only process CPU/memory labels plus safe File Provider state.

```sh
scripts/onedrive-fileprovider-repair.sh --diagnose
```

Treat repeated high `fileproviderd`, `suggestd`, or OneDrive CPU together with abnormal evaluation state as churn evidence. A stale Finder badge alone is not enough. If the helper reports `EVALUATE_DOMAIN=unresolved`, stop; do not work around it with a symlink or a different Documents location.

## Repair

Ask for explicit approval before running FPCK. Then run:

```sh
scripts/onedrive-fileprovider-repair.sh --repair --confirm-repair
```

The helper resolves `~/Documents` to its physical provider path before calling:

```sh
fileproviderctl repair -a <physical-Documents> -P -d -v -o <private-temporary-report>
```

The actual command uses the physical Documents root, not only the Codex child, because stale reconciliation state can live at the parent scope. Never pass logical `~/Documents` directly: macOS can reject that symlinked view with `No providerDomainID`.

Read the `FPCK_*` aggregate lines only. `FPCK_EXIT=0` is the sole success result; any nonzero exit is partial/failure even if counters changed. `FPCK_DOMAIN=unresolved` means stop with no restart. Do not paste or retain the raw report.

## Bounded Restart After FPCK

If the user has also explicitly approved the restart, include the flag in the original repair command:

```sh
scripts/onedrive-fileprovider-repair.sh --repair --confirm-repair --restart-after-repair
```

It restarts OneDrive and `fileproviderd` after that FPCK invocation, including a partial/nonzero result, then waits for OneDrive to fully exit before relaunching it once. It never quits Codex. If CPU stays high or errors recur, stop there and request a separate provider-level recovery decision; do not reset or delete anything.

## Related Codex Issues

These open upstream issues are adjacent evidence, not confirmation of this exact `suggestd`/FPCK loop:

- [`openai/codex#20880`](https://github.com/openai/codex/issues/20880): Codex recreates `~/Documents/Codex` on launch.
- [`openai/codex#28857`](https://github.com/openai/codex/issues/28857): request for a configurable artifact/output directory.
- [`openai/codex#15159`](https://github.com/openai/codex/issues/15159): broad searches can hydrate macOS CloudStorage trees.
- [`openai/codex#28729`](https://github.com/openai/codex/issues/28729): warn about active workspaces in cloud-synced folders.
- [`openai/codex#32853`](https://github.com/openai/codex/issues/32853): restored macOS OneDrive File Provider workspaces can fail after relaunch.
