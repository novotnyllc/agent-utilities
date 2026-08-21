# Enclosure feature evidence rules

Every dimensional value is a Fusion expression with explicit units and one
closed evidence label. The toolkit ships meanings and refusal rules, not a
material database or slicer profile.

| Value | Allowed v1 evidence | Required treatment |
|---|---|---|
| Boss outside diameter | user preference or provisional default | label provisional unless sourced for the exact application |
| Boss height | user preference or geometric dependency | keep as a native Fusion parameter/expression |
| Insert bore diameter | exact manufacturer specification or coupon result | source required; coupon remains required |
| Insert bore depth | exact manufacturer specification or coupon result | source required; coupon remains required |
| Socket-head seat diameter/depth | exact manufacturer specification or coupon result | source required; coupon remains required |
| Gusset thickness | FDM process heuristic or stronger evidence | validate on the chosen material/process |
| Gusset centre-to-tip length | user preference or geometric dependency | must extend beyond the boss radius |
| Pull-out/torque/cycle life | physical test | never inferred or emitted by the recipe |

Parameter names use `des_`, `fab_`, `clr_`, or `calc_` and contain the feature
namespace. A changed insert, material formulation, nozzle/process, print
orientation, or installation process invalidates dependent fit confidence.

Static policy: no private Autodesk API, hidden command ID, preview
`CustomFeature`, process spawn, filesystem/network I/O, manifest dependency,
nearest-geometry search, all-intersected-body behavior, timeline-index
identity, whole-enclosure entry point, unclassified numeric default, or custom
geometry validator.

Runtime geometric preconditions require positive dimensions, outer diameter
greater than head-seat diameter greater than bore diameter, bore depth no
greater than boss height, head-seat depth less than boss height, and any
gusset length greater than the boss radius. Bore depth plus head-seat depth
must reach at least the boss height so the required passage is continuous.
