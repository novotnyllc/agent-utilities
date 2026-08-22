---
title: Enclosure Design Extension Parity - Plan
type: feat
date: 2026-08-22
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Enclosure Design Extension Parity

## Goal Capsule

**Objective:** A human Fusion user (normal Fusion command dialogs) and an agent (typed recipe requests) can produce enclosure joinery on base Fusion that matches Design Extension plastic outcomes for Boss, Snap Fit, Lip, Rest, Rib, Web, and rule-driven thickness/draft/radius/clearance, including polymer- and nozzle-aware FDM values.

**Means:** Ship a Fusion add-in with ordinary Fusion command inputs. Geometry is ordinary sketches/extrudes/holes/combines grouped as enclosure features. Agents call the same service without a JSON textbox UI (KTD1, KTD9).

**Authority:** User instruction > this plan > Autodesk Help for outcome shape > implementer judgment. R wins on product behavior. KTD wins on mechanism.

**Stop conditions:** Using Claire's vest enclosure as the live audit part. Generating many enclosure CAD candidates in host Python instead of modeling in Fusion. Shipping a named cut as a complete joint. A JSON textbox or paste-JSON inputBox as the human UI. Merge without live Fusion acceptance for the shipped family.

**Execution profile:** Offline contract tests per unit. Live Fusion acceptance per family before that family is called done. Plugin version bump and marketplace repin on any plugins/ change.

**Tail ownership:** railyard:deliver through a fix PR, review settlement, and post-merge proof. This plan authorizes that PR.

---

## Product Contract

### Summary

The enclosure toolkit already names most recipes. It does not yet replace Design Extension plastic commands. This plan closes that gap on base Fusion: Fusion-native dialogs for humans, the same service for agents, complete joints, polymer- and nozzle-aware FDM rules, user and agent docs, and a shippable PR.

### Problem Frame

Design Extension automates Boss, Snap Fit, Lip, Rest, Rib, Web, Geometric Pattern, Design Advice, and Plastic Rules. Those commands are entitled. Agents and many human users work in base Fusion. PR 72 shipped an add-in that publishes recipe ids. Several of those ids are named cuts, silent defaults, no-ops, or missing families. A confused agent can still get a support boss or a 55 mm nut pocket.

### Requirements

**Design Extension outcomes**

- R1. Base-Fusion recipes reproduce Autodesk Boss results: sketch-point placement, two-body pairing, offset, shank, hole (simple/counterbore/countersink/blank), alignment, draft, and optional ribs. They must not require Features.bossFeatures.
- R2. Snap Fit recipes reproduce Autodesk cantilever hook-and-groove pairing on two bodies, including parallel hook-and-groove. Hidden and perpendicular variants stay first-class if they already publish.
- R3. Lip recipes reproduce Autodesk Lip, Groove, and Lip And Groove on one or two bodies from a tangent edge path with face-guide or pull-direction.
- R4. Rest recipes create a flat intersecting rest from a closed profile, with offset, wall thickness, and draft.
- R5. Rib and Web recipes create thin features from an open profile to nearest faces, inheriting rule thickness when a rule is assigned.
- R6. A component-assigned FDM plastic-rule analogue stores thickness, draft angle, nominal radius, and clearance as Fusion parameters, plus polymer family (PLA, PETG, ASA, PCCF, or user-named) and nozzle diameter when known. Later Extrude, Rib, Web, Boss, Snap, Lip, Rest, Shell, Thicken, and Draft inherit those values unless the request overrides them. Unsourced polymer-specific fit numbers still refuse (R18).
- R7. Design Advice injection-molding analysis is not cloned. Rule values that still apply to printed parts (thickness, draft, radius, clearance) are in. Mold-only advice stays out.

**Complete joints**

- R8. A published recipe_id is either a complete physical joint or an explicit refusal. A named polygon cut is not a captive-nut boss.
- R9. Captive hex/square nut recipes require sourced across-flats and depth. Missing values refuse. Sketch points use millimeters converted at the Fusion cm boundary.
- R10. Heat-set bosses keep refusing without hardware.insert_spec. Insert bore and depth come from that spec, not a silent default.
- R11. Standalone hardware.* requests land on the intended hole/pocket primitive. They must not become boss.support.
- R12. Coordinated two-body features (boss pair, snap, lip-and-groove) share one connection identity with two child roles.

