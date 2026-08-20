# Design doctrine

## Evidence hierarchy

A CAD model is only as correct as the facts it encodes. Use this precedence:

1. physical law and safety requirements;
2. official standard or manufacturer evidence;
3. verified measurement of the actual sample;
4. trustworthy exact CAD checked against dimensions;
5. conservative proxy;
6. visual estimate, used only to choose what to measure next.

A rendered image is useful for noticing a problem. It is not dimensional evidence.

## One owner for each fact

Every important dimension has one owner:

- `src_` owns the real object's measured or published dimension;
- `clr_` owns functional spacing;
- `fab_` owns process capability;
- `pack_` owns dynamic/service space;
- `des_` owns preference;
- `calc_` derives geometry.

Never let the same physical fact appear as unrelated literals in multiple sketches or features.

## Document lifecycle

The working document is named and saved before it is mutated, and never left in
an unsaved Untitled state at the end of a transaction batch — an unsaved Fusion
document is one crash away from gone, so naming and saving are part of
establishing the document, not an afterthought:

- the name comes from the manifest's `project.fusion_document` and is
  human-sensible — what a person would write, never a slug, hash, or timestamp;
- adopting a user's existing unsaved document means saving it first, under a
  manifest-derived name stated to the user, before any mutation;
- each successful transaction batch ends with a save; a Fusion save creates a
  version, and that checkpoint is the desired behavior;
- the document's durable identity is its dataFile id, recorded in
  `DESIGN-STATE.md` after the first save — names are user-mutable, so later
  sessions reconnect by id (open documents first, then the data API) and only
  report the current name;
- an unresolvable save or reconnect — offline data API, no active project,
  missing declared folder, missing recorded id — is a named refusal, never a
  silently kept Untitled;
- read-only inspection of an unsaved document stays allowed.

## Naming

The browser is a user interface, not a database. Names are for the person
reading the tree; classification the tooling needs rides on Fusion attributes.

What the sourced practice says:

- Name components, bodies, and sketches meaningfully the moment they are
  created; `Component1` is the anti-pattern. Keep names short but descriptive
  and use one consistent convention. (Product Design Online, "Understanding
  Bodies and Components — Fusion 360 Rule #1"; Autodesk Fusion community and
  support articles on renaming browser items; cadin360, "How to name
  components properly in Fusion 360".)
- Spaces are legal and idiomatic in component, body, sketch, and feature
  names — "Left Wheel", "Main Frame" — so write plain words, not slugs.
- Fusion appends an immutable `:N` instance suffix to every occurrence, and
  `+`/`:digits` inside a name collides with occurrence-path syntax, so names
  must read well in front of `:1` and never imitate it. (Autodesk Fusion API
  documentation, "Documents, Products, Components, Occurrences, Proxies".)
- User parameters cannot contain spaces and cannot be unit tokens; snake_case
  and camelCase are both accepted. (Product Design Online, "User Parameters";
  Autodesk forum, "Name Syntax for Change Parameters".) This skill's `src_`,
  `clr_`, `fab_`, `pack_`, `des_`, `calc_` snake_case prefixes stay: parameter
  identifiers live under identifier rules, not display-name rules, and the
  prefix is the ownership convention above.
- Machine metadata belongs in the Attributes API under an add-in-specific
  group, not in display names. (Autodesk Fusion API documentation,
  "Attributes".) This skill's group is `fusion_parametric_design`.
- Component names and Part Number/Description properties flow into BOM and
  parts-list exports, so a shouty machine name leaks into every downstream
  document. (Autodesk support articles on BOM/parts lists; OpenBOM Fusion
  best practices.)

Synthesis, applied by this skill:

- Group components read like a product tree: `References`, `Product`,
  `Fixtures`, `Validation`. No numeric prefixes — the Fusion browser preserves
  authoring order and does not alphabetize, so `00_`/`90_` sorts nothing and
  only shouts.
- Children are plain named: `PD Trigger Reference`, `PD Trigger Envelope`,
  `USB-C Insertion Keep-Out`, `Base`, `Lid`, `PD Fit Coupon`.
- Roles (`reference`, `packing`, `keepout`, `product`, `validation`) are
  derived from the manifest blocks that already own the classification and
  written by the scaffold as the `role` attribute in
  `fusion_parametric_design`. A name never encodes a role.
- Adoption is by attribute or legacy name: an existing design keeps resolving
  because every lookup is by the manifest's own component paths, and inventory
  reads the `role` attribute first, recognizing the legacy
  `REF__`/`PACK__`/`KEEP__`/`PROD__`/`FIX__`/`VAL__` prefixes only when no
  attribute answers — reported with `legacy-name` provenance, never silently.

## Parametric integrity

A healthy Fusion model has:

- design history enabled;
- fully or intentionally constrained sketches;
- expressions that reference named user parameters;
- stable datum planes, axes, and component origins;
- descriptive components/features;
- no silent errors or warnings after Compute All;
- local feature edits rather than broad reconstruction.

Imported geometry is reference evidence unless it was created as a controlled native component. Avoid building long chains from transient imported face identities.

## Functional geometry before exterior sculpture

For enclosures and mounts, finish this order:

1. reference and packing models;
2. support and mounting datums;
3. connector/cable/service keep-outs;
4. insertion and removal paths;
5. internal boundary;
6. structural walls, ribs, bosses, and seams;
7. exterior form;
8. polish and labels.

Do not use exterior styling to conceal an unresolved packing problem.

## Load path

Trace each applied load to a support:

- component retention through ledges, saddles, screws, or pads;
- connector insertion load into grounded shoulders or walls;
- cable pull into strain relief;
- lid fastener tension into bosses and base walls;
- wearable impact into broad, smooth garment support;
- shelf/bracket load into fasteners and substrate.

Avoid thin cantilevers, abrupt thickness changes, isolated bosses, and tension across weak layer interfaces. Ribs and gussets should join the actual load path, not merely decorate empty space.

## FDM process assumptions

Record printer, nozzle, layer height, material, and orientation. Use process parameters rather than folklore. A rule such as “2 mm wall” is incomplete unless it is compatible with the selected nozzle and load.

Check:

- printable wall and roof thickness;
- bridges/overhangs;
- support removal;
- seam and fit clearances;
- hole compensation where required;
- first-layer contact and warping risk;
- fastener and insert geometry;
- anisotropic strength;
- heat exposure.

## Polish

Polish is the last functional pass, not a substitute for structure:

- break sharp exposed edges;
- add deliberate chamfers/fillets where they survive printing;
- smooth garment/body-facing surfaces;
- protect controls and connectors without blocking access;
- keep labels legible and associated with ports;
- remove accidental ledges that snag or trap support.

## Physical proof

Use the smallest physical artifact that answers the uncertainty:

- mating-profile coupon for scan-derived contours;
- hole/insert coupon for fasteners;
- snap/clip coupon for flexures;
- connector-mouth coupon for overmolds;
- thermal test article near converters;
- load coupon or full proof test for structural claims.

A coupon result should update the manifest's confidence/provisional status and the Fusion parameter comment.
