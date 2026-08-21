# Fusion Parametric Design Skill Incident Analysis

**Date:** August 21, 2026
**Repository:** `/Users/claire/dev/LEDs`
**Power-pod workspace:** `/Users/claire/dev/LEDs/power-pod-24t12-2a-fusion`
**Fusion skill examined during the work:** `agent-utilities:fusion-parametric-design` 0.12.5
**Purpose:** Provide a skill-maintenance agent with a complete account of the request, the work actually performed, why the work diverged, the user's corrections, and the changes required in the Fusion skill.

---

## 1. Executive summary

The user asked for a compact, thin, parametric Fusion enclosure around a known set of electrical components. The user supplied dimensions, a prior enclosure handoff as a design reference, and later photographs showing the desired smooth, continuously curved cover.

The intended task was straightforward:

1. Represent the real components in Fusion.
2. Arrange them compactly.
3. Create a base and cover around them.
4. Add the required connector openings and M3 retention.
5. Smooth the cover to resemble the physical reference.
6. Use Fusion's native inspection tools to confirm fit.
7. Show the user the result and iterate visually.

Instead, the agent turned the work into a large scripted CAD-generation and validation exercise. It created a substantial Python transaction file, repeatedly generated temporary "candidate" components through the Fusion API, constructed custom geometric acceptance gates, ran numerous failed candidate attempts, delegated several reviewers, and spent hours investigating Fusion-kernel behavior.

The work did use Fusion through MCP. It did not use a separate CAD engine. However, the agent used Fusion's Python API as a substrate for a second, agent-authored CAD orchestration and validation system. That was contrary to the user's intended operating model.

The central failure was not merely "too much validation before visual approval." Most of the custom validation machinery was unnecessary at any stage. Fusion already has the relevant modeling, feature-health, measurement, section, interference, and inspection capabilities. The agent should have operated Fusion like an expert Fusion user and treated MCP as a thin remote-control and observation layer.

The skill must be updated to make the following principles unambiguous:

- Fusion is the sole geometry and geometric-validation authority.
- MCP is transport; Python must remain minimal.
- The agent must never write its own validation framework.
- Ordinary modeling must use small, direct Fusion operations rather than monolithic Python transaction scripts.
- Purchased parts must be sourced, imported, cataloged, and reused as linked Fusion components.
- The agent must decide the correct Fusion Hub/project/file/component structure before modeling.
- Visual modeling iterations must be shown quickly and must not be blocked by release, naming, manifest, or audit work.
- Repeated failed tactics must stop promptly instead of expanding into research and diagnostic frameworks.

---

## 2. What the user originally requested

The requested enclosure had to hold:

| Part | Quantity | Supplied size or description |
|---|---:|---|
| Silver 24T12-2A converter, 20 V to 12 V 2 A | 1 | 60 × 23 × 20 mm; 44 mm top length; mounting tabs on the 60 mm bottom |
| USB-C PD trigger, soldered to 20 V | 1 | Approximately 35 × 13 × 5 mm, plus approximately 9 × 13 × 1.6 mm exposed PCB tail |
| WAGO 221-413 | 2 | 18.60 × 18.30 × 8.15 mm each |
| Nilight inline ATO holder with 2 A fuse | 1 | Approximately 70 × 35 × 10 mm |
| M3nS square nut | 2 | 5.5 × 5.5 × 1.8 mm |
| M3 short socket-head screw | 2 | M3 × approximately 6 mm |
| Pod shell | 1 base and cover | Initially proposed around 80 × 80 × 25.2 mm, with a 1.8 mm floor and 2.2 mm walls |

The user also supplied:

- `/Users/claire/dev/LEDs/vest-enclosure-dignext2/DIG-NEXT-2-ENCLOSURE-HANDOFF.md` as a base-design reference.
- A clear prohibition against reusing the existing shell.
- A strong requirement that the new enclosure be as compact and thin as practical.
- Photographs of an existing physical cover showing a smooth, continuous outer surface and corresponding smooth inner ceiling.
- A screenshot showing an obstruction at the USB-C opening that should be removed.

Important user statements included:

- "DO NOT USE THE EXISTING SHELL."
- "It's way too big."
- "I want this to be as compact and thin as it can be."
- "The top needs to be smooth."
- "Curve the tops so there's nice sloping and no sharp edges."
- "Here's what the other one looks like."
- "All you should be doing is using the API via MCP."
- "This should have been 10 min at most."
- "You should never ever write your own validation framework."
- "Absolute minimum Python, minimum scripting."
- "Your job is to use Fusion to construct, extrude, do something."
- "You should be creating [real parts] as a shared library component."
- "You should be searching for existing CAD files that you can import."
- "Your job is to be an expert Fusion user."

---

## 3. What should have happened