**Human and agent parity**

- R13. The same recipe service serves Fusion commands and agent requests. Humans never paste JSON.
- R14. First agent use installs, loads, and verifies the bundled add-in. Copying files to disk is not enough if Fusion has not loaded the add-in. A version mismatch is reported; it does not silently keep a stale copy. Humans can also install from Fusion's add-in manager. Roundhouse MCP is not required.
- R15. Agent execution returns structured results. It does not block on ui.messageBox or ui.inputBox.
- R16. Every shipped create command uses ordinary Fusion CommandInputs: selections, value inputs, dropdowns, and checkboxes, with tooltips. No request_json textbox. No paste-JSON inputBox.
- R17. User-facing command/menu docs and agent-facing SKILL/API docs both exist and agree with add-in behavior. A lie is a defect.

**Evidence and safety**

- R18. Fit-sensitive numbers stay sourced or coupon-backed. The shipped rules file does not invent unsourced nut clearance, snap strain, or heat-set bore.
- R19. Offline tests fail if units, discriminators, refusals, or registry/add-in parity break.
- R20. Live Fusion acceptance proves each shipped family on disposable geometry with screenshots, timeline groups, parameters, and Undo.
- R21. A failed create leaves no partial residue. Coordinated two-body work is one transaction or an explicit rollback.
- R22. Selection resolution uses occurrence/component context for mating roles. A missing receiver/side body refuses instead of building a one-sided joint presented as complete.

### Actors

- A1. Human Fusion user on the Plastic-equivalent command set.
- A2. MCP agent sending one bounded recipe request.
- A3. Add-in recipe service in the live Fusion document.

### Key Flows

- F1. First MCP create
  - **Trigger:** Agent sends boss.screw with no add-in loaded.
  - **Actors:** A2, A3
  - **Steps:** Host installs and loads add-in. Service validates. Geometry is created and stamped. Result JSON returns.
  - **Covered by:** R13, R14, R15
- F2. Two-body boss
  - **Trigger:** User or agent places sketch points and two bodies.
  - **Actors:** A1, A2, A3
  - **Steps:** Shared axis/datum. Side 1 and side 2 bosses. Hole/seat from sourced hardware. Timeline group.
  - **Covered by:** R1, R12, R21, R22
- F3. Rule then feature
  - **Trigger:** Assign FDM rule, then Rib or Boss.
  - **Actors:** A1, A2, A3
  - **Steps:** Rule parameters exist on the component. Feature expressions reference them unless overridden.
  - **Covered by:** R5, R6
- F4. Sourced nut pocket
  - **Trigger:** boss.captive_hex_nut with only OD/height, then with AF/depth.
  - **Actors:** A2, A3
  - **Steps:** First request refuses. Second request cuts a mm-correct polygon pocket of sourced depth. No 5.5 cm default.
  - **Covered by:** R8, R9, R19

### Acceptance Examples

