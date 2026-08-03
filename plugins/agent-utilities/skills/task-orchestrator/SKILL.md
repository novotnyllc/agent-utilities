---
name: task-orchestrator
description: Orchestrate complex objectives across independently resumable tasks, projects, hosts, pull requests, and dependencies while remaining available as the control task. Use when an objective needs multiple tasks, parallel or staged execution, separate ownership, cross-project work, or cross-host placement; do not use for one bounded host-local task.
---

# Task Orchestrator

Orchestrate the objective; never execute delegated task work. Remain available
to the user and delegate execution to visible tasks or bounded subagents.

## Thread title

Read and enforce `../../references/task-titles.md` whenever this skill
activates. Use this skill's fixed role emoji for the orchestrator task:

`💼 <state emoji> <Git issue and/or PR if applicable> <specific focus>`

Task Orchestrator also owns the titles of visible child tasks it creates. Use
`🎯` for a Goal Driven Delivery child and `🖥️` for a Fleet Readiness child,
followed by the shared state, Git reference, and focus fields. A child workflow
that owns its own title must continue enforcing the shared policy after
dispatch.

## Boundary

Use this skill when an objective has two or more independently resumable tasks
or must place a task on another host. One task may use several bounded local
subagents without requiring this skill. For one host-local software delivery
task, use `agent-utilities:goal-driven-delivery` directly; for one bounded
non-delivery task, use its appropriate skill or native tools directly.

Route each child by its own outcome. Software implementation and pull-request
delivery use Goal Driven Delivery. Research, operations, review, documentation,
and decision tasks use their appropriate skills directly. A child invokes Task
Orchestrator only when its assignment itself contains multiple independently
resumable tasks; otherwise it executes the assignment and must not create an
orchestration loop.

The orchestrator is scoped to the requested objective, not to one project or
machine. It may coordinate tasks within one project or across several projects
and repositories. For cross-project delivery, give each project an explicit
integration and baseline owner. Give each mutable task one canonical writer
and its own branch or PR, validation boundary, and handoff; keep shared
integration files in one named task. Record dependencies without merging
ownership.

## Propagate the software-delivery policy

The orchestrator owns the task graph and global concurrency budget. Use Sol
High by default and Sol Max for cross-cutting,
release-critical, security-sensitive, multi-repository, or otherwise complex
work. A delegated software-delivery task invokes
`agent-utilities:goal-driven-delivery`, which routes explicit brainstorm,
plan, diagnosis, review, and local-only outcomes to their narrower CE routes
and defaults generic implementation or bug-fix delivery to LFG.

- Assign most implementation work to Luna. Prefer Max effort and require the
  child to disclose the actual effort used.
- Assign independent primary review to a separate Sol High or Sol Max context
  by risk.
- Use Fable 5 only through a supported CE cross-model review path that verifies
  the model; otherwise use an independent Sol reviewer and disclose the
  fallback.
- Run independent research, implementation, and review in parallel when safe.
  Keep one canonical writer per mutable scope and serialize overlapping writes,
  dependent stack segments, and integration operations.

Pass this policy only to software-delivery children. Give every child its
objective, owner, dependencies, terminal evidence, and title contract. Allocate
each child an explicit concurrency allowance and nested-subagent ceiling from
the orchestrator's global budget; a child must not exceed either or assume it
owns the host. Rebalance allowances when a child blocks or completes. Do not
send execution back into the orchestrator.

Before dispatch, verify that the preferred carrier, model, tools, and skills
are actually exposed. A tool absent from the eagerly listed surface is unknown,
not unavailable. When a deferred or lazy catalog is available, eager absence
remains unknown until the exact capability search completes. Before fallback or
blocking, search that host catalog for the exact capability (for example, app
`list_projects`, `create_thread`, or `wait_threads`) and call its read-only
discovery operation when available. If the exact catalog or search is
unavailable, record `capability_discovery_unavailable`; a required route blocks
because discovery cannot complete, while an explicitly optional capability
selects its one disclosed supported fallback. Record `capability_ready` only
when discovery confirms the route. Record failures as `tool_surface_missing`,
`host_offline`, `saved_project_missing`, `task_creation_failed`, or
`executor_mismatch`. WSL-only evidence for native Windows records
`native_evidence_unavailable`, not `executor_mismatch`, and cannot satisfy the
route. Record that receipt in the ledger.
If an explicitly optional capability is unavailable,
choose its supported fallback once, disclose it to all affected children, and
keep that choice stable unless its capability changes.
A capability required by the selected route
blocks dispatch only after discovery proves absence, discovery is unavailable,
or the operation fails.
Never silently relabel a fallback as the preferred route.