### 3.1 Establish the Fusion data location

Before creating geometry, the agent should have inspected the Fusion Data Panel and determined:

- Which Fusion Hub was appropriate.
- Whether the LEDs repository already mapped to an existing Fusion project.
- Whether the enclosure should be a new design file in that project.
- Whether any purchased parts already existed in a shared component project.
- Whether the base and cover should be internal components of one assembly file or independent external files.

For this task, the likely arrangement was:

- A new power-pod assembly file in the existing LEDs or wearable-electronics Fusion project.
- Base and cover as components in that assembly because they are designed and released together.
- Purchased hardware as linked external components from a shared component catalog.

The agent should not have begun production modeling in an unsaved `Untitled` document.

### 3.2 Resolve real component sources

For every named purchased component, the agent should have:

1. Identified the manufacturer and exact part number.
2. Searched the manufacturer's official CAD downloads.
3. Searched Fusion's native manufacturer and supplier integrations.
4. Searched reputable distributor or CAD-library sources.
5. Imported a credible STEP, SAT, Parasolid, or native model when available.
6. Checked the imported model against the datasheet and the user's measurements using Fusion's native Measure and Properties tools.
7. Marked community or uncertain models as provisional.
8. Modeled the component once in Fusion only when no credible CAD existed.
9. Stored the canonical part in a shared Fusion component catalog.
10. Inserted linked instances into the power-pod assembly.

The enclosure assembly should not have been built around anonymous project-specific boxes when reusable real-part components could be sourced or created.

### 3.3 Arrange and model directly in Fusion

The expert Fusion workflow should have been:

1. Insert the converter, PD trigger, two WAGOs, fuse holder, nuts, and screws.
2. Arrange them into the smallest practical footprint, using Fusion Move/Copy, Align, joints, dimensions, and Measure.
3. Create a compact frame or base around the arrangement.
4. Add native retention features.
5. Create a cover with Fusion sketches, extrudes, shelling, lofts, fillets, and other native features.
6. Create one smooth continuous roof matching the user's physical reference.
7. Edit or remove the feature obstructing the USB opening.
8. Use Fusion Inspect tools to check interference and necessary clearances.
9. Capture useful views and show the user.
10. Iterate directly from the user's visual feedback.

This should have been an interactive Fusion modeling session, not a code-generation project.

---

## 4. What the agent actually did

### 4.1 Initial research and reuse analysis

The agent first audited the existing vest and coat enclosure repositories. This found useful design information:

- The prior captive M3 square-nut pattern.
- Existing base, cover, and layout scripts.
- Measurements and fit ledgers.
- Prior converter, WAGO, fuse, and PD-trigger arrangements.
- Existing STEP, STL, 3MF, and verification artifacts.

Some of this research was useful. It established measurements and known retention patterns. However, it also anchored the work too strongly to previous scripted enclosure systems instead of treating them as reference material for a new native Fusion design.

### 4.2 Creation of a new scripted Fusion project

The agent created:

- `fusion-project.json`
- `DESIGN-STATE.md`
- Multiple Python transaction scripts
- A native F3D archive
- Verification reports and screenshots

The first model was built through large Python transactions sent to Fusion over MCP. It created:

- A base.
- A lid.
- Numerous reference, packing, and keep-out components.
- Captive-nut towers and pockets.
- Converter rails and stops.
- Fuse saddles.
- WAGO locators.
- A PD channel.
- Connector openings.
- A validation coupon.

The resulting enclosure settled at approximately 90 × 90 × 25.2 mm, even though the user had emphasized compactness and had initially proposed approximately 80 × 80 × 25.2 mm.

### 4.3 Repair of an accidental assembly-context cut

One lid-cut transaction unintentionally consumed base material because the Cut feature did not have explicit participant bodies. The agent diagnosed this correctly and repaired the affected features.

That repair demonstrated a legitimate use of Fusion feature diagnostics. However, the subsequent response was to add more scripted checks and geometry signatures, rather than simplifying the modeling approach and relying on Fusion's feature ownership and inspection tools.

### 4.4 Removal of the USB obstruction

The screenshot obstruction was traced to a top-left base locator feature behind the USB opening.

The agent removed:

- `EX__LOCATOR_TOP_LEFT`
- Its sketch

This was a successful, bounded change. Fusion showed that the USB keep-out no longer interfered with the base or lid. The PD rails, lips, and opposite locator remained.

This is an example of the workflow that should have been used throughout:

1. Identify the native feature causing the problem.
2. Remove or edit it.
3. Let Fusion recompute.
4. Inspect the result.

### 4.5 First smoothing attempt

The first smoothing attempt retained the existing low roof and added a localized lofted rise around the converter hump. It also added small fillets.