- AE1. Covers F4 / R9. Given a captive-hex request with no AF, when the service runs, then it refuses with a sourced-dimension token and creates no pocket.
- AE2. Covers R9. Given AF 5.5 mm, when the polygon sketch is built, then vertex coordinates are centimeters (0.55), not 5.5.
- AE3. Covers R11. Given hardware.hex_nut, when dispatch runs, then the nut-pocket path runs, not boss.support.
- AE4. Covers F2 / R1. Given two bodies and a sketch point, when boss.screw runs with sourced counterbore, then both sides exist, the head seat is flush, and a section through the joint shows engagement.
- AE5. Covers R2. Given two bodies and a parallel snap request, when the recipe runs, then a hook body and a matching groove exist on opposite sides.
- AE6. Covers R3. Given a tangent edge loop, when Lip And Groove runs, then one body gets a lip and the other a matching groove.
- AE7. Covers R6. Given an assigned rule thickness of 2.0 mm on PETG at 0.4 mm nozzle, when a rib is created without override, then rib thickness equals the rule parameter.
- AE8. Covers R15. Given an agent create, when the add-in executes, then no modal Fusion dialog is shown and a structured result is returned.
- AE9. Covers R16. Given Add Enclosure Boss, when the command dialog opens, then the user sees Fusion selection and value inputs (target body, plane, diameter, height, hardware), not a JSON textbox.
- AE10. Covers R8. Given retention.skirt_bump or retention.bayonet with no geometry yet, when the recipe runs, then it refuses or builds the joint. It must not return success with only a warning.
- AE11. Covers R21. Given a coordinated pair whose second side fails, when the service returns, then the first side is not left as unmanaged residue.
- AE12. Covers R14. Given files copied to the add-ins folder but the add-in not loaded, when an agent create runs, then the add-in is loaded or the call refuses enclosure-addin-not-installed after a failed load, not a silent no-op.
- AE13. Covers R14. Given a loaded add-in whose version/bytes do not match the bundle, when an agent create runs, then the result reports a mismatch token and does not execute the stale copy.

### Success Criteria

- A reviewer can map each Autodesk Plastic command in the Design Extension documentation reference to a shipped recipe, an explicit out-of-scope row, or a deferred unit.
- Captive-nut, hardware alias, skirt-bump, and bayonet no-ops are gone before any complete-joint claim.
- Live Fusion fixtures exist for Boss pair, Snap, Lip, Rest, Rib/Web, and rule inheritance.

### Scope Boundaries

- In: published recipe families plus missing Design Extension families (Rest, FDM rule analogue, Rib/Web inheritance).
- In: docs/matrix/SKILL/example parity with add-in behavior.
- In: auto-install and load, Fusion-native command dialogs, structured agent results, user docs and agent docs.
- Out: Autodesk BossFeature / designPlasticRules as the required path.
- Out: Cloning Design Advice injection-molding analysis.
- Out of this first PR only: Autodesk Geometric Pattern size-gradient patterning. Ordinary rectangular/circular/path pattern already exists as operations and stays.
- Out: Live modeling of Claire's vest enclosure as the audit method.
- Out: Generating many enclosure CAD candidates in host Python, or a host-side clearance solver that invents unsourced numbers. Fusion remains the model.

#### Deferred to Follow-Up Work

- Optional entitled bossFeatures.add adapter after a two-license live probe. Not required for the commercial bar.
- Optional later: a fastener catalog UI that inserts real Fusion fastener components into holes. This PR still models complete seats and pockets; it does not have to clone Autodesk Insert Fastener.
- Autodesk Geometric Pattern size-gradient patterning.

#### Outside this product's identity

- A second CAD store on the host.
- Unsourced universal snap-strain or heat-set bore tables shipped as truth.

### Key Decisions

- KD1. Commercial bar is Design Extension outcomes on base Fusion, including plastic-rule values that printed parts still use, plus polymer family and nozzle when known. Governs R1-R7.
- KD2. This plan authorizes a fix PR through railyard:deliver. Live Fusion acceptance remains a merge gate. Governs R20.
- KD3. Independent Autodesk Help/API research is the outcome source. The prior spec attachment is input, not authority. Governs R1-R7. Native Autodesk BossFeature/PlasticRule objects are not required if ordinary Fusion features match the outcomes.

### Sources

- Autodesk Help: Create a boss, Create a snap fit, Create a lip and groove, Create a rest, Create a rib, Create a web, Plastic rules, Design Advice, Design Extension documentation reference.
- API: BossFeatureSideInput, PlasticRule, designPlasticRules.
- Local: plugins/agent-utilities/skills/fusion-parametric-design/

---

## Planning Contract

### Key Technical Decisions

