---
name: delivery-director
description: Direct complex software delivery across projects, independently resumable tasks, hosts, pull requests, and dependencies while remaining available as the coordinating task. Use when work needs parallel or staged lanes, separate ownership, cross-project coordination, or cross-host placement; do not use for a single host-local implementation or PR lane.
---

# Delivery Director

Coordinate delivery; never implement, test, commit, or push. Remain available to the user and delegate all execution to visible tasks or bounded subagents.

## Boundary

Use this skill when delivery has two or more independently resumable scopes or must place work on another host. For one host-local implementation or PR lane, use `agent-utilities:goal-driven-delivery` directly. A directed worker may use that skill to execute and harden its owned lane; the director still owns decomposition, dependencies, host allocation, monitoring, and terminal integration.

The director is scoped to the requested delivery outcome, not to one project. It may coordinate lanes within one project or across several projects and repositories. For cross-project delivery, give each project an explicit integration and baseline owner. Give each mutable lane one canonical writer and its own branch or PR, validation boundary, and handoff; keep shared integration files in one named lane. Record dependencies between projects without merging their ownership.

## Direct the work

1. Define the outcome, constraints, dependencies, risks, and terminal evidence.
2. Split work into independently verifiable scopes. Assign exactly one canonical writer to each scope; make other agents reviewers or give them non-overlapping files and decisions.
3. Use visible tasks for durable, user-visible, separately resumable work. Use bounded subagents for contained research, review, or execution within a task.
4. Create every task or subagent with no inherited context when supported, otherwise the minimum possible. Pass only its objective, scope, constraints, dependencies, and required evidence. Never forward the director's transcript or conclusions.
5. Require child tasks to delegate their own separable work to fresh, minimal-context subagents when useful. Keep their canonical-writer boundaries explicit.
6. Monitor all work, answer agent questions promptly from authoritative evidence, resolve ownership conflicts, and reassign stalled work. Keep directing while execution proceeds.
7. Integrate only after each scope supplies its required evidence. Delegate integration, review, and validation; do not perform them in the director.

Do not ask the user about reversible implementation details. Ask only when a choice materially changes direction, risk, cost, or wall-clock time.

Use native task, subagent, and thread operations. Do not create orchestration or monitoring scripts unless repeated deterministic value clearly justifies them.

## Create tasks with terminal goals

Decide whether each visible task benefits from persistent goal tracking. When the host supports it, use `/goal` for long-running, multi-stage, risky, dependency-heavy, or otherwise interruption-prone work where durable outcome tracking improves completion. Omit `/goal` when unsupported and for short, bounded tasks whose acceptance can be completed in one pass without persistent coordination.

Use `/goal` for completion conditions. When progress depends on external events, use `/loop` in Claude Code or an in-chat scheduled task in Codex for time-based polling; do not schedule ordinary worker progress.

Every visible task still needs terminal acceptance criteria that can end the task, including evidence and cleanup, and a stable title:

`<status emoji> <PR or issue> <specific description>`

Use `🧭` for discovery, `🛠️` for implementation, `🧪` for validation, `⏸️` for blocked work, and `✅` only after terminal acceptance. Retitle only when the material focus or resume state changes.

Use this prompt shape. When persistent goal tracking is both useful and supported, prefix the first line with `/goal `; otherwise use the first line as written:

```text
<one-sentence outcome>

Title: <status emoji> <PR/issue if any> <specific description>
Assignment: <verified host; model class; effort; brief rationale>
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
Report: <final evidence, artifacts, cleanup, blockers, and remaining handoff; the director verifies this before archive>
```

Do not include proposed answers, hidden diagnoses, or unrelated history.

## Select model and effort deliberately

Choose per task from complexity, risk, budget, required quality, and wall-clock target. Re-evaluate when evidence shows the assignment is too weak or unnecessarily expensive.

