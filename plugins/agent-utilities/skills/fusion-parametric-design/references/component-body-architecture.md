# Component and body architecture

Choose architecture from product identity and motion. Bodies describe
geometry within one part. Components describe parts and subassemblies that
carry their own origin, occurrences, relationships, identity, and lifecycle.

## Keep one part's geometry as bodies

Use multiple bodies inside one component while constructing one manufactured
part: tool bodies for Combine, surface bodies before Stitch, separate regions
before a final join, or alternate material volumes that still share one part
identity and never move independently.

Do not promote every construction body to a component. A component that has
no independent identity, placement, motion, reuse, or lifecycle adds browser
noise without expressing a real assembly boundary.

## Create components for real assembly items

Make an item a component when it is independently moving, reusable, repeated,
replaceable, sourced separately, or visible in the bill of materials. Create
an occurrence for every installed instance; repeated hardware is one component
definition with multiple occurrences, not copied anonymous bodies.

Position components with joints, joint origins, grounding, and rigid groups.
Do not encode assembly relationships as body transforms or coordinate math.

If a joint command rejects a body/component pairing, correct the architecture:
create the real part component, then joint component to component.

## Choose internal or linked external ownership

Use an internal component for geometry owned by this assembly: a fitted lid,
an assembly-specific spacer, a bracket whose interface and version move with
the parent design, or a one-off subassembly without an independent lifecycle.

Use a linked external design for a purchased part, shared catalog item,
independently reusable subassembly, or part that must be revised and versioned
without editing every parent assembly. Insert the canonical design and retain
the link; do not fork copies per project.

Promote an internal component to an external design only when independent
reuse, ownership, permissions, or versioning becomes real. Do not create a
file boundary in anticipation of a future product family.

## Choose the narrowest assembly relationship

| Situation | Native relationship | Rule |
|---|---|---|
| Components are already in their correct assembled positions | As-built Joint | Define their relative motion without repositioning them |
| Several components must behave as one rigid unit | Rigid Group | Lock the selected occurrences together without inventing pairwise motion |
| Components need mating, alignment, motion type, limits, or a maintained parametric relationship | Joint (parametric) | Select stable joint origins and let Fusion position and constrain the components |

Use a rigid As-built Joint when two already-positioned components need an
explicit pairwise rigid relationship. Use a Rigid Group when several placed
components form one rigid cluster and no internal motion matters.

Do not use Capture Position as the assembly model. A captured pose records a
position; joints and rigid groups express why the position persists.

After creating relationships, drive each moving joint through the relevant
poses and run the one native interference or clearance read the question
requires. Fusion does not infer physical contact from the joint alone.

## Sources

- [Component types](https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-E9E0A9D7-6CB4-4B37-A5A5-D4B17B2BC1F6)
- [Joints](https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-C82B7BF7-7E51-4E11-B4EA-3BE5CA04F803)