- KTD1. Ordinary Fusion features only for the required path. Optional extension APIs stay a separately identified probe. Chosen over calling bossFeatures.add as the default: API docs do not prove base-account entitlement.
- KTD2. Completeness is per published recipe_id in the shipped families: registry, discriminator, complete joint, mm/cm, sourced-or-refuse, human example, docs agreement, and a test that fails if any of those break. Coupon evidence is required only for fit-sensitive numbers (R18).
- KTD3. Fix the shared unit and dispatch bugs once. makePolygonProfile must call mmToCm. Hardware aliases must set the discriminator boss actually reads. No-op recipes (skirt_bump, bayonet) must refuse or build.
- KTD4. FDM plastic rules are Fusion parameters on the component, not Autodesk PlasticRule objects. Thickness, draft, nominal radius, clearance, polymer family, and nozzle diameter are in. Injection-molding Design Advice analysis stays out; Geometric Pattern size-gradient stays follow-up.
- KTD5. Sequence by print-wrong and missing-family risk. Units: shared correctness, boss/hardware, snap/lip/rest, rules including Extrude/Shell/Thicken/Draft, Fusion-native dialogs plus agent path, user/agent docs, tests/release.
- KTD6. Live Fusion acceptance is the geometry gate. Offline tests own contracts, units, and refusals. They do not certify B-Rep.
- KTD7. Do not revive host-side enclosure solvers. Fusion remains the feature tree.
- KTD8. Create is atomic. If a later native step fails, undo or delete the managed group created in that request before returning a refusal.
- KTD9. Humans use Fusion CommandInputs (selections, values, dropdowns, checkboxes, tooltips). Agents call the same service with structured requests. No JSON textbox and no paste-JSON inputBox.

### High-Level Technical Design

Request JSON enters one service. Family plus subtype pick a recipe. Recipes call shared native helpers. Fusion holds geometry, parameters, and identity. Host code does not keep a second model.

Flow: MCP or Fusion command JSON -> installer probe and load -> EnclosureFeatureService -> family discriminator -> boss/hardware, snap, lip/groove, rest, or FDM rule params -> sketches/extrudes/holes/combine -> timeline group plus attributes -> structured FeatureResult.

### Assumptions

- Matching Autodesk plastic *results* (geometry and parameters) is the bar. We do not have to create Autodesk's private BossFeature or PlasticRule timeline objects if ordinary Extrude/Hole/Combine plus our parameters look and edit the same for users.
- Roundhouse MCP is optional convenience. The add-in plus skill installer must work without it. Bundling a small MCP helper later is allowed; it is not a Roundhouse dependency.
- Existing dirty worktrees stay untouched. Implementation uses a fresh branch from current main and opens a PR.

### Implementation Constraints

- Plugin changes bump both manifests and repin the marketplace.
- Preserve unrelated working-tree changes.
- No live Fusion calls in this planning thread.
- scripts/test.sh is the Python/hook gate. New TypeScript enclosure tests need an explicit runner in Verification.

### Sequencing

U1 shared units/dispatch. U2 boss/hardware complete joints. U3 snap/lip/rest. U4 FDM rules plus Extrude/Rib/Web/Shell/Thicken/Draft inheritance. U5 Fusion-native dialogs and agent path. U6 user/agent docs, coupons, matrix, live fixtures, PR/release.

---

## Implementation Units

### U1. Shared units and dispatch

- **Goal:** Wrong-size sketches and mis-routed hardware aliases cannot ship.
- **Requirements:** R9, R11, R19, R21
- **Dependencies:** none
- **Files:**
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/native/sketches.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/native/holes_threads.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/service.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/src/enclosure-features/recipe-registry.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/tests/test_enclosure_dispatch.py
    (create this module; scripts/test.sh discovers tests/test_<area>*.py)
- **Approach:**
  1. Convert polygon acrossFlats through mmToCm like circles.
  2. When family is hardware, set the subtype boss/hardware actually consume. Do not leave it on unused type while boss reads variant.
  3. Add a registry/add-in parity check: every published id has a family handler and a discriminator that the handler reads.
  4. Refuse numeric AF/depth defaults for nut pockets.
  5. On recipe failure after native creates, undo or delete the managed group from that request (KTD8).
