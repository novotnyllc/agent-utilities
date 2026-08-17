# Electronics enclosure and packing workflow

## 1. Identify the actual build

Record exact part numbers, board revisions, installed headers/hats, converter variants, connector orientation, buttons, antennas, microphones, fuses, wire gauges, terminal hardware, batteries, and cable overmolds. A bare-board drawing is not enough when the installed assembly is taller or routes wires differently.

## 2. Build the reference system

For each item create:

- `REF__<item>__PARAMETRIC`: editable dimensions and datums;
- `PACK__<item>__EXACT_OR_CONSERVATIVE`: occupancy used for placement;
- one or more `KEEP__<function>` components.

The reference model should expose:

- body envelope;
- PCB plane and mounting holes;
- connector centerlines and mouth geometry;
- supportable surfaces;
- forbidden support regions;
- maximum installed height;
- component-side orientation;
- service direction.

## 3. Classify keep-outs

### Rigid clearance

Manufacturing tolerance and printed fit around the physical body.

### Connector operation

Plug body, overmold, insertion stroke, extraction grip, latch travel, and neighboring cable bend.

### Wire routing

Straight terminal departure, ferrule/boot length, minimum bend, relaxed loop, branch junction, strain-relief load path, and assembly feed-through.

### Human/tool access

Finger diameter, switch cap travel, screwdriver/nut-driver access, WAGO lever opening, fuse replacement, and visual inspection.

### Thermal/acoustic/RF

Converter stand-off, vent corridor, hot-surface exclusion, microphone opening, antenna keep-away, and sensor field of view.

### Assembly/service

Board insertion angle, lid lift, component removal, fastener withdrawal, and cable unplug sequence.

## 4. Establish datums and coordinate ledger

Choose a stable product coordinate system. Record each packing occurrence's translation and rotation. Avoid arbitrary drag placement that cannot be reconstructed.

The packing ledger should include:

| Field | Meaning |
|---|---|
| id | Stable item id |
| source | Evidence source/revision |
| transform | Installed translation and rotation |
| authoring model | Editable `REF__` component |
| packing model | `PACK__` occurrence |
| keep-outs | Functional spaces |
| support | Ledges, screws, pads, saddles, adhesive, etc. |
| clearance | Required rigid and service spacing |
| insertion/removal | Direction and sequence |
| confidence | Published, measured, provisional, coupon-verified |

## 5. Solve packing

Place the largest/least-flexible bodies and hard interfaces first. Then solve:

1. exterior ports and user controls;
2. rigid component bodies;
3. terminal departures and cable loops;
4. fasteners and tool paths;
5. thermal/acoustic/RF spaces;
6. lid closure and removal;
7. external harness strain relief.

Use minimum-distance measurements and interference analysis. Record the smallest margin for each critical pair.

## 6. Author the product

Create the base/lid around the settled internal system. Prefer parameters/equations such as:

```text
calc_inner_width = pack_width + 2 * clr_rigid_xy
calc_outer_width = calc_inner_width + 2 * fab_wall_thickness
```

Supports should contact intended load-bearing surfaces. Retainers must not crush components or occupy connector/service zones. External port mouths must clear both the connector nose and overmold geometry.

For variable-height electronics, use local roof height where it materially reduces bulk, but preserve manufacturable transitions and lid structure.

## 7. Closed and service assemblies

Verify at least these states:

- fully closed/installed;
- lid lifted enough to expose every retainer;
- component insertion/removal;
- plug insertion/extraction;
- buttons at full travel;
- cable at relaxed and worst credible positions.

For a wearable, also check smooth body-facing surfaces, local stiffness, garment attachment, and hard-edge isolation.

## 8. Release evidence

Produce:

- parameter/source ledger;
- component transform ledger;
- clearance table;
- interference report;
- closed/internal/section screenshots;
- fit-coupon status;
- print orientation and slicer estimate;
- export hashes;
- explicit unverified physical/thermal/electrical items.
