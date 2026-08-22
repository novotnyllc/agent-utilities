/**
 * Cutout recipes: rectangle/rounded_rectangle/circle/named_profile + recess + holes.
 */

import { adsk } from "@adsk/fas";
import { makePlanarProfile } from "../native/sketches";
import { makeHole } from "../native/holes_threads";
import { makeNamedPlane } from "../native/datums";
import { stampAttributes, ManagedIdentity } from "../identity";
import { requireAdsk } from "./shared";

export const CUTOUT_SHAPES = new Set(["rectangle", "rounded_rectangle", "circle", "named_profile"]);

type Refusal = [string, string, string];

export type CutoutRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

export function executeCutoutRecipe(
  component: any,
  identity: ManagedIdentity,
  request: Record<string, any>,
): CutoutRecipeResult {
  requireAdsk();
  const warnings: string[] = [];
  const created: unknown[] = [];
  const ns = identity.parameterNamespace;

  const shape: string = request.shape ?? "rectangle";
  if (!CUTOUT_SHAPES.has(shape)) {
    return { created, warnings,
      refusal: ["feature-create-failed",
        `Unknown cutout shape: ${shape}`,
        "use rectangle, rounded_rectangle, circle, or named_profile"] };
  }
  if (shape === "named_profile") {
    // Named profiles require the user to supply an existing sketch profile.
    if (request.profile_reference === undefined || request.profile_reference === null) {
      return { created, warnings,
        refusal: ["target-not-found", "Named profile reference not resolved.", "select an existing sketch profile"] };
    }
  }
  const targetBody = request.target_body;
  if (targetBody === undefined || targetBody === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Cutout target body not resolved.", "select an explicit target body"] };
  }
  const placement: Record<string, any> = request.placement_frame ?? {};
  const plane = placement.plane;
  if (plane === undefined || plane === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Cutout placement plane not resolved.", "provide a placement plane normal to the wall"] };
  }

  // Python keeps only numeric dimension values.
  const dims: Record<string, number> = {};
  for (const [k, v] of Object.entries(request.dimensions ?? {})) {
    if (typeof v === "number") {
      dims[k] = v;
    } else if (typeof v === "string") {
      const parsed = parseFloat(v);
      if (!Number.isNaN(parsed)) {
        dims[k] = parsed;
      } else {
        return { created, warnings,
          refusal: ["invalid-parameter-expression",
            `dimension '${k}' value '${v}' is not a number or unit expression.`,
            "send a number (mm) or a '<value> <unit>' expression"] };
      }
    } else {
      return { created, warnings,
        refusal: ["invalid-parameter-expression",
          `dimension '${k}' is not a number or unit expression.`,
          "send a number (mm) or a '<value> <unit>' expression"] };
    }
  }
  const sketch = makePlanarProfile(component, `cutout_${ns}_profile`, plane, shape, dims);
  if (sketch === null || sketch.sketchProfiles.count === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Cutout profile sketch failed.", "check plane and dimensions"] };
  }
  created.push(sketch);

  const extrudes = component.features.extrudeFeatures;
  const extIn = extrudes.createInput(sketch.sketchProfiles.item(0),
    adsk.fusion.FeatureOperations.CutFeatureOperation);
  const extentMode: string = request.extent ?? "through_all";
  if (extentMode === "through_all") {
    extIn.setAllExtent(adsk.fusion.ExtentDirections.SymmetricExtentDirection);
  } else if (extentMode === "distance" && "distance" in dims) {
    extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(String(dims.distance)));
  } else if (extentMode === "to_entity" && request.extent_entity) {
    extIn.setOneSideToEntityExtent(request.extent_entity, false);
  } else {
    extIn.setAllExtent(adsk.fusion.ExtentDirections.SymmetricExtentDirection);
  }
  extIn.participantBodies = [targetBody];
  const cutFeat = extrudes.add(extIn);
  if (cutFeat === null || cutFeat === undefined) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Cutout extrude failed.", "check extent and participant bodies"] };
  }
  created.push(cutFeat);

  // Optional recess.
  const recess = request.recess;
  if (recess && "width" in recess && "height" in recess && "depth" in recess) {
    const clearance = Number(recess.clearance ?? 2.0);
    const rw = (typeof recess.width === "number" ? recess.width : 18.0) + 2 * clearance;
    const rh = (typeof recess.height === "number" ? recess.height : 13.0) + 2 * clearance;
    const rd = String(recess.depth ?? "1 mm");
    if (clearance !== 0) {
      warnings.push(`Recess applies ${clearance} mm per-side clearance around the nominal size.`);
    }
    const recSk = makePlanarProfile(component, `cutout_${ns}_recess`, plane,
      "rectangle", { width: rw, height: rh });
    if (recSk !== null && recSk.sketchProfiles.count > 0) {
      created.push(recSk);
      const recExt = extrudes.createInput(recSk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      recExt.setDistanceExtent(false, adsk.core.ValueInput.createByString(rd));
      recExt.participantBodies = [targetBody];
      const recFeat = extrudes.add(recExt);
      if (recFeat) created.push(recFeat);
    }
  }

  // Optional mounting holes.
  const mountingHoles: any[] = request.mounting_holes ?? [];
  for (const mh of mountingHoles) {
    const center = mh.center_point;
    const dia = mh.diameter ?? "3.2 mm";
    const depth = mh.depth ?? "";
    if (center !== undefined && center !== null) {
      const feat = makeHole(component, targetBody, center,
        placement.direction, String(dia), String(depth), "simple");
      if (feat) created.push(feat);
    }
  }

  // Optional chamfer/fillet on cutout edges.
  const outsideChamfer = request.outside_chamfer ?? "";
  const edgeFillet = request.edge_fillet ?? "";
  if (outsideChamfer || edgeFillet) {
    warnings.push("Chamfer/fillet requires explicit post-cutout edge selection (topology rule 4).");
  }

  // Publish seam-exclusion datums.
  const exclusionClearance = request.seam_exclusion_clearance ?? "";
  if (exclusionClearance) {
    const exclPlane = makeNamedPlane(component, `seam_exclusion_${ns}`, "offset",
      { face: plane, offset: exclusionClearance });
    if (exclPlane) created.push(exclPlane);
  }

  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}