## Freeze shared contracts before parallel work

For every coupled seam, name one integration owner and one canonical writer for
each shared file. Freeze the exact paths, schemas, ordered fields,
permissions/ACLs, ownership, and acceptance checks before parallel writers
expand. Bind the contract to content hashes and require both sides of the seam
to acknowledge that exact contract. Do not dispatch dependent implementation
until both acknowledgements are recorded.

Run the thinnest end-to-end seam canary immediately after the contract freezes,
before downstream units or fixtures expand. Once the interface converges,
freeze scope: reject adjacent abstractions, features, and cleanup unless they
are required by the accepted contract or a later user instruction changes the
objective.

At kickoff, classify every terminal gate separately as hosted, locally runnable
native, interactive-elevation, or recoverable-host. Name the owner and evidence
source for each class; never infer one class from another. Verify exact local
toolchain and CI parity early, once, then reuse the resulting cache and receipt.

## GitHub preflight, checkpoints, and stacks

When a writable GitHub remote exists, require the software-delivery owner to push useful
active-branch or integration-branch checkpoints so work is resumable across
agents and machines. A checkpoint is not a review-ready branch, open PR, green
CI result, merge, or completion signal. The orchestrator records the checkpoint
evidence but never pushes it itself.

When dependent delivery is selected against a GitHub upstream, use `gh-stack`.
If its GitHub extension or companion skill is missing, install both and verify
the capability before dispatching, without prompting:

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

The owned software-delivery task uses `gh-stack` for the dependent PR chain; unrelated PRs stay
independent. The orchestrator retains integration ownership and verifies the
result, while the child performs the implementation and Git operations.

## Direct the work

1. Define the outcome, constraints, dependencies, risks, and terminal evidence.
2. Split work into independently verifiable scopes. Assign exactly one canonical writer to each scope and shared file; make other agents reviewers or give them non-overlapping files and decisions.
3. Use visible tasks for durable, user-visible, separately resumable work. Use bounded subagents for contained research, review, or execution within a task.
4. Create every task or subagent with no inherited context when supported, otherwise the minimum possible. Pass only its objective, owner, scope, title/concurrency/readiness contract, constraints, dependencies, acceptance criteria, and required evidence. For mutable seams, include exact owned files and frozen hashes. Require concise milestone output. Never forward the orchestrator's transcript or conclusions.
5. Require child tasks to delegate their own separable work to fresh, minimal-context subagents when useful. Keep their canonical-writer boundaries explicit.
6. Monitor all work, answer agent questions promptly from authoritative evidence, resolve ownership conflicts, and reassign stalled work. Keep directing while execution proceeds.
7. Synthesize the child evidence and verify the combined objective. Delegate
   any integration, review, validation, or repair execution to named owners;
   do not implement, test, commit, push, or merge in the orchestrator.
8. When the user changes the objective, preserve still-valid evidence, revise
   or cancel only affected children, and propagate the new dependency and
   terminal contracts without restarting unaffected work. Reconcile the
   shipping boundary explicitly: a later local/return-to-caller instruction
   stops shipping, while a later authorized ship instruction replaces an
   earlier local stop unless a higher-priority boundary still forbids it.

Do not ask the user about reversible implementation details. Ask only when a choice materially changes direction, risk, cost, or wall-clock time.

Use native task, subagent, and thread operations. Do not create orchestration or monitoring scripts unless repeated deterministic value clearly justifies them.

## Test and review cadence

Use targeted tests in each edit loop. Run a component gate only when that
component's content hash changes. After all writers acknowledge the frozen
seams, run one full integration gate; rerun it only when a relevant shared-code
fix invalidates that evidence. Preserve each receipt with the command,
toolchain, input/content hashes, result, and timestamp so downstream reviewers
can reuse rather than recreate it.

