# Architecture

## Decision

The system has three stores, each with a distinct responsibility:

1. **Fusion document:** authoritative editable CAD, assembly, and parameter state.
2. **`*.fusion-project.json`** (one manifest per design; bare `fusion-project.json` in a single-design directory)**:** authoritative evidence and verification contract.
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