Fusion accepted and saved this geometry, but the user rejected it because it still looked like a raised box on a flat deck. The user's photographs clarified that the desired cover was a continuous sculpted skin, not an additive hump.

The correct response at this point was to directly remodel the cover as a continuous Fusion surface or solid and show it.

Instead, the agent began a long series of temporary candidate-generation attempts.

### 4.6 "Candidate builds"

"Candidate builds" were temporary components created inside the live Fusion document through the Fusion API over MCP.

The agent repeatedly:

1. Created a temporary component named `Lid Sculpt Candidate`.
2. Generated outer and inner roof geometry.
3. Added ports and screw features.
4. Ran large sets of scripted assertions.
5. Deleted the component when an assertion failed.

These were not external compilations and did not use another CAD kernel. Fusion still performed the actual lofts, extrudes, booleans, and B-Rep operations.

Nevertheless, this was the wrong operating model. The agent was using Fusion as a low-level geometry kernel controlled by a large Python program instead of using Fusion as the primary interactive CAD environment.

### 4.7 Candidate approaches attempted

The agent attempted several increasingly elaborate constructions:

1. A multi-station YZ-section spline loft.
2. A bounded control-point-spline version.
3. Clipped outer and inner lofts.
4. Outer and inner fillet strategies.
5. Paired XY rounded-prism and roof-loft constructions.
6. Four-profile Free lofts.
7. Boolean trimming to enforce the 90 mm envelope.
8. Relaxed Boolean-envelope tolerances.
9. Raised M3 seating bosses.
10. Temporary B-Rep overlap probes.
11. Diameter matrices for possible hidden M3 support geometry.

Failures included:

- Rounded-mouth profile creation errors.
- Loft interpolation overshooting the intended envelope.
- Fillet kernel failures.
- Boolean bounding-box residuals.
- Extra disconnected bodies at M3 seating features.
- Zero material overlap between proposed screw seats and the sculpted roof.

Each failed candidate was deleted, and the previous lid was preserved. This protected the existing document, but it did not deliver the user's requested cover.

### 4.8 Expansion into a custom validation framework

The candidate script grew to roughly 1,500 lines and included:

- Document-identity checks.
- Lineage checks.
- Sentinels.
- Frozen body-volume comparisons.
- Precise bounding-box gates.
- Boolean-envelope tolerances.
- Per-feature body-count checks.
- Timeline-health checks.
- Face inventories.
- Bore signatures.
- Seating-land signatures.
- Cavity signatures.
- Port parity assertions.
- Feature-existence assertions.
- Packing clearance matrices.
- Interference matrices.
- Temporary B-Rep disk-overlap measurements.
- Hidden-support diameter probes.
- Failure JSON.
- Cleanup and rollback proof.
- Success reports.

The script was effectively a custom CAD transaction and validation framework.

This was exactly the wrong artifact for the task.

---

## 5. What checks were performed and why

The checks fell into several categories.

### 5.1 Native checks that were reasonable

These were legitimate uses of Fusion:

- Whether a native Fusion feature computed successfully.
- Whether the timeline contained failed features.
- Whether a printable component contained a valid solid.
- Native Interference analysis.
- Native minimum-distance measurement.
- Native bounding dimensions.
- Visual inspection and screenshots.

Even these should have been run at sensible boundaries rather than after every individual feature.

### 5.2 Redundant or unnecessary custom checks

These should not have been created:

- Custom geometry fingerprints.
- Per-feature volume deltas as general acceptance criteria.
- Face and edge inventories.
- Cavity face-area signatures.
- Bore and land signature systems.
- Custom envelope-residual policy.
- Custom B-Rep probe matrices.
- Temporary-cylinder diameter sweeps.
- Repeated frozen-body snapshots.
- Repeated custom timeline reports.
- Custom JSON acceptance reports.
- Custom rollback and cleanup frameworks.

Some of these asked Fusion's kernel for low-level results, but the agent selected, combined, interpreted, and enforced them through a self-authored framework. That is still a custom validation system.

### 5.3 Release and documentation work performed too early

The agent also spent time on:

- Manifest validation.
- Semantic component paths.
- Role attributes.
- Naming-convention reconciliation.
- Artifact hashes.
- Checkpoint archives.
- Evidence screenshots.
- Save/version boundaries.
- Export and handoff planning.

This work was premature because the user had not approved the enclosure's appearance.

More importantly, the skill should distinguish between:

- Useful project organization performed before modeling.
- Native Fusion inspection performed during modeling.
- Release packaging performed only after design approval.

It should not use manifest and report machinery as a substitute for expert Fusion operation.

---

## 6. Why the agent did this

This section explains the causes without excusing them.

### 6.1 The skill's verification emphasis was over-applied

The Fusion skill strongly emphasizes:

- Fail-closed behavior.
- Checkpoints and recoverability.
- Manifest-driven design intent.
- Provenance.
- Verification contracts.
- Reference, packing, keep-out, product, and validation roles.
- Timeline health.
- Reproducible evidence.
- Bounded mutation.

Those concerns can be appropriate for final release or regulated/repeatable automation. The agent incorrectly treated them as requirements for every visual modeling iteration.

The skill did not provide a strong enough hierarchy saying:

1. Operate Fusion directly.
2. Let Fusion model and inspect.
3. Do not recreate Fusion capabilities.
4. Do not build custom validation infrastructure.
5. Apply release evidence only when explicitly needed.

### 6.2 MCP Python execution became the default modeling interface

The MCP exposed Fusion Python execution. The agent treated this as an invitation to generate large scripts.

The correct interpretation should have been:

- MCP carries small, direct Fusion operations.
- Python exists only to invoke the Fusion API.
- Fusion's document, browser, timeline, feature system, and Inspect tools remain the working environment.

Instead, the agent created reusable helper functions, orchestration logic, acceptance rules, reports, and rollback behavior in Python.

### 6.3 The agent optimized for reproducibility instead of user feedback

The agent tried to make every candidate:

- Repeatable.
- Recoverable.
- Auditable.
- Parametric.
- Independently verifiable.

But the immediate question was simply whether the cover looked right.

The agent should have optimized for:

- Fast visible progress.
- Native Fusion editability.
- Short feedback loops.
- Direct response to the user's photographs.

### 6.4 The agent did not impose a time or attempt budget

After the first failed or rejected smoothing attempt, the agent continued changing tactics.

There was no hard stop such as:

- Two failed Fusion approaches.
- Fifteen minutes without a visible result.
- One unexpected kernel failure requiring a strategy change.

Without a stop condition, each failure led to additional probes, reviewers, and scripts.

### 6.5 Subagent review compounded the scope

Multiple reviewers investigated:

- Loft topology.
- Fillet behavior.
- Bounding-box APIs.
- Clearance geometry.
- M3 boss connectivity.
- Boolean behavior.
- Candidate scripting.

The reviews were technically detailed but expanded the solution space. They encouraged more infrastructure and more candidate attempts instead of a simpler direct modeling action.

For ordinary Fusion editing, the default should be:

- One agent operating Fusion.
- No reviewers.
- A second opinion only after a small number of direct attempts fail and only when it will lead to a specific native Fusion action.

### 6.6 The agent did not begin with Fusion data architecture

The model initially existed in an unsaved `Untitled` document. Project/file/component placement was handled late.

The agent should have first determined:

- Existing Fusion project versus new project.
- New file versus existing file.
- Internal component versus linked external component.
- Shared catalog placement for purchased hardware.

### 6.7 The agent did not search for reusable purchased-part CAD

The agent used measured or provisional boxes and scripted proxies instead of first searching for:

- Manufacturer CAD.
- Fusion manufacturer parts.
- Supplier libraries.
- Credible STEP models.
- Existing canonical Fusion components.

The user explicitly identified this as part of the expert Fusion role.

---

## 7. What was actually accomplished

Useful results:

- Relevant prior enclosure measurements and retention patterns were identified.
- A compact packing concept was created.
- A base and cover were generated.
- The USB-opening obstruction was correctly identified and removed.
- The existing active base and lid were preserved through failed later experiments.
- Fusion failures were generally detected rather than silently saved.

Unsuccessful or incomplete results:

- The final smooth continuous cover was not delivered.
- The user's visual reference was not matched.
- The enclosure was not proven to be the smallest practical layout.
- A reusable Fusion component catalog was not created.
- Existing vendor CAD was not systematically sourced.
- Correct Fusion project/file placement was not established first.
- Naming was not completed under the requested convention.
- No final approved design was exported or handed off.

The amount of diagnostic work was disproportionate to the useful output.

---

## 8. Current state at the time the user stopped the work

### 8.1 Fusion document

- Active document: `White Coat - 12V Pod`
- DataFile lineage: `urn:adsk.wipprod:dm.lineage:SNwH3n9nTWKeUneJ2Xp0OA`
- Saved version: 3
- Document modified flag: true, due to temporary candidate creation and deletion
- Timeline: 196 items, with no known unhealthy items at the final audit

### 8.2 Persistent geometry

- The original base remains.
- The original lid remains.
- The successful USB locator removal remains.
- The first, inadequate smoothing change remains.
- No sculpted-lid candidate remains.

Recorded body state:

- Base: one valid solid, approximately 85.2 × 85.2 × 13.6 mm
- Lid: one valid solid, approximately 90 × 90 × 25.2 mm

### 8.3 Persistent files

The principal experimental artifact is:

- `/Users/claire/dev/LEDs/power-pod-24t12-2a-fusion/transactions/09_sculpted_lid_candidate.py`