- **Patterns to follow:** existing mmToCm in makePlanarProfile; refusal tokens already in service.ts.
- **Test scenarios:**
  - Happy: AF 5.5 mm produces cm coordinates 0.55.
  - Edge: AF 5.5 without unit is treated as mm, still converted.
  - Error: hardware.hex_nut without AF refuses; it does not build boss.support.
  - Integration: registry lists hardware.hex_nut and dispatch reaches polygon pocket.
- **Verification:** Offline test fails if polygon points skip mmToCm or hardware aliases default to support.

### U2. Boss and hardware complete joints

- **Goal:** Boss variants match Autodesk Boss results on ordinary features.
- **Requirements:** R1, R8, R9, R10, R12, R22
- **Dependencies:** U1
- **Files:**
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/recipes/boss.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/native/holes_threads.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/src/enclosure-features/recipe-registry.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/docs/live-fusion-acceptance.md
- **Approach:**
  1. captive_* is boss plus sourced polygon pocket plus screw clearance if the variant is a fastening boss. No silent 5.5 / 2.5 mm.
  2. Publish or refuse boss.compression in the registry. Do not leave an executable unlisted variant.
  3. Coordinated pair uses one connection identity and two child roles with a shared axis. Missing side body refuses. Inspect must show the same parent feature_id on both sides.
  4. Screw/tapped/thread-forming seats use Hole counterbore/countersink APIs when the request names a head type. Head types follow Autodesk Boss: pan, round, round washer, flat, oval, hex, hex washer.
  5. Heat-set remains insert-spec gated.
- **Patterns to follow:** current extrude-then-join boss; makeInsertBore; Autodesk BossFeatureSideInput as the outcome checklist, not the call path.
- **Test scenarios:**
  - Happy: sourced hex pocket depth below boss height creates a cut participant on the target body.
  - Error: missing insert_spec on heat-set refuses with coupon-required.
  - Edge: pocket depth >= boss height warns or refuses rather than cutting through silently.
  - Integration: coordinated_pair without two bodies refuses assembly-context-required.
  - Integration: successful pair inspects as one connection identity with two child roles.
- **Verification:** Live fixture: M3 heat-set, captive hex, screw counterbore pair. Offline: refusal and unit tests.
- **Execution note:** Characterization-cover current captive-nut defaults before changing them.

### U3. Snap, lip, rest

- **Goal:** Two-body snap and lip, plus Rest, exist as real geometry.
- **Requirements:** R2, R3, R4, R8, R12, R22
- **Dependencies:** U1
- **Files:**
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/recipes/retention.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/recipes/seam.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/recipes/support.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/docs/live-fusion-acceptance.md
- **Approach:**
  1. Cantilever snap must create hook and matching groove when a receiver body is supplied. Parallel is the Autodesk default to match first. Hook and groove share one connection identity with two child roles (R12).
  2. skirt_bump and bayonet currently stamp nothing and return success. Change to refuse-until-built or implement. Success with only a warning is a defect.
  3. Seam lip/groove already exists. Align parameters and two-body behavior with Autodesk Lip types: Lip, Groove, Lip And Groove.
  4. Add support.rest as a closed-profile intersect/offset/thickness/draft recipe. There is no public Rest API. Do not invent a rest.* family; support already publishes rest-like landing geometry.
- **Patterns to follow:** current cantilever beam+hook; Autodesk Create a snap fit, Create a lip and groove, Create a rest.
- **Test scenarios:**
  - Happy: parallel snap with two bodies yields hook join and groove cut.
  - Error: snap with no receiver body refuses instead of a one-sided hook presented as complete.
  - Error: retention.skirt_bump without implementation refuses.
  - Integration: lip_and_groove on two bodies shares one feature id with two roles.
  - Integration: parallel snap with two bodies shares one connection identity with hook and groove child roles.
- **Verification:** Live fixtures for snap, lip-and-groove, rest. Offline refusal tests for no-ops.

### U4. FDM plastic-rule analogue and inheritance

