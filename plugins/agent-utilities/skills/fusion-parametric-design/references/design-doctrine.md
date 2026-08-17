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
