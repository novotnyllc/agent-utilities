# Electronics enclosure and packing workflow

## 1. Identify the actual build

Record exact part numbers, board revisions, installed headers/hats, converter variants, connector orientation, buttons, antennas, microphones, fuses, wire gauges, terminal hardware, batteries, and cable overmolds. A bare-board drawing is not enough when the installed assembly is taller or routes wires differently.

## 2. Build the reference system

For each item create:

- `<Item> Reference` (role `reference`): editable dimensions and datums;
- `<Item> Envelope` (role `packing`): occupancy used for placement;
- one or more `<Function> Keep-Out` (role `keepout`) components.

Names are plain words for the browser; the role is the `role` attribute in the
`fusion_parametric_design` group (`references/design-doctrine.md` § Naming; in
the automation lanes the scaffold writes it from the manifest). For a purchased
part, the canonical linked catalog component is the reference model — source it
first (`references/data-and-catalog.md`).

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
| authoring model | Editable reference component |
| packing model | Packing-envelope occurrence |
| keep-outs | Functional spaces |
| support | Ledges, screws, pads, saddles, adhesive, etc. |
| clearance | Required rigid and service spacing |
| insertion/removal | Direction and sequence |
| confidence | `published`, `verified_cad`, `measured`, `provisional`, `coupon_verified` |

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

## 7. Wiring and terminations

Wiring is part of the design when the design is built around electrical
modules — LED strips and displays, IMUs and sensors, buttons, step-down
converters, power injection, existing boards. This is module-to-module hookup,
not PCB design: the deliverable is a design that shows where wires run, at
what gauge, ideally with the voltage and current each run carries, and with
real terminations at the ends.

**Wire runs are native geometry.** Prefer the Wire Generator add-in when it
is installed (`references/add-ins.md`); otherwise the expert technique is a 3D sketch path —
fit-point splines routed through the enclosure — swept with Pipe or Sweep at
the run's overall outside diameter (insulation, conductor count, and jacket
included, taken from the actual wire or its datasheet, never inferred from
bare-conductor gauge), with appearances matching the real
wire colors and bend radii the actual wire tolerates. Wire channels, strain
relief, and grommet features in the enclosure are ordinary native modeling,
and wire clearance is checked with native Measure and Interference like
everything else.

**Electrical metadata is base-tier recorded data.** Gauge, conductor count,
voltage, and current per run live in component/body descriptions and
attributes — no paid data-management extension assumed. The agent may add
gentle advisory notes (a gauge that looks thin for a stated current is worth
saying), but this is recorded data and advice, never a host-side
electrical-validation engine: the validation-framework prohibition applies
here exactly as it does to geometry, and electrical safety review stays
outside CAD (`references/verification-contract.md`).

**Terminations are components.** Ferrules, fork and ring terminals, JST and
other connector housings, and headers get the same treatment as all purchased
hardware: catalog or manufacturer CAD first, provisional simple geometry when
that is enough, stored and reused through the catalog doctrine
(`references/data-and-catalog.md`), and placed at wire ends so the assembly
shows real terminations.

**What Fusion does not provide, plainly.** Base Fusion has no general harness
or cable-routing environment, and the Electronics workspace is PCB design —
not the vehicle for module hookup (an MCP electronics-read capability, where
present, reads that PCB-oriented workspace and is not this). Do not hunt for a
nonexistent native harness tool, and do not invent a framework to fake one:
wire modeling is ordinary sweep/pipe modeling with recorded metadata.

Proportionality applies: wires appear when they matter to the design — exits,
channel sizing, clearances, service loops — and not every task needs a full
harness model.

## 8. Closed and service assemblies

Verify at least these states:

- fully closed/installed;
- lid lifted enough to expose every retainer;
- component insertion/removal;
- plug insertion/extraction;
- buttons at full travel;
- cable at relaxed and worst credible positions.

For a wearable, also check smooth body-facing surfaces, local stiffness, garment attachment, and hard-edge isolation.

## 9. Release evidence

After the user approves the shape, and when a release or handoff is requested,
produce:

- parameter/source ledger;
- component transform ledger;
- clearance table;
- interference report;
- closed/internal/section screenshots;
- fit-coupon status;
- print orientation and slicer estimate;
- export hashes;
- explicit unverified physical/thermal/electrical items.
