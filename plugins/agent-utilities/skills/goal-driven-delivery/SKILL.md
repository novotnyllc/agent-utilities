---
name: goal-driven-delivery
description: Route one host-local software change or pull-request task through the correct Compound Engineering workflow, with LFG-first implementation delivery, Thermos review gates, React Doctor, PR babysitting, merge proof, and durable learnings. Use for a feature, bug fix, risky refactor, long-running implementation, or existing PR cleanup; use agent-utilities:task-orchestrator for multiple independently resumable tasks or cross-host placement.
---

# Goal Driven Delivery

Use this skill to choose the delivery route and invoke the right existing skills. Do not replace those skills with a long ad hoc prompt.

## Thread title

Read and enforce `../../references/task-titles.md` whenever this skill
activates. Goal Driven Delivery always owns and maintains its task title,
whether invoked directly or by Task Orchestrator. Use its fixed role emoji:

`🎯 <state emoji> <Git issue and/or PR if applicable> <specific focus>`

Continue enforcing that title when a child workflow would otherwise impose a
different naming convention.

## Boundary

Own one host-local implementation or pull-request lane from planning through its requested terminal state. If the outcome needs multiple independently resumable scopes or PRs, or work placed on another host, invoke `agent-utilities:task-orchestrator`; each worker may then use this skill for its single owned lane. Do not duplicate the orchestrator's decomposition, host allocation, cross-lane dependency tracking, or task monitoring here.

Do not archive tasks or mutate Codex runtime when returning locally verified, review-ready, PR-ready, blocked, or owner-action-required work. Leave the task visible and resumable. `Stop`, completed turns, idle or sidebar state, `SubagentStop`, and a completed v2 subagent without a native close or dispose operation are nonterminal; never turn them into cleanup authority. When this is a directed child, Task Orchestrator may separately archive it after terminal acceptance and report verification, followed by read-only `cleanup-codex inspect`.

PR monitoring routes require Compound Engineering with `ce-babysit-pr`
available (v3.20.0 or newer). If that skill is unavailable, stop and ask the
user to update Compound Engineering. Do not fall back to a copied or
hand-rolled watcher.

## Intent And Terminal Routing

Resolve the requested artifact and terminal boundary before invoking a child
skill. An explicit narrower outcome wins over the implementation default:

1. Brainstorm or explore only -> `compound-engineering:ce-brainstorm`; return
   the framing artifact without creating a branch or PR.
2. Plan only -> `compound-engineering:ce-plan`; return the plan without
   starting LFG.
3. Diagnose only -> `compound-engineering:ce-debug`; return findings without
   treating diagnosis as delivery completion.
4. Review-only or watch-only work on an existing PR -> the appropriate CE
   review route or `compound-engineering:ce-babysit-pr`; stop at the requested
   review artifact or settled watch result.
5. Local-only or another user-directed stop -> run the requested checks and
   stop at that boundary.
6. Implement, fix, or ship without a narrower stop ->
   `compound-engineering:lfg` by default.
7. Diagnose-and-fix -> run `ce-debug` to establish the cause, then run LFG;
   the diagnosis is not the terminal state.
8. Fix, drive, or deliver an existing PR -> use the appropriate CE review or
   babysitting route, then continue through merge and post-merge proof.

Re-evaluate that boundary whenever the user gives a later instruction. Preserve
still-valid evidence, but let an explicit later local/return-to-caller stop halt
shipping and let a later authorized ship instruction replace an earlier local
stop unless a higher-priority boundary still applies. Record the reconciled
boundary before invoking another carrier.

An instruction that asks to plan and implement is implementation delivery, so
LFG owns its plan stage. LFG is the child workflow here: it must not invoke
Goal Driven Delivery recursively, and Goal Driven Delivery must not wrap it in
another top-level plan/work route.

