---
name: goal-driven-delivery
description: Orchestrate higher-quality first-pass software delivery with goal-mode execution, Compound Engineering, Thermos review gates, RepoPromptCE context building, React Doctor, PR feedback resolution, CI watching, and durable learnings. Use when starting a feature, bug fix, risky refactor, long-running implementation, existing PR cleanup, or any task where the goal is to reduce agent/CI/review churn and land a green PR.
---

# Goal Driven Delivery

Use this skill to choose the delivery route and invoke the right existing skills. Do not replace those skills with a long ad hoc prompt.

## Skill Router

Resolve skill names against the host's available-skills list before invoking. Usual routes:

- `compound-engineering:lfg`: full plan -> work -> simplify -> review -> browser test -> commit/push/PR -> CI loop.
- `compound-engineering:ce-plan`: implementation-ready plan before chunked work.
- `compound-engineering:ce-work`: plan execution when not using LFG.
- `compound-engineering:ce-simplify-code`: behavior-preserving simplification before final review.
- `compound-engineering:ce-code-review`: pre-PR or pre-rereview code review.
- `compound-engineering:ce-test-browser`: browser/UI verification.
- `compound-engineering:ce-commit-push-pr`: commit, push, and PR creation.
- `compound-engineering:ce-resolve-pr-feedback`: active PR review feedback evaluation, fixes, replies, and thread resolution.
- `compound-engineering:ce-compound`: durable learning capture after a solved problem.
- `agent-utilities:babysit-pr`: quiet PR monitoring after PR creation or after a fix push.
- `github:gh-fix-ci`: focused GitHub Actions failure repair.
- RepoPromptCE tools: context building, oracle review, and explicit RP-agent experiments when installed.

Use native host subagents by default for implementation. Use RepoPromptCE deliberately for context quality, not accidentally as the worker pool.

## Thermos Gate

For every Thermos gate, invoke or read the sibling skills in this plugin:

- `agent-utilities:thermos`: orchestration and synthesis instructions.
- `agent-utilities:thermo-nuclear-review`: correctness, breakage, security, devex, and feature-leak audit.
- `agent-utilities:thermo-nuclear-code-quality-review`: maintainability, structure, abstraction, and code-health audit.

If the host does not expose plugin-qualified skill names, read the sibling `../thermos/SKILL.md`, `../thermo-nuclear-review/SKILL.md`, and `../thermo-nuclear-code-quality-review/SKILL.md` files directly.

Run the two review passes in parallel when the host supports subagents. Give both reviewers the same scoped diff and enough source context to evaluate without guessing. Synthesize their findings, deduplicate overlaps, fix every real finding before committing the chunk, and record any non-fix with evidence.

Do not treat Thermos as a substitute for tests, React Doctor, CE code review, or hosted CI. It is the pre-commit "would review have caught this?" gate.

## RepoPromptCE Route

Use RepoPromptCE when one of these is true:

- the feature spans unfamiliar code and the right files are not obvious;
- previous PRs in the area churned because agents missed architecture, tests, or review context;
- docs and code may disagree and a curated context packet would reduce guesswork;
- the user explicitly asks for RepoPromptCE, RP, context builder, oracle, or an RP orchestrator experiment;
- a second model review of the plan or diff is valuable before committing more work.

Do not use RP for tiny edits, known-file fixes, docs-only changes, or as the default implementation agent.

Preferred RP uses:

1. RP scout before CE planning. Run RepoPromptCE `context_builder` with `response_type:"clarify"` or `response_type:"plan"` when discovery is the bottleneck. Export the response when the next agent needs it, then pass the export/path into `compound-engineering:ce-plan` or the goal prompt.
2. RP oracle before a risky chunk. Curate the relevant files with `manage_selection`, then use `oracle_send mode:"plan"` for design concerns or `mode:"review"` for a finished diff. Treat the output as review input, not automatic truth.
3. RP agent delegation only when requested. If the user explicitly wants RP agents, use `agent_run` with bounded ownership: one worker, one slice, named files, no broad parallel edits. Close RP agents when done.

Bad RP uses:

- dispatching RP agents because "subagent" was mentioned;
- running RP and CE plans that compete without reconciling them;
- letting RP workers edit the same files as native workers;
- treating an oracle response as a substitute for local tests, Thermos, CE code review, or CI.

If RP is unavailable, continue with CE/native host tools and say RP was skipped.

## React Gate

If a chunk touches React, Next UI, JSX/TSX, component packages, styling recipes, client/server component boundaries, or browser-visible behavior, run React Doctor before committing that chunk.

Use the documented React Doctor CLI from the project root:

```bash
npx react-doctor@latest --staged --no-score
```

