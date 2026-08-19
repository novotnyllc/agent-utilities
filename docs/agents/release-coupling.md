# Release coupling

Changes under `plugins/` ship to installed fleets. They couple to a release:

1. Bump the version in both plugin manifests, in lockstep:
   - `plugins/agent-utilities/.codex-plugin/plugin.json`
   - `plugins/agent-utilities/.claude-plugin/plugin.json`
2. Commit and push, then repin the marketplace from a checkout of
   [`novotnyllc/marketplace`](https://github.com/novotnyllc/marketplace):

   ```sh
   scripts/repin agent-utilities <40-char-sha> <version>
   ```

   That one command updates every catalog file — both marketplace manifests
   and `.agents/plugins/plugin-versions.json` — and verifies them. Do not
   hand-edit those files.

Step 2 now runs itself: pushing to `main` with anything under `plugins/**`
triggers `.github/workflows/repin-marketplace.yml`, which repins to the new
head sha and the version the manifests declare. Run `scripts/repin-marketplace`
by hand only when the workflow cannot (no `MARKETPLACE_TOKEN`, Actions down).
It refuses if the two manifests disagree on the version, if the sha is not on
`origin/main`, or if the sha would move under a version the marketplace already
publishes — that last one is a silent no-op, because `claude plugin update`
compares versions and would report success while installing nothing.

Never treat the installed plugin cache as the source repo for release work.

## Documentation-only exemption

Documentation-only changes (`docs/**`, `README.md`, `UPSTREAM.md`) need no
version bump, no marketplace repin, and no fleet redeploy/convergence pass —
commit and push them directly. Only changes under `plugins/` couple to the
release machinery above.
