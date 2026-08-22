# Enclosure feature toolkit — commands, requests, dispatch, lifecycle

The toolkit turns recurring enclosure construction — bosses, seams,
retention, supports, cutouts, seals, vents, coupons, patterns — into shipped,
versioned recipes executed by the bundled Fusion add-in. Fusion stays the sole
feature tree and geometry store; host code owns typed requests and evidence
schemas and owns no geometry. This page is the operator/agent guide to the
command families, the request surface, how an agent invocation reaches the
add-in, and the lifecycle of a managed feature. The evidence/rules model lives
in `references/enclosure-feature-rules.md`; per-capability status lives in
`references/enclosure-feature-capability-matrix.md`.

The toolkit depends on ordinary public Fusion features only — sketches,
construction entities, extrudes, revolves, sweeps, combines, holes, threads,
patterns, mirrors, parameters, attributes, timeline groups. Autodesk's
extension-owned plastic features (Boss, Snap Fit, Lip, Rest, Plastic Rules) are
never a dependency; see `references/unsupported.md` and
`docs/research-basis.md` for the entitlement boundary.

## Command families

Human-facing Fusion commands and agent requests use the same internal recipe
service; there is one geometry implementation per family.

| Family | Representative operations |
|---|---|
| Boss / hardware | Support, screw, heat-set-insert, captive-nut, thread-forming, tapped, PCB-standoff bosses; coordinated base/lid pairs; standalone counterbores, countersinks, spot faces, insert bores, nut pockets |
| Seam | Lip, groove, lip+groove, tongue/groove, skirt/channel, labyrinth, splash overlap; registration keys, anti-shear stops, alignment tabs; interruptions around ports, hinges, latches, fasteners |
| Retention | Cantilever snaps (parallel/perpendicular/hidden), skirt-bump, annular/slotted/fingered/keyed rings, press and interference rings, dovetail, sliding key, scoped bayonet |
| Support | PCB edge/corner rests, shelves, landing pads, saddles, cylindrical cradles, profile ledges; keep-out-trimmed variants |
| Reinforcement | Straight ribs, radial boss ribs, gussets, triangular webs, wall/floor/boss ribs — via the shared reinforcement primitive, not a fake native RibFeature |
| Cutout | Rectangular, rounded, circular, and named-planar-profile ports; connector recesses and flanges; angled-wall and curved-wall axis-projected cuts; mounting holes |
| Strain relief | Cable-exit supports, clamp saddles, zip-tie anchors/slot pairs, retention bridges, bend-radius guides, flexible fingers, tangent channel transitions, service-loop retainers |
| Seal | Flat gasket channels and lands, O-ring grooves, perimeter/interrupted channels, compression stops — geometry only; ingress claims stay physical |
| Vent | Linear/rectangular/circular/hexagonal aperture arrays over bounded regions; clipped regions via explicit masks; louvers are ordinary modeling (`references/unsupported.md`) |
| Coupon | Sliding-clearance, press-fit, pin/hole, captive-nut, heat-set-insert, lip/groove, snap-engagement, dovetail, and connector-cutout fit coupons |
| Patterns / mirror | Managed rectangular, circular, and path patterns and mirrors referencing a managed source feature |

Every operation returns a typed result carrying the managed instance identity,
what it created or changed, direct native observations, warnings, and — on
failure — a structured refusal. There is no silent partial success: either the
result describes a healthy managed feature or the refusal names what went wrong
and what residue, if any, remains.

## Request surface summary

A request is JSON, versioned by recipe id and semantic recipe version, and
carries exactly what one coherent feature group needs:

- `request_id`, `recipe` (id/version), document/component/occurrence context;
- `selections[]`: role-typed handles (component, body, face, edge, sketch,
  plane, path, managed feature) with acquisition tokens and expected types;
- `parameters[]`: each a quantity (expression string or value plus explicit
  unit — never both, never bare), an ownership class
  (`source`/`clr`/`fab`/`des`/`pack`/`calc` prefix convention), an evidence
  reference, and export-confirm/test-required flags;
- material and fabrication context (family/formulation identifiers, nozzle,
  layer height, orientation intent) — identifiers only, never copied profiles;
- `upstream_feature_ids[]` for managed dependencies.

Selections name stable things: component origins, named datums, managed
sketches, explicit faces the design actually requires. Arbitrary post-fillet or
post-combine faces are accepted only with eyes open and are the least stable
handles the toolkit knows (`references/design-doctrine.md`). Entity tokens are
reacquisition handles only — validate what `findEntityByToken` returns; never
compare token strings across sessions.

