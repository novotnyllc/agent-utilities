/**
 * Support recipes with INVARIANT: extrude NEW tool body, trim, cut keep-outs,
 * JOIN last.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/recipes/support.py.
 */

import { adsk } from "@adsk/fas";
import { makePlanarProfile } from "../native/sketches";
import { joinExact, cutExact } from "../native/booleans";
import { stampAttributes, ManagedIdentity } from "../identity";
import { featureBodies, requireAdsk } from "./shared";

type Any = any;

export const SUPPORT_TYPES = new Set([
  "pcb_edge", "pcb_corner", "support_point", "shelf", "landing_pad",
  "saddle", "cylindrical_cradle", "profile_ledge",
]);

type Refusal = [string, string, string];

export type SupportRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

export function executeSupportRecipe(
  component: Any,
  identity: ManagedIdentity,
  request: Record<string, Any>,
): SupportRecipeResult {
  requireAdsk();
  const warnings: string[] = [];
  const created: unknown[] = [];
  const ns = identity.parameterNamespace;

  const stype: string = request.type ?? "shelf";
  if (!SUPPORT_TYPES.has(stype)) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Unknown support type: ${stype}`, "use a documented type"] };
  }
  const targetBody = request.target_body;
  if (targetBody === undefined || targetBody === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Support target body not resolved.", "select an explicit target body"] };
  }
  const profilePlane = request.profile_plane;
  if (profilePlane === undefined || profilePlane === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Support profile plane not resolved.", "provide a sketch plane for the support profile"] };
  }
  const params: Record<string, Any> = request.parameters ?? {};
  const thickness = String(params.thickness ?? "2 mm");
  const shape: string = request.shape ?? "rectangle";
  const dims: Record<string, Any> = {};
  for (const [k, v] of Object.entries(request.dimensions ?? {})) {
    if (typeof v === "number") dims[k] = v;
  }
  const sketch = makePlanarProfile(component, `support_${ns}_profile`, profilePlane, shape, dims);
  if (sketch === null || sketch.sketchProfiles.count === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Support profile sketch failed.", "check plane and dimensions"] };
  }
  created.push(sketch);
  const extrudes = component.features.extrudeFeatures;
  const extIn = extrudes.createInput(sketch.sketchProfiles.item(0),
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
  extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(thickness));
  const supportExt = extrudes.add(extIn);
  if (supportExt === null || supportExt === undefined) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Support extrude failed.", "check thickness and plane"] };
  }
  created.push(supportExt);
  const toolBodies = featureBodies(supportExt);
  if (toolBodies.length === 0) {
    return { created, warnings,
      refusal: ["zero-thickness-result", "Support body empty after extrude.", "undo and check parameters"] };
  }
  const extentRef = request.extent_reference;
  if (extentRef !== undefined && extentRef !== null) {
    try {
      const trimIn = extrudes.createInput(sketch.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      trimIn.participantBodies = toolBodies;
      trimIn.setOneSideToEntityExtent(extentRef, false);
      const trimFeat = extrudes.add(trimIn);
      if (trimFeat) created.push(trimFeat);
    } catch (exc: Any) {
      return { created, warnings,
        refusal: ["feature-create-failed", `Support trim to extent failed: ${exc}`, "verify the extent reference exists and is valid"] };
    }
  }
  const keepouts: Any[] = request.keepout_bodies ?? [];
  if (keepouts.length > 0) {
    // Trim EVERY tool body against the keep-outs, not just the first one.
    for (const tb of toolBodies) {
      const trimmed = cutExact(component, tb as Any, keepouts);
      if (trimmed) created.push(trimmed);
    }
  }
  const retentionLip = request.retention_lip;
  if (retentionLip) {
    warnings.push("Retention lip on support requires separate retention recipe instance for managed tracking.");
  }
  const joinFeat = joinExact(component, targetBody, toolBodies);
  if (joinFeat) created.push(joinFeat);
  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}
