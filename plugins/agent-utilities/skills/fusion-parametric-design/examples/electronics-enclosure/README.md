# Electronics enclosure example

This example encodes two measured electronics modules:

- a USB-C PD trigger board;
- an EKYLIN 20 V to 12 V converter.

It demonstrates:

- source dimensions with traceable user-measurement records;
- fabrication, clearance, packing, and design parameter roles;
- a separate editable reference and packing component for each module;
- connector and wire-bend keep-outs;
- required base, lid, and fit-coupon components;
- minimum-distance and forbidden-interference checks;
- a recorded `material_decision` that drives the geometry.

## The material decision, and what it changes

The manifest decides **PETG, family only** — no formulation, `confidence: provisional`, bound to `Validation/PD Fit Coupon`. The reason is the lid: its snap rim deflects at every opening and has to recover. PETG has the toughness and strain recovery for that. All three parts' `material.assumption` name PETG, which the validator cross-checks against the decision.

The decision is family-only on purpose. No product is named, so no data-sheet number backs `fab_fit_clearance` — it is a hypothesis until the coupon is printed and measured, which is exactly what the recorded risks say.

The counterexample: the same lid, under a different decision, is a different design.

- **PLA.** The snap rim is the failure. PLA cracks at the root instead of bending back, so the snap either has to become a fastened lid or grow into a long, thin, compliant arm with a generous root radius — a different feature, not a tuned one. The base's wall and boss geometry would change with it.
- **ASA (outdoors).** The snap survives, but the enclosure now cycles through a wide temperature range and ASA shrinks and warps more. `fab_fit_clearance` and the base/lid overlap have to be re-derived and re-couponed — the PETG-proven value does not transfer — and the large flat floor needs warp mitigation (ribs, a split, no long unbroken span) that the PETG version does not.
- **Soft TPU.** The snap geometry stops making sense at all. A low-hardness TPU lid deflects under its own assembly load, will not hold an engagement rim, and squashes rather than fitting. The lid becomes a stretch-over cover or a captured gasket, and the base grows a retention feature to hold it — which is a different product, not a material swap.

That is why the decision is recorded before the geometry: changing it later re-opens every fit, the snap, the wall, the orientation, and the coupon result. See `../../references/material-selection.md`.

Generate the scripts:

```bash
../../scripts/fusion-design emit-inventory fusion-project.json -o generated/inventory.py
../../scripts/fusion-design emit-parameter-sync fusion-project.json -o generated/sync_parameters.py
../../scripts/fusion-design emit-scaffold fusion-project.json -o generated/scaffold.py
../../scripts/fusion-design emit-verification fusion-project.json -o generated/verify.py
```

Run them through the Python-execution capability discovered from the live Fusion MCP. The scaffold intentionally creates empty components; native sketches/features must then be authored in Fusion according to the skill.

The `generated/` directory contains a reproducible emitted copy of all four transactions plus `positive_control.py`, a deliberately simple live-only box builder for this fixture. After parameter sync and scaffolding in a new disposable document, run verification once to prove the expected empty-model failure, run `positive_control.py` twice to prove creation and idempotence, then run verification again to prove the complete positive path. These scripts are syntax- and contract-checked offline but still require the live Fusion acceptance procedure. Copy `../../templates/DESIGN-STATE.md` into the working project when starting a real design.
