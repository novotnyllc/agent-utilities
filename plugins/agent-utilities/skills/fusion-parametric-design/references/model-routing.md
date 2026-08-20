# Model-tier task routing

Which model tier should drive which of this skill's task classes. Classify by the shape of the work, never by model IDs: tiers are **frontier** (deep design reasoning), **mid** (bounded iteration), and **economy** (mechanical driving of fail-closed tooling). If the session has a routing skill or policy (an org router, a harness-level routing rule), that policy is the authority; this reference only classifies the skill's own work shapes.

## The orchestrator pattern

The session thread that receives the user's request is a **dispatcher, not a worker**. It holds the conversation, classifies each piece of work against the tier table below, spawns a subagent (Claude Code subagent, Codex spawned agent/thread) with an explicitly named model and effort for it, and stays responsive to the user while the work runs in the background. It never executes Fusion MCP transactions, long CLI runs, exports, or verification passes inline. This is the skill's required operating shape, not a suggestion.

The one bounded exception: cheap read-only lookups needed to answer the user or to classify the work — reading a manifest, listing available presets, checking MCP connectivity — may run inline. Anything that mutates the Fusion document, takes more than a few seconds, or produces evidence artifacts goes to a subagent.

The orchestrator is also the enforcement point for the single live Fusion writer: at most one spawned worker holds Fusion-mutation rights at a time. The orchestrator sequences writers and may run read-only workers concurrently.

Results flow back through the orchestrator, which relays outcomes to the user in plain language. Workers return raw results — reports, refusals, artifact paths — not user-facing prose.

## Why economy is safe here at all

The skill's CLI and generated transactions validate fail-closed: a malformed manifest is refused, a missing preset is refused before PrusaSlicer runs, a drifted export binding fails the transaction, a deviation run that cannot establish containment reports `not-established`. A weak model driving these paths can therefore produce refusals — never silent wrongness. That property is the entire justification for routing mechanical work to a cheap model; where it does not hold (open-ended design judgment the contract cannot check), the frontier tier holds the pen.

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

These names will age; they are examples of the tiers, not requirements. A session routing policy overrides this table.

| Tier | Claude Code example | Codex example |
|---|---|---|
| Frontier | Opus or better | GPT-5.6 Sol |
| Mid | Sonnet | current mid tier |
| Economy | Haiku | current economy tier, or a GLM-class subscription model for mechanical runs |

## Dispatch rules

- **Name the model and effort in every subagent dispatch.** Silent inheritance of a premium session tier is the failure mode this reference exists to prevent — an unlabeled dispatch runs economy work on frontier spend.
- **One live Fusion writer, regardless of tier.** Tiering never licenses concurrent Fusion mutation; parallel economy runs are for host-side work (report diffs, project builds, cache warms), never for two agents holding the same live document.
- **Escalate on non-mechanical refusals.** An economy run that hits a refusal requiring judgment — a classification gate, an implausible-declared-minimum, a deviation verdict of `not-established` — comes back to the frontier tier for diagnosis. It is never retried at the same tier in the hope the refusal goes away.