For implementation delivery, LFG owns plan -> work -> simplify -> review ->
browser test -> commit/push/PR -> CI and review-settlement, including the
applicable local checks. Goal Driven Delivery owns the authorized merge and
post-merge verification tail. A pushed checkpoint, review-ready branch, open
PR, green CI, merged change, and post-merge proof are separate states. An
explicit user or repository stop still ends the route earlier.

Selecting an implementation-delivery route authorizes the ordinary repository
merge after required checks and reviews pass. Explicit user or repository
approval requirements, merge restrictions, and protected-branch policy still
win.

After LFG returns, execute this tail rather than merely reporting merge
readiness:

1. Consume any bounded follow-up watch LFG returns and continue until review,
   CI, branch currency, and stack state are settled. Do not require a new user
   request.
2. Confirm the review evidence includes an independent Sol High or Sol Max
   pass. If it does not, run that read-only review before merge; fix actionable
   findings with the selected implementation model, preferring Max effort and
   disclosing the actual effort,
   then rerun affected checks and CI.
3. Confirm no explicit hold or approval requirement remains, then merge with
   the repository's configured strategy. For a stack, use `gh-stack` and merge
   in dependency order.
4. Verify the PR reports `MERGED`, record its merge commit, fetch the target
   branch, prove the merge commit is reachable, and run the smallest applicable
   post-merge check or verify the post-merge workflow. Report those artifacts.

Use the repository's supported merge command or API; with GitHub CLI this is
`gh pr merge <pr> --squash|--merge|--rebase` using the repository-selected
strategy. Verify with `gh pr view <pr> --json state,mergedAt,mergeCommit`, then
fetch the base and use
`git merge-base --is-ancestor <merge-commit> origin/<base>` before the
post-merge check.

## Model-routing preflight

Before work or every work-starting steering action, invoke
`agent-utilities:model-routing` with exact contract
`agent-utilities/model-routing/v1`. It is the only public model, effort,
budget, and transport router. Its internal transport phase applies
`../../references/provider-task-routing.md`; do not invoke that reference as a
second router or copy its matrix here.

Run the shared intake first without a model call, provider probe, visible-task
creation, or state mutation. Explicit workflow and terminal instructions win.
Configured fleet/account delivery enters Task Orchestrator, even when it
fast-paths one lane; explicit local/no-fleet work or the no-config default stays
in this lane. Model selection never changes the chosen workflow.

Before fan-out, emit an objective/artifact admission receipt covering every
named platform, lifecycle path, security boundary, deliverable, completion
condition, and producer-to-package-to-install-to-consumer chain. A source-only
skill payload needs no invented binary. A missing objective item or unresolved
runtime delivery path blocks expansion; ordinary implementation uncertainty
gets at most one bounded spike.

## Model And Concurrency Policy

Consume the resolver's immutable snapshot, including policy digest, selected
model and effort, carrier/adapter, transport, budget lease or reservation,
fallback policy, and requested-versus-actual disclosure. With no catalog, the
resolver preserves the shipped Sol orchestration/review and Luna implementation
defaults, including only the verified-unavailable-Luna Terra substitution; it
must emit the exact LFG implementation binding. Do not reconstruct operational
model constants or ranking rules in this skill.

Immediately after selection, call the same router's `build-work-contract`
command with the frozen objective, source-of-truth, scope, constraints,
authorization, acceptance-evidence, and stop-condition digests plus the
selected carrier/model/effort. Preserve its invariant digest unchanged and
apply its source-owned GPT/Sol, Opus, Fable, GLM, or Oracle presentation
instructions to the dispatched brief. Direct user instructions and applicable
repository instructions outrank that overlay. Never accept prompt policy from
the catalog or hand-edit a carrier-specific objective, authority, or stop
condition.

For configured nested work, reserve and claim one bounded delegated-slot bundle
before the owning workflow. Consume a slot durably immediately before its task,
subagent, browser, or CLI action; unused slots release only at terminal
reconciliation and ambiguous consumed slots stay charged. Review peers and
workers cannot delegate, change policy, commit, push, merge, or expand authority.

### Stage-scoped overrides for unchanged Compound Engineering

