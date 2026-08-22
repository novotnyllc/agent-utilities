# Native inspection fluency

Ask one precise question with the native Fusion instrument that owns it. Read the direct result, compare it once to the stated requirement, and stop. A
battery of checks is not fluency; it is an undeclared validation framework.

## Match the tool to the question

| Tool | Answers | Does not answer |
|---|---|---|
| Measure | Distance, minimum distance, angle, area, position, or another direct value between named entities | Hidden topology, collision volume, wall continuity, motion clearance, or why a feature failed |
| Section Analysis | Internal topology, obscured geometry, wall layout, joint engagement, and visible thickness at a chosen cut plane | A numeric minimum wall-thickness survey, interference verdict, or proof for geometry outside the section plane |
| Interference | Overlap between selected solid bodies or components in the current assembled pose | Required clearance when bodies do not overlap, future motion collisions, contact behavior, or surface quality |
| Curvature analysis | Surface quality, curvature distribution, tangent or curvature continuity; zebra stripes expose reflection continuity across faces | Distance, thickness, watertightness, interference, or structural strength |

## Measure named interfaces

Select only the entities that define the current question: connector face to
opening edge, screw head to seat, lid lip to groove, or body to keep-out. Read
Fusion's reported value and preserve its units.

Measure answers the selected geometry in the current state. It does not prove the same clearance at another pose or across an unselected region. If the
question is collision, use Interference; if it is hidden construction, cut a
section.

## Cut one decisive section

Place Section Analysis through the joint, wall, passage, or buried feature
whose topology is uncertain. Hide irrelevant objects and orient the view so
the cut exposes the intended interface.

Use the section to inspect what exists, then use Measure on specific section
geometry only when a number is required. Do not infer a global minimum wall
thickness from one attractive section, and do not add a stack of section
planes when the uncertainty names one location.

## Check overlap in the installed state

Run Interference on the named bodies or components in their real assembly
positions. Report which selected entities overlap and Fusion's direct result.

No reported interference means no overlap for that selection and pose. It
does not establish positive clearance. Measure the required gap separately,
and drive a moving joint to each user-relevant critical pose before asking the
same bounded interference question there.

## Read surface continuity visually

Use Curvature Comb for curvature along an edge, Curvature Map for high and low
surface curvature, and Zebra Analysis for reflection continuity across faces.
Aligned but sharply changing zebra stripes indicate tangent continuity; smooth
stripe flow supports curvature continuity. Discontinuous stripes expose a
positional or tangent break.

Curvature tools judge surface flow, not manufacturing fit. Do not convert a
zebra image into an invented score or use visual smoothness as dimensional
evidence.

## Bound every read

State the uncertainty, name the entities, invoke one tool, and report the
native result. If that result does not answer the question, choose the one
correct next instrument or report the capability gap. Never enumerate broad
pair sets, generate clearance matrices, or aggregate inspection results into
an agent-authored verdict.

## Sources

- [Measure](https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-EC996CE0-4B79-47C6-8FA9-4D5FBD98D2E5)
- [Interference](https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-22FB1D14-2E39-4EE5-84F3-4B29C1FCF5D9)
- [Section Analysis](https://help.autodesk.com/view/fusion360/ENU/?guid=GUID-24BB0F1A-6D31-4A05-96F6-4E4D6D2B7C0F)
