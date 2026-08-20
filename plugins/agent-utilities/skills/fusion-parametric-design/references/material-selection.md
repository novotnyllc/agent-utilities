# Material selection

Filament choice is a geometry decision, not a slicer setting. A snap arm that flexes and recovers in one polymer fractures in another. A press fit sized against one material's shrinkage is loose or immovable in a second. A living hinge that survives its service life in a third splits on the first close. Choose the material before committing the geometry that depends on it, then record the choice — family, formulation, source, confidence, coupon, unresolved risk — in the manifest's `material_decision`.

This file carries no property values. It states what each family does to geometry, and where the numbers have to come from.

## Three rules

### A family sets the envelope; a named formulation sets the numbers

`PETG` is a design envelope: roughly what stiffness band to expect, how it behaves at a flexure, whether it needs an enclosure, how it fails. A specific manufacturer product is what actually has a modulus, a shrinkage figure, a glass transition, and a published print window. Reason about geometry from the family; take every number from the formulation.

The manifest keeps these apart deliberately: `family` is a closed enum, `formulation` is free text naming the product on the spool. A decision with a family and no formulation is legitimate and common — it means the design envelope is settled and the numbers are not. Do not launder it into precision it does not have.

An unfamiliar trade name inherits nothing. "Tough PLA", "PLA+", "engineering PETG", "high-speed", "matte", a house brand with no chemistry stated — none of these is evidence of any property. A blend marketed as one family may be another family, or a filled version of it, or the base polymer with a colorant that changed its layer adhesion. If the vendor does not state the polymer, the decision is `OTHER` with the product named, and the properties are unknown until the data sheet or a coupon says otherwise.

### Specialty filled materials require the manufacturer's technical data sheet

Carbon-filled, glass-filled, and other short-fiber composites are not drop-in substitutes for their base polymer. Do not size a part in PA and then "print it in PA-CF because it is stronger."

What changes, at minimum:

- **Nozzle.** Fill is abrasive. A brass nozzle wears open during a single large part, which silently moves every extrusion width and every printed fit. Hardened steel, ruby, or tungsten carbide is a requirement of the decision, not an accessory. Record it in the decision's `nozzle` field, which is a closed enum — not in prose.
- **Stiffness up, toughness down.** Fiber raises modulus and lowers elongation and impact resistance. Snap arms, clips, and hinges that depend on strain recovery get worse, not better. A filled polymer is the wrong answer to a flexure problem.
- **Layer adhesion.** Fiber aligns with the extrusion, so in-plane strength rises while Z strength does not keep pace. Anisotropy is stronger, not weaker, than in the unfilled base.
- **Surface and dimension.** Filled prints are matte and hide their own defects; a filled part that looks clean can still be under-extruded from a worn nozzle.
- **Handling and safety.** Fine fiber dust from sanding or machining is a respiratory hazard, cut ends are sharp, and some filled and styrene-family filaments emit enough to want ventilation or filtration. This belongs in the recorded decision where the person printing it will read it, not in a footnote.

The validator enforces the visible half of this: a `*_CF` family — and `PA`, which absorbs enough water from a room to change what prints — must set `nozzle` to an abrasion-resistant value, and the polyamide families must also set `drying`. Both are closed enums, because a safety gate read out of free text is discharged by text that denies the constraint as readily as by text that declares it, and `printer_requirements` prose therefore discharges nothing. An open risk does not discharge it either: a risk about the lid colour says nothing about the nozzle that is about to wear open. That check confirms the constraint was declared. It cannot confirm it was understood; the data sheet does that.

### Published generic tolerances are not measured truth

A clearance from a forum post, a printing-guidelines page, or another project's parameters is a starting hypothesis. It encodes that author's printer, nozzle, extrusion width, layer height, cooling, speed, and spool — none of which are yours.

Any material-dependent value in the manifest must trace to one of:

1. the formulation's technical data sheet, cited as a named source;
2. an official standard;
3. a printed coupon measured on the machine and settings that will make the part.

Nothing else clears the bar. When a value is a hypothesis, mark the parameter provisional, set the decision's `confidence` to `provisional`, and bind it to a `coupon_component` or a recorded risk — a provisional material decision may never look settled. See `references/design-doctrine.md` for the evidence hierarchy and `references/verification-contract.md` for what a coupon has to demonstrate.

This skill does not ship a materials database. It records the decision, its provenance, and what remains unproven.

## Select from the requirement

Start from what the part has to survive. Each requirement rules families out and changes geometry; read the intersection, not one line.

**Outdoor or UV exposure.** ASA is the default. ABS is chemically similar but yellows and embrittles in sunlight. PLA and silk PLA are disqualified — they creep in a parked car and degrade outdoors. PETG holds up better than PLA but chalks and loses toughness over seasons. Geometry consequence: outdoor parts cycle through a wide temperature range, so mating clearances, press fits, and captured hardware need room for differential expansion and the seasonal creep of any preload.

