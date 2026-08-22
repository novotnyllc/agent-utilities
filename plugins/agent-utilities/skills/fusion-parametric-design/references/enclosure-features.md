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

## Installing the add-in

The toolkit depends on the bundled Fusion add-in, so installation is
**automatic**: the first time the toolkit is used (any CLI invocation or agent
request), it checks Fusion's standard add-in folders and installs
AgentUtilitiesEnclosure if missing. On later uses it compares versions and
refreshes the installed copy whenever the bundled add-in has been updated, so
toolkit updates carry the add-in along with them. No manual step is required.

Diagnostics and force-repair remain available:

```sh
# From this skill directory. FUSION_ADDIN_DIR overrides the search location.
npx tsx src/enclosure-features/cli.ts status
npx tsx src/enclosure-features/cli.ts install --target DIR [--force]
```

After the add-in is installed (or refreshed), open
**Utilities > Add-Ins > Scripts and Add-Ins > Add-Ins**, select
AgentUtilitiesEnclosure, and click **Run** once per session (or enable
**Run on startup**). Its commands then register as AgentUtilitiesEnclosure_*
definitions - e.g. Add Enclosure Boss, Add Seam, Add Cutout - usable from ordinary Fusion command dialogs. Agents call the same service through the staged mailbox; they never paste JSON into a textbox.

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
failure — a structured refusal. Create either returns a managed feature or a structured refusal. Fit-sensitive values without a source or coupon refuse. Some older warning-only paths remain defects until they refuse or build the joint.

## Request surface summary

A request is JSON, versioned by recipe id and semantic recipe version, and
carries exactly what one coherent feature group needs:

- `request_id`, `recipe` (id/version), document/component/occurrence context;
- `selections[]`: role-typed handles (component, body, face, edge, sketch,
  plane, path, managed feature) with acquisition tokens and expected types;
- `parameters[]`: each a quantity (expression string or value plus explicit
  unit — never both, never bare), an ownership class
  (`source`/`clr`/`fab`/`des`/`pak`/`calc` prefix convention (`pak_ef_`)), an evidence
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

Humans use ordinary Fusion CommandInputs. Agents stage one JSON request in the
add-in mailbox and execute the matching command definition. The handler consumes
the staged request, calls EnclosureFeatureService, stores the structured result,
and does not open messageBox or inputBox.

Copying the add-in tree is not enough. First agent use should:

1. run `npx tsx src/enclosure-features/cli.ts status` so missing/drifted files are installed;
2. load AgentUtilitiesEnclosure in Fusion (Run, or Run on startup);
3. confirm command definitions exist before creating geometry.

If the loaded add-in bytes/version do not match the bundle, the installer reports
`recipe-version-mismatch` and refreshes files. Do not run the stale copy.

Roundhouse MCP is optional convenience. The add-in and skill installer work
without it.

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
