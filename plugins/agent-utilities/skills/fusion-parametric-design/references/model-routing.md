# Model-tier task routing

Which model tier should drive which of this skill's task classes. Classify by the shape of the work, never by model IDs: tiers are **frontier** (deep design reasoning), **mid** (bounded iteration), and **economy** (mechanical driving of fail-closed tooling).

This reference is the skill's **standalone doctrine**. The skill is used in harnesses with no org router or session routing policy present, so the dispatcher operating shape and the tier/effort guidance below must be self-sufficient here and travel with the skill. The one exception: when a session-level routing policy *is* present (an org router such as railyard's model-routing doctrine, or a harness-level rule), it takes precedence over the example table — the skill classifies, the router selects.

## The dispatcher operating shape

The thread that uses this skill is a **dispatcher, not a worker**, and the shape exists for token and cost efficiency through tier-matching. The conversational thread stays responsive at a modest tier and effort by default — talking to the user and routing work does not need high effort, and probably should not run there. It classifies each piece of work by the work-shape table below and hands substantial work to a spawned worker (a Claude Code subagent, a Codex spawned agent/thread). Inline work is limited to cheap read-only lookups needed to answer the user or classify the task: reading a manifest, listing presets, checking MCP connectivity.

Effort escalates in the worker, where the work demands it: research passes, hard geometry strategy, and integration work get high effort as needed, while routine Fusion operation is tool-driving and usually mid-tier per the work-shape table. The cost architecture is a cheap responsive front, one persistent Fusion-operating worker at the tier the modeling actually needs, and escalated-effort workers only for the genuinely hard reasoning pieces — never a swarm. Which model and effort each worker gets: defer to the tier table and, when present, the session routing policy — that boundary is stated above and it holds here.

Workers return raw results — reports, refusals, artifact paths — and the dispatcher relays outcomes to the user in plain language.

## Single Fusion operator

The dispatcher spawns **exactly one persistent Fusion-operating worker for the whole task**, and that worker is the only thing that touches Fusion. Every Fusion call — mutations and read-only Python alike — serializes through that one live session: Fusion's active document, UI state, and stdout stream are shared, so concurrent Fusion callers can receive one another's report blocks. The parent does not duplicate design reasoning, spawn parallel analysts, create candidate workers, or replace the worker between attempts, and foreign-report detection in the adapter is defensive handling for an external violation — it never authorizes concurrent Fusion execution.

Ordinary modeling remains single-operator until the lane ends, not merely until the first screenshot: no reviewers, no parallel candidate builders, no swarm — a simple modeling task is never an agent-orchestration exercise. One read-only specialist consultation is allowed only after the hard stop and after the user directs the work to continue; the specialist does not touch Fusion, create artifacts, propose infrastructure, or reset the attempt budget, and its answer must identify one specific native Fusion action. Advice that proposes infrastructure instead of a Fusion action is declined.

**Standalone degradation.** The dispatcher/decision-worker/executor shape applies when the session has subagent facilities. A session running this skill standalone — no worker facility at all — performs everything as the single agent in one live Fusion session: the same lane lock, attempt budgets, screenshot heartbeat, and single-operator discipline hold unchanged, with effort escalated within itself for decision-heavy moments. The tier shape is an optimization of the same discipline, never a prerequisite for it.

Host-only work that never touches Fusion — documentation reads, offline computations, report diffs, project builds, cache warms — may run in parallel only in an activated machinery lane.

## Why economy is safe here at all

The skill's CLI and generated transactions validate fail-closed: a malformed manifest is refused, a missing preset is refused before PrusaSlicer runs, a drifted export binding fails the transaction, a deviation run that cannot establish containment reports `not-established`. A weak model driving these paths can therefore produce refusals — never silent wrongness. That property is the entire justification for routing mechanical work to a cheap model; where it does not hold (open-ended design judgment the contract cannot check), the frontier tier holds the pen.

## The tier principle

