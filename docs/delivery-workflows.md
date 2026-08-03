# Delivery Director and Goal Driven Delivery

The plugin has two delivery skills with different jobs:

- `delivery-director` coordinates work across lanes or machines. It does not
  implement, test, commit, or push.
- `goal-driven-delivery` routes and executes one host-local change or pull
  request through the appropriate CE route. Generic implementation and bug
  fixes enter LFG by default and continue through merge and post-merge proof.

`orchestrate` is not a third workflow. Its useful delegation rules are now in
`delivery-director`, so keeping it would add another name without adding a
distinct responsibility.

## One project or several?

`delivery-director` is scoped to a delivery outcome, not to a project. It can
coordinate several lanes in one repository or related work across multiple
projects and repositories.

For cross-project delivery, each project gets an explicit integration and
repository-baseline owner. Each mutable lane inside it gets one canonical
writer and its own branch or PR, validation boundary, and handoff; shared
integration files stay in one named lane. The director records dependencies
between projects and verifies their evidence. It does not blur ownership or
combine working trees.

## Which skill should I use?

| Situation | Use | What happens |
| --- | --- | --- |
| Brainstorm, plan, diagnosis, review, or local-only request | `goal-driven-delivery` | It selects the matching CE route and stops at the requested artifact. |
| One feature, bug fix, refactor, or ship request on the current host | `goal-driven-delivery` | It routes generic implementation to LFG, then owns authorized merge and post-merge proof. |
| Existing PR to fix, drive, or deliver | `goal-driven-delivery` | It runs the applicable CE review or babysitting route, then owns authorized merge and post-merge proof. Review-only or watch-only requests stop earlier. |
| Two or more independently resumable scopes or PRs, in one project or several | `delivery-director` | It creates owned lanes, propagates the lane policy, tracks dependencies, and verifies terminal evidence. Each implementation lane may use `goal-driven-delivery`. |
| Work must run on another machine | `delivery-director` | It verifies that host, places a visible task there, and lets that task use host-local subagents and `goal-driven-delivery`. |
| Fleet setup or reconciliation without software delivery | Machine Utilities | It inventories and, with separate approval, reconciles projects, agents, plugins, skills, or authentication. |
| A tiny known-file or documentation edit | Direct edit and targeted check | Neither delivery skill is required unless durable tracking or remote placement adds value. |

You normally invoke one skill. For a local single lane, invoke
`goal-driven-delivery`; it routes brainstorm, plan, diagnosis, review, and
local-only requests to their narrower CE terminal state and generic
implementation to LFG. For multi-lane or cross-host work, invoke
`delivery-director`; the director propagates that policy and decides which
workers should invoke `goal-driven-delivery`.

## How they fit together

```mermaid
flowchart TD
    request["Delivery request"] --> decision{"Multiple lanes, projects, machines, or accounts?"}
    decision -- No --> gdd["Goal Driven Delivery"]
    decision -- Yes --> director["Delivery Director: coordinate and verify"]
    director --> lanes["Owned lanes with one writer and integration owner"]
    lanes --> gdd
    gdd --> intent{"Requested outcome"}
    intent -- "brainstorm / plan / diagnose / review / local-only" --> narrow["Matching CE route and requested artifact"]
    intent -- "implement / fix / ship" --> lfg["LFG: plan through CI and review settlement"]
    lfg --> checkpoint["Checkpoint or gh-stack chain"]
    checkpoint --> merge["Authorized merge and post-merge proof"]
    narrow --> evidence["Evidence and handoff"]
    merge --> evidence
    evidence -. delegated lane evidence .-> director
    director --> terminal{"Terminal acceptance and report verified?"}
    terminal -- No --> resumable["Keep task visible and resumable"]
    terminal -- Yes --> retitle["Retitle task ✅"]
    retitle --> archive["Native archive"]
    archive --> inspect["cleanup-codex inspect (read only)"]
    inspect --> verified{"Runtime cleanup verified?"}
    verified -- Yes --> closed["Close the lane"]
    verified -- No --> unresolved["Record child archived; keep director active"]
```

The separation is intentional. A director must remain available to coordinate,
unblock, and monitor. A lane worker must be free to edit, test, and repair its
owned scope. Combining those roles would make it unclear whether the active
task is allowed to execute or must remain a control plane.

Delivery Director invokes native archive only after the lane's existing
acceptance criteria and final report are verified. It then runs read-only
`cleanup-codex inspect` for host-wide runtime health; that inspection cannot
attribute a residual process to the archived task. If archive succeeds but inspection fails, the child
stays recorded as archived while the director remains active with runtime
cleanup unresolved. An explicit `reap` or `recycle` is a separate repair and is
allowed only after the cleanup skill proves its stronger exact ownership,
identity, snapshot, and selection requirements.

Goal Driven Delivery does not archive or mutate runtime when it stops at a
locally verified, review-ready, PR-ready, blocked, or owner-action-required
state. Generic tasks, `Stop`, completed turns, `SubagentStop`, idle or sidebar
state, and completed v2 subagents without a native close or dispose operation
remain visible and resumable. Root `SessionEnd` may perform inspection only; it
does not prove that a saved task should be archived.

## Tasks, agents, and subagents

A visible task or thread is a durable lane that can be resumed, monitored, and,
when the host supports it, placed on another machine. A bounded subagent works
inside its parent task's host and workspace unless the native tool explicitly
supports host placement.

For Codex work on another machine, the director uses a visible task attached to
the destination's saved project. That destination task may create its own
host-local subagents. For other harnesses, the director uses their native
remote-task mechanism when available. Running a command over SSH is remote
command execution; it is not a remote agent.

One lane does not mean one agent. A lane may use several bounded host-local
subagents while retaining one owner and one terminal acceptance contract.
Likewise, `/goal` tracks completion for a task; it does not turn that task into
a multi-lane director.

