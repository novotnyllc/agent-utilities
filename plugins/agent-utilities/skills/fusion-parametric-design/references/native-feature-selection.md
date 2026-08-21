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
| Closed solid | Uniform hollowing | Shell, with opening faces removed explicitly | Minimum-radius or passage warnings mean the wall cannot offset - inspect curvature first |
| Open surface | Closed volume | Patch the gaps, then Stitch | Boundary Fill is the tool when several intersecting surfaces or cells define the intended solid |
| Valid surface | Material normal to it | Thicken | Offset failure means the requested thickness does not survive the local curvature - see the B-Rep model |
| Imported or dirty topology | Usable geometry | Heal, simplify, delete/replace faces, or bounded direct modeling | Do not hang parametric features on unhealthy imported topology |

## Prefer solid-first construction

If the intended result is naturally a closed volume - an enclosure lid,
a cap, a shell - construct the outer solid and Shell it. Do not loft or
sweep an open sheet and then force a thickness onto it; that path ends
in unfinished-sheet and no-surface offset failures that solid-first
construction never meets.

## Use surface workflows deliberately

Surfaces are construction geometry until Stitch or Boundary Fill makes
them a closed volume. An open sheet is not a body. Never treat a
surface that looks closed on screen as solid.

## Refuse invalid normal offsets

When an offset folds or collides - concave regions collapse, adjacent
faces intersect - the answer is a different construction, not a smaller
number: change the topology, the feature order, or the strategy. One
diagnostic reduction is allowed; a radius ladder is not.

## Inspect before continuing

Read body solidity, feature health or error, gap state, and a section
view before building on any result. An unhealthy body poisons every
downstream feature and every diagnosis of them.

## Sources

- [Understanding Fusion design concepts](https://www.autodesk.com/learn/ondemand/curated/understanding-fusion-design-concepts)
- [Surface modeling course](https://www.autodesk.com/learn/ondemand/course/surface-modeling)
