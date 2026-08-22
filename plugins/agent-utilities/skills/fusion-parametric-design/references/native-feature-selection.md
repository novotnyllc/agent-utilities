# Native feature selection

Choose construction from the current topology, not from the desired
appearance. The same silhouette can be built as a closed solid, an open
surface, or a repaired imported body, and each starting state has a
different native feature that owns the job. Before creating geometry,
classify the body; after creating it, read the native health result
before stacking anything on top.

## Classify the starting body

One bounded read answers this: is the target a closed solid, an open
surface, or imported/dirty topology? Fusion reports body solidity and
feature health natively; do not infer solidity from a screenshot.

## Decision table

| Starting state | Desired result | Native feature | Change signal |
|---|---|---|---|
| Closed solid | Uniform hollowing | Shell; select the body for closed hollowing, or select only intended opening faces; set `isTangentChain` deliberately (`false` for an exact face set) | Minimum-radius or passage warnings mean the wall cannot offset - inspect curvature first |
| Open surface set with gaps | Watertight stitched body | Patch the gaps, then Stitch | Stitch joins adjacent surfaces; a fully enclosed stitched set becomes solid |
| Planes and open or closed B-Rep tool bodies that define closed cells | Selected cell volume | Boundary Fill | Compute cells from the tools, select the intended cells, then choose Join, Cut, Intersect, New Body, or New Component |
| Valid surface | Material normal to it | Thicken | Offset failure means the requested thickness does not survive the local curvature - see the B-Rep model |
| Imported or dirty topology | Usable geometry | Heal, simplify, delete/replace faces, or bounded direct modeling | Do not hang parametric features on unhealthy imported topology |

## Prefer solid-first construction

If the intended result is naturally a closed volume - an enclosure lid,
a cap, a shell - prefer solid-first when it avoids a separate closure
operation. Surface Loft or Sweep plus Thicken remains a valid native
strategy. Solid-first avoids the unfinished-sheet failure class, but it
does not exempt Shell itself: tight curvature, small faces, or
intersecting offsets can still make any offset infeasible. Read the
native health result either way.

## Use surface workflows deliberately

Surface workflows can leave open or stitched surface bodies until a
closed volume is formed. Fusion represents sheet/surface topology as a
`BRepBody` with `isSolid` false, so an open sheet is still a body --
collect it and read `isSolid` exactly as for any other body. Never
treat a surface that looks closed on screen as solid; the native flag,
not the viewport, decides.

## Refuse invalid normal offsets

When an offset folds or collides - the signed offset reaches a local
curvature limit, or displaced faces intersect - inspect the governing
limit first. One bounded numeric correction is allowed when inspection
identifies that limit and the corrected value still satisfies design
intent. Otherwise change the topology, feature order, or strategy;
repeated unguided laddering is not a repair.

## Inspect before continuing

Read the native feature health or error first. Then invoke one additional
named inspection - body solidity, gap state, or a section view - only
when it answers the immediate uncertainty before building downstream.
An unhealthy body poisons every downstream feature and every diagnosis
of them.

## Sources

- [Understanding Fusion design concepts](https://www.autodesk.com/learn/ondemand/curated/understanding-fusion-design-concepts)
- [Surface modeling course](https://www.autodesk.com/learn/ondemand/course/surface-modeling)