## Machine readiness is a prerequisite

Before cross-host dispatch, `delivery-director` delegates readiness checks to
the installed Machine Utilities plugin:

- `machine-utilities:fleet-projects` verifies repository identity, checkout
  state, the required baseline, and Codex saved-project readiness.
- `machine-utilities:fleet-agents` verifies agent runtimes, plugin versions,
  skill hashes and provenance, duplicate providers, and required capabilities.
- `machine-utilities:fleet-inventory` preserves a read-only fleet snapshot.
- `machine-utilities:fleet-auth` is used only when a lane needs authenticated
  tooling.

Missing projects, unavailable saved projects, stale required tooling,
inconsistent required skills, unhealthy required authentication, and
unreachable hosts become prerequisite lanes. Machine Utilities owns any
inventory and user-approved reconciliation; Delivery Director does not copy
its scripts or silently update machines. If fleet-wide parity is part of the
outcome, every configured node is verified, not only the selected workers.
Consistency means matching the required project identity and capabilities. It
does not require unrelated tools or machine configuration to be byte-identical.
A repository present on disk is also not sufficient for Codex placement: the
destination checkout must be available as the correct saved project.

## Models, checkpoints, and terminal states

Goal Driven Delivery, LFG, and Delivery Director use Sol High for orchestration
by default and Sol Max for cross-cutting, release-critical, security-sensitive,
multi-repository, or otherwise complex work. Luna handles most implementation,
with Max effort preferred and the actual effort disclosed. Independent primary
review uses a separate Sol High or Sol Max context by risk. Fable 5 is used only
through a supported CE cross-model review
path that verifies the model; otherwise the lane uses an independent Sol
reviewer and discloses the fallback.

Independent research, implementation, and review may run in parallel. Each
mutable scope still has one canonical writer, branch, verification boundary,
and handoff; overlapping writes, dependent stack segments, and integration
operations serialize under named owners.

The director assigns every lane a concurrency allowance and nested-agent
ceiling from its global budget. A Goal Driven Delivery implementation lane
starts LFG in Sol, carries the required Codex `gpt-5.6-luna` implementation
binding to the `ce-work` seam, and prefers Max effort. Because effort is not a
carrier field, an installed CE adapter that only supports a lower effort must
disclose that actual effort; it may not fall back to a non-Luna implementation
model or claim Max ran.

When a writable GitHub remote exists, lane owners push useful active-branch or
integration-branch checkpoints for resumability. A checkpoint does not open a
PR, trigger review, or imply completion. Goal Driven Delivery establishes the
branch and upstream before LFG, then runs a non-writing sidecar that publishes
only clean, stable commits as the work stage advances; it stops before LFG's
commit/push/PR stage. For a dependent stack against a GitHub upstream, use
`gh-stack`; if its extension or skill is missing, run the authoritative
bootstrap and verify it:

```bash
gh extension install github/gh-stack --force
gh skill install github/gh-stack --all --agent codex --scope user --force
gh stack --version
gh skill list --agent codex --scope user
```

On hosts that use Claude Code, additionally install and verify its copy with
`gh skill install github/gh-stack --all --agent claude-code --scope user --force`
and `gh skill list --agent claude-code --scope user`. Keep unrelated PRs
independent. The director owns integration visibility and evidence; the lane
owns implementation and Git operations.

Brainstorm-only, plan-only, diagnosis-only, review-only, and local-only work
ends at the requested artifact or check boundary. Generic implementation,
bug-fix, and ship requests use LFG for plan through CI and review settlement;
Goal Driven Delivery then owns authorized merge and post-merge proof. The
director verifies that integrated terminal evidence and does not execute the
lane.

That tail consumes any bounded follow-up watch returned by LFG, confirms an
independent Sol review, resolves real findings, merges with the repository's
configured strategy, verifies GitHub reports the PR merged, proves the merge
commit is reachable from the fetched base branch, and runs or verifies the
smallest applicable post-merge check.

## Why `orchestrate` was removed

The former `orchestrate` skill said to delegate substantial work, assign
distinct ownership, choose agent effort deliberately, and remain available to
the user. `delivery-director` already contains those rules with stronger task,
host, dependency, evidence, and cleanup contracts.

Keeping both also created conflicts: `orchestrate` prohibited delegation by
leaf workers and made the coordinator integrate results, while
`delivery-director` permits useful bounded delegation and requires integration
and validation to be delegated. The clearer rule is one control-plane skill,
`delivery-director`, and one lane-execution skill, `goal-driven-delivery`.

## Examples

**One local bug fix:** invoke `goal-driven-delivery`. It diagnoses as needed,
routes implementation to LFG, runs the applicable quality gates, and continues
through authorized merge and post-merge proof unless a narrower stop was
requested.

**A plan or brainstorm request:** invoke `goal-driven-delivery`. It uses the
matching CE route and returns the requested artifact without starting LFG or
creating a PR.

**Frontend and API changes in separate PRs:** invoke `delivery-director`. It
assigns one canonical writer per PR, records their dependency, propagates the
model and completion policy, and gives each worker its own acceptance evidence.
Each worker uses `goal-driven-delivery`; dependent PRs use `gh-stack` after the
conditional bootstrap when needed.

**The same project on several nodes:** invoke `delivery-director`. It first
uses Machine Utilities to verify project and agent readiness on each required
node, creates destination tasks only on ready hosts, and collects their final
evidence before declaring the delivery complete.

## Source skills

- [`delivery-director`](../plugins/agent-utilities/skills/delivery-director/SKILL.md)
- [`goal-driven-delivery`](../plugins/agent-utilities/skills/goal-driven-delivery/SKILL.md)
