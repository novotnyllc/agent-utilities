---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Fusion Test Area Filters

## Goal Capsule

**Objective:** After this change, a contributor or agent can run one area of
the Fusion plugin's offline suite by naming it on the existing gate script,
without running all 33 test files, and the no-argument invocation remains the
full release gate.

**Means:** Extend `plugins/agent-utilities/skills/fusion-parametric-design/scripts/test.sh`
with optional positional area filters passed through as unittest name patterns;
compileall and hooks checks stay full-suite (KTD1).

**Authority:** User instruction > this plan > implementer judgment.

**Stop conditions:** Any change that would make the bare `./scripts/test.sh`
invocation weaker than today's full gate stops the lane.

## Product Contract

### Summary

`scripts/test.sh` currently runs `python3 -m unittest discover -s tests -v`,
`compileall`, and node hook tests (when node is present). Every edit-loop check
and every agent session pays the full ~29k-line suite even when one area is in
play. This change adds area selection without changing what the full gate is.

### Requirements

- R1. `scripts/test.sh` accepts zero or more positional area arguments.
- R2. With no arguments, behavior is equivalent to today's full
  gate: unittest discovery over `tests`, `compileall` over `src tests`, and
  node hook tests when node is present.
- R3. With one or more area arguments, only unittest modules matching the
  areas run (`unittest` dotted-name matching); compileall and hook tests are
  skipped because a partial run is an edit-loop check, not the release gate.
- R4. An area argument that matches no test module fails fast with exit code 1
  and names the unmatched argument.
- R5. README documents the usage and states that the full gate is still the
  no-argument invocation.

### Acceptance Examples

- AE1: `./scripts/test.sh mesh_segmentation` runs only
  `tests.test_mesh_segmentation` and exits green.
- AE2: `./scripts/test.sh manifest cli` runs both modules' tests.
- AE3: `./scripts/test.sh nonexistent_area` exits 1 with a clear message.
- AE4: `./scripts/test.sh` output matches today's full-gate shape.

### Scope Boundaries

- No pytest migration (repo doctrine pins unittest).
- No test reorganization into subdirectories; flat discovery stays.
- No CI changes (this repo has none).

## Planning Contract

### Key Technical Decisions

- KTD1. Filter at the unittest layer via `unittest discover -p` patterns, not
  by copying files or building a new runner (session-settled: user-directed —
  chosen over pytest markers or a custom selector: smallest diff, keeps the
  pinned unittest doctrine). Mechanism: each area maps to discovery pattern
  `test_<area>*.py`; multiple areas run as sequential `discover -p`
  invocations (one process per area). Verified locally on Python 3.14:
  `discover -p 'test_manifest*.py'` runs exactly that module. Trailing-glob
  name arguments (`tests.manifest*`) do NOT glob — unittest treats them as
  literal dotted names and fails — and must not be used.
- KTD2. Unmatched-area validation uses `python3` itself to list matching files
  under `tests/` before invoking unittest, so R4 fails before any test runs.
- KTD3. Partial runs skip compileall/hooks deliberately: they are release-gate
  components, not per-edit feedback (R3 rationale recorded here so reviewers
  do not "fix" it back).

### Assumptions

- Area words are snake_case module fragments (`mesh_segmentation`,
  `manifest`, `cli`). Hyphens are accepted and normalized to underscores.
- Some test files import helpers from sibling test files directly (e.g.,
  `test_cli.py` imports from `test_prusaslicer_project`); area-filtered
  loading routes through unittest discovery so `tests/` stays on `sys.path` —
  dotted-name loading without discovery breaks these imports.
- Multi-area runs execute one discovery process per area in sequence; shared
  module state across areas is not preserved, which is acceptable for an
  edit-loop check.
- The benchmark suite's env-var gating (`FUSION_DESIGN_RECONSTRUCTION_BENCHMARK=1`)
  composes naturally since filtering happens below the env gate.

## Implementation Units

### U1. Area-filtered test entrypoint

- **Goal:** R1–R4.
- **Files:** `plugins/agent-utilities/skills/fusion-parametric-design/scripts/test.sh`
- **Approach:** Parse positional args; if none, run today's three stages
  unchanged. If any, validate each against actual files in `tests/` (after
  normalizing `-` to `_`), then run
  `python3 -m unittest discover -s tests -p 'test_<area>*.py' -v`
  sequentially per area with `PYTHONPATH=src`. Use `set -euo pipefail`
  semantics already present.
- **Test scenarios:**
  - Happy: AE1, AE2 run exactly their modules and exit 0.
  - Error: AE3 exits 1 before any test output, message names the bad area.
  - Edge: hyphenated input (`mesh-segmentation`) behaves like underscore form.
  - Full-gate regression: AE4 unchanged output shape, same exit semantics.
- **Verification:** Commands from the Verification Contract, targeted tier.

### U2. Document usage

- **Goal:** R5.
- **Files:** `plugins/agent-utilities/skills/fusion-parametric-design/README.md`
- **Approach:** Under "Validation and tests", add the filtered form next to the
  full-gate command with one sentence on when each applies.
- **Test scenarios:** docs-only; verify the referenced command string appears
  verbatim and matches U1's accepted syntax.
- **Verification:** Manual read-back; no runtime check needed beyond U1.

## Verification Contract

Targeted (edit loop):

```sh
cd plugins/agent-utilities/skills/fusion-parametric-design
./scripts/test.sh mesh_segmentation   # single area
./scripts/test.sh mesh-segmentation   # hyphen form, same as underscore
./scripts/test.sh nonexistent_area    # must exit 1
```

Full gate (pre-commit):

```sh
cd plugins/agent-utilities/skills/fusion-parametric-design && ./scripts/test.sh
```

Repo-level gate after merge of the chunk:
`npx tsx plugins/agent-utilities/skills/skill-cleaner/scripts/skill-cleaner.test.ts`
(unchanged surface, run once).

## Definition of Done

- Global: R1–R5 true; full gate green with unmasked exit code; diff contains
  only the two files above, this plan, and the release-coupling manifest
  bumps and marketplace pin files required below.
- Per unit: U1's scenarios observed, not inferred; U2's doc text read back.
- Release coupling: change is under `plugins/**`, so both manifests bump to
  0.14.2 and the marketplace repin runs via the push-triggered workflow.