**Sustained heat.** Rank the polymer against the actual temperature the part sees, from the formulation's data sheet — not against a remembered ranking. PLA is the first to go soft, and it goes soft below temperatures that occur in ordinary life. ABS and ASA are usable further up; PC and PC-CF further still. Annealed and semi-crystalline behavior complicates all of this, which is why the number comes from the data sheet. Geometry consequence: a part under sustained load near its softening point creeps whether or not it is "strong enough" — see load below.

**Flex, hinges, and repeated deflection.** Two separate problems.
- A *snap or clip* deflects once per assembly and must recover. It wants toughness and strain recovery: PETG, ABS, PA, PC. PLA is brittle at the snap and cracks at the root. Filled grades are worse than their base polymer here.
- A *living hinge* or a part that flexes repeatedly needs fatigue resistance, and the geometry (hinge thickness, radius, layer direction) matters as much as the polymer. Print flexures so the bend loads material along the extrusion, never across a layer interface.
- *Compliance* — a gasket, a bumper, a strain relief, a grip — is TPU's job, and only with a stated hardness.

**Wear and abrasion of the part itself.** Sliding, rubbing, and bushing surfaces favor PA; some filled grades are formulated for it and some are the opposite. Do not infer wear performance from stiffness. Geometry consequence: design a replaceable wear surface rather than a whole part sized around wearing out.

**Structural load.** Distinguish short-term strength from *creep* — slow deformation under a load that is simply left applied. PLA is stiff on a test bench and creeps badly under sustained load, so a bracket that passes when it is installed sags later under the same load. PETG creeps too. Load-bearing parts under continuous stress want PC, PA, or a filled grade, and want geometry that carries load in compression or shear rather than as a preloaded plastic spring. All FDM parts are weakest across layers: orient so the load path never runs a tension line through a layer interface, and never claim a load rating without simulation with correct assumptions or a physical proof test.

**Chemical exposure.** Solvents, fuels, cleaners, oils, sunscreen, and skin contact all differ by polymer and often by formulation. Take compatibility from the data sheet or a soak test on a coupon. PETG and PLA are attacked by things people casually wipe surfaces with.

**Cosmetic finish.** Silk PLA and other high-gloss grades exist for appearance and cost mechanical properties for it — they are visibly the wrong choice for anything structural. Matte and filled surfaces hide layer lines and hide defects with them. Choose the finish last, and never let it override a requirement above it; if the cosmetic material cannot meet the mechanical requirement, split the part.

**Dimensional accuracy and printed fit.** Warping, shrinkage, and moisture all move dimensions. The low-shrink, low-warp families (PLA, PETG) hold a fit most predictably; the styrene families (ABS, ASA) and semi-crystalline families (PA, PC) shrink more, warp more, and want an enclosure. Every printed fit — press fit, sliding fit, snap engagement, heat-set insert boss, threaded hole — is material-dependent and belongs on a coupon before it goes in the part.

## Families and their design consequences

Each entry states what the family does to geometry. Numbers come from the formulation.

**PLA.** Stiff, easy, dimensionally well-behaved, and brittle. Prints without an enclosure, warps least, holds a printed fit most predictably, supports come off cleanly. Fails by cracking rather than yielding, so snap arms and clip roots fracture instead of bending. Creeps under sustained load and softens at temperatures reached inside a closed car or near a power supply. Not for outdoors. Excellent for prototypes, jigs, fit coupons, and indoor parts under no continuous load — which is most of what gets designed, which is why the wrong default is so easy to reach for.

**Silk PLA and other cosmetic PLA grades.** PLA's design envelope with worse layer adhesion and worse toughness, traded for gloss. Treat as decorative. Never use it for a snap, a hinge, a boss, or anything carrying load, and do not let a silk sample stand as evidence for plain PLA's behavior.

**PETG.** The general-purpose tough choice. More strain to failure than PLA, recovers from deflection rather than cracking, tolerates modest heat better, mildly hygroscopic and better for drying. Costs: it is stringy and squishy at fine detail, it is more sensitive to overhangs and bridges, and it welds to smooth build surfaces and to its own supports — support removal can tear the surface it touched, so keep supports off mating faces and cosmetic surfaces or design them out. Creeps under sustained load. Good for enclosures, snap-fit lids, brackets under intermittent load, and anything that will be handled and dropped.