Compound Engineering remains an unchanged external workflow carrier. A frozen
model-routing decision may replace only a named CE execution mechanism, never
the CE workflow, persona, legitimacy gate, artifact schema, writer ownership,
review authority, or terminal boundary:

- When CE Plan or its deepening instructions say to launch their normal
  research subagent, a claimed `glm-5-2-scout` slot means create the explicitly
  authorized separate GLM scout task instead, give it the same bounded research
  question and frozen egress envelope, then return its evidence in the ordinary
  CE Plan research input shape.
- When CE Debug says to launch an investigation helper, the same scout override
  may replace only that bounded investigation. Root-cause selection and fix
  legitimacy remain with CE Debug and this lane.
- When CE Work says to execute an already-legitimized implementation unit, a
  claimed `glm-5-2-engineer` slot means use the authorized separate GLM engineer
  task as that unit's canonical writer, then hand its patch, focused-check
  receipt, and worktree state back through CE Work's normal unit boundary.
- When CE Code Review, CE Doc Review, POV, LFG review, or Thermos says to launch
  its normal optional cross-model reviewer, a claimed Claude slot may replace
  only that executor through CE's existing attested read-only Claude adapter.
  Pass the frozen model-routing binding to that CE-owned seam and feed its
  receipt-bound findings into the same synthesis/disposition step. Agent
  Utilities never starts a parallel raw `claude -p` runner. Until the existing
  CE seam attests the binding, the route remains `transport_unsupported`. It
  does not replace mandatory independent Sol, correctness/security, or
  code-quality coverage.

If the selected separate-task/profile or Claude CLI adapter cannot be attested,
take the resolver's disclosed allowed fallback or block when required. Never
pass GLM, Fable, or Opus through a Codex selector, silently inherit CE's model,
patch CE source/cache, or claim the override ran from instructions alone.

Run independent work in parallel only when writers, dependencies, transport,
and reservations do not overlap. Keep one canonical writer per mutable scope.

## GitHub Checkpoints And Stacked Delivery

When a writable GitHub remote exists, push active lane or integration branches
at useful checkpoints so another agent or machine can resume. A checkpoint
push does not open a PR, trigger review, or imply completion. Keep one named
integration owner per project and one named writer per mutable lane.

Before starting LFG, establish the named branch and its writable upstream. Run
a lane-owned checkpoint monitor beside LFG: when the canonical branch advances
to a clean, stable commit created by the work stage, push that commit without
opening a PR. Stop the monitor when LFG enters commit/push/PR or returns. The
monitor never edits, commits, stages, or decides readiness; it only publishes
already committed lane state and records branch, commit, and remote evidence.

When dependent delivery is selected against a GitHub upstream, use `gh-stack`.
If its GitHub extension or companion skill is missing, install both and then
verify the capability before continuing, without prompting:

```bash
gh extension install github/gh-stack --force
gh skill install github/gh-stack --all --agent codex --scope user --force
gh stack --version
gh skill list --agent codex --scope user
```

On a host that also runs Claude Code, additionally run and verify:

```bash
gh skill install github/gh-stack --all --agent claude-code --scope user --force
gh skill list --agent claude-code --scope user
```

Use `gh-stack` for the dependent PR chain; keep unrelated PRs independent.

## Lane contract and verification cadence

When directed by Task Orchestrator, acknowledge its frozen paths, schemas,
ordered fields, permissions/ACLs, ownership, hashes, and acceptance checks
before writing. For a standalone lane with parallel writers, establish the same
contract locally. Keep one canonical writer per shared file and run the
thinnest real seam canary before downstream code or fixtures expand.

Use targeted checks in the edit loop. Run a component gate only when its input
hash changes, then run one full integration gate after all writers freeze;
rerun only evidence invalidated by a relevant shared-code fix. Preserve the
command, toolchain, input/content hashes, result, and timestamp. Give one
independent reviewer per frozen lane those receipts and require focused
reproductions instead of another full-suite run when the evidence still
matches. Existing required React, Thermos, CE review, hosted CI, and
post-merge gates still apply; this cadence prevents duplicate runs, not gates.

