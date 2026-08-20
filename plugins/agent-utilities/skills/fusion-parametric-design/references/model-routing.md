# Model-tier task routing

Which model tier should drive which of this skill's task classes. Classify by the shape of the work, never by model IDs: tiers are **frontier** (deep design reasoning), **mid** (bounded iteration), and **economy** (mechanical driving of fail-closed tooling).

This reference is the skill's **standalone doctrine**. The skill is used in harnesses with no org router or session routing policy present, so the dispatcher operating shape and the tier/effort guidance below must be self-sufficient here and travel with the skill. The one exception: when a session-level routing policy *is* present (an org router such as railyard's model-routing doctrine, or a harness-level rule), it takes precedence over the example table — the skill classifies, the router selects.

## The dispatcher operating shape

The thread that uses this skill is a **dispatcher, not a worker**. It stays responsive to the user, classifies each piece of work by the work-shape table below, and hands every substantial piece — Fusion MCP mutations, long CLI runs, exports, verification passes — to a spawned worker (a Claude Code subagent, a Codex spawned agent/thread). Inline work is limited to cheap read-only lookups needed to answer the user or classify the task: reading a manifest, listing presets, checking MCP connectivity.

Which model and effort each worker gets: defer to the tier table and, when present, the session routing policy — that boundary is stated above and it holds here.

The dispatcher also arbitrates the single live Fusion writer: at most one mutating worker at a time; read-only workers may run concurrently. Workers return raw results — reports, refusals, artifact paths — and the dispatcher relays outcomes to the user in plain language.

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
