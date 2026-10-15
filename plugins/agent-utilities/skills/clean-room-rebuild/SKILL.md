---
name: clean-room-rebuild
description: Two-room clean-room rebuild of a feature from an app you don't have source for. Room A investigates with REA and writes SPEC.md (behaviour only), Room B builds from SPEC.md alone, and a test oracle that has itself been proven with planted failures decides what's true. Use when the user wants to understand a feature in a shipped app and build their own version, recover rules into a spec, or verify a reconstruction. For investigation only, with no rebuild, use reverse-engineer-anything.
---

# Clean-room rebuild

Study the original. Ship your own. The model proposes and the **test oracle**
decides, and the oracle gets tested too.

> Naming: "oracle" here means a *verification check*. It is not
> `railyard:oracle` (the GPT-6 Pro consult). Never invoke that skill for this
> workflow.

## The line (check first, every time)

Proceed only for software the user owns or is allowed to examine, and for
behavioural understanding, interoperability, preservation, education or
security research. Stop and say so if the goal is to bypass DRM, license checks,
anti-cheat, authentication or access controls, to cheat in or tamper with online
services, or to ship the original's code, assets, names or icons. Output carries
no rights to the original. Server-side code was never shipped and can't be read.
Opus 5.5 may re-route or refuse protection-adjacent targets. That is expected,
not a setup failure.

## Layout

Scaffold with `scripts/new-rebuild.sh <root> <feature-slug>`:

```
<root>/
  reader/    Room A cwd: git repo, NOTES.md, evidence/, SPEC.md (draft)
  builder/   Room B cwd: git repo, SPEC.md (copied across the wall), src/, tests/,
             oracle/mutants/*.patch, NOTES.md, AGENTS.md (CLAUDE.md links to it)
  wall/      denylist.txt: original names, symbols, strings that must not cross
```

The wall is a process, not a sandbox: separate folders, a fresh session, and
only SPEC.md crosses. Each room's AGENTS.md (with CLAUDE.md linked to it) states
its rules, so no agent settings are needed. Separate folders also keep agent
memory and any repo-local learnings stores apart. Proof against a determined
agent would need a VM, not hardened folders; this workflow doesn't call for it.

## The loop

1. **Room A, the reader** (REA session in `reader/`, effort medium; high for the spec).
   Load `reverse-engineer-anything` for tool routing. Use the reader prompt in
   [prompts.md](prompts.md). Every claim is tagged observation / inference /
   unknown and cites Evidence IDs. Output: `reader/SPEC.md` from
   [templates/SPEC.md](templates/SPEC.md). Behaviour, inputs, outputs, edge
   cases, worked examples, open unknowns. No code, addresses, symbol names or assets.
2. **The wall.** `scripts/cross-wall.sh <root>` lints SPEC.md (hex addresses,
   denylisted names, code fences that look like decompiled code), then copies it
   to `builder/SPEC.md`. Fix the spec in Room A if the lint fails. SPEC.md is the
   only thing that crosses.
3. **Room B, the builder**: a *fresh* session in `builder/`. It is never a fork
   and never a subagent that inherits Room A's context. It gets SPEC.md and nothing else.
   Use the builder prompt, then the `/goal` prompt (effort xhigh for verification
   or heavy arithmetic).
4. **Test the oracle.** Before trusting any green run, plant three wrong variants
   as patches in `builder/oracle/mutants/`: one changed constant, one swapped
   branch, one boundary shifted by one. Run `scripts/check-oracle.sh <builder> "<test cmd>"`.
   Every mutant must fail. If any passes, fix the tests first; every earlier
   green result is suspect. (The TH08 lesson: a byte-matching check passed
   `0.0` where the original used `128.0`.)
5. **Outside oracle, when possible.** Behaviour oracle: run the same inputs
   through the real app and compare. Byte oracle: compare compiled output.
   Runtime oracle: use it. Record which oracles ran in NOTES.md.
6. **Factory memory.** End each session by updating NOTES.md from
   [templates/NOTES.md](templates/NOTES.md) (confirmed, unknown, checks that
   exist, next experiment) and committing. The repo is the memory, not the chat.

"Unknown" is a valid answer. Evidence decides what you claim.

## Launching the rooms

Open each room as its own session with that folder as the working directory,
in Claude Code or Codex. Room B must start fresh: never a fork, resume or
subagent of Room A. In the Claude desktop app that means `start_session` with
`context: "fresh"` and `cwd: <root>/builder`.

Scripts live in this skill's `scripts/` directory; run them with `bash`.

## Alongside other workflow tools

- Two sessions and a copied file are the whole topology; a fleet orchestrator is
  only worth it for many parallel feature rebuilds.
- Planning, build and review skills are fine in Room B as long as they work from
  SPEC.md and the builder folder. Never point them at `reader/`.
- Reviewers, including cross-model ones, may see builder code and SPEC.md. Keep
  reader evidence and decompiled output local unless the user asks otherwise.

## Sources

Adapted from "How to Turn Opus 5.5 Into a Reverse Engineer" (N01ennn, Oct 2026),
REA (https://github.com/morluto/rea, https://rea.tools) and its disclaimer, and
the oracle lessons in https://rea.tools/blog/touhou-reconstruction/.

## Credit

If the rebuild continues someone else's reconstruction, keep their history and
credit, and respect their contribution rules.