At kickoff, verify the preferred carrier/model and exact CI-parity toolchain
once. Record one disclosed fallback only for an explicitly optional capability;
a carrier or model required by the selected route blocks instead. Classify
native gates as hosted, locally runnable native, interactive-elevation, or
recoverable-host; one class never proves another. At seam freeze and before
integration, surface disproportionate line growth, execution time, or fixture
cost, then simplify or rescope. After interface convergence, freeze scope and
reject adjacent abstractions or features unless the user explicitly reopens it.

### Objective, artifact, and simplification gates

Before a substantial implementation unit, name its observable user operation
and the required secondary state that proves the result reached the real
consumer. A new platform, manager, carrier, or privileged capability needs one
such end-to-end exemplar before sibling expansion. Parser, build, broker, or
simulated-target success alone is not that proof.

Before scaling a compiled/native helper, service, daemon, runtime payload, or
material complexity increase, write a simplification receipt comparing an
existing helper, stdlib, platform API/CLI/module, and repository primitive. Name
the exact required security property a simpler choice loses and prove the
chosen artifact's build, package, install, and invocation chain. If that chain
or justification is unresolved, stop after one bounded feasibility spike.

Implement a coherent vertical chunk before pausing: the smallest behaviorally
complete slice with a focused check that can fail for that behavior. A cheap
boundary canary runs inside the chunk only when it can change the next step.
At the boundary run the minimum focused checks; do not rerun an unchanged check
because another file was edited. Freeze full/native/hosted/lifecycle/release
and review inputs, run each required gate once, and invalidate only receipts
whose dependency hash changed.

### Hosted feedback, restart, and completion ledger

Treat hosted CI and remote/native matrices as frozen-input proof, not the
default debugger. After the first opaque, silent, or late failure, isolate the
smallest stage, add bounded secret-free progress evidence, and move the cheapest
decisive check before unrelated setup. Permit at most one instrumented
diagnostic push for that unresolved stage; every later push needs new evidence.

Keep `executionHost` separate from `targetPlatform`; choose shell, filesystem,
process, permission, and utility semantics from the real execution host while
policy and expected behavior come from the target. WSL never proves native
Windows.

Maintain a compact restart receipt containing plan digest, objective epoch,
governing skill/package digest, active lanes, frozen inputs, decisions, and
reusable evidence. Resume at the next invalidated action rather than rereading
the repository or transcript. A skill or objective digest change requires
reconciliation; a local delta invalidates only dependent evidence.

Render status from one terminal-gate ledger: implementation units, changed
repositories, frozen local checks, native/hosted/lifecycle gates, review,
Git/PR/merge state, release coupling, source pins, and local/remote clean-state
proof. `No currently known implementation defects` is not terminal completion,
and `only X remains` is allowed only when every other gate is satisfied,
intentionally excluded, or explicitly blocked.

Report critical-path wall time, active-agent time, external wait, and tool time
separately from model tier, token/cost estimate, retries, and duplicated work.
Parallelism may lower wall time while increasing aggregate model cost; never
use either metric as permission to weaken final proof.

## Evidence And Blockers

Report the selected route, terminal state, checks, review or CI evidence, and
branch/PR/merge evidence that applies. If blocked, stop with the exact failing
gate, evidence, and next human decision while leaving the work resumable.

## Skill Router

Resolve skill names against the host's available-skills list before invoking. Usual routes:

- `compound-engineering:lfg`: full plan -> work -> simplify -> review -> browser test -> commit/push/PR -> CI and review settlement; Goal Driven Delivery owns authorized merge and post-merge proof.
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

Use the immutable model-routing decision and disclose its requested and actual
model, effort, adapter, transport, reason, and fallback. The built-in policy
owns the no-config defaults and exact LFG binding. Use native host subagents
only when the selected model is exposed by that selector and the fork/effort
controls are attested; non-selector routes use their fixed stage override.

