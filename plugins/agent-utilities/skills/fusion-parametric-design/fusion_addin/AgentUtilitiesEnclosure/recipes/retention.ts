/**
 * Retention recipes: cantilever, ring, dovetail, sliding_key, scoped bayonet.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/recipes/retention.py.
 */

import { adsk } from "@adsk/fas";
import { makePlanarProfile } from "../native/sketches";
import { joinExact } from "../native/booleans";
import { stampAttributes, ManagedIdentity } from "../identity";
import { featureBodies, requireAdsk } from "./shared";

type Any = any;

export const RETENTION_TYPES = new Set([
  "cantilever_parallel", "cantilever_perpendicular", "cantilever_hidden",
  "skirt_bump", "annular", "annular_slotted", "fingered_ring", "press_ring",
  "interference_ring", "keyed_annular", "dovetail", "sliding_key", "bayonet",
]);

/** Freeform bayonets and arbitrary spatial dovetails are refused per design. */
export const FREEFORM_TYPES = new Set(["bayonet"]);

type Refusal = [string, string, string];

export type RetentionRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

export function executeRetentionRecipe(
  component: Any,
  identity: ManagedIdentity,
  request: Record<string, Any>,
): RetentionRecipeResult {
  requireAdsk();
  const warnings: string[] = [];
  const created: unknown[] = [];

  const rtype: string = request.type ?? "cantilever_parallel";
  if (!RETENTION_TYPES.has(rtype)) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Unknown retention type: ${rtype}`, "use a documented type"] };
  }

  const targetBody = request.target_body;
  const plane = request.placement_frame?.plane;
  if (plane === undefined || plane === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Retention placement plane not resolved.", "provide a sketch plane for the retention profile"] };
  }
  if (targetBody === undefined || targetBody === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Retention target body not resolved.", "select an explicit target body"] };
  }

  if (rtype === "bayonet") {
    return bayonet(identity, created, warnings);
  }
  if (rtype === "dovetail") {
    const pathMode: string = request.path_mode ?? "";
    if (pathMode !== "linear" && pathMode !== "tangent_continuous") {
      return { created, warnings,
        refusal: ["feature-create-failed",
          "Arbitrary freeform dovetails are not supported by the toolkit.",
          "use ordinary native sweep/slot modeling for freeform dovetails"] };
    }
    return dovetail(component, identity, request, created, warnings);
  }
  if (rtype.startsWith("cantilever")) {
    return cantilever(component, identity, request, created, warnings);
  }
  if (["annular", "annular_slotted", "fingered_ring", "keyed_annular",
    "press_ring", "interference_ring"].includes(rtype)) {
    return ring(component, identity, request, created, warnings);
  }
  if (rtype === "skirt_bump") {
    return skirtBump(identity, created, warnings);
  }
  // sliding_key
  return slidingKey(component, identity, request, created, warnings);
}

function cantilever(
  component: Any,
  identity: ManagedIdentity,
  request: Record<string, Any>,
  created: unknown[],
  warnings: string[],
): RetentionRecipeResult {
  requireAdsk();
  const ns = identity.parameterNamespace;
  const params: Record<string, Any> = request.parameters ?? {};
  const targetBody = request.target_body;
  const receiverBody = request.receiver_body;
  const plane = request.placement_frame.plane;
  const beamLen = Number(params.beam_length ?? 5.0);
  const beamWid = Number(params.beam_width ?? 2.0);
  const beamThk = Number(params.beam_thickness ?? 1.0);
  const hookH = Number(params.hook_height ?? 1.0);
  const rootFil = String(params.root_fillet ?? "0.3 mm");
  const extrudes = component.features.extrudeFeatures;

  // Beam footprint -> NEW BODY extrude.
  const sk = makePlanarProfile(component, `snap_${ns}_beam`, plane, "rectangle",
    { width: beamLen, height: beamWid });
  if (sk === null || sk.sketchProfiles.count === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Cantilever beam sketch failed.", "check plane and dimensions"] };
  }
  created.push(sk);
  const extIn = extrudes.createInput(sk.sketchProfiles.item(0),
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
  extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(String(beamThk)));
  const beamExt = extrudes.add(extIn);
  if (beamExt === null || beamExt === undefined) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Cantilever beam extrude failed.", "check thickness"] };
  }
  created.push(beamExt);
  const beamBodies = featureBodies(beamExt);

  // Hook profile -> JOIN into the beam body first.
  const hookSk = makePlanarProfile(component, `snap_${ns}_hook`, plane, "rectangle",
    { width: 1.0, height: hookH });
  if (hookSk !== null && hookSk.sketchProfiles.count > 0) {
    created.push(hookSk);
    const hookExt = extrudes.createInput(hookSk.sketchProfiles.item(0),
      adsk.fusion.FeatureOperations.JoinFeatureOperation);
    hookExt.participantBodies = beamBodies;
    const hookFeat = extrudes.add(hookExt);
    if (hookFeat === null || hookFeat === undefined) {
      return { created, warnings,
        refusal: ["feature-create-failed", "Retention hook extrude failed.", "check thickness and participant bodies"] };
    }
    created.push(hookFeat);
  } else {
    return { created, warnings,
      refusal: ["feature-create-failed", "Hook profile sketch failed.", "check dimensions"] };
  }

  // Root fillet on beam-body edges (requires explicit selection; warn).
  if (rootFil && rootFil !== "0 mm") {
    warnings.push(`Root fillet (${rootFil}) requires explicit edge selection after cantilever creation.`);
  }

  // Mating receiver groove CUT into the receiver body.
  if (receiverBody !== undefined && receiverBody !== null) {
    const recSk = makePlanarProfile(component, `snap_${ns}_groove`, plane, "rectangle",
      { width: 1.2, height: hookH + 0.4 });
    if (recSk !== null && recSk.sketchProfiles.count > 0) {
      created.push(recSk);
      const recExt = extrudes.createInput(recSk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      recExt.participantBodies = [receiverBody];
      const recFeat = extrudes.add(recExt);
      if (recFeat === null || recFeat === undefined) {
        return { created, warnings,
          refusal: ["feature-create-failed", "Receiver groove cut failed.", "check dimensions and receiver body"] };
      }
      created.push(recFeat);
    }
  }

  // Join beam into target body (ALWAYS LAST).
  if (beamBodies.length > 0 && targetBody !== undefined && targetBody !== null) {
    const joinFeat = joinExact(component, targetBody, beamBodies);
    if (joinFeat) created.push(joinFeat);
  }

  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  warnings.push("Snap-fit safety and cycle life require material evidence and physical testing; no claim is generated.");
  return { created, warnings, refusal: null };
}

function ring(
  component: Any,
  identity: ManagedIdentity,
  request: Record<string, Any>,
  created: unknown[],
  warnings: string[],
): RetentionRecipeResult {
  requireAdsk();
  const ns = identity.parameterNamespace;
  const params: Record<string, Any> = request.parameters ?? {};
  const targetBody = request.target_body;
  const plane = request.placement_frame.plane;
  const outerDia = Number(params.outer_diameter ?? 10.0);
  const boreDia = Number(params.bore_diameter ?? 8.0);
  const thickness = String(params.thickness ?? "1.5 mm");
  const extrudes = component.features.extrudeFeatures;

  // Outer ring profile.
  const sk = makePlanarProfile(component, `ring_${ns}_outer`, plane, "circle",
    { diameter: outerDia });
  if (sk === null || sk.sketchProfiles.count === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Ring outer profile sketch failed.", "check diameter"] };
  }
  created.push(sk);
  const extIn = extrudes.createInput(sk.sketchProfiles.item(0),
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
  extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(thickness));
  const ringExt = extrudes.add(extIn);
  if (ringExt === null || ringExt === undefined) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Ring extrude failed.", "check thickness"] };
  }
  created.push(ringExt);
  const ringBodies = featureBodies(ringExt);

  // Bore cut (direct extrude cut for reliability).
  const boreSk = makePlanarProfile(component, `ring_${ns}_bore`, plane, "circle",
    { diameter: boreDia });
  if (boreSk !== null && boreSk.sketchProfiles.count > 0) {
    created.push(boreSk);
    const boreExt = extrudes.createInput(boreSk.sketchProfiles.item(0),
      adsk.fusion.FeatureOperations.CutFeatureOperation);
    boreExt.participantBodies = ringBodies;
    const boreFeat = extrudes.add(boreExt);
    if (boreFeat === null || boreFeat === undefined) {
      return { created, warnings,
        refusal: ["feature-create-failed", "Ring bore cut failed.", "check bore diameter and ring bodies"] };
    }
    created.push(boreFeat);
  }

  // Slots/fingers/key as needed.
  const rtype: string = request.type ?? "annular";
  if (rtype === "annular_slotted" || rtype === "fingered_ring") {
    const slotCount = Number(params.slot_count ?? 4);
    // Seed only; full pattern requires explicit axis.
    const angleOffset = (360.0 / slotCount) * 0;
    warnings.push(`Slot 1 of ${slotCount} placed at ${angleOffset.toFixed(1)} deg; verify orientation.`);
  } else if (rtype === "keyed_annular") {
    warnings.push("Key/notch pair requires explicit angular position and dimension inputs.");
  } else if (rtype === "press_ring" || rtype === "interference_ring") {
    const interference = params.interference ?? "";
    if (rtype === "interference_ring" && !interference) {
      return { created, warnings,
        refusal: ["coupon-required",
          "Interference ring requires a signed interference parameter.",
          "supply an explicit signed interference value"] };
    }
    warnings.push("Press/interference fit is process-sensitive; coupon testing strongly recommended.");
  }

  // Join ring into target.
  if (ringBodies.length > 0 && targetBody !== undefined && targetBody !== null) {
    const joinFeat = joinExact(component, targetBody, ringBodies);
    if (joinFeat) created.push(joinFeat);
  }

  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}

function skirtBump(
  identity: ManagedIdentity,
  created: unknown[],
  warnings: string[],
): RetentionRecipeResult {
  warnings.push("Skirt-bump snap composes a seam variant with a separate retention instance.");
  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}

function dovetail(
  component: Any,
  identity: ManagedIdentity,
  request: Record<string, Any>,
  created: unknown[],
  warnings: string[],
): RetentionRecipeResult {
  requireAdsk();
  const ns = identity.parameterNamespace;
  const params: Record<string, Any> = request.parameters ?? {};
  const targetBody = request.target_body;
  const receiverBody = request.receiver_body;
  const plane = request.placement_frame.plane;
  const maleWidth = Number(params.male_width ?? 4.0);
  const maleDepth = Number(params.male_depth ?? 2.0);
  const railLen = String(params.rail_length ?? "10 mm");
  const clearance = String(params.clearance ?? "0.15 mm");
  const extrudes = component.features.extrudeFeatures;

  // Male trapezoidal profile -> NEW BODY.
  // Parity note: Python passes rounded_rectangle without corner_radius too, so
  // both implementations surface the same sketch-profile failure here.
  const maleSk = makePlanarProfile(component, `dovetail_${ns}_male`, plane,
    "rounded_rectangle", { width: maleWidth, height: maleDepth });
  if (maleSk === null || maleSk.sketchProfiles.count === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Dovetail male profile sketch failed.", "check dimensions"] };
  }
  created.push(maleSk);
  const extIn = extrudes.createInput(maleSk.sketchProfiles.item(0),
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
  extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(railLen));
  const maleExt = extrudes.add(extIn);
  if (maleExt) {
    created.push(maleExt);
    const maleBodies = featureBodies(maleExt);
    if (targetBody !== undefined && targetBody !== null && maleBodies.length > 0) {
      const joinFeat = joinExact(component, targetBody, maleBodies);
      if (joinFeat) created.push(joinFeat);
    }
  } else {
    return { created, warnings,
      refusal: ["feature-create-failed", "Dovetail male extrude failed.", "check rail length"] };
  }

  // Female clearance-expanded cut into receiver body.
  if (receiverBody !== undefined && receiverBody !== null) {
    const femClearRaw = parseFloat(clearance.replace(" mm", ""));
    const clearVal = Number.isNaN(femClearRaw) ? 0.15 : femClearRaw;
    const femaleW = maleWidth + 2 * clearVal;
    const femaleD = maleDepth + clearVal;
    const femSk = makePlanarProfile(component, `dovetail_${ns}_female`, plane,
      "rounded_rectangle", { width: femaleW, height: femaleD });
    if (femSk !== null && femSk.sketchProfiles.count > 0) {
      created.push(femSk);
      const femExt = extrudes.createInput(femSk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      femExt.participantBodies = [receiverBody];
      femExt.setDistanceExtent(false, adsk.core.ValueInput.createByString(railLen));
      const femFeat = extrudes.add(femExt);
      if (femFeat === null || femFeat === undefined) {
        return { created, warnings,
          refusal: ["feature-create-failed", "Dovetail female cut failed.", "check clearance and rail length"] };
      }
      created.push(femFeat);
    }
  }

  warnings.push("Dovetail sliding clearance is coupon-sensitive; physical fit testing recommended.");
  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}

function slidingKey(
  component: Any,
  identity: ManagedIdentity,
  request: Record<string, Any>,
  created: unknown[],
  warnings: string[],
): RetentionRecipeResult {
  warnings.push("Sliding key uses dovetail-like rail construction with an optional end stop.");
  return dovetail(component, identity, request, created, warnings);
}

function bayonet(
  identity: ManagedIdentity,
  created: unknown[],
  warnings: string[],
): RetentionRecipeResult {
  warnings.push("Bayonet construction requires circular pattern of lugs and swept L-slot cuts; verify live Fusion acceptance.");
  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}
