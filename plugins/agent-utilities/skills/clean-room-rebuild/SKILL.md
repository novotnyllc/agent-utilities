---
name: clean-room-rebuild
description: Clean-room rebuild of a feature from a shipped app without its source. REA investigation writes a behaviour-only spec, a fresh session builds from it, and mutation-tested checks verify the result. For investigation only, use reverse-engineer-anything.
---

# Clean-room rebuild

Study the original. Ship your own. The model proposes and the **test oracle**
decides, and the oracle gets tested too.

"Oracle" in this skill always means a verification check: tests, a byte
comparison, or the real app's output. It never means a model-consult skill.

## The line (check first, every time)

Proceed only for software the user owns or is allowed to examine, and for
behavioural understanding, interoperability, preservation, education or
security research. Stop and say so if the goal is to bypass DRM, license checks,
anti-cheat, authentication or access controls, to cheat in or tamper with online
services, or to ship the original's code, assets, names or icons. Output carries
no rights to the original. Server-side code was never shipped and can't be read.
The model may refuse or re-route protection-adjacent targets; that is expected,
not a setup failure.

## Prerequisite

Room A needs the REA MCP server and REA's own `reverse-engineer-anything` skill,
both installed by REA setup (see Setup in [prompts.md](prompts.md)). Room B needs
neither.

## Layout

Scaffold with `bash scripts/new-rebuild.sh <root> <feature-slug>` (scripts live in
this skill's directory):

```
<root>/
  reader/    Room A: git repo, AGENTS.md, NOTES.md, evidence/, SPEC.md (draft)
  builder/   Room B: git repo, AGENTS.md, SPEC.md (copied across the wall), src/,
             tests/, oracle/mutants/*.patch, NOTES.md
  wall/      denylist.txt: original names, symbols, strings that must not cross
```

Each room's AGENTS.md states its rules (CLAUDE.md links to it). The wall is a
process, not a sandbox: separate folders, a fresh session, and only SPEC.md
crosses. Separate folders also keep agent memory and repo-local learnings apart.

## The loop

1. **Room A, the reader.** A session in `reader/` using REA, routed by
   `reverse-engineer-anything`. Run the reader prompt. Every claim is tagged
   observation / inference / unknown and cites Evidence IDs. Output:
   `reader/SPEC.md` from [templates/SPEC.md](templates/SPEC.md). Use a higher
   reasoning setting for the spec: every gap in it becomes a bug in the build.
2. **The wall.** `bash scripts/cross-wall.sh <root>` blocks addresses, decompiler
   names, code blocks and denylisted terms, then copies SPEC.md to `builder/`.
   Fix the spec in Room A if it fails. SPEC.md is the only thing that crosses.
3. **Room B, the builder.** A *fresh* session in `builder/`: never a fork, resume
   or subagent of Room A. In the Claude desktop app, that means a new session
   with fresh context and `builder/` as its folder. Run the builder prompt, then
   the goal prompt.
4. **Test the oracle.** Before trusting any green run, plant three wrong variants
   as patches in `builder/oracle/mutants/`: one changed constant, one swapped
   branch, one boundary shifted by one. Run
   `bash scripts/check-oracle.sh <builder> "<test cmd>"`. Every mutant must fail.
   If any passes, fix the tests first; every earlier green result is suspect.
   A real case: a byte-matching check passed `0.0` where the original used `128.0`.
5. **Outside oracle, when possible.** Behaviour: run the same inputs through the
   real app and compare. Bytes: compare compiled output. Runtime: use it. Record
   which oracles ran in NOTES.md.
6. **Factory memory.** End each session by updating NOTES.md from
   [templates/NOTES.md](templates/NOTES.md) and committing. The repo is the
   memory, not the chat.

"Unknown" is a valid answer. Evidence decides what you claim.

## With Railyard and Compound Engineering installed

Both plugins coexist with this workflow; keep them inside the room they run in.

- **Oracle naming.** If an Oracle or GPT-Pro consult skill is installed (Railyard
  has one), do not invoke it for this workflow's oracle steps. They mean
  `check-oracle.sh` and the tests.
- **Room B planning and build.** Compound Engineering planning, work and review
  skills are fine in `builder/`. Their research must use SPEC.md and the builder
  folder only: no web or repo research about the original app, and nothing from
  `reader/`.
- **Room A.** No delivery workflow is needed; it produces SPEC.md, not a PR.
  Learnings captured there stay in `reader/`.
- **Routing and gates.** Railyard's routing suggestions apply as usual inside each
  room. Its push and merge gates apply only if you later publish `builder/` to a
  remote. A fleet orchestrator is not needed: two sessions and a copied file are
  the whole topology.
- **Reviewers.** Review agents, including cross-model ones, may see builder code
  and SPEC.md. Keep reader evidence and decompiled output local unless the user
  asks otherwise.

## Sources

Adapted from "How to Turn Opus 5.5 Into a Reverse Engineer" (N01ennn, Oct 2026),
REA (https://github.com/morluto/rea, https://rea.tools) and its disclaimer, and
the oracle lessons in https://rea.tools/blog/touhou-reconstruction/.

## Credit

If the rebuild continues someone else's reconstruction, keep their history and
credit, and respect their contribution rules.