## How an agent invocation reaches the add-in

Agent invocation follows the same command transaction boundary as a human
clicking the add-in's command. The MCP snippet stays tiny because the geometry
lives in the installed add-in:

```text
MCP thin snippet
    -> AgentUtilitiesEnclosure.dispatch.stage(request) -> nonce
    -> commandDefinition.execute()
    -> command handler consumes nonce exactly once
    -> result stored against nonce
    -> dispatcher returns result
```

The mailbox is ephemeral process-local memory keyed by a random nonce: one
request, one consumption, bounded lifetime, no filesystem backing. It is
tooling state, not design state. Prefer the public `CommandDefinition.execute()`
path so the operation runs inside the same transaction boundary human use gets;
live acceptance must prove staged-request → execute → result → Undo behavior
before destructive lifecycle operations are enabled
(`references/mcp-adapter.md`).

A realistic thin snippet is well under the script gate's ordinary-lane limits
(120 lines / 8 KB) and needs no generated-lane marker:

```python
import json, uuid
import adsk.core, adsk.fusion

app = adsk.core.Application.get()
design = adsk.fusion.Design.cast(app.activeProduct)
assert design and design.designType == adsk.fusion.DesignTypes.ParametricDesignType

request = {
    "request_id": str(uuid.uuid4()),
    "recipe": {"recipe_id": "boss.support", "version": "1.0.0"},
    "context": {"document_id": design.document.name, "component_path": "Base"},
    "selections": [
        {"role": "target_body", "kind": "body",
         "component_path": "Base", "name": "Base"},
        {"role": "placement_origin", "kind": "point",
         "component_path": "Base", "name": "Boss Placement"},
        {"role": "z_axis", "kind": "axis", "component_path": "Base",
         "name": "Boss Axis"},
    ],
    "parameters": [
        {"key": "outer_diameter", "value": {"expression": "des_boss_od"},
         "ownership": "design"},
        {"key": "height", "value": {"value": 8.0, "unit": "mm"},
         "ownership": "source"},
    ],
}
nonce = _au_enclosure_dispatch_stage(request)          # add-in API, injected
cmd = app.commandDefinitions.itemById("AgentUtilitiesEnclosureAddBoss")
cmd.execute()                                           # consumes nonce once
result = _au_enclosure_dispatch_result(nonce)           # raises on refusal
print(json.dumps({"feature_id": result["instance"]["feature_id"],
                  "healthy": result["native_observations"][0]["is_healthy"]}))
```

If the staged execute probe fails, stop; do not fall back to a giant MCP
script. Whole-enclosure generation is not an ordinary-lane operation under any
circumstances — the shipped-command exception covers exactly one coherent
managed feature group per invocation, nothing more.

## Managed feature identity and attributes

Every managed instance receives a UUID abbreviated into a display suffix and
stamps attributes in the existing `fusion_parametric_design` group:

```text
enclosure_feature_id            e.g. a4b8f2
enclosure_recipe_id             e.g. boss.heat_set_insert
enclosure_recipe_version        e.g. 1.2.0
enclosure_role                  e.g. lid_receiver
enclosure_parameter_namespace   e.g. ef_a4b8f2
enclosure_upstream_ids          comma-separated managed dependencies
```

User parameters follow the existing ownership-prefix convention inside the
namespace: `des_ef_a4b8f2_boss_outer_diameter`,
`clr_ef_a4b8f2_insert_bore`, `fab_ef_a4b8f2_root_fillet`,
`calc_ef_a4b8f2_boss_height`. Timeline groups are named for humans —
`Enclosure · Heat-Set Boss · a4b8f2` — and timeline indexes are never stored
as identity. Provenance lives in Fusion attributes and parameter comments; the
project manifest schema does not change for this toolkit.

## Lifecycle

### Create

Validate the request → resolve context and every selection exactly → refuse
direct/no-history designs → allocate the feature id and parameter namespace →
create/update user parameters → create named associative datums → execute the
recipe's native features → create the timeline group → stamp attributes →
Compute All → inspect direct results (created feature health, intended claimed
bodies still exist and satisfy `BRepBody.isSolid`, expected local body count).
No generalized interference or clearance sweep runs at create time.

### Edit

