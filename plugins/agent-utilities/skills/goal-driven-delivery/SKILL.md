---
name: goal-driven-delivery
description: Route and harden one host-local software change or pull-request lane with goal-mode execution, Compound Engineering, Thermos review gates, RepoPromptCE context building, React Doctor, PR babysitting, and durable learnings. Use for a feature, bug fix, risky refactor, long-running implementation, or existing PR cleanup; use delivery-director for multi-lane or cross-host delivery.
---

# Goal Driven Delivery

Use this skill to choose the delivery route and invoke the right existing skills. Do not replace those skills with a long ad hoc prompt.

## Boundary

Own one host-local implementation or pull-request lane from planning through its requested terminal state. If the outcome needs multiple independently resumable scopes or PRs, or work placed on another host, invoke `agent-utilities:delivery-director`; each worker may then use this skill for its single owned lane. Do not duplicate the director's decomposition, host allocation, cross-lane dependency tracking, or task monitoring here.

Do not archive tasks or mutate Codex runtime when returning locally verified, review-ready, PR-ready, blocked, or owner-action-required work. Leave the task visible and resumable. `Stop`, completed turns, idle or sidebar state, `SubagentStop`, and a completed v2 subagent without a native close or dispose operation are nonterminal; never turn them into cleanup authority. When this is a directed child, Delivery Director may separately archive it after terminal acceptance and report verification, followed by read-only `cleanup-codex inspect`.

PR monitoring routes require Compound Engineering with `ce-babysit-pr`
available (v3.20.0 or newer). If that skill is unavailable, stop and ask the
user to update Compound Engineering. Do not fall back to a copied or
hand-rolled watcher.

## Skill Router

Resolve skill names against the host's available-skills list before invoking. Usual routes:

- `compound-engineering:lfg`: full plan -> work -> simplify -> review -> browser test -> commit/push/PR -> CI loop.
- `compound-engineering:ce-plan`: implementation-ready plan before chunked work.
- `compound-engineering:ce-work`: plan execution when not using LFG.
- `compound-engineering:ce-simplify-code`: behavior-preserving simplification before final review.
- `compound-engineering:ce-code-review`: pre-PR or pre-rereview code review.
- `compound-engineering:ce-test-browser`: browser/UI verification.
- `compound-engineering:ce-commit-push-pr`: commit, push, and PR creation.
- `compound-engineering:ce-babysit-pr`: continuous PR monitoring and repair across review feedback, CI, branch currency, and managed stacks.
- `compound-engineering:ce-resolve-pr-feedback`: focused one-shot review cleanup when continuous monitoring was not requested.
- `compound-engineering:ce-debug`: focused one-shot CI or code failure diagnosis.
- `compound-engineering:ce-compound`: durable learning capture after a solved problem.
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

Use `compound-engineering:ce-babysit-pr` whenever the request is to watch,
babysit, or drive an open GitHub PR toward merge readiness. It owns the watch
loop and delegates feedback fixes to `ce-resolve-pr-feedback` and CI fixes to
`ce-debug`; do not pre-run or duplicate those stages.

Use `mode:pipeline` when another workflow needs a bounded, non-interactive
result. Use the default interactive mode when the user asks to keep watching
through review. Babysitting never authorizes merging.

Use `ce-resolve-pr-feedback` or `ce-debug` directly only for an explicitly
one-shot cleanup or diagnosis that does not need continuous monitoring.

On an LFG route, do not invoke `ce-babysit-pr` separately: LFG owns its
pipeline invocation. Invoke `ce-babysit-pr` from this skill only on non-LFG
routes that create or operate on a PR.

## Route Selection

Pick one route.

| Situation | Route |
| --- | --- |
| New scoped feature or bug fix with the user in the loop | `compound-engineering:ce-plan`, then `compound-engineering:ce-work mode:return-to-caller` |
| Explicit autonomous ship-to-PR or LFG request | `compound-engineering:lfg` |
| Explicit request for Thermos review after each chunk | Goal + chunked hardening loop |
| Unknown or historically missed code context | RP scout, then the standard or explicitly requested chunked route |
| Explicit RepoPromptCE experiment | RP scout/oracle/agent route with bounded ownership, then normal CE/Thermos/CI gates |
| Existing PR to drive toward merge readiness | `compound-engineering:ce-babysit-pr` |
| One-shot review cleanup | `compound-engineering:ce-resolve-pr-feedback` |
| One-shot CI or code failure | `compound-engineering:ce-debug` |
| Docs-only or tiny diff | Direct edit + targeted check, skip LFG and Thermos |
| Recently solved issue with reusable lesson | `compound-engineering:ce-compound mode:headless depth:full` |

