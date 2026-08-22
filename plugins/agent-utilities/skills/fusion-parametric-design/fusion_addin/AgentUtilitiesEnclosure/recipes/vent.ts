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
import { featureBodies, requireAdsk } from "./shared";

type Any = any;

function toCollection(items: Any[]): Any {
  const coll = adsk.core.ObjectCollection.create();
  for (const item of items) coll.add(item);
  return coll;
}

export const VENT_PATTERNS = new Set([
  "linear_slots", "rectangular_holes", "circular_holes", "hexagonal",
]);

type Refusal = [string, string, string];

export type VentRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

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
  let patFeat: Any | null = null;
  try {
    const axes: Any[] = request.pattern_axes ?? [];
    if (countX > 1 && countY > 1) {
      // Two-direction native grid: Fusion lays out countX * countY instances;
      // no manual multiply here.
      const directionOne = axes[0] ?? component.xConstructionAxis;
      const directionTwo = axes[1] ?? component.yConstructionAxis;
      const rp = component.features.rectangularPatternFeatures;
      const inputObj = rp.createInput(toCollection([seedExt]), directionOne, directionTwo);
      inputObj.quantityOne = adsk.core.ValueInput.createByString(String(countX));
      inputObj.distanceOne = adsk.core.ValueInput.createByString(spacing);
      inputObj.quantityTwo = adsk.core.ValueInput.createByString(String(countY));
      inputObj.distanceTwo = adsk.core.ValueInput.createByString(
        params.spacing_y != null ? `${params.spacing_y} mm` : spacing);
      inputObj.directionTwoEntity = directionTwo;
      patFeat = rp.add(inputObj);
    } else {
      const [feat, warn] = makePattern(component, [seedExt], "rectangular",
        Math.max(countX, 1), { spacing });
      if (warn) warnings.push(warn);
      patFeat = feat;
    }
  } catch (exc) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Vent pattern failed: ${exc}`, "check pattern axes and counts"] };
  }
  if (patFeat) created.push(patFeat);
  // Pattern bodies (seed + copies) are the complete tool set; collect them
  // AFTER the pattern so the mask clips every aperture, not just the seed.
  const patternTools: Any[] = patFeat ? featureBodies(patFeat) : seedTools;

  // Clip: intersect ALL pattern tools with an explicit mask before cutting target.
  const maskBody = request.mask_body;
  if (maskBody !== undefined && maskBody !== null && patternTools.length > 0) {
    const clipped = intersectExact(component, patternTools[0], [maskBody, ...patternTools.slice(1)]);
    const clippedBodies = clipped ? featureBodies(clipped) : [];
    if (!clipped || clippedBodies.length === 0) {
      return { created, warnings,
        refusal: ["zero-thickness-result",
          "Vent mask intersection produced no tool bodies.",
          "check that the mask overlaps the vent region"] };
    }
    created.push(clipped);
    // The clipped result replaces every raw pattern body as the cutting tool.
    patternTools.length = 0;
    for (const b of clippedBodies) patternTools.push(b as Any);
  }

  // Final cut into target using every (possibly clipped) pattern body.
  const finalCut = cutExact(component, targetBody, patternTools);
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
