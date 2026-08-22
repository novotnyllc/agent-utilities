# Sketch constraint discipline

A sketch that drives a feature is an interface, not disposable drawing geometry.
Settle its size, position, and intended motion before downstream features depend on it.

## Gate the feature on a stable sketch

Before Extrude, Revolve, Sweep, Loft, Rib, Hole placement, or another feature
consumes a sketch:

1. Constrain the profile to stable datums.
2. Replace governing literals with named user parameters.
3. Remove redundant or conflicting dimensions and constraints.
4. Confirm every remaining degree of freedom is intentional.
5. Run Compute All and read the sketch and timeline health.

Do not build downstream features on a sketch that is accidentally free to
translate, rotate, flip, or change topology. Fusion considers a sketch fully
constrained when every curve's size and position are completely defined.

## Dimension intent, not coordinates

Use geometric constraints for relationships: horizontal, vertical, parallel,
perpendicular, tangent, concentric, coincident, equal, midpoint, symmetry.
Use dimensions for values the design owns. Do not dimension every endpoint
independently when one relationship and one governing dimension express the
same intent.

Bind governing dimensions to named parameters such as `src_board_width`,
`clr_connector_side`, or `fab_wall_thickness`. A repeated literal is not a
relationship; an expression referencing one named owner is.

Use driven dimensions only to report derived geometry. Do not turn a required
design value into a driven dimension merely to silence an over-constraint.

## Anchor to stable datums

Prefer the component origin planes, origin axes, origin point, and named
construction geometry. Constrain the sketch to those datums explicitly.

Avoid anchoring critical geometry to fillet edges, split faces, or other
downstream topology that may be renamed or replaced after recompute. Project
only the geometry the sketch genuinely needs, and prefer construction lines,
centerlines, axes, and planes that state the design's invariant.

Do not use Fix as a substitute for understandable constraints. Fix is valid
for intentionally frozen imported or traced geometry when its provenance and
reason are named; otherwise express why the geometry cannot move.

## Treat partial constraint as an exception

A layout or exploratory sketch may remain partially constrained only when the
remaining motion is deliberate. Name the sketch and record the allowed degree
of freedom in its description or nearby construction geometry, for example:
`Connector path - endpoint slides along rail`.

Never leave unexplained blue geometry in a sketch that drives production
features. If the free motion cannot be stated in one sentence, constrain it
before continuing.

## Recompute before dependency

Finish the sketch, run Compute All, and read the result before adding the next
feature. A clean viewport is not a clean recompute. Resolve sketch warnings,
lost projections, over-constraints, and solver errors at the sketch that owns
them; do not bury them under downstream features.

## Source

- [Sketch constraints](https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-8D64C643-8FCC-4B4E-A2C0-34ACD7E3C4E5)