Use `--staged` after staging the intended chunk paths and before committing. If the chunk is not staged yet, run the branch/local diff scan instead:

```bash
npx react-doctor@latest --diff --no-score
```

For automation that needs machine-readable output, add `--json`:

```bash
npx react-doctor@latest --staged --json --no-score
```

Do not invent project scripts, do not assume a local package install, and do not add React Doctor as a dependency unless the user or repo policy explicitly asks for that. Fix real React Doctor findings before commit. Run it again before PR for UI-heavy branches. Skip it for backend-only, schema-only, script-only, and docs-only diffs.

## PR Feedback And Monitoring

Use `ce-resolve-pr-feedback` for active review cleanup. It fetches unresolved review threads, judges each item centrally, fixes valid issues, commits/pushes, replies, resolves eligible threads, and verifies the thread list.

Use `babysit-pr` for ongoing monitoring. It watches CI, review feedback, mergeability, Copilot/reviewer state, flaky retry opportunities, and late-arriving feedback after a PR exists or after a feedback-fix push.

Do not use the watcher as the primary review-feedback fixer when unresolved review threads already exist. Start with `ce-resolve-pr-feedback`, then hand the PR back to `babysit-pr` for quiet monitoring.

## Route Selection

Pick one route.

| Situation | Route |
| --- | --- |
| New scoped feature or bug fix, one PR expected | Goal + `compound-engineering:lfg` |
| Large, risky, or historically churny feature | Goal + chunked hardening loop |
| Unknown or historically missed code context | RP scout, then Goal + LFG or chunked hardening |
| Explicit RepoPromptCE experiment | RP scout/oracle/agent route with bounded ownership, then normal CE/Thermos/CI gates |
| Existing PR with review comments | `compound-engineering:ce-resolve-pr-feedback`, then `agent-utilities:babysit-pr` |
| Existing PR with CI failures only | `github:gh-fix-ci` or `agent-utilities:babysit-pr` |
| Docs-only or tiny diff | Direct edit + targeted check, skip LFG and Thermos |
| Recently solved issue with reusable lesson | `compound-engineering:ce-compound mode:headless` |

Default to LFG for normal feature work. Use chunked hardening when the user asks for Thermos before each chunk, the work touches auth/data/migrations/providers, or previous PRs in the area churned on real review findings.

## Route A: LFG Goal

Use when the change can be one coherent PR and the built-in CE gates are enough.

Goal template:

```text
/goal Deliver <FEATURE> as a green, review-ready PR.

Outcome: <measurable behavior>.
Verification: <targeted tests/checks>, plus the repo final gate.
Constraints: preserve <critical existing behavior/security/data boundaries>.

If the right files or architecture are not obvious, first use RepoPromptCE context_builder to produce a curated context packet and feed that into planning. Then use compound-engineering:lfg with this feature brief. Let LFG run plan first, then work, simplify, CE code review, browser testing when applicable, commit/push/PR, and CI autofix. If React/Next UI is touched, run the React Gate before final commit/PR readiness and fix real findings.
After the PR exists, monitor CI and review feedback until checks are green and actionable review feedback is resolved or durably recorded. If unresolved review threads appear, invoke compound-engineering:ce-resolve-pr-feedback. After active review cleanup, invoke agent-utilities:babysit-pr to monitor late review feedback and CI. If the work produces a reusable lesson or fixes a repeated failure mode, invoke compound-engineering:ce-compound mode:headless before the final summary.
If blocked: report the exact failing gate, evidence, and next human decision needed.
```

Do not insert Thermos into LFG's internal step order. LFG has a fixed contract. If Thermos must run between chunks, use Route B.

## Route B: Chunked Hardening Goal

Use when first-pass quality matters more than maximum autopilot: migrations, auth/RBAC, provider side effects, import/cutover work, large UI slices, or any area with recent CI/review churn.

Goal template:

```text
/goal Deliver <FEATURE> as a green, review-ready PR with chunk-level hardening.

Outcome: <measurable behavior>.
Verification: <targeted tests/checks>, plus the repo final gate.
Constraints: preserve <critical existing behavior/security/data boundaries>.

Workflow:
1. If context is uncertain or this area has churned before, run RepoPromptCE context_builder first and pass the exported context into planning.
2. Invoke compound-engineering:ce-plan. Do not code until an implementation-ready plan exists.
3. Implement one vertical chunk at a time using existing repo patterns and native host subagents only when useful. Use RP agents only when explicitly requested, with bounded ownership.
4. After each non-trivial chunk, run the smallest relevant checks. If React/Next UI is involved, run the React Doctor gate before commit. Run the Thermos gate using the sibling Thermos skills, fix all real findings, inspect the diff, and commit explicit paths.
5. Before PR, invoke compound-engineering:ce-simplify-code unless the diff is docs-only or trivial.
6. If the branch is UI-heavy, run the React Doctor gate again after simplify and before CE code review.
7. For risky chunks, optionally use RepoPromptCE oracle_send mode:review on the selected diff/files before CE code review. Apply only findings that survive normal code/test inspection.
8. Invoke compound-engineering:ce-code-review with mode:agent and the plan path. Apply all eligible findings.
9. Invoke compound-engineering:ce-test-browser with mode:pipeline when UI/browser behavior changed.
10. Invoke compound-engineering:ce-commit-push-pr.
11. After PR creation, run compound-engineering:ce-resolve-pr-feedback for unresolved review threads. Use github:gh-fix-ci for focused branch-related CI failures. Use agent-utilities:babysit-pr for quiet ongoing monitoring after active fixes.
12. Invoke compound-engineering:ce-compound mode:headless when the run discovers a reusable pattern, repeated failure mode, or durable project vocabulary.

Complete only when CI is green and actionable PR feedback is resolved or durably recorded. If blocked, report the exact gate, evidence, and next human decision needed.
```

The chunk loop is the churn reducer. It forces local review before the branch accumulates enough mistakes for CI and GitHub review to become the first real QA pass.

## Route C: Existing PR Cleanup Goal

Use when a PR already exists and the goal is merge readiness.

```text
/goal Make PR <NUMBER_OR_URL> merge-ready.

Outcome: PR has green CI and no unresolved actionable review feedback.
Verification: gh pr checks is green, reviewThreads have no unresolved actionable findings, and any required local checks for fixes pass.
Workflow: invoke compound-engineering:ce-resolve-pr-feedback for review comments. Invoke github:gh-fix-ci for branch-related GitHub Actions failures. After active fixes are pushed, invoke agent-utilities:babysit-pr to keep watching until the PR is merged/closed or a real blocker needs user help.
Do not merge unless explicitly asked.
If blocked: record the unresolved check/thread, URL, evidence, and needed human decision.
```

## Route D: RP-Assisted Goal

Use when the user explicitly wants RP involved or the task has a history of missed context.

```text
/goal Deliver <FEATURE> as a green, review-ready PR using RP for context quality and CE/Thermos for delivery gates.

Outcome: <measurable behavior>.
Verification: <targeted tests/checks>, plus the repo final gate.
Constraints: preserve <critical existing behavior/security/data boundaries>.

Workflow:
1. Use RepoPromptCE context_builder to discover the relevant files and produce a context packet. Export it if it will be handed to another agent.
2. Reconcile the RP context with source-of-truth docs and repo guidance.
3. Invoke compound-engineering:ce-plan using the RP context packet and the feature brief.
4. Implement with native host subagents by default. Use RP agent_run only if explicitly requested, with one bounded slice per agent.
5. After each non-trivial chunk, run targeted checks, React Doctor if React is involved, and the Thermos gate from the sibling Thermos skills. Fix all real findings before commit.
6. Before PR, run ce-simplify-code, optional RP oracle review for risky areas, ce-code-review mode:agent, and ce-test-browser when UI changed.
7. Open/update the PR, then use ce-resolve-pr-feedback, gh-fix-ci, and babysit-pr until CI and review are clean or a real blocker is durable.
8. Run ce-compound mode:headless if the run reveals reusable learning.

Do not let RP replace local tests, Thermos, CE code review, or CI. Complete only when the verification surfaces are green and actionable feedback is resolved or durably recorded.
```

## When To Run Ce-Compound

Run `compound-engineering:ce-compound mode:headless <brief context>` after the work, before final summary, when any of these happened:

- a review/CI failure found a real reusable mistake;
- a new repo pattern or project vocabulary was established;
- a provider, migration, auth, data, or deployment edge case was solved;
- the same kind of churn has happened before and this run clarifies how to avoid it.

Skip it for typo fixes, obvious one-line changes, and purely mechanical docs edits.

## First-Pass Quality Rules

Stop and fix before PR when any of these are true:

- Tests are all mocked around a cross-layer behavior.
- A status, provider intent, email, import, or migration can partially write and then fail without an idempotent retry story.
- The code adds a new helper while an existing helper already does the job.
- The code adds config, UI, worker, queue, or abstraction not required for the current behavior.
- The implementation changes a public/API contract without a test at the boundary.
- The plan or PR cannot name the exact verification surface.
- A React/Next UI diff has not passed the React Gate above.
- A non-trivial chunk skipped the Thermos gate.

When any rule trips, fix it in the chunk before moving on.