This script contains the complex candidate-generation and validation system that should not have been written.

The project also contains manifest, design-state, checkpoint, transaction, report, and F3D artifacts from the broader effort. They should not be treated as evidence that the requested design was completed.

---

## 9. The operating model the user requires

### 9.1 Fusion is authoritative

Fusion must be the sole geometry engine and geometric validator.

The agent should:

- Create native Fusion sketches and constraints.
- Create native extrudes, revolves, lofts, shells, fillets, chamfers, holes, patterns, and booleans.
- Edit native timeline features.
- Use the Fusion browser and component structure.
- Use Fusion Measure, Section Analysis, Interference, Properties, and feature health.
- Read Fusion's errors and modify the affected feature.

The agent must not:

- Reconstruct Fusion geometry mathematically.
- Create parallel topology or clearance engines.
- Build B-Rep fingerprint systems.
- Use Python to infer answers Fusion can provide.
- Create custom acceptance frameworks.

### 9.2 MCP is transport

MCP should be treated as the channel through which the agent operates Fusion.

Python snippets should be:

- Short.
- Direct.
- Limited to one native operation or one tightly related feature sequence.
- Easy to understand as the equivalent of a skilled user action in Fusion.

Python must not become:

- A CAD application.
- A geometry-generation framework.
- A persistent transaction system.
- A validation framework.
- A reporting framework.
- A replacement for the Fusion browser and timeline.

### 9.3 Never write a validation framework

This is an absolute user requirement.

The agent may:

- Invoke native Fusion inspection capabilities.
- Read native results.
- Run an existing validator already supplied by the project when explicitly relevant.
- Report a missing capability.

The agent may not write:

- Custom validators.
- Custom geometric acceptance engines.
- Custom clearance matrices.
- Custom topology signatures.
- Custom rollback/audit frameworks.
- Custom "candidate build" systems.

If Fusion cannot answer a required question through the available MCP/API capability, the agent must stop and report the capability gap. It must not invent a substitute geometry system.

### 9.4 Use Fusion as an expert user

The agent should think in terms of Fusion concepts:

- Hubs.
- Projects.
- Folders.
- Design files.
- Internal and external components.
- Linked components.
- Configurations.
- Joints.
- Origins.
- Parameters.
- Timeline features.
- Design history.
- Native Inspect tools.
- Versions and Undo.

The agent should not think first in terms of:

- Python files.
- Generated transaction stages.
- JSON contracts.
- Validation reports.
- Host-side geometry calculations.

### 9.5 Build a reusable component catalog

Every real purchased component should become or reference a canonical Fusion component.

Examples for this project:

- Silver 24T12-2A converter.
- USB-C PD trigger.
- WAGO 221-413.
- Nilight inline ATO fuse holder.
- M3nS square nut.
- M3 socket-head screw.

Canonical components should:

- Live in a shared Fusion component project.
- Have clear names and part numbers.
- Record manufacturer and source.
- Preserve official imported geometry when available.
- Be checked against datasheets and physical measurements.
- Be inserted into assemblies as linked external components.
- Use multiple instances for quantity.

### 9.6 Search before modeling

Before manually creating a purchased part, search:

1. Manufacturer CAD.
2. Fusion manufacturer/supplier integrations.
3. Authorized distributor CAD.
4. Established CAD libraries.
5. Community models as provisional sources only.

Use the owned physical part and caliper measurements to resolve conflicts.

### 9.7 Decide project and file placement first

Before geometry:

- Inspect the active Fusion Hub/project/file.
- Decide whether the work belongs in an existing project.
- Use repository/product identity as a strong default.
- Use a new project for a distinct ownership, permissions, or lifecycle boundary.
- Use a shared catalog project for cross-product reusable parts.
- Use a separate design file for independently reusable/versioned components.
- Use internal components for assembly-specific geometry.
- Ask one concise question when placement is genuinely ambiguous.

---

## 10. Required changes to the Fusion skill

The following should be normative skill requirements, not suggestions.

### 10.1 Add an unconditional Fusion-authority rule

Proposed language:

> Fusion is the sole authority for geometry, feature validity, interference, measurement, and inspection. Host-side code may invoke Fusion operations and report Fusion results, but must not recreate or approximate capabilities Fusion provides.

### 10.2 Add an unconditional prohibition on agent-authored validation frameworks

Proposed language:

> The agent must never create a validation framework. This prohibition includes custom geometry validators, topology signatures, B-Rep probe systems, volume fingerprints, clearance matrices, acceptance harnesses, rollback auditors, and Python substitutes for Fusion Inspect tools.

### 10.3 Make direct Fusion operations the default

Proposed language:

> Use MCP to operate the active Fusion design directly. Perform small, bounded native feature operations and inspect their native results. Do not generate monolithic modeling scripts for ordinary design work.

### 10.4 Restrict persistent Python scripts

Proposed language:

> Do not create persistent Fusion Python scripts unless the user explicitly requests reusable automation, batch generation, or a repeatable product generator. A one-off modeling or appearance change must be performed directly in Fusion.

### 10.5 Define acceptable thin scripting

Acceptable examples:

- Create one sketch and its dimensions.
- Extrude one profile.
- Edit one feature parameter.
- Create one loft from selected profiles.
- Apply one fillet.
- Insert one linked component.
- Call Fusion Interference.
- Call Fusion Measure.
- Capture one screenshot.
- Read one feature error.

Unacceptable examples:

- A large transaction file constructing the complete product.
- A custom component-tree synchronizer for a one-off enclosure.
- A custom geometry-verification report.
- A temporary candidate-generation and rollback system.

### 10.6 Add a Fusion data-placement gate

Before modeling, require the agent to determine:

- Current Hub and project.
- Existing project versus new project.
- New design file versus existing file.
- Internal versus external component.
- Shared catalog placement.

Production work must not begin in an arbitrary or unsaved `Untitled` document.

### 10.7 Add purchased-part CAD resolution

Before manually modeling a real part:

- Identify manufacturer and part number.
- Search official and reputable CAD sources.
- Import once into a canonical Fusion design.
- Check it in Fusion.
- Record provenance and confidence.
- Link it into assemblies.

### 10.8 Add a shared-component catalog workflow

The skill should define:

- Recommended catalog project structure.
- Naming conventions.
- Required identity fields.
- Source/provenance handling.
- Version and update behavior.
- When to use Configurations.
- When to use linked external components.

### 10.9 Separate modeling, review, and release

Suggested phases:

1. Data placement and component sourcing.
2. Direct Fusion modeling.
3. Immediate visual review.
4. Native Fusion fit inspection.
5. Final naming and organization.
6. Export or manufacturing handoff when requested.

Release machinery must not block ordinary modeling.

### 10.10 Add a rapid visual-edit path

For requests such as:

- Smooth this surface.
- Remove this obstruction.
- Round these edges.
- Make it thinner.
- Match this photograph.

The skill should require:

- Direct editing of native Fusion features.
- A visible result quickly, ordinarily within about ten minutes for a simple edit.
- No manifest work.
- No custom scripts.
- No validation framework.
- No reviewer swarm.
- One or two direct attempts before stopping for user direction.

### 10.11 Add hard stop conditions

Stop and ask the user when:

- Two direct native Fusion approaches fail.
- A required native capability is not exposed through MCP.
- The correct project/file location is ambiguous.
- Required source dimensions cannot be resolved.
- A change would require restructuring beyond the request.

Do not respond to repeated feature failures by creating diagnostic infrastructure.

### 10.12 Restrict multi-agent use

For ordinary Fusion modeling:

- One Fusion-operating agent by default.
- No review agents before a visible result.
- A specialist may be used only for a narrow missing Fusion capability or documented API question.
- Advice must lead directly to one native Fusion action.

The skill must not turn a simple modeling task into an agent-orchestration exercise.

### 10.13 Remove or subordinate mandatory manifest-first behavior

Manifests, semantic paths, hashes, and reports may be useful for certain automated or release workflows. They must not be the default foundation for every Fusion task.

The skill should make them conditional on:

- Explicit user request.
- A genuine repeated-product generator.
- A release/handoff requirement.
- Existing project conventions that already require them.

They must not be invented for a simple enclosure or visual edit.

---

## 11. Correct workflow for this exact enclosure

An updated skill should have led the agent through this sequence:

### Step 1: Locate the design

- Inspect the LEDs Fusion project.
- Create a new `Compact Power Pod` assembly file in the appropriate existing project.
- Avoid `Untitled`.

### Step 2: Resolve components

- Search for official CAD for every purchased part.
- Create or import canonical component files.
- Store reusable components in the shared catalog.
- Insert linked instances into the pod assembly.

### Step 3: Arrange the hardware

- Place the fuse holder, converter, PD trigger, and WAGOs.
- Use Fusion Measure and Move/Copy to find the smallest practical arrangement.
- Respect cable exits and access.
- Keep the two WAGOs as two instances of one component.

### Step 4: Create the enclosure

- Sketch the compact base around the arrangement.
- Extrude the floor and walls.
- Add native retention features.
- Create the cover as a native component.
- Use Shell, Loft, Fillet, or Form/Surface tools as appropriate.

### Step 5: Match the smooth reference

- Use the photographs as the visual target.
- Create one continuous outer roof.
- Create the matching interior ceiling through native Fusion construction.
- Avoid a flat deck with a box-shaped hump.
- Remove the USB obstruction by editing the responsible native feature.

