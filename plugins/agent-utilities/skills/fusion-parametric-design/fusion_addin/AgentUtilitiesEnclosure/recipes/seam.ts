/**
 * Seam recipes: lip/groove/lip_groove/tongue_groove/skirt_channel/labyrinth/splash_overlap.
 */

import { adsk } from "@adsk/fas";
import { makeOffsetProfile, makePlanarProfile } from "../native/sketches";
import { validateTangentContinuity, makeSweep } from "../native/paths";
import { stampAttributes, ManagedIdentity } from "../identity";
import { AddInNotRunningError } from "../dispatch";

export const SEAM_VARIANTS = new Set([
  "lip", "groove", "lip_groove", "tongue_groove", "skirt_channel",
  "labyrinth", "splash_overlap",
]);

type Refusal = [string, string, string];

export type SeamRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

function requireAdsk(): void {
  if (!adsk || !adsk.core || !adsk.fusion) {
    throw new AddInNotRunningError("adsk not available.");
  }
}

function mmToFloat(expr: string): number {
  return parseFloat(String(expr).replace(" mm", ""));
}

export function executeSeamRecipe(
  component: any,
  identity: ManagedIdentity,
  request: Record<string, any>,
): SeamRecipeResult {
  requireAdsk();
  const warnings: string[] = [];
  const created: unknown[] = [];
  const ns = identity.parameterNamespace;

  const variant: string = request.variant ?? "lip_groove";
  if (!SEAM_VARIANTS.has(variant)) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Unknown seam variant: ${variant}`, "use a documented variant"] };
  }

  const pathMode: string = request.path_mode ?? "planar_closed_loop";

  if (variant === "splash_overlap") {
    warnings.push("Splash overlap provides geometric overlap only; no IP rating is implied.");
  }
  if (variant === "labyrinth") {
    warnings.push("Labyrinth provides light-path blocking geometry; not a certified optical seal.");
  }

  if (pathMode === "planar_closed_loop" || pathMode === "planar_partial") {
    return planarSeam(component, identity, request, created, warnings);
  } else if (pathMode === "tangent_nonplanar") {
    return tangentSeam(component, identity, request, created, warnings);
  } else if (pathMode === "segmented_nonplanar") {
    warnings.push("Segmented nonplanar seams use explicit named segments per the design contract.");
    return planarSeam(component, identity, request, created, warnings);
  } else {
    return { created, warnings,
      refusal: ["seam-nontangent-unsupported",
        `Unsupported seam path mode: ${pathMode}`,
        "use planar_closed_loop, planar_partial, tangent_nonplanar, or segmented_nonplanar"] };
  }
}

function planarSeam(
  component: any,
  identity: ManagedIdentity,
  request: Record<string, any>,
  created: unknown[],
  warnings: string[],
): SeamRecipeResult {
  requireAdsk();
  const ns = identity.parameterNamespace;
  const variant: string = request.variant ?? "lip_groove";
  const sideA = request.side_a_body;
  const sideB = request.side_b_body;
  const masterSketch = request.path_sketch;
  if (masterSketch === undefined || masterSketch === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Seam master sketch not resolved.", "provide a named sketch on the parting plane"] };
  }

  const params: Record<string, any> = request.parameters ?? {};
  const lipWidth = String(params.lip_width ?? "1.0 mm");
  const engagement = String(params.engagement_depth ?? "0.8 mm");
  const clearance = String(params.radial_clearance ?? "0.15 mm");
  const extrudes = component.features.extrudeFeatures;

  // Lip profile (offset outward) and join to side A.
  if (variant === "lip" || variant === "lip_groove") {
    const lipSk = makeOffsetProfile(component, `seam_${ns}_lip`, masterSketch, lipWidth);
    if (lipSk !== null && lipSk.sketchProfiles.count > 0) {
      created.push(lipSk);
      const extIn = extrudes.createInput(lipSk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.JoinFeatureOperation);
      extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(engagement));
      if (sideA) extIn.participantBodies = [sideA];
      const feat = extrudes.add(extIn);
      if (feat) created.push(feat);
    } else {
      return { created, warnings,
        refusal: ["seam-segment-collapsed",
          "Lip offset collapsed; width too large for corner radius.",
          "reduce lip_width or increase corner radius"] };
    }
  }

  // Groove profile (offset inward with clearance) and cut into side B.
  if (variant === "groove" || variant === "lip_groove") {
    const grooveWidth = `(${lipWidth} + ${clearance})`;
    const grooveSk = makeOffsetProfile(component, `seam_${ns}_groove`, masterSketch, grooveWidth);
    if (grooveSk !== null && grooveSk.sketchProfiles.count > 0) {
      created.push(grooveSk);
      const extIn = extrudes.createInput(grooveSk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(engagement));
      if (sideB) extIn.participantBodies = [sideB];
      const feat = extrudes.add(extIn);
      if (feat) created.push(feat);
    } else {
      return { created, warnings,
        refusal: ["seam-self-intersection",
          "Groove offset produced self-intersecting profile.",
          "reduce lip_width or increase corner radius"] };
    }
  }

  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}

function tangentSeam(
  component: any,
  identity: ManagedIdentity,
  request: Record<string, any>,
  created: unknown[],
  warnings: string[],
): SeamRecipeResult {
  requireAdsk();
  const ns = identity.parameterNamespace;
  const path = request.sweep_path;
  if (path === undefined || path === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Sweep path not resolved.", "provide a tangent-continuous path"] };
  }

  if (!validateTangentContinuity(path)) {
    return { created, warnings,
      refusal: ["seam-nontangent-unsupported",
        "Path has non-tangent junctions; use segmented_nonplanar mode.",
        "split the path at sharp corners into explicit segments"] };
  }

  const crossSectionPlane = request.cross_section_plane;
  if (crossSectionPlane === undefined || crossSectionPlane === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Cross-section placement plane not resolved.", "provide a start plane perpendicular to the path"] };
  }

  const params: Record<string, any> = request.parameters ?? {};
  const lipW = mmToFloat(String(params.lip_width ?? "1.0 mm"));
  const engagement = String(params.engagement_depth ?? "0.8 mm");
  const clearance = String(params.radial_clearance ?? "0.15 mm");

  // Cross-section sketch for the lip. NOTE: Python ignores engagement here and uses a fixed 2.0 height.
  const lipCs = makePlanarProfile(component, `seam_${ns}_lip_cs`, crossSectionPlane,
    "rectangle", { width: lipW, height: 2.0 });
  if (lipCs !== null && lipCs.sketchProfiles.count > 0) {
    const op = adsk.fusion.FeatureOperations.JoinFeatureOperation;
    const feat = makeSweep(component, lipCs.sketchProfiles.item(0), path, op,
      [request.side_a_body], `seam_sweep_lip_${ns}`);
    if (feat) created.push(feat);
  } else {
    return { created, warnings,
      refusal: ["feature-create-failed", "Cross-section sketch failed.", "check plane orientation"] };
  }

  // Receiver sweep with clearance.
  const grooveW = lipW + mmToFloat(clearance);
  const grooveCs = makePlanarProfile(component, `seam_${ns}_groove_cs`, crossSectionPlane,
    "rectangle", { width: grooveW, height: 2.0 });
  if (grooveCs !== null && grooveCs.sketchProfiles.count > 0) {
    const op = adsk.fusion.FeatureOperations.CutFeatureOperation;
    const feat = makeSweep(component, grooveCs.sketchProfiles.item(0), path, op,
      [request.side_b_body], `seam_sweep_groove_${ns}`);
    if (feat) created.push(feat);
  }

  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}