- **Goal:** Assigned rule values, including polymer and nozzle when known, drive later plastic-like features.
- **Requirements:** R5, R6, R7, R18
- **Dependencies:** U1
- **Files:**
  - plugins/agent-utilities/skills/fusion-parametric-design/data/enclosure-feature-rules.json
  - plugins/agent-utilities/skills/fusion-parametric-design/src/enclosure-features/rules.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/recipes/reinforcement.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/service.ts
  - new assign-rule operation (not a geometry recipe)
- **Approach:**
  1. Store thickness, draft angle, nominal radius, clearance, polymer family, and nozzle diameter as named Fusion parameters on the target component.
  2. Extrude, Rib, Web, Boss, Snap, Lip, Rest, Shell, Thicken, and Draft read those parameters when the request omits an override.
  3. Do not call design.designPlasticRules on the required path.
  4. Keep unsourced fit numbers as placeholders. Fit-sensitive create/export refuses unless a source token or coupon result is present (R18). Polymer/nozzle change invalidates fit-sensitive claims until re-sourced or couponed.
  5. Design Advice injection-molding analysis is not cloned. Geometric Pattern size-gradient patterning stays follow-up.
- **Patterns to follow:** Autodesk Plastic rules field list; local enclosure-feature-rules.json refusal doctrine.
- **Test scenarios:**
  - Happy: assigned thickness 2 mm on PETG / 0.4 mm nozzle is referenced by rib thickness expression.
  - Happy: a subsequent Shell or Draft without override reads the same rule parameters.
  - Edge: request override 3 mm wins over rule 2 mm.
  - Error: creating a fit-sensitive pocket with only placeholder clearance refuses.
  - Integration: rule change updates parameter; next inspect shows the new expression.
- **Verification:** Parameter inspect on a disposable component. No Autodesk PlasticRule object required.

### U5. Fusion-native dialogs and agent path

- **Goal:** Humans get ordinary Fusion command dialogs. Agents call the same service without a JSON UI.
- **Requirements:** R13, R14, R15, R16
- **Dependencies:** U1
- **Files:**
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/commands.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/dispatch.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/main.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/src/enclosure-features/installer.ts
- **Approach:**
  1. Replace request_json textboxes and paste-JSON inputBox with Fusion CommandInputs: body/plane/point selections, value inputs, dropdowns, checkboxes, tooltips (KTD9).
  2. Agent lane must not call ui.messageBox or ui.inputBox. It returns structured results.
  3. First agent use: installer probe, copy, load, command discovery. File copy without load is not success (AE12). A loaded add-in whose bytes/version do not match the bundled copy reports a mismatch token.
  4. Roundhouse MCP is not required. If a small MCP helper is bundled later so this skill does not depend on Roundhouse, that is optional follow-up, not this unit's gate.
- **Patterns to follow:** Autodesk plastic command dialogs (selections then values). Existing installer probe. Avoid modal execute wedges.
- **Test scenarios:**
  - Happy: Add Enclosure Boss dialog exposes selection and value inputs, not a JSON box.
  - Error: agent execute with add-in missing returns enclosure-addin-not-installed and triggers install, not a modal.
  - Integration: the same boss parameters from the human dialog and from an agent request produce the same recipe_id and parameter names.
- **Verification:** Live first-use install on a clean Fusion user add-ins folder. Live screenshot of a native dialog. Offline tests that commands.ts no longer contains request_json or inputBox JSON prompts.

### U6. Docs, coupons, matrix, live fixtures, release

- **Goal:** User docs and agent docs match geometry, and the PR can ship.
- **Requirements:** R17, R18, R19, R20
- **Dependencies:** U2, U3, U4, U5
- **Files:**
  - plugins/agent-utilities/skills/fusion-parametric-design/SKILL.md
  - plugins/agent-utilities/skills/fusion-parametric-design/references/enclosure-features.md
  - plugins/agent-utilities/skills/fusion-parametric-design/references/enclosure-feature-capability-matrix.md
  - plugins/agent-utilities/skills/fusion-parametric-design/fusion_addin/AgentUtilitiesEnclosure/recipes/coupon.ts
  - plugins/agent-utilities/skills/fusion-parametric-design/docs/live-fusion-acceptance.md
  - plugin manifests and marketplace pin