**TPU — by hardness, never as one material.** "TPU" is not a material decision; the durometer is the decision. A hard TPU is a tough, semi-rigid engineering plastic that will hold a shape, take a snap, and resist abrasion. A soft TPU is a rubber: it will not hold a snap geometry at all, it deflects under its own assembly loads, screw bosses pull through, thin walls collapse, and press fits are dominated by squash rather than by dimension. The same drawing in two hardnesses is two different designs. Also: hygroscopic and needs drying, prints slowly, needs a short filament path, bridges poorly, and supports are miserable to remove from a compliant surface. Design gaskets, bumpers, grips, feet, and strain reliefs in TPU — with the required hardness or flex behavior stated in the rationale, which the validator requires.

**ASA.** The outdoor family. UV and weather resistance is its reason to exist; mechanically it sits near ABS. Warps, needs an enclosure and a controlled ambient, and emits enough to want ventilation. Larger flat parts want warp mitigation designed in — split the part, add ribs, avoid long unbroken flat spans, avoid sharp internal corners that concentrate a shrinkage crack. Fits shift with the higher shrinkage, so a clearance proven in PETG does not transfer.

**ABS.** ASA's indoor sibling: tough, heat-tolerant beyond PLA and PETG, solvent-bondable and vapor-smoothable, and not weatherable. Same warping, enclosure, and ventilation constraints. Choose it over ASA for indoor parts that benefit from solvent bonding or post-processing; choose ASA the moment sunlight is involved.

**PC.** High heat and high toughness, at the cost of process difficulty: strongly hygroscopic (must be dried, and prints wet-and-bubbly if it is not), high printing temperatures, significant warping, and demanding layer adhesion. Interlayer bonding is where PC parts actually fail, so orientation matters more here than in the easy families. Use it when heat and impact are both real requirements and the printer can actually run it.

**PC-CF.** PC's heat resistance with fiber stiffness, less warping than unfilled PC, and materially less toughness. Requires an abrasion-resistant nozzle and drying. Not a flexure material. Read the "specialty filled" rule above before choosing it.

**PA (nylon).** Tough, wear-resistant, self-lubricating, and good at repeated flexing — the family for gears, bushings, hinges, and living hinges. Its defining problem is water: it absorbs it from ordinary room air, which changes dimensions, mechanical properties, and printability, and continues after the part is finished. A PA part's fits move with humidity. It must be dried before printing and kept dry, and dimensional claims about a PA part need to say when they were measured and in what condition. Warps and needs an enclosure.

**PA-CF.** Fiber-stiffened nylon: much stiffer, dimensionally steadier, less prone to warping, and less tough and less flexible than unfilled PA. Requires an abrasion-resistant nozzle and drying. Choosing it for a hinge or a snap gives up exactly the property that made PA right for those.

**PET-CF and other specialty filled.** Treat the whole class by the filled rule: base polymer sets the family behavior, the fill raises stiffness and lowers toughness, the nozzle is a hard requirement, and every number comes from that product's data sheet. When the chemistry is not stated, record it as `OTHER` with the product named and its properties unknown.

## What the decision has to record

`material_decision` in the manifest, alongside `DESIGN-STATE.md`'s material row:

- `family` — the design envelope, from the closed enum.
- `formulation` — the specific product, or null when only the family is settled. Never a guess.
- `source_id` — the declared source the decision rests on: the data sheet, the standard, the coupon record, or the user's stated requirement.
- `confidence` — from the same vocabulary as every other source. `provisional` until something measured supports it, and never stronger than the cited source's own confidence unless the decision is bound by both a coupon and a recorded risk.
- `coupon_component` — the declared printable part that will settle the material-dependent fits; by convention a validation article under `Validation/`. A component that is never printed cannot settle anything, so the validator requires a printable part.
- `rationale` — why this family, in terms of the requirement it satisfies. For TPU, this must state the hardness as a Shore or durometer figure, or the flex behavior the part needs.
- `unresolved_risks` — what is still unproven. Advisory to the filled-material gate: a risk does not stand in for a declared nozzle.
- `nozzle` — closed enum: brass, hardened steel, ruby, or tungsten carbide. Filled and hygroscopic families require an abrasion-resistant value here.
- `drying` — closed enum: required, done, or not needed. The polyamide families must declare it, and `not_needed` does not satisfy the gate.
- `printer_requirements` — free prose for anything the enums do not carry: enclosure, ventilation, handling. It records context and discharges no gate, and it is not a slicer profile: printer, filament, and process profiles stay in the slicer.

Per-part `material.assumption` values must name the decided family or formulation. A part quietly assuming something else is a validation error, not a divergence to be reconciled later.

## When the material changes

A material change is a design change. Re-open, at minimum: every printed fit and clearance, snap and clip geometry, hinge thickness and orientation, boss and insert dimensions, wall thickness against the new stiffness, build orientation against the new anisotropy, support strategy against the new removal behavior, and any coupon result that was measured in the old material. Do not carry a coupon-verified clearance across a material change; it was evidence about a material that is no longer in the design.
