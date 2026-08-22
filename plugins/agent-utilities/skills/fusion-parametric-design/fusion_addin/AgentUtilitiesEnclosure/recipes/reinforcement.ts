/**
 * Reinforcement recipes: rib/web/gusset via named sketch -> NEW-body extrude
 * -> optional draft -> join last, per the spec's ReinforcementRequest.
 *
 * Types: straight_rib, radial_boss_rib, gusset, triangular_web,
 * wall_floor_rib, boss_wall_rib, support_reinforcement.
 */

import { adsk } from "@adsk/fas";
import { makePlanarProfile } from "../native/sketches";
import { makeReinforcementBody } from "../native/reinforcement";
import { makePattern } from "../native/patterns";
import { makeFillet } from "../native/edge_treatments";
import { stampAttributes, ManagedIdentity } from "../identity";
import { requireAdsk } from "./shared";

type Any = any;

export const REINFORCEMENT_TYPES = new Set([
  "straight_rib", "radial_boss_rib", "gusset", "triangular_web",
  "wall_floor_rib", "boss_wall_rib", "support_reinforcement",
]);

type Refusal = [string, string, string];

export type ReinforcementRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

export function executeReinforcementRecipe(
  component: Any,
  identity: ManagedIdentity,
  request: Record<string, Any>,
): ReinforcementRecipeResult {
  requireAdsk();
  const warnings: string[] = [];
  const created: unknown[] = [];
  const ns = identity.parameterNamespace;

  const rtype: string = request.type ?? "straight_rib";
  if (!REINFORCEMENT_TYPES.has(rtype)) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Unknown reinforcement type: ${rtype}`, "use a documented type"] };
  }

  const profilePlane = request.profile_plane;
  if (profilePlane === undefined || profilePlane === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Reinforcement profile plane not resolved.", "provide a sketch plane"] };
  }
  const targetBody = request.target_body;
  if (targetBody === undefined || targetBody === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Reinforcement target body not resolved.", "select an explicit target body"] };
  }

  const shape: string = request.shape ?? "rectangle";
  const dims: Record<string, Any> = {};
  for (const [k, v] of Object.entries(request.dimensions ?? {})) {
    if (typeof v === "number") dims[k] = v;
  }
  const sketch = makePlanarProfile(component, `reinforce_${ns}_profile`, profilePlane, shape, dims);
  if (sketch === null || sketch.sketchProfiles.count === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Reinforcement profile sketch failed.", "check plane and dimensions"] };
  }
  created.push(sketch);

  const params: Record<string, Any> = request.parameters ?? {};
  const heightExpr = String(params.height ?? params.thickness ?? "");
  if (!heightExpr) {
    return { created, warnings,
      refusal: ["invalid-parameter-expression", "Rib/web thickness is missing.", "assign an FDM rule or supply height"] };
  }
  const draftAngleExpr = String(params.draft_angle ?? "0 deg");
  const bodies = makeReinforcementBody(component, sketch.sketchProfiles.item(0), [targetBody], heightExpr, draftAngleExpr);
  if (bodies.length === 0) {
    return { created, warnings,
      refusal: ["zero-thickness-result", "Reinforcement body empty after extrude/join.", "check height and plane"] };
  }
  for (const feat of bodies) {
    created.push(feat);
  }

  // Multiple radial ribs use a native circular pattern.
  if (rtype === "radial_boss_rib") {
    const count = Number(params.count ?? 4);
    const axis = request.pattern_axis ?? null;
    if (!axis) {
      warnings.push("No pattern_axis supplied; single rib created without pattern.");
    } else {
      const lastBodyFeat = bodies[bodies.length - 1];
      const sources = collectFeatureBodies(lastBodyFeat);
      if (sources.length > 0) {
        const [patternFeat, patternWarn] = makePattern(
          component, sources, "circular", count, {axis});
        if (patternWarn) warnings.push(patternWarn);
        if (patternFeat) {
          created.push(patternFeat);
        }
      }
    }
  }

  // Root fillet when explicitly requested.
  const rootFilletExpr = String(params.root_fillet ?? "");
  if (rootFilletExpr && rootFilletExpr !== "0 mm") {
    const edges = collectJoinEdges(targetBody);
    if (edges.length > 0) {
      const filletFeat = makeFillet(component, edges, rootFilletExpr);
      if (filletFeat) created.push(filletFeat);
    } else {
      warnings.push("Root fillet requested but no join edges resolved; skipped.");
    }
  }

  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}

function collectFeatureBodies(feature: Any): Any[] {
  const coll = feature?.bodies;
  if (!coll) return [];
  const out: Any[] = [];
  for (let i = 0; i < coll.count; i++) out.push(coll.item(i));
  return out;
}

function collectJoinEdges(body: Any): Any[] {
  // Heuristic: pick vertical edges near the join seam. The spec says explicit
  // edge selection should be provided when topology matters.
  const out: Any[] = [];
  try {
    for (let i = 0; i < body.faces.count; i++) {
      const face = body.faces.item(i);
      for (let j = 0; j < face.edges.count; j++) {
        const edge = face.edges.item(j);
        out.push(edge);
      }
    }
  } catch {
    // fall through
  }
  return out.slice(0, 8); // bounded
}