## Thermos Gate

For every Thermos gate, invoke or read the sibling skills in this plugin:

- `agent-utilities:thermos`: orchestration and synthesis instructions.
- `agent-utilities:thermo-nuclear-review`: correctness, breakage, security, devex, and feature-leak audit.
- `agent-utilities:thermo-nuclear-code-quality-review`: maintainability, structure, abstraction, and code-health audit.

If the host does not expose plugin-qualified skill names, read the sibling `../thermos/SKILL.md`, `../thermo-nuclear-review/SKILL.md`, and `../thermo-nuclear-code-quality-review/SKILL.md` files directly.

Run the two review passes in parallel when the host supports subagents. Give both reviewers the same scoped diff and enough source context to evaluate without guessing. Synthesize their findings, deduplicate overlaps, fix every real finding before committing the chunk, and record any non-fix with evidence.

Do not treat Thermos as a substitute for tests, React Doctor, CE code review, or hosted CI. It is the pre-commit "would review have caught this?" gate.

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

For an existing-PR delivery route, Goal Driven Delivery owns the merge and
post-merge tail after babysitting returns a settled, mergeable result. A
review-only or watch-only request stops at its narrower boundary.

Use `ce-resolve-pr-feedback` or `ce-debug` directly only for an explicitly
one-shot cleanup or diagnosis that does not need continuous monitoring.

On an LFG route, do not invoke `ce-babysit-pr` separately: LFG owns its
pipeline invocation. Invoke `ce-babysit-pr` from this skill only on non-LFG
routes that create or operate on a PR.

## Route Selection

Pick one route.

| Situation | Route |
| --- | --- |
| Explicit brainstorm-only request | `compound-engineering:ce-brainstorm`, then stop with the framing artifact |
| Explicit plan-only request | `compound-engineering:ce-plan`, then stop with the plan artifact |
| Explicit diagnosis-only request | `compound-engineering:ce-debug`, then stop with findings |
| Generic implementation, bug fix, or ship request | `compound-engineering:lfg`, then Goal Driven Delivery owns merge and post-merge proof |
| Explicit local-only implementation request | `compound-engineering:ce-plan` plus `compound-engineering:ce-work`, then stop after the requested local checks |
| Explicit request for Thermos review after each chunk | Goal + chunked hardening loop |
| Existing PR review or watch only | Appropriate CE review route or `compound-engineering:ce-babysit-pr`, then stop at the requested artifact |
| Existing PR to fix, drive, or deliver | Appropriate CE review route or `compound-engineering:ce-babysit-pr`, then Goal Driven Delivery owns merge and post-merge proof |
| One-shot review cleanup | `compound-engineering:ce-resolve-pr-feedback` |
| One-shot CI or code failure | `compound-engineering:ce-debug` |
| Explicit direct tiny or local-only edit | Direct edit + targeted check, skip LFG and Thermos |
| Recently solved issue with reusable lesson | `compound-engineering:ce-compound mode:headless depth:full` |

Default generic implementation and bug-fix work to LFG. Use `ce-plan` and
`ce-work mode:return-to-caller <plan-path>` only for explicit plan/local-only
boundaries. Neither route archives a task or mutates runtime. Use chunked
hardening only when the user asks for Thermos before each chunk. Risky work
otherwise uses the standard LFG route with stronger targeted verification and
a final Thermos gate where applicable.

When invoked by Task Orchestrator, consume its explicit frozen contract rather
than inferring one from transcript history. A ready plan with an explicit
local/return-to-caller boundary routes through `compound-engineering:ce-work
mode:return-to-caller`; unconstrained end-to-end implementation routes through
`compound-engineering:lfg`. Task Orchestrator owns that routing decision and
this lane passes the contract to the selected external carrier without
modifying or patching the carrier.

## Route A: Standard LFG Delivery

Use for normal in-the-loop feature and bug-fix work.

LFG invocation template (the routing line is stage-scoped control data, not
product-plan content):

