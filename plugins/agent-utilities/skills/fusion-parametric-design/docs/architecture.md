# Architecture

## Decision

The system has three stores, each with a distinct responsibility:

1. **Fusion document:** authoritative editable CAD, assembly, and parameter state.
2. **`*.fusion-project.json`** (one manifest per design; bare `fusion-project.json` in a single-design directory): authoritative evidence and verification contract.
3. **Generated reports:** immutable observations used for audit and diff.

Host-side Python is not a fourth CAD store. It generates narrow scripts that operate on Fusion's existing parametric model.

## Components

### Agent skill

`SKILL.md` defines the orchestration policy, evidence gates, modeling discipline, packing architecture, visual loop, verification, and handoff.

### Manifest validator

`fusion_design.manifest` validates required project/list structure, provenance enumerations, parameter types and role prefixes, critical values, scan provisional status, dual reference/packing models, keep-outs or explicit no-keepout rationale, component paths, and verification structure. The standard-library validator is the CLI gate; the JSON Schema is supplied for editor and ecosystem tooling.

### Script emitter

`fusion_design.scripts` emits four Fusion Python transactions:

- read-only inventory;
- idempotent parameter synchronization;
- non-destructive component scaffold;
- read-only verification using recompute health, all-geometry and B-Rep bounds, positive-volume root-context B-Rep preconditions, minimum distance, and interference.

Generated scripts emit delimited JSON for reliable parsing.

### Report diff

`fusion_design.report_diff` compares semantic inventory state: parameter expressions, component paths, per-component geometry summaries, and added/removed unhealthy timeline records.

## Why not generate all geometry from Python?

Whole-model generation makes the script the real source and Fusion an output cache. That undermines the user's goal: open the document later, inspect the timeline, change a parameter, edit a sketch, or replace one feature without invoking an agent.

Instead, geometry transactions should create one coherent native feature group once. Subsequent iterations update user parameters or supported feature inputs. This retains normal Fusion behavior and minimizes topology churn.

## Hybrid add-in + host-contracts boundary (enclosure feature toolkit)

The enclosure feature toolkit splits responsibility across a bundled Fusion
add-in and geometry-free host contracts:

```text
     Agent / human
         │  selects intent + entities
         │
 Host Agent Utilities        Fusion command UI
 contracts/rules only             │
         └──── JSON request ──────┘
                   │ MCP / command
      AgentUtilitiesEnclosure add-in
       recipe registry + lifecycle service
                   │ shared native primitives
      public Autodesk Fusion API only
                   ▼
     Fusion document + timeline — sole CAD authority
```

- The add-in owns all Fusion geometry construction and lifecycle operations,
  using only ordinary public features (sketches, planes, extrudes, holes,
  sweeps, combines, threads, patterns, mirrors, attributes, parameters,
  timeline groups). Extension-owned plastic features are never a dependency.
- Host code (`src/enclosure-features/`) owns typed request
  contracts, evidence/rule schemas, serialization, install/probe tooling, and
  pure tests. It owns **no geometry**.
- Agent invocation uses a staged nonce → `CommandDefinition.execute()` →
  result mailbox so the operation shares the human command transaction
  boundary (`references/mcp-adapter.md`). An installed, versioned toolkit
  command implementing one coherent enclosure feature group is shipped tooling,
  not ad hoc task machinery — the narrow ordinary-lane exception SKILL.md
  records. It permits no host project state, no whole-model generation, no
  generated transaction reports, and never more than one feature group per
  ordinary invocation.

### Managed feature lifecycle

Create: validate → resolve selections exactly → refuse direct/no-history
designs → allocate identity/namespace → parameters → datums → native features →
timeline group → attribute stamps → Compute All → inspect direct results only.
Edit prefers master user parameters; controlled rebuilds require all expected
managed objects intact, and manual divergence is reported, never silently
healed. Delete resolves by managed attributes in reverse dependency order;
destructive operations require the command-transaction Undo proof first.
Upgrades are explicit, declared per `(recipe_id, from_version, to_version)`,
and may correctly answer "cannot safely upgrade this instance". Instance
identity lives in Fusion attributes/parameters — never timeline indexes; the
manifest schema does not change for this toolkit.

### Cross-feature dependency rule

Fusion-native relationships are authoritative; attributes supply discovery
metadata only. Managed dependencies are acyclic (port cutout → seam
interruption → seal path; shared datum → boss pair; source → pattern/mirror;
coupon result → explicit rule override) and cycles are rejected before any
mutation. Deleting an upstream instance with managed dependents refuses;
a vanished upstream user feature reports `upstream-feature-missing` — the
toolkit never substitutes a nearest-similar entity.

### Strict responsibilities

| Area | Runs where | Owns | Must not own |
|---|---|---|---|
| host `contracts.ts` | host/tests | types and validation | `adsk`, geometry |
| host `evidence.ts` | pure TypeScript both sides | evidence classifications/invalidation | material database |
| host `rules.ts` | pure TypeScript both sides | parse shipped rules/presets | slicer profiles |
| host `dependencies.ts` | pure tests + add-in | managed-ID dependency checks | global topology graph |
| host `request-codec.ts` | host/add-in | JSON wire format/versioning | Fusion calls |
| host `installer.ts` | host setup only | install/probe bundled add-in | project geometry/state |
| add-in `service.ts` | Fusion | one request lifecycle | host files/reports |
| add-in `native/*` | Fusion | low-level public Fusion operations | enclosure policy |
| add-in `recipes/*` | Fusion | feature sequences | generalized CAD kernel |
| add-in `identity.ts` | Fusion | params/attrs/reacquisition | timeline-index identity |
| add-in `inspect.ts` | Fusion | direct result inspection | generalized validation |
| add-in `commands.ts` | Fusion | command UI | separate geometry implementation |

## Managed identity

Managed parameters/components/features use:

- stable names and component paths;
- the Fusion attribute group `fusion_parametric_design`;
- source id, role, provisional status, and manifest hash;
- entity tokens only as resolvable handles, never as directly compared identities.

## Failure boundaries

- Invalid manifest: block before mutation.
- Direct design: refuse automatic conversion.
- Missing MCP capability: declare unsupported and use documented fallback.
- Timeline warning/error after mutation: stop that feature group and diagnose.
- Clearance/interference failure: do not sculpt around or suppress the evidence.
- Unsupported print/physical check: retain as an explicit handoff item.
