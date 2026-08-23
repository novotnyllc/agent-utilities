# Kernel failure playbook

Use a kernel or feature-health error to choose one bounded diagnostic or
corrective action. The error string names a failure family, not a repair
recipe: preserve and report it exactly, then test the suspected
construction.

## Evidence labels

The map below is a diagnostic heuristic, not a set of verified diagnoses.
`observed-live` marks an error token observed in live Fusion
feature-health/error output; it does not verify the proposed cause or
action. `forum-case` marks mechanisms documented in community case
threads; those are evidence of behavior, never Autodesk kernel
specifications, and no public documentation defines the ASM tokens.

## Error-to-action map

| Error string or signature | Evidence | Diagnostic next action |
|---|---|---|
| ASM_BL_UNFIN_SHEET | observed-live | Suspect an unfinished/open sheet result. Inspect body solidity first to confirm; then close gaps with Patch/Stitch, use Boundary Fill where cells define the volume, or rebuild solid-first before hollowing. |
| ASM_LOP_OFF_NO_SURF | observed-live | Stop radius/offset laddering. First suppress suspected downstream blends or cuts as a discriminating test. Reorder only after dependency and result-equivalence checks. If the offset still fails, inspect signed direction, curvature, and tiny faces; simplify or replace the topology, or choose a different construction. |
| ASM_LOFT_SURFACE_SELF_INTERSECTS | observed-live | Inspect section order and seam alignment, rail intersections, and section compatibility. Enable cyclic closure only when the section sequence wraps back to the first. Simplify or split the loft when interpolation crosses itself. |
| Offset Faces fails at a high-curvature transition | forum-case | Use one requirements-valid reduction as a local correction when inspection identifies the feasible limit; otherwise repair the collapsing region or change construction when displaced faces collide. |
| Fillet fails on imported or near-tangent segments | forum-case | Inspect endpoints; replace tiny or nearly tangent segments with clean native curves before retrying the blend. |
| Fillet succeeds on single edges but fails on the chain | forum-case | Disable tangent-chain selection, isolate the first failing endpoint or intersection, remove the tiny face or reorder neighboring blends, then rebuild the intended fillet. |

## Two-strategy retry policy

The initial native construction may receive one local correction guided
by inspection. If it still fails, try one genuinely different native
construction strategy. If that second strategy fails, stop and escalate
with the evidence. Repeated numeric changes are not a new strategy. This
budget is workflow policy, not a kernel diagnosis.

## Preserve evidence

Report the feature name, the exact error string, the selected entities,
and a section or screenshot of the failing region. Evidence survives
handoff; a paraphrase does not. For Loft, also preserve ordered sections,
connection mapping, rails or centerline, `isClosed`, end conditions, and
solid-versus-surface output.

## Stop conditions

Stop and report when: a second native approach has also failed; the
topology remains unhealthy after repair attempts; or the repair would
restructure geometry beyond what the user requested. A hard stop with
evidence is a result, not a failure of the session.

## Sources and evidence status

The three error tokens were observed in live Fusion feature-health/error
output; the cause and action mappings remain diagnostic heuristics.
Community cases: [offset failure](https://forums.autodesk.com/t5/fusion-design-validate-document/unable-to-offset-faces/td-p/12071111), [loft self-intersection](https://forums.autodesk.com/t5/fusion-design-validate-document/loft-self-intersects/td-p/10380571), [fillet on curved chains](https://forums.autodesk.com/t5/fusion-design-validate-document/fillet-in-curved-objects/td-p/10789255).
