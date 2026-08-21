/**
 * Barrel re-exports for native primitives.
 *
 * Mirrors fusion_addin/AgentUtilitiesEnclosure/native/__init__.py.
 */

export { resolveEntity, resolveOccurrenceContext } from "./selections";
export { makeParameter } from "./parameters";
export { makeNamedPlane, makeNamedAxis, makeNamedPoint } from "./datums";
export { makePlanarProfile, makePolygonProfile, makeOffsetProfile } from "./sketches";
export { extentDistance, extentToEntity, extentToBody } from "./extents";
export { joinExact, cutExact, intersectExact } from "./booleans";
export {
  makeHole,
  makeThread,
  makeInsertBore,
  makePolygonPocket,
  makeSpotFace,
} from "./holes_threads";
export { makeSweepPath, validateTangentContinuity, makeSweep } from "./paths";
export { makeChamfer, makeFillet } from "./edge_treatments";
export { makeReinforcementBody } from "./reinforcement";
export { makePattern, makeMirror } from "./patterns";