```text
Implementation routing: apply the claimed `agent-utilities/model-routing/v1` snapshot verbatim. Pass its emitted LFG implementation binding only at the ce-work seam. Apply any named stage-scoped override above without changing the CE workflow, persona, artifact schema, authority, or terminal boundary. Disclose requested and actual model, effort, adapter, transport, and fallback; do not reconstruct a model constant here.

Deliver <FEATURE> through merge and post-merge proof.

Outcome: <measurable behavior>.
Verification: <targeted tests/checks>, plus the repo final gate.
Constraints: preserve <critical existing behavior/security/data boundaries>.

Invoke compound-engineering:lfg for implementation delivery. Inspect its
structured handoff, verify the applicable local evidence, and continue through
authorized merge and post-merge proof. LFG owns its simplify, CE review,
browser, commit/push/PR, CI, and review-settlement stages. Do not add a second
top-level plan/work route or a second babysitter. If the user explicitly
requested local-only work, invoke compound-engineering:ce-plan then
compound-engineering:ce-work mode:return-to-caller with the resulting plan
instead. Fix eligible findings and rerun affected checks. If blocked, report
the exact gate, evidence, and next human decision needed while leaving the
work resumable. If the work produces a reusable lesson or fixes a repeated
failure mode, invoke compound-engineering:ce-compound mode:headless depth:full
before the final summary.
```

For implementation delivery, invoke `compound-engineering:lfg` directly with
the feature brief. LFG owns its fixed plan, work, simplify, review, browser,
commit/push/PR, and `ce-babysit-pr mode:pipeline` stages. Do not wrap it in
`/goal`, insert Thermos into its internal order, or start a duplicate
`ce-babysit-pr mode:pipeline` run. When LFG returns an explicit follow-up watch
invocation, run exactly that continuation, then execute the merge and
post-merge tail above. If Thermos must run between chunks, use Route B.

## Route B: Chunked Hardening Goal

Use only when the user explicitly requests Thermos review after each
implementation chunk.

Goal template:

```text
/goal Deliver <FEATURE> with chunk-level hardening through merge and post-merge proof.

Outcome: <measurable behavior>.
Verification: <targeted tests/checks>, plus the repo final gate.
Constraints: preserve <critical existing behavior/security/data boundaries>.

Workflow:
1. Invoke compound-engineering:ce-plan. Do not code until an implementation-ready plan exists.
2. Implement one vertical chunk at a time using the selected implementation model and existing repo patterns; prefer Max effort, disclose the actual model and effort, and keep one canonical writer for the chunk.
3. After each non-trivial chunk, run the smallest relevant checks. If React/Next UI is involved, run the React Doctor gate. Run the Thermos gate using the sibling Thermos skills, fix all real findings, and inspect the diff. Commit explicit paths only when the user authorized commits.
4. Before final review, invoke compound-engineering:ce-simplify-code unless the diff is docs-only or trivial.
5. If the branch is UI-heavy, run the React Doctor gate again after simplify and before CE code review.
6. Invoke compound-engineering:ce-code-review with mode:agent and the plan path. Apply all eligible findings.
7. Invoke compound-engineering:ce-test-browser with mode:pipeline when UI/browser behavior changed.
8. Stop with a locally verified, review-ready tree only for an explicit local-only stop. Otherwise continue through the delivery tail.
9. For implementation delivery, invoke compound-engineering:ce-commit-push-pr, then invoke compound-engineering:ce-babysit-pr with the resulting PR URL. Let it own feedback, CI, branch currency, durable watch state, and the settled merge-readiness decision; Goal Driven Delivery owns authorized merge and post-merge proof.
10. Invoke compound-engineering:ce-compound mode:headless depth:full when the run discovers a reusable pattern, repeated failure mode, or durable project vocabulary.

Complete a local-only route when its verification surfaces are green. Complete
implementation delivery only when CI is green, actionable PR feedback is
resolved or durably recorded, the authorized merge is complete, and
post-merge proof passes. If blocked, report the exact gate, evidence, and next
human decision needed.
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
