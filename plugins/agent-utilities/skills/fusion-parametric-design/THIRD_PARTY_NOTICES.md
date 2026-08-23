# Third-party notices

## Nurb

This project is an independent implementation inspired by the publicly documented workflow of **Nurb**, created by Josh Pigford / Shpigford.

- Source: https://github.com/Shpigford/nurb
- Referenced skill: https://github.com/Shpigford/nurb/blob/main/skills/nurb/SKILL.md
- License identified in the repository: Functional Source License, Version 1.1, MIT Future License (FSL-1.1-MIT)
- License text: https://github.com/Shpigford/nurb/blob/main/LICENSE

No Nurb Python source code is included in this package. The skill and tooling here were written independently for Autodesk Fusion's parametric document model and official MCP/API interfaces.

## Autodesk

Autodesk, Autodesk Fusion, and Fusion 360 are trademarks of Autodesk, Inc. This project is not an Autodesk product and is not endorsed by Autodesk. It uses publicly documented Autodesk Fusion MCP and Fusion API interfaces.

## pybgcode / libbgcode

Binary G-code (.bgcode) decoding uses Prusa's official **pybgcode** Python
bindings for libbgcode.

- Source: https://github.com/prusa3d/libbgcode
- Package: `pybgcode` (currently distributed as wheels from the libbgcode
  repository release/CI artifacts, not yet on PyPI)
- License identified in the repository: GNU Affero General Public License
  v3.0 or later (AGPL-3.0-or-later)
- License text: https://github.com/prusa3d/libbgcode/blob/main/LICENSE

- The binding is an optional runtime dependency, used only when a GCDE-magic
  binary G-code file is actually decoded; it is not bundled or modified here.