**Whatever is making decisions runs high, xhigh, or max — likely xhigh or max; whatever is executing decisions runs lower, on instructions the decider wrote.** Design choices, join selection, geometry strategy, research synthesis, and failure triage are decision work and get the top tiers. Driving Fusion through an already-decided feature sequence, captures, exports, and lookups are execution work and run lower, briefed precisely by the decider. The decider writes the executor's instructions; the executor does not re-litigate them, and anything that turns out to need a decision escalates back up — the escalate-on-non-mechanical-refusal rule below is this principle applied to refusals. A decider is always a **worker** doing architectural or design reasoning, never the dispatcher: routing, talking, and classifying are not decision work in this sense.

This composes with the single-Fusion-operator contract because **decision workers are Fusion-free**: they reason over state the Fusion worker and dispatcher provide — screenshots, read results, refusal reports — and produce briefs; the one persistent Fusion-operating worker executes every Fusion call. Two shapes, by how heavy the decision work is:

- **Ordinary tasks with small decisions** (most modeling): no separate decision worker exists. The single Fusion-operating worker simply runs at the tier the work needs — frontier for a task whose failure mode is a verified-but-wrong model, lower for mechanical driving — and makes its own in-flow calls.
- **Tasks with genuinely heavy decision work** (a hard packing resolution, a research-backed strategy, a large integration): a Fusion-free decision worker at high/xhigh/max reasons and briefs; the Fusion worker executes the brief; the dispatcher stays at its modest default.

The work-shape table that follows is the elaboration of this one rule.

## Frontier — deep design reasoning

Work where the verification contract can only check the *result*, not the *intent* — a passing report does not prove the design is the right design.

- New part or enclosure design from requirements.
- Packing and clearance resolution: choosing what moves when keep-outs collide.
- Repair diagnosis of a broken timeline: reading errors and deciding which feature edit heals the history without changing recorded intent.
- Mesh-reconstruction judgment calls: interpreting refusal tokens, choosing among `mesh-edit`, `faceted-brep`, and `parametric-rebuild`, deciding what an unreconstructed region means for the edit.
- Any task whose failure mode is a verified-but-wrong model.

## Mid — bounded iteration

Work on an already-healthy design where the manifest and contract bound the blast radius.

- Manifest edits and parameter tuning on an existing design.
- Adding bounded features to a healthy timeline.
- Variant-matrix *design* — choosing the parameter sets and overrides (regeneration is economy).
- Translating stated user intent into manifest changes.

## Economy — mechanical driving of fail-closed tooling

Work that is running the tooling, not making design decisions. The CLI refuses anything malformed, so the worst outcome is a refusal handed back.

- Running verification transactions and report diffs.
- Export plus handoff runs (`emit-export`, handoff index).
- PrusaSlicer project builds and headless slices.
- Variant-matrix regeneration from an already-designed plan.
- Preset and dependency checks, module-cache warms.

## Per-harness examples (illustrative, not authoritative)

These names will age; they are examples of the tiers, not requirements. A session routing policy overrides this table. Effort is part of every route: a dispatch names both model and effort, never model alone.

| Tier | Claude Code example | Codex example |
|---|---|---|
| Frontier | Opus or better, at high (max for the very hardest design work) | GPT-5.6 Sol at max |
| Mid | Sonnet at medium | Terra at max |
| Economy | Haiku at low | Luna at max, or a GLM-class subscription model for mechanical runs |

## Dispatch rules

- **Name the model and effort in every subagent dispatch.** Silent inheritance of a premium session tier is the failure mode this reference exists to prevent — an unlabeled dispatch runs economy work on frontier spend.
- **One live Fusion writer, regardless of tier.** Tiering never licenses concurrent Fusion mutation; parallel economy runs are for host-side work (report diffs, project builds, cache warms), never for two agents holding the same live document.
- **Escalate on non-mechanical refusals.** An economy run that hits a refusal requiring judgment — a classification gate, an implausible-declared-minimum, a deviation verdict of `not-established` — comes back to the frontier tier for diagnosis. It is never retried at the same tier in the hope the refusal goes away.