Assign one independent reviewer per frozen lane. Give the reviewer the frozen
contract and prior hash-bound receipts; require focused reproductions for risks
or changed code, not another full-suite run when the integration receipt still
matches. The integration owner resolves cross-lane findings and decides which
evidence was invalidated.

At each seam freeze and before the integration gate, compare line growth,
execution time, and fixture cost with the plan. Surface disproportionate growth
before accepting more implementation; do not let a large solution accumulate
silently.

## Create tasks with terminal goals

Decide whether the orchestrator and each visible child benefit from persistent
goal tracking. When the host supports it, use `/goal` for long-running,
multi-stage, risky, dependency-heavy, or otherwise interruption-prone work
where durable outcome tracking improves completion. Omit `/goal` when
unsupported and for short, bounded tasks whose acceptance can be completed in
one pass without persistent tracking.

Use `/goal` for completion conditions. When progress depends on external events, use `/loop` in Claude Code or an in-chat scheduled task in Codex for time-based polling; do not schedule ordinary worker progress.

Every visible task still needs terminal acceptance criteria that can end the
task, including evidence and cleanup, and the two-emoji title required above.

Use this prompt shape. When persistent goal tracking is both useful and supported, prefix the first line with `/goal `; otherwise use the first line as written:

```text
<one-sentence outcome>

Title: <role emoji> <state emoji> <PR/issue if any> <specific description>
Assignment: <verified host; model class; effort; brief rationale>
Concurrency: <global budget; this task's allowance; nested-subagent ceiling>
Readiness: <project identity/baseline; runtime/plugin/skill evidence>
Objective: <single owned result>
Scope: <owned project/repository, files, system, PR, or decision>
Constraints: <safety, compatibility, exclusions, time/budget>
Dependencies: <required inputs and owners>
Execution: Delegate separable work only to bounded, fresh minimal-context subagents given objective, scope, constraints, and required evidence. Keep one canonical writer per scope.
Acceptance:
- <observable result>
- <required checks and evidence>
- <docs/tests owned by this scope>
- Remove only unused clean worktrees created by this task and only its owned merged, closed, or abandoned topic refs.
Report: <final evidence, artifacts, cleanup, blockers, and remaining handoff; the orchestrator verifies this before archive>
```

Do not include proposed answers, hidden diagnoses, or unrelated history.

## Select model and effort deliberately

Choose per task from complexity, risk, budget, required quality, and wall-clock target. Re-evaluate when evidence shows the assignment is too weak or unnecessarily expensive.

| Work | Model class | Effort |
|---|---|---|
| Lookup, inventory, mechanical bounded edit | Fast/economical | Low |
| Most implementation work in an owned software-delivery task | Luna required | Max preferred; disclose actual effort |
| Orchestrator or Goal Driven Delivery orchestration | Sol | High by default; Max for complex coordination |
| Independent primary review | Separate Sol | High or Max by risk |
| Supported cross-model review | Fable 5 when the CE path verifies it; otherwise separate Sol review | High or xhigh |
| Security, data loss, release-critical design, final adversarial review | Strongest available | High or xhigh |

Prefer multiple cheap independent reviews over one expensive agent only when scopes do not overlap and synthesis has a named owner. Do not spend high effort on deterministic mechanical work.

## Prepare distributed hosts

Orchestrator-side subagents run on the orchestrator's host unless the native tool explicitly supports host placement. For Codex work on another machine, use a visible task or thread on that destination's saved project; it may use bounded host-local subagents. For other harnesses, use their native remote-task mechanism when available and report unsupported placement rather than treating SSH command execution as a remote agent.

Before cross-host dispatch, resolve the participating hosts and invoke the installed Machine Utilities skills when available:

- `machine-utilities:fleet-projects` verifies repository identity, checkout state, the required project baseline, and Codex saved-project readiness.
- `machine-utilities:fleet-agents` verifies agent runtimes, plugin versions, skill hashes and provenance, duplicate providers, and required logical capabilities.
- `machine-utilities:fleet-inventory` supplies a preserved read-only fleet snapshot; use `machine-utilities:fleet-auth` only when a task requires authenticated tooling.