Default to `ce-plan` then `ce-work mode:return-to-caller <plan-path>` for normal
feature work so this skill retains ownership of the remaining local gates and
does not silently push, open a PR, archive a task, or mutate runtime. Use LFG
only when the user explicitly asks for autonomous delivery through an open PR
or invokes LFG. Use chunked hardening only when the user asks for Thermos before
each chunk. Risky work otherwise uses the standard route with stronger targeted
verification and a final Thermos gate.

## Route A: Standard Plan And Work

Use for normal in-the-loop feature and bug-fix work.

Goal template:

```text
/goal Implement and locally verify <FEATURE>.

Outcome: <measurable behavior>.
Verification: <targeted tests/checks>, plus the repo final gate.
Constraints: preserve <critical existing behavior/security/data boundaries>.

If the right files or architecture are not obvious, first use RepoPromptCE context_builder to produce a curated context packet and feed that into planning. Invoke compound-engineering:ce-plan, then invoke compound-engineering:ce-work mode:return-to-caller with the resulting plan. Inspect its structured return. Run compound-engineering:ce-simplify-code unless the diff is docs-only or trivial, the React Gate when applicable, the Thermos Gate for risky work, compound-engineering:ce-code-review mode:agent with the plan path, and compound-engineering:ce-test-browser mode:pipeline when browser-visible behavior changed. Fix eligible findings and rerun affected checks. Stop with a locally verified, review-ready tree unless the user explicitly requested shipping. If shipping was requested, invoke compound-engineering:ce-commit-push-pr and then compound-engineering:ce-babysit-pr with the resulting PR URL.
If the work produces a reusable lesson or fixes a repeated failure mode, invoke compound-engineering:ce-compound mode:headless depth:full before the final summary.
If blocked: report the exact failing gate, evidence, and next human decision needed.
```

When the user explicitly requests autonomous delivery through an open PR,
invoke `compound-engineering:lfg` directly with the feature brief. LFG owns its
fixed plan, work, simplify, review, browser, commit/push/PR, and
`ce-babysit-pr mode:pipeline` stages. Do not wrap it in `/goal`, insert Thermos
into its internal order, or start another babysitter automatically afterward.
LFG may hand back an interactive watch invocation; a later explicit watch
request is a new existing-PR route. If Thermos must run between chunks, use
Route B.

## Route B: Chunked Hardening Goal

Use only when the user explicitly requests Thermos review after each
implementation chunk.

Goal template:

```text
/goal Implement and locally verify <FEATURE> with chunk-level hardening.

Outcome: <measurable behavior>.
Verification: <targeted tests/checks>, plus the repo final gate.
Constraints: preserve <critical existing behavior/security/data boundaries>.

Workflow:
1. If context is uncertain or this area has churned before, run RepoPromptCE context_builder first and pass the exported context into planning.
2. Invoke compound-engineering:ce-plan. Do not code until an implementation-ready plan exists.
3. Implement one vertical chunk at a time using existing repo patterns and native host subagents only when useful. Use RP agents only when explicitly requested, with bounded ownership.
4. After each non-trivial chunk, run the smallest relevant checks. If React/Next UI is involved, run the React Doctor gate. Run the Thermos gate using the sibling Thermos skills, fix all real findings, and inspect the diff. Commit explicit paths only when the user authorized commits.
5. Before final review, invoke compound-engineering:ce-simplify-code unless the diff is docs-only or trivial.
6. If the branch is UI-heavy, run the React Doctor gate again after simplify and before CE code review.
7. For risky chunks, optionally use RepoPromptCE oracle_send mode:review on the selected diff/files before CE code review. Apply only findings that survive normal code/test inspection.
8. Invoke compound-engineering:ce-code-review with mode:agent and the plan path. Apply all eligible findings.
9. Invoke compound-engineering:ce-test-browser with mode:pipeline when UI/browser behavior changed.
10. Stop with a locally verified, review-ready tree unless the user explicitly requested shipping.
11. If shipping was requested, invoke compound-engineering:ce-commit-push-pr, then invoke compound-engineering:ce-babysit-pr with the resulting PR URL. Let it own feedback, CI, branch currency, durable watch state, and the settled merge-readiness decision.
12. Invoke compound-engineering:ce-compound mode:headless depth:full when the run discovers a reusable pattern, repeated failure mode, or durable project vocabulary.

Complete locally when the verification surfaces are green. When shipping was
requested, complete only when CI is green and actionable PR feedback is
resolved or durably recorded. If blocked, report the exact gate, evidence, and
next human decision needed.
```

The chunk loop is the churn reducer. It forces local review before the branch accumulates enough mistakes for CI and GitHub review to become the first real QA pass.

## When To Run Ce-Compound

Run `compound-engineering:ce-compound mode:headless depth:full <brief context>`
after the work, before final summary. This keeps the full session-history probe,
overlap research, and grounding validation without blocking the orchestration
or editing instruction files without consent. Run it when any of these
happened:

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
- Risky work skipped its final Thermos gate, or an explicitly chunk-hardened route skipped a chunk gate.

When any rule trips, fix it in the chunk before moving on.