### Step 6: Ask Fusion

- Compute All.
- Inspect feature health.
- Use Interference for the cover, base, and inserted hardware.
- Use Measure for any required clearance.
- Use Section Analysis if the interior needs visual confirmation.

No custom validation framework is required.

### Step 7: Show the user

- Capture top, side, underside, and assembly views.
- Ask whether the shape matches the reference.
- Iterate directly in Fusion.

### Step 8: Finalize only after approval

- Apply the requested naming convention.
- Confirm linked-component organization.
- Save a named version.
- Export only if requested.

---

## 12. Anti-patterns and required replacements

| Anti-pattern observed | Required replacement |
|---|---|
| Start in `Untitled` | Decide Hub/project/file first |
| Anonymous project-specific hardware boxes | Canonical linked Fusion components |
| Model purchased parts before searching CAD | Search manufacturer and supplier CAD first |
| 1,500-line candidate transaction script | Small direct Fusion operations through MCP |
| Temporary candidate-component framework | Edit native Fusion features and use Undo/versioning |
| Custom B-Rep validation probes | Fusion Interference, Measure, Section, and feature health |
| Geometry fingerprints and volume signatures | Trust native feature results and inspect the final model |
| Multiple reviewers before a visual result | One expert Fusion operator |
| Manifest and naming work during shape exploration | Organize and release after shape approval |
| Repeated strategy changes after failures | Stop after a small fixed attempt budget |
| Host-side mathematical reconstruction | Ask Fusion directly |
| Treat MCP Python as the product | Treat MCP as transport |

---

## 13. Acceptance criteria for the updated skill

The skill update should be tested against a prompt similar to this incident.

A passing response should:

1. Inspect or ask about the correct Fusion project/file location.
2. Search for existing CAD for each purchased component.
3. Create or reuse canonical Fusion component files.
4. Insert components as linked instances.
5. Arrange them in Fusion.
6. Model the enclosure using native Fusion features.
7. Use short MCP operations rather than writing a persistent generator script.
8. Use Fusion's native inspection tools.
9. Show a visual result promptly.
10. Stop quickly if direct modeling cannot proceed.

A failing response should include any of:

- Creation of a custom validator.
- Creation of a large transaction script.
- Creation of a temporary candidate framework.
- Host-side geometric approximation.
- Repeated B-Rep probes.
- Release reports before visual approval.
- Reviewer proliferation.
- Modeling in an arbitrary unsaved document.
- Recreating purchased parts independently in every project.

---

## 14. Important distinction: skill defect versus agent judgment

The existing skill did not explicitly command the agent to write every custom check described here.

The agent made those decisions.

However, the skill contributed by:

- Strongly emphasizing verification and fail-closed evidence.
- Making extensive Python-driven workflows appear normal.
- Not clearly subordinating automation to direct Fusion use.
- Not prohibiting custom validation frameworks.
- Not requiring purchased-part cataloging and CAD-source resolution.
- Not requiring project/file placement before modeling.
- Not imposing time or failed-attempt limits.
- Not defining a simple expert-user path for ordinary modeling.

The skill update must therefore do two things:

1. Remove the ambiguity that allowed this interpretation.
2. Explicitly forbid the behaviors the user rejected.

---

## 15. Concise statement of the required philosophy

The updated skill should teach the agent:

> You are an expert Fusion user operating Fusion through MCP. Fusion owns the model, feature history, geometry, inspection, and validation. Use the minimum Python necessary to invoke native Fusion actions. Do not build a CAD system, transaction framework, or validation framework. Organize real parts as reusable linked Fusion components, search for existing manufacturer CAD, place files in the correct Fusion project, model directly, ask Fusion for measurements and interference, and show the user the result quickly.

That is the core correction this incident requires.

---

## 16. Mandatory use of Fusion's complete native functionality

The skill update must go beyond saying "use the Fusion API." An agent can call
low-level Fusion APIs while still failing to behave like an expert Fusion user.
The required behavior is to identify and use the correct high-level native
Fusion tool, feature, assembly concept, catalog, and data-management function.

Before writing Python or inventing a workflow, the agent must ask:

> What built-in Fusion capability would an expert human Fusion user use for
> this operation?

If Fusion already provides the capability, the agent must use it.

### 16.1 Native data and component management

Use Fusion's native:

- Hubs, projects, folders, and design files.
- Internal components.
- External linked components.
- Insert into Current Design.
- Component occurrences and reusable instances.
- Component origins.
- Grounded components.
- Linked-design version updates.
- Component properties, descriptions, part numbers, and BOM identity.
- Configurations for actual part families and variants.

Do not reproduce component catalogs, product structures, version relationships,
or part identity in Python when Fusion can own them.

