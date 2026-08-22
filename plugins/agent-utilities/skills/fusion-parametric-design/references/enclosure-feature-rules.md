# Enclosure feature rules — the FDM evidence model

The toolkit implements a rule system, deliberately not a material or slicer
database. Rules carry evidence; they never smuggle in folklore numbers. This
file is the model: what classifications exist, what metadata every numeric
rule must carry, where each kind of data lives, which numbers may never ship
unsourced, and what coupons mean.

## Evidence classifications

Every numeric rule cites exactly one closed classification:

| Class | Meaning | Example |
|---|---|---|
| `geometric-invariant` | True by geometry, not by process | square nut corner radius = across-flats / √2 |
| `fusion-api-constraint` | A Fusion API contract fact | bare API lengths are database centimetres |
| `manufacturer-specified` | A named product/insert/fastener spec | SPIROL Series 29 M3 recommended hole |
| `standard-specified` | An official standard's value | an ISO O-ring gland from the standard's table |
| `material-datasheet` | A named formulation's data sheet | allowable strain for a snap arm |
| `fdm-process-heuristic` | Process guidance, explicitly heuristic | overhang/support preference for an orientation |
| `user-preference` | An explicit user design choice | chosen boss outer diameter |
| `provisional-default` | A stated starting hypothesis, never evidence | first-guess sliding clearance |
| `coupon-verified` | Measured from a printed coupon on the production process | coupon-verified sliding clearance |
| `physical-test-required` | Only a physical test can settle it | snap cycle life, pull-out retention |

## Required rule metadata

Every numeric rule in the shipped catalog carries all of:

```text
value / expression
units
classification            (from the closed list above)
source_id                 (named source; never a URL invented for this file)
confidence
safe_as_default           (bool)
confirm_before_export     (bool)
invalidated_by_material_change
invalidated_by_nozzle_change
invalidated_by_layer_height_change
invalidated_by_orientation_change
coupon_requirement        (none | recommended | required)
```

A policy test fails every numeric rule missing any of this metadata. A rule
without evidence class is not a rule; it is an unverified number wearing one.

## Data placement

| Rule state | Owner |
|---|---|
| Shipped generic intent/rule definitions | versioned plugin data |
| Shipped named presets | versioned plugin data |
| User's active design values | Fusion user parameters |
| Provenance/recipe linkage | Fusion attributes and parameter comments |
| Material decision in ordinary modeling | Fusion attributes/comments + conversation |
| Material decision in automation/release | existing manifest model |
| Printer/print/filament profile | PrusaSlicer, unchanged |
| Physical coupon result | Fusion coupon attributes/parameters; lane evidence where applicable |
| Reusable user-defined plugin preset | explicit plugin configuration/import action only — never written merely because ordinary modeling happened |

The project manifest schema receives no new enclosure-feature fields. Fusion
owns instance state; the plugin owns shipped definitions; the slicer owns
profiles; nothing else keeps a parallel copy.

## Forbidden unsourced numbers

The shipped catalog contains no universal value for any of:

```text
wall thickness
rib/wall ratio
boss/wall ratio
snap strain
printed hole compensation
sliding clearance
press interference
heat-set bore
nut pocket clearance
O-ring gland
minimum printable slot
```

Prusa's official FFF design guidance itself emphasizes that fit, tolerance,
and printable geometry depend on machine setup, orientation, and material
rather than one universal number. Current Agent Utilities doctrine goes further
and requires formulation/standard/coupon evidence for material-dependent fits
(`references/material-selection.md`). A rule may *reference* a sourced value —
an insert spec, a standard's gland table, a coupon result — but the value and
its evidence travel together or not at all.

Representative parameter policies:

| Parameter | Default policy | Invalidation |
|---|---|---|
| square/hex polygon geometric radius | `geometric-invariant`; safe | none |
| Fusion DB-unit conversion | `fusion-api-constraint`; safe | API contract change |
| specific insert recommended hole | `manufacturer-specified` | insert/formulation/process may require a new coupon |
| screw counterbore/countersink | `standard`/`manufacturer-specified` | hardware change |
| snap allowable strain | `material-datasheet`/manufacturer design guide | formulation, orientation, temperature/use assumptions |
| sliding clearance | `provisional-default` or `coupon-verified` | material, nozzle/extrusion, layer, orientation/process |
| hole compensation | `provisional-default` or `coupon-verified` | process/material/orientation |
| rib thickness | explicit user/preset design intent; not structural proof | material/process/load |
| O-ring groove | `standard`/`manufacturer-specified` | seal size/material/application |
| overhang/support preference | `fdm-process-heuristic` | orientation/nozzle/layer/slicer |
| cycle life | `physical-test-required` | any meaningful geometry/material/process change |

`insufficient-wall-thickness` refusals are legal only when a specific declared
rule establishes the minimum. No hidden folklore threshold exists in the code.

## Coupon semantics

Fit coupons calibrate a signed parameter against an explicit finite candidate
list the caller supplies — for example `[-0.10, 0.00, +0.10, +0.20]` mm for a
sliding clearance. The toolkit never searches the range, scores candidates, or
chooses a winner.

Each coupon:

1. creates a normal `Validation/<name>` Fusion component;
2. creates one native printable body containing all test stations;
3. gives every station an explicit parameter;
4. labels each station through native sketch text/extruded labeling;
5. stamps tested parameter, material, and fabrication evidence;
6. records status `generated`.

Physical lifecycle: `generated` → `printed` → `measured` → `accepted` or
`rejected` → `stale`. Geometry never marks itself accepted:
`record_coupon_result()` requires the user to supply the observed result and
the chosen value. An accepted value may update an explicit design-local rule
parameter; reusing it globally is a separate, explicit preset-management
action.

Staleness is declared, not guessed: a coupon result carries its dependency set
(material/formulation, nozzle, layer height, orientation, process), and any
declared dependency change marks it `stale` — the geometry stays, the evidence
stops being current. Material changes invalidate printed-fit evidence per the
existing doctrine (`references/material-selection.md` § When the material
changes); the toolkit's invalidation flags are the mechanical form of the same
rule.

## What this model is not

- Not Autodesk Plastic Rules: those are extension-owned, injection-oriented,
  and intentionally not depended upon (`references/unsupported.md`).
- Not a clearance solver: the toolkit checks one named location against a
  declared rule when asked; it does not sweep an assembly.
- Not a materials database: family/formulation decisions stay in
  `references/material-selection.md`'s model; rules reference them, never
  replace them.
- Not a slicer: process profiles stay in PrusaSlicer; the toolkit stores
  identifiers and evidence only.