Treat missing projects, unavailable saved projects, stale required runtimes or
plugins, inconsistent required skills, unhealthy required authentication, and
unreachable hosts as Fleet Readiness prerequisites. Delegate inventory and any
user-approved reconciliation to Machine Utilities; do not reproduce its
scripts or mutate hosts directly. Respect its plan, approval, manager-ownership,
and post-inventory requirements. Dispatch only after every assigned host has
evidence for its exact project and capabilities. When the outcome requires
fleet-wide parity, verify every configured node, not only the selected workers.
If Machine Utilities is unavailable, require equivalent read-only evidence and
report consistency as unverified rather than guessed.

## Allocate hosts

Treat host priority as configurable. Unless the user specifies another order:

1. Filter to hosts with the required repository access, plugins, skills, credentials, platform, and toolchain.
2. Verify those requirements and the required project baseline on the chosen host before dispatch.
3. Prefer an idle capable host, then the least-utilized capable host.
4. Break ties by data locality and expected wall-clock time.

Never dispatch first and discover required capabilities later. Reassign when a host is unhealthy, overloaded, or missing a dependency.

## Keep delivery independent

- Give each PR its own implementation, tests, documentation, review, validation, and cleanup.
- Publish documentation as soon as its owning PR is ready; never wait on unrelated PRs.
- Record dependencies explicitly. A downstream task may wait only on the specific artifact it consumes.
- Prevent concurrent writers to the same scope. Transfer ownership explicitly before reassignment.
- Let reviewers inspect evidence or diffs without becoming an unannounced second writer.
- Keep integration branches and checkpoint pushes under their named owners;
  do not open a PR merely because a checkpoint is available.

## Monitor to terminal completion

Maintain a compact ledger for every task: owner, host, scope, status, dependency, last evidence, next action, and terminal criteria.

Planning, brainstorming, diagnosis-only, and review-only tasks are terminal at
their requested artifact. Software implementation delivery is terminal only
after the child's LFG handoff has settled review and CI, the authorized merge has
completed, and post-merge verification proves the integrated outcome. The
orchestrator verifies that evidence and the integrated result; it never performs
the child's execution.

In user-facing updates, link to each task when possible; otherwise use its stable title. Do not substitute raw thread IDs for readable task names unless an exact ID is needed for troubleshooting or handoff.

On each monitoring pass:

1. Collect progress without replaying unchanged status.
2. Answer questions or obtain the one material user decision.
3. Unblock dependencies, replace failed assignments, and trigger the next ready work.
4. Demand concrete evidence for claimed completion.
5. Verify the final report and terminal acceptance, then retain its fixed role emoji and change its state emoji to `✅`.
6. Invoke the host's native archive operation. Only after it succeeds, run read-only `cleanup-codex inspect` to inspect host-wide runtime health. This inspection cannot attribute a residual process to the archived task.

A task is eligible for native archive only when:

- its acceptance criteria are met with inspectable evidence;
- required tests, reviews, docs, and publication owned by that scope are complete;
- software-delivery tasks include authorized merge and post-merge proof;
- its report identifies artifacts and remaining dependencies;
- the orchestrator has verified its report and retitled it `✅`;
- unused clean worktrees created by that task are removed; and
- that task's owned merged, closed, or abandoned topic branches and refs are cleaned up safely.

If native archive fails, leave the task visible and resumable. If archive succeeds but inspection fails, record the child as archived, keep the orchestrator active, and leave runtime cleanup unresolved. Run `cleanup-codex reap` or `recycle` only as a separate, explicit repair after its exact ownership, identity, snapshot, and selection gates pass; archive status alone never authorizes mutation.

Treat `Stop`, completed turns, `SubagentStop`, completed subagent turns, idle or sidebar state, and blocked or otherwise nonterminal work as resumable. When the active v2 subagent surface has no native close or dispose operation, leave a completed subagent resident; do not reclaim it externally. Generic tasks remain visible until the user or host archives them.

Never delete a dirty worktree or an unmerged ref without explicit authorization. Keep the orchestrator active while any archived child has unresolved runtime cleanup, or until every remaining scope is archived with verification, remains visible with a clearly evidenced blocker the user accepts, or is otherwise explicitly handed off.
