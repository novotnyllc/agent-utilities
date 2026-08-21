# Bounded enclosure feature recipes

The recipe surface emits one standalone Fusion Python transaction for one
managed native feature instance. Fusion remains the CAD state; the host holds
only the request long enough to emit source.

## V1: heat-set-insert boss

`boss.heat_set_insert/v1` requires:

- a canonical feature UUID and human-readable instance name;
- one explicit target `BRepBody` token;
- one explicit support `BRepFace` token owned by that body;
- one explicit `SketchPoint` or `ConstructionPoint` token;
- namespaced user parameters for boss outside diameter/height, insert bore
  diameter/depth, and socket-head seat diameter/depth;
- manufacturer or coupon evidence for bore and head-seat dimensions, all still
  marked coupon-sensitive;
- either no gussets or four orthogonal gussets with explicit thickness and
  centre-to-tip length parameters.

All three selected entities must belong to the root component. V1 refuses
subcomponent definitions and occurrence proxies because editing a repeated
component definition could change every occurrence.

Creation makes named boss, bore, and socket-seat sketches; New Body extrudes
followed by explicit target-body Combine joins; participant-scoped cuts;
optional ordinary-extrude gussets; attributes under `fusion_parametric_design`;
and one timeline group. It calls Compute All, reads feature health and
`BRepBody.isSolid`, and returns the complete parameter/object/group receipt. It
uses no Design Extension feature and makes no mechanical claim.

Lifecycle operations accept the feature UUID plus the exact parameter names,
object tokens, and timeline-group name returned by creation. They prove that
the receipt is complete before mutation. Edit snapshots all expressions,
recomputes, rechecks the recipe's dimensional invariants and managed native
health, and either succeeds or restores the snapshot. Inspect reports each
managed object's native health. Delete uses the
timeline group as the bounded geometry deletion unit, then deletes parameters;
because public Fusion deletion is not transactional, any incomplete delete is
reported as `failed-dirty` with deleted and remaining roles and must not be
retried automatically.

Deferred: base fillets, coordinated base/lid pairs, captive nuts, patterns,
curved supports, lips/grooves, rests, and snaps. Add them only after
the v1 live fixture passes base-account create, parameter edit, Compute All,
save/reopen, and neighboring-body isolation.
