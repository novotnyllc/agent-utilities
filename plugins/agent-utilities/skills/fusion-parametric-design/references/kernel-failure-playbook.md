# Kernel failure playbook

Translate a kernel or feature-health error into one different native
construction action. The error string names a failure family, not a
repair recipe: preserve and report it exactly, then change the
construction that produced it.

## Evidence labels

[verified-live] marks errors observed in real MCP sessions under this
skill's doctrine. [forum-case] marks mechanisms documented in community
case threads; those are evidence of behavior, never Autodesk kernel
specifications, and no public documentation defines the ASM tokens.

## Error-to-action map

| Error string or signature | Evidence | Next action |
|---|---|---|
| ASM_BL_UNFIN_SHEET | verified-live | The result is an unfinished/open sheet. Close gaps with Patch/Stitch, use Boundary Fill where cells define the volume, or rebuild solid-first before hollowing. |
| ASM_LOP_OFF_NO_SURF | verified-live | Stop radius/offset laddering. Inspect curvature, tiny faces, and feature order; simplify or replace the topology, or move Shell/offset before blends and cuts. |
| ASM_LOFT_SURFACE_SELF_INTERSECTS | verified-live | Inspect profile order and seam alignment, rails, section compatibility, and whether the intended wrap should be a closed loft. Simplify or split the loft when interpolation crosses itself. |
| Offset Faces fails at a high-curvature transition | forum-case | Reduce offset only as a diagnostic; repair the collapsing region or change construction when displaced faces collide. |
| Fillet fails on imported or near-tangent segments | forum-case | Inspect endpoints; replace tiny or nearly tangent segments with clean native curves before retrying the blend. |
| Fillet succeeds on single edges but fails on the chain | forum-case | Disable tangent-chain selection, isolate the first failing endpoint or intersection, remove the tiny face or reorder neighboring blends, then rebuild the intended fillet. |

## One discriminating retry

Permit one retry with a changed construction. Changing only a numeric
radius repeatedly is not a new approach; it is the same approach with a
smaller number.

## Preserve evidence

Report the feature name, the exact error string, the selected entities,
and a section or screenshot of the failing region. Evidence survives
handoff; a paraphrase does not.

## Stop conditions

Stop and report when: a second native approach has also failed; the
topology remains unhealthy after repair attempts; or the repair would
restructure geometry beyond what the user requested. A hard stop with
evidence is a result, not a failure of the session.

## Sources and evidence status

The three verified tokens were observed live in MCP sessions. Community
cases: [offset failure](https://forums.autodesk.com/t5/fusion-design-validate-document/unable-to-offset-faces/td-p/12071111), [loft self-intersection](https://forums.autodesk.com/t5/fusion-design-validate-document/loft-self-intersects/td-p/10380571), [fillet on curved chains](https://forums.autodesk.com/t5/fusion-design-validate-document/fillet-in-curved-objects/td-p/10789255).