- **Approach:**
  1. Captive-nut coupon stations must be polygons, not circles.
  2. Matrix rows for Rest, FDM rules, and complete joints match capability after the code exists.
  3. Write user-facing command/menu docs (what each dialog does) and agent-facing SKILL/API docs (what each recipe_id does). They must agree with the add-in. Do not claim Autodesk Insert Fastener unless that catalog UI ships.
  4. Live fixtures: boss pair, captive hex, heat-set, snap, lip, rest, rib-with-rule, web-with-rule, first-use install, Undo.
  5. Version bump both manifests and repin marketplace.
- **Test scenarios:**
  - Happy: coupon type captive_nut sketches a hex/square, not a circle.
  - Error: docs/matrix listing a recipe the add-in cannot execute fails a parity test.
  - Integration: scripts/test.sh enclosure or the named TypeScript runner covers new tests.
- **Verification:** Repo gate green. Live acceptance notes filled. Manifest versions match.

---

## Verification Contract

| Check | When | Command / evidence |
|---|---|---|
| Skill-cleaner / manifests | every plugins/ change | npx tsx plugins/agent-utilities/skills/skill-cleaner/scripts/skill-cleaner.test.ts; JSON parse both plugin manifests; SKILL frontmatter name matches directory |
| Fusion Python/hook gate | units that touch the skill | plugins/agent-utilities/skills/fusion-parametric-design/scripts/test.sh |
| Enclosure contract tests | U1-U6 | extend scripts/test.sh or add a documented node --test/tsx path for add-in unit tests; the plan is incomplete if new TS tests have no runner |
| Live Fusion | each shipped family | disposable document; screenshots; timeline group; parameters; Undo; record Fusion build and add-in version in docs/live-fusion-acceptance.md |
| Release coupling | any plugins/ change | bump both manifests; marketplace repin |

---

## Definition of Done

- Every R1-R22 is cited by at least one unit, a boundary, or an explicit deferral.
- AE1-AE13 have a test or live fixture.
- No published geometry recipe returns success after creating no geometry. Assign-rule is an operation that stores parameters, not a geometry recipe.
- No silent 5.5 / 2.5 nut defaults.
- Agent create does not open a modal dialog.
- A fix PR is opened from this plan. Live Fusion acceptance remains a merge gate.
- Live Fusion acceptance exists for Boss, Snap, Lip, Rest, and rule-driven Rib and Web.

---

## Appendix

### Current code-backed gaps

| Id | Symptom | Evidence |
|---|---|---|
| G1 | Polygon nut pocket likely 10x oversized | makePolygonProfile skips mmToCm |
| G2 | Silent AF 5.5 and depth 2.5 mm | boss.ts captive branch |
| G3 | hardware.* can become support boss | service sets type; boss reads variant |
| G4 | Captive-nut coupon is circles | coupon.ts station sketches |
| G5 | skirt_bump and bayonet succeed with no geometry | retention.ts |
| G6 | boss.compression executable but unpublished | boss variants vs registry |
| G7 | No Rest family | registry has no rest id |
| G8 | No Autodesk-like assigned plastic rule | rules JSON is placeholders; no component assign path |
| G9 | Human examples incomplete / stale | commands.ts vent.rectangular |
| G10 | Agent lane uses modal UI | commands.ts inputBox/messageBox |
| G11 | TS enclosure tests not in test.sh | Python unittest discover only |

### Autodesk outcome checklist used

Plastic tab: Assign/Manage Plastic Rules, Boss, Snap Fit, Lip, Rest, Rib, Web, Geometric Pattern, Design Advice, Presets. Rib/Web also exist under Solid. This plan keeps rule values, polymer/nozzle awareness, and Fusion-native dialogs. Injection-molding Design Advice analysis is not cloned. Geometric Pattern size-gradient is follow-up.

External research was load-bearing for R1-R7 and KTD1/KTD4.
