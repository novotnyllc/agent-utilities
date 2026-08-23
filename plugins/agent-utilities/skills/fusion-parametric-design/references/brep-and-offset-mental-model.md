# B-Rep and offset mental model

The minimum topology model needed to choose and debug native features:
what a body is made of, why signed offsets move along normals instead of
scaling, and why Shell, Thicken, Offset Face, fillet, and loft fail in
predictable ways for different reasons.

## Geometry and topology are different

Geometry is the curves and surfaces themselves. Topology is the record
of how faces, edges, vertices, and loops bound one another. Two bodies
with identical geometry can differ in topology, and the kernel reasons
about topology first.

## Read the hierarchy

Body/shell, then faces, then loops, then edges, then vertices. An inner
loop normally represents a hole or a trimmed-away region. Most
construction and repair questions are questions about this hierarchy,
not about coordinates.

## Open and closed bodies

An open surface body has exposed boundaries. A closed, consistently
connected shell can bound a solid, and operations that require a solid
need that closed topology. Open surface bodies are still valid Boundary
Fill tools when the complete set of tool bodies and planes defines
closed cells.

## Offsets move along local normals

Shell, Thicken, and Offset Face construct displaced surfaces over regular
regions: source points move along the chosen signed normal direction by
the requested distance. Check face orientation and offset side. An
offset can become singular when it moves toward a center of curvature
and the signed distance reaches the corresponding principal radius;
separate displaced regions can collide sooner. These operations do not
scale the body. Consequences:

- The same magnitude can succeed in one normal direction and fail in the other.
- A signed offset can collapse where it reaches a local principal radius.
- Adjacent displaced faces can collide or cross.
- Tight curvature outruns the requested thickness.
- Tiny faces and edges create degenerate intersections.

## Why fillets fail

A fillet is a rolling-ball blend between adjacent faces, not a pointwise
normal displacement of source-surface points. It fails when it
terminates badly at an endpoint, consumes a tiny adjacent face, or
intersects a neighboring blend. Endpoint and tiny-face inspection comes
before any radius change.

## Why lofts fail

A loft interpolates through ordered sections. Rails are separate guide
curves and must intersect every section; a centerline is a distinct path
input, not a rail. `isClosed` reconnects the last section to the first
for a cyclic loft; it does not mean the profiles are closed or request
solid output. Failures come from profile seam mismatch or order,
incompatible rails, abrupt topology changes between sections, or
interpolation that folds the surface through itself. Inspect sections,
rails, and any centerline before touching dimensions.

## Inspect the construction, not the radius ladder

Isolate the failing region, inspect loops, endpoints, and curvature,
and check feature order. One bounded numeric correction is valid when
inspection identifies the governing limit and the corrected value still
satisfies design intent. Otherwise change topology or construction;
repeated unguided reduction is diagnosis by exhaustion, not a repair.

## Sources

- [Understanding Geometry and B-Rep (Autodesk University, 2018)](https://www.autodesk.com/autodesk-university/class/Understanding-Geometry-and-B-Rep-Inventor-and-Fusion-360-2018)
- [Fusion Models (B-Rep and Geometry)](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/BRepGeometry_UM.htm)