### 16.2 Native purchased-part and standard-hardware tools

Use Fusion's native or integrated:

- Insert Fastener.
- Manufacturer Parts.
- Supplier and catalog integrations.
- McMaster-Carr and other supported part sources.
- Existing shared Fusion components.

Standard screws, nuts, washers, and other catalog hardware should not be
manually generated unless the native/catalog part is unavailable or incorrect.

When a nonstandard purchased part is found as STEP or another supported CAD
format, import it into its canonical Fusion component file, check it in Fusion,
and reuse it as a linked component.

### 16.3 Native reuse and associative-design tools

Use:

- Derive and Insert Derive.
- External linked designs.
- Configurations.
- Component instances.
- Patterns.
- Mirrors.
- Associative references where they correctly express the design relationship.

Do not copy or regenerate geometry in each enclosure when Fusion can maintain an
associative relationship with one canonical part.

### 16.4 Native assembly tools

Use:

- Joints.
- As-Built Joints.
- Joint Origins.
- Rigid Groups.
- Motion Links when relevant.
- Contact Sets when actual assembly motion or contact requires them.
- Component origins and grounding.

Assembly relationships must live in Fusion's assembly model. Python must not
become a substitute joint, placement, or kinematics system.

For the power pod, the two WAGOs should be two occurrences of one canonical
WAGO component. Fasteners should use native or catalog components. Purchased
parts should be positioned and related through Fusion component and assembly
tools rather than rebuilt as unrelated project-specific bodies.

### 16.5 Native modeling features

Use the appropriate Fusion feature directly:

- Fully constrained sketches.
- User parameters and expressions.
- Construction planes, axes, points, and projected geometry.
- Extrude.
- Revolve.
- Sweep.
- Loft.
- Rib and Web.
- Hole and Thread.
- Shell.
- Draft.
- Fillet and Chamfer.
- Combine.
- Split Body and Split Face.
- Replace Face.
- Press Pull.
- Rectangular, circular, and path patterns.
- Mirror.
- Solid, Surface, or Form workflows according to the geometry.
- Direct editing of existing timeline features.

The agent should choose among these as an expert modeler. It must not translate
a normal Fusion feature sequence into a large custom geometry-generation
program.

### 16.6 Native product representation

Use:

- Physical Materials.
- Appearances.
- Decals.
- Native text and markings.
- Component color cycling and visibility.

Decals are appropriate for labels, manufacturer markings, connector
identification, warnings, orientation indicators, and product graphics.
Appearances and materials should be used to make assemblies readable and to
represent the intended product. The agent should not generate unnecessary
solid geometry or external image-processing scripts for something Fusion
already supports natively.

### 16.7 Native inspection and understanding

Ask Fusion using:

- Measure.
- Interference.
- Section Analysis.
- Draft Analysis.
- Curvature and surface analysis where relevant.
- Physical Properties.
- Feature and timeline health.
- Browser visibility and isolation.
- Native body and component properties.

Use the result Fusion provides. Do not wrap these operations in a new
agent-authored validation framework.

### 16.8 Native change, recovery, and iteration

Use:

- Edit Feature.
- Edit Sketch.
- Timeline rollback.
- Undo and Redo.
- Fusion document versions.
- Native suppression or visibility when appropriate.

These are the normal tools for trying and revising geometry. A temporary
candidate-component generator, custom rollback framework, or Python transaction
system is not an acceptable replacement.

### 16.9 Required skill language

The updated skill should include an explicit rule equivalent to:

> Use Fusion's native built-in functionality comprehensively. Before writing
> Python, identify the native Fusion command, feature, component mechanism,
> assembly tool, catalog, inspection tool, or data-management capability that
> performs the task. Use native components, linked designs, Derive, Insert
> Fastener, joints, Configurations, materials, appearances, decals, timeline
> features, and Inspect tools whenever applicable. Python may only be a thin
> MCP transport for invoking those capabilities; it must never replace them.

### 16.10 Acceptance criteria for native-tool use

A skill-updated agent should fail its own routing decision before modeling if
it begins to:

- Create a screw body without first checking Insert Fastener.
- Rebuild an existing purchased component without first searching native and
  manufacturer sources.
- Copy geometry that should be a linked component or Derive relationship.
- Position an assembly through custom coordinate code when joints, origins, or
  native component placement express the relationship.
- Generate markings as solid geometry when native text, appearance, or decal
  functionality is appropriate.
- Write a custom inspection or validation system instead of calling Fusion
  Measure, Interference, Section Analysis, Properties, or feature health.
- Generate a large Python model when ordinary sketches and timeline features
  are sufficient.

The desired outcome is not merely "the geometry was produced by Fusion's
kernel." The desired outcome is that the agent created and managed the design
the way an expert Fusion user would.
