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

Never treat the installed plugin cache as the source repo for release work.

## Documentation-only exemption

Documentation-only changes (`docs/**`, `README.md`, `UPSTREAM.md`) need no
version bump, no marketplace repin, and no fleet redeploy/convergence pass —
commit and push them directly. Only changes under `plugins/` couple to the
release machinery above.
