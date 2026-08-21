/**
 * Vent recipes: seed feature + native patterns with explicit mask clipping.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/recipes/vent.py.
 */

import { adsk } from "@adsk/fas";
import { makePlanarProfile, makePolygonProfile } from "../native/sketches";
import { makePattern } from "../native/patterns";
import { cutExact, intersectExact } from "../native/booleans";
import { stampAttributes, ManagedIdentity } from "../identity";
import { AddInNotRunningError } from "../dispatch";

type Any = any;

export const VENT_PATTERNS = new Set([
  "linear_slots", "rectangular_holes", "circular_holes", "hexagonal",
]);

type Refusal = [string, string, string];

export type VentRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

function requireAdsk(): void {
  if (!adsk || !adsk.core || !adsk.fusion) {
    throw new AddInNotRunningError("adsk not available.");
  }
}

export function executeVentRecipe(
  component: Any,
  identity: ManagedIdentity,
  request: Record<string, Any>,
): VentRecipeResult {
  requireAdsk();
  const warnings: string[] = [];
  const created: unknown[] = [];
  const ns = identity.parameterNamespace;

  const patternType: string = request.pattern ?? "linear_slots";
  if (!VENT_PATTERNS.has(patternType)) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Unknown vent pattern: ${patternType}`,
        "use linear_slots, rectangular_holes, circular_holes, or hexagonal"] };
  }
  const targetBody = request.target_body;
  if (targetBody === undefined || targetBody === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Vent target body not resolved.", "select an explicit target body"] };
  }
  const plane = request.placement_frame?.plane;
  if (plane === undefined || plane === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Vent placement plane not resolved.", "provide a sketch plane for the vent pattern"] };
  }

  const params: Record<string, Any> = request.parameters ?? {};
  const aperture = params.aperture ?? 1.0;
  const pitch = params.pitch ?? 3.0;
  const countX = Number(params.count_x ?? 4);
  const countY = Number(params.count_y ?? 1);
  const boundaryPolicy: string = request.boundary_policy ?? "clip";
  const suppressed: Set<Any> = new Set(request.suppressed_indices ?? []);

  // whole_cells without explicit suppressed_indices -> refusal per design.
  if (boundaryPolicy === "whole_cells") {
    const regionShape: string = request.region_shape ?? "rectangle";
    if (regionShape !== "rectangle" && regionShape !== "circle" && suppressed.size === 0) {
      return { created, warnings,
        refusal: ["feature-create-failed",
          "whole_cells policy in a freeform region requires explicit suppressed_indices.",
          "supply suppressed_indices or use clip policy"] };
    }
  }

  const extrudes = component.features.extrudeFeatures;

  // Create the seed aperture as a cutting tool NEW BODY.
  let sk: Any;
  if (patternType === "linear_slots" || patternType === "rectangular_holes") {
    const apW = patternType === "linear_slots" ? Number(aperture) * 3 : Number(aperture);
    sk = makePlanarProfile(component, `vent_${ns}_seed`, plane,
      patternType === "linear_slots" ? "slot" : "rectangle",
      { length: apW, width: Number(aperture) });
  } else if (patternType === "circular_holes") {
    sk = makePlanarProfile(component, `vent_${ns}_seed`, plane, "circle",
      { diameter: Number(aperture) });
  } else if (patternType === "hexagonal") {
    sk = makePolygonProfile(component, `vent_${ns}_seed`, plane,
      6, Number(aperture));
  } else {
    return { created, warnings,
      refusal: ["feature-create-failed", `Unhandled vent pattern type: ${patternType}`, "use a documented type"] };
  }

  if (sk === null || sk === undefined || sk.sketchProfiles.count === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Vent seed sketch failed.", "check plane and aperture dimensions"] };
  }
  created.push(sk);

  // Extrude seed as NEW BODY (cutting tool).
  const extIn = extrudes.createInput(sk.sketchProfiles.item(0),
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
  extIn.setAllExtent(adsk.fusion.ExtentDirections.SymmetricExtentDirection);
  extIn.participantBodies = [targetBody];
  const seedExt = extrudes.add(extIn);
  if (seedExt === null || seedExt === undefined) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Vent seed extrude failed.", "check extent and participant bodies"] };
  }
  created.push(seedExt);

  const seedBodiesColl = seedExt.bodies;
  const seedTools: unknown[] = [];
  if (seedBodiesColl) {
    for (let i = 0; i < seedBodiesColl.count; i++) seedTools.push(seedBodiesColl.item(i));
  }
  if (seedTools.length === 0) {
    return { created, warnings,
      refusal: ["zero-thickness-result", "Vent seed tool body empty.", "undo and check parameters"] };
  }

  // Create native rectangular pattern of the seed extrude feature.
  const spacing = typeof pitch === "number" ? `${pitch} mm` : String(pitch);
  const [patFeat, patWarn] = makePattern(component, [seedExt], "rectangular",
    countX * Math.max(1, countY), { spacing });
  if (patWarn) warnings.push(patWarn);
  if (patFeat) created.push(patFeat);

  // Clip: intersect pattern tools with an explicit mask before cutting target.
  const maskBody = request.mask_body;
  if (maskBody !== undefined && maskBody !== null && seedTools.length > 0) {
    const clipped = intersectExact(component, seedTools[0], [maskBody]);
    if (clipped) created.push(clipped);
  }

  // Final cut into target using all seed tools.
  const finalCut = cutExact(component, targetBody, seedTools);
  if (finalCut) {
    created.push(finalCut);
  } else {
    warnings.push("Final vent cut did not produce a combine feature; verify manually.");
  }

  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  warnings.push("Vent geometry provides no thermal performance claim.");
  return { created, warnings, refusal: null };
}