Master user parameters are the preferred edit surface. Selection changes,
optional-feature toggles, or topology-altering changes may invoke a controlled
rebuild only when all expected managed objects are intact. Manual editing is
allowed and respected: `inspect_feature` distinguishes
`managed-intact`, `managed-parameter-edited`,
`managed-native-edit-observed`, `managed-definition-diverged`, and
`managed-object-missing`, and a divergence that makes rebuild unsafe refuses
with `manual-edit-prevents-update`. The add-in never silently heals manual
geometry back to recipe intent.

### Delete

Resolve everything by managed attributes, compute managed dependency order,
delete managed entities in reverse creation/dependency order, parameters last.
Deletion refuses while another managed instance depends on the target unless
cascade was explicitly requested. Arbitrary user-created downstream geometry is
never discovered, rewritten, or promised safe.

### Inspect

Returns the instance's identity, parameter values, native feature health, and
divergence classification above. Inspection is observation, not release
verification — see `references/verification-contract.md`.

### Upgrade

Recipe version is stamped at creation; installing a newer toolkit never changes
existing geometry. Upgrades are explicit, declared per
`(recipe_id, from_version, to_version)`, parameter-only where possible, and
refuse when expected roles are missing, extra managed objects exist, selection
context no longer resolves, or manual edits prevent a provably bounded rebuild.
"Cannot safely upgrade this instance" is a correct outcome.

**Migration rules for agents working in this repo.** When authoring or editing
recipe code, follow these rules so future upgrades stay safe and mechanical:

1. **Never change a recipe's geometry semantics without bumping its version.**
   If you alter what `execute<Family>Recipe` produces — shapes, dimensions,
   feature ordering, refusal conditions — increment `recipe_version` in the
   request default (and the shipped rules catalog if it pins versions).
2. **Read the stamped attribute as truth.** The instance's current version
   lives in the Fusion attribute `enclosure_recipe_version` inside group
   `fusion_parametric_design`. Never trust a client-supplied current version;
   `upgradeFeature` already reads the stamp.
3. **Declare migrations explicitly.** A migration is a function keyed by
   `(recipe_id, from_version, to_version)` registered in the service's
   migrator table. Parameter-only migrations (updating user-parameter values)
   are preferred; topology-changing migrations must verify all expected managed
   roles exist before mutating and must refuse otherwise.
4. **Refuse rather than guess.** If no migrator is declared for a transition,
   return `recipe-version-mismatch`. If manual edits are detected, return
   `manual-edit-prevents-update`. Both are correct outcomes; silently
   rebuilding is not.
5. **Keep identity attributes forward-compatible.** New attribute keys may be
   added to `ATTRIBUTE_KEYS`; existing keys must never be renamed or removed
   without a declared migration that rewrites them on upgrade.
6. **Test both directions.** A recipe-version bump needs at least one test
   showing the new version creates successfully and one showing an old-version
   instance refuses upgrade until a migrator exists.

## Cross-feature dependencies

Fusion-native relationships are authoritative; attributes supply discovery
metadata. Legal managed dependencies are acyclic — port cutout before seam
interruption, seam before seal path, shared datum before boss pair, source
before pattern/mirror, coupon result before explicit rule override — and the
add-in rejects cycles before mutating anything. An upstream user feature that
disappears later surfaces as `upstream-feature-missing`; the toolkit never
substitutes the nearest similar entity.

## Refusal handling guidance

Refusals are structured, preserve Fusion's own exception text beside a stable
token, and classify recovery:

| Situation | Response |
|---|---|
| Invalid expression, obvious input typo | correct once, resubmit |
| Ambiguous target, missing required evidence | ask the user; never guess |
| Native create failure, intact command transaction | Undo, diagnose, retry |
| Upstream timeline failure | manual Fusion repair first |
| Unsupported topology | take the recipe refusal; model natively if useful |
| Manual divergence blocking rebuild | no automatic rebuild; decide manually |
| Partial destructive op without proven rollback | stop dirty; repair manually |
| Missing coupon/material evidence | geometry may remain provisional; claims do not become verified |

Never loop retries, launch alternative geometry searches, or score candidates —
that prohibition is the point of the refusal design. Common tokens:
`target-not-found`, `ambiguous-target`, `selection-token-stale`,
`participant-body-ambiguity`, `seam-self-intersection`,
`seam-segment-collapsed`, `unsupported-conformal-cutout`,
`cross-feature-cycle`, `managed-dependent-exists`,
`manual-edit-prevents-update`, `configuration-topology-changed`,
`coupon-required`, `physical-proof-required`. The full taxonomy and its
recovery table live in the implementation-ready design specification mirrored
by `docs/architecture.md`.
