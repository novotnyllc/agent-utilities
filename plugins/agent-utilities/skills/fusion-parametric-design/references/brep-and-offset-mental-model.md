# B-Rep and offset mental model

The minimum topology model needed to choose and debug native features:
what a body is made of, why offsets move along normals instead of
scaling, and why that makes Shell, Thicken, fillet, and loft fail in
predictable ways.

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

An open sheet has exposed boundaries. A closed, consistently connected
shell can bound a solid. Only a closed shell supports solid operations
reliably; an open sheet asked to behave like one produces the classic
offset failures.

## Offsets move along local normals

Shell, Thicken, offset faces, and many fillets construct displaced
surfaces: every point moves along its local normal by the offset
distance. They do not scale the body. Consequences:

- Concave regions collapse where the offset exceeds the local radius.
- Adjacent displaced faces can collide or cross.
- Tight curvature outruns the requested thickness.
- Tiny faces and edges create degenerate intersections.

## Why fillets fail

A fillet is a rolling blend surface. It fails when it terminates badly
at an endpoint, consumes a tiny adjacent face, or intersects a
neighboring blend. Endpoint and tiny-face inspection comes before any
radius change.

## Why lofts fail

A loft interpolates through sections and rails. Failures come from
profile seam mismatch or order, incompatible rails, abrupt topology
changes between sections, or interpolation that folds the surface
through itself. Inspect sections and rails before touching dimensions.

## Inspect the construction, not the radius ladder

Isolate the failing region, inspect loops, endpoints, and curvature,
and check feature order. Then change topology or construction. Repeated
numeric reduction is diagnosis by exhaustion, not a repair.

## Sources

- [Understanding Geometry and B-Rep (Autodesk University, 2018)](https://www.autodesk.com/autodesk-university/class/Understanding-Geometry-and-B-Rep-Inventor-and-Fusion-360-2018)
- [Fusion solids and surfaces](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/FusionSolidsAndSurfaces_UM.htm)
