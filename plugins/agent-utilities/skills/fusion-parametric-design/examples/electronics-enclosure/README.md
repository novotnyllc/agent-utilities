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
- minimum-distance and forbidden-interference checks.

Generate the scripts:

```bash
../../scripts/fusion-design emit-inventory fusion-project.json -o generated/inventory.py
../../scripts/fusion-design emit-parameter-sync fusion-project.json -o generated/sync_parameters.py
../../scripts/fusion-design emit-scaffold fusion-project.json -o generated/scaffold.py
../../scripts/fusion-design emit-verification fusion-project.json -o generated/verify.py
```

Run them through the Python-execution capability discovered from the live Fusion MCP. The scaffold intentionally creates empty components; native sketches/features must then be authored in Fusion according to the skill.

The `generated/` directory contains a reproducible emitted copy of all four transactions. They are syntax-checked offline but still require the live Fusion acceptance procedure. Copy `../../templates/DESIGN-STATE.md` into the working project when starting a real design.
