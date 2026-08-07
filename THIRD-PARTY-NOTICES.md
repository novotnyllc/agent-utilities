# Third-party notices

agent-utilities incorporates the material below. This file is the licensing
record; [`UPSTREAM.md`](UPSTREAM.md) holds the adaptation notes and
[`upstreams.json`](upstreams.json) is the machine-readable pin ledger.

Everything here was copied or adapted into this repository. Our own code is
MIT ([`LICENSE`](LICENSE)) — **except** the Apache-2.0 skill noted below,
which stays under its own license.

## Skills adapted from `steipete/agent-scripts` (MIT)

- **What:** `plugins/agent-utilities/skills/` — `browser-use`, `create-cli`,
  `instruments-profiling`, `native-app-performance`, `one-password`,
  `skill-cleaner`.
- **From:** https://github.com/steipete/agent-scripts, paths
  `skills/<name>`, commit `c46ea65b6323e8a2b6f441f8b6449ae731bc8f81`.
- **Copyright:** Copyright (c) 2026 Peter Steinberger.
- **License:** MIT — text in [`LICENSE`](LICENSE), where the upstream
  copyright notice is preserved alongside ours.
- **Modifications:** maintainer-specific hosts, users, and repos removed;
  fixed home paths replaced with `$HOME` or plugin-relative paths;
  environment-driven 1Password routing. See [`UPSTREAM.md`](UPSTREAM.md).

## `frontend-design` (Apache-2.0)

- **What:** `plugins/agent-utilities/skills/frontend-design/SKILL.md`,
  imported byte-for-byte — **not** modified, and **not** relicensed.
- **From:** https://github.com/steipete/agent-scripts, path
  `skills/frontend-design`, commit
  `c46ea65b6323e8a2b6f441f8b6449ae731bc8f81`, which carries it under the
  Apache License 2.0.
- **Copyright:** Copyright 2024 Anthropic PBC.
- **License:** Apache-2.0 — full text ships beside the skill at
  [`plugins/agent-utilities/skills/frontend-design/LICENSE.txt`](plugins/agent-utilities/skills/frontend-design/LICENSE.txt).
- **NOTICE:** upstream ships no `NOTICE` file, so there is none to propagate.
- **Modifications:** none. If this skill is ever edited, Apache-2.0 §4(b)
  requires a prominent modification statement in the changed file.

## Generated CI artifact

`.github/workflows/refresh-imported-skills.lock.yml` is compiled output from
[github/gh-aw](https://github.com/github/gh-aw) (MIT) and embeds that
project's runner scaffolding. Regenerate it with `gh aw compile`; never edit
it by hand.

Corrections welcome — an incomplete or wrong notice here is a bug.
[File it](https://github.com/novotnyllc/agent-utilities/issues).