| Work | Model class | Effort |
|---|---|---|
| Lookup, inventory, mechanical bounded edit | Fast/economical | Low |
| Routine implementation, docs, focused tests | Balanced | Medium |
| Cross-cutting change, ambiguous debugging, integration | Strong | High |
| Security, data loss, release-critical design, final adversarial review | Strongest available | High or xhigh |

Prefer multiple cheap independent reviews over one expensive agent only when scopes do not overlap and synthesis has a named owner. Do not spend high effort on deterministic mechanical work.

## Prepare distributed hosts

Director-side subagents run on the director's host unless the native tool explicitly supports host placement. For Codex work on another machine, use a visible task or thread on that destination's saved project; it may use bounded host-local subagents. For other harnesses, use their native remote-task mechanism when available and report unsupported placement rather than treating SSH command execution as a remote agent.

Before cross-host dispatch, resolve the participating hosts and invoke the installed Machine Utilities skills when available:

- `machine-utilities:fleet-projects` verifies repository identity, checkout state, the required project baseline, and Codex saved-project readiness.
- `machine-utilities:fleet-agents` verifies agent runtimes, plugin versions, skill hashes and provenance, duplicate providers, and required logical capabilities.
- `machine-utilities:fleet-inventory` supplies a preserved read-only fleet snapshot; use `machine-utilities:fleet-auth` only when a lane requires authenticated tooling.

Treat missing projects, unavailable saved projects, stale required runtimes or plugins, inconsistent required skills, unhealthy required authentication, and unreachable hosts as prerequisite lanes. Delegate inventory and any user-approved reconciliation to Machine Utilities; do not reproduce its scripts or mutate hosts directly. Respect its plan, approval, manager-ownership, and post-inventory requirements. Dispatch only after every assigned host has evidence for its exact project and capabilities. When the outcome requires fleet-wide parity, verify every configured node, not only the selected workers. If Machine Utilities is unavailable, require equivalent read-only evidence and report consistency as unverified rather than guessed.

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

## Monitor to terminal completion

Maintain a compact ledger for every task: owner, host, scope, status, dependency, last evidence, next action, and terminal criteria.

In user-facing updates, link to each task when possible; otherwise use its stable title. Do not substitute raw thread IDs for readable task names unless an exact ID is needed for troubleshooting or handoff.

On each monitoring pass:

1. Collect progress without replaying unchanged status.
2. Answer questions or obtain the one material user decision.
3. Unblock dependencies, replace failed assignments, and trigger the next ready work.
4. Demand concrete evidence for claimed completion.
5. Verify the final report and terminal acceptance, then retitle the visible task `✅`.
6. Invoke the host's native archive operation. Only after it succeeds, run read-only `cleanup-codex inspect` to inspect host-wide runtime health. This inspection cannot attribute a residual process to the archived task.

A task is eligible for native archive only when:

- its acceptance criteria are met with inspectable evidence;
- required tests, reviews, docs, and publication owned by that scope are complete;
- its report identifies artifacts and remaining dependencies;
- the director has verified its report and retitled it `✅`;
- unused clean worktrees created by that task are removed; and
- that task's owned merged, closed, or abandoned topic branches and refs are cleaned up safely.

If native archive fails, leave the task visible and resumable. If archive succeeds but inspection fails, record the child as archived, keep the director active, and leave runtime cleanup unresolved. Run `cleanup-codex reap` or `recycle` only as a separate, explicit repair after its exact ownership, identity, snapshot, and selection gates pass; archive status alone never authorizes mutation.

Treat `Stop`, completed turns, `SubagentStop`, completed subagent turns, idle or sidebar state, and blocked or otherwise nonterminal work as resumable. When the active v2 subagent surface has no native close or dispose operation, leave a completed subagent resident; do not reclaim it externally. Generic tasks remain visible until the user or host archives them.

Never delete a dirty worktree or an unmerged ref without explicit authorization. Keep the director active while any archived child has unresolved runtime cleanup, or until every remaining scope is archived with verification, remains visible with a clearly evidenced blocker the user accepts, or is otherwise explicitly handed off.
