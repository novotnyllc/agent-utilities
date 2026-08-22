/**
 * Strain relief recipes composed from cutout/support/retention primitives.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/recipes/strain_relief.py.
 */

import { adsk } from "@adsk/fas";
import { makePlanarProfile } from "../native/sketches";
import { joinExact } from "../native/booleans";
import { validateTangentContinuity, makeSweep } from "../native/paths";
import { stampAttributes, ManagedIdentity } from "../identity";
import { featureBodies, requireAdsk } from "./shared";
import { executeRetentionRecipe } from "./retention";

type Any = any;

export const STRAIN_RELIEF_TYPES = new Set([
  "cable_exit_support", "clamp_saddle", "zip_tie_anchor", "zip_tie_slot_pair",
  "retention_bridge", "bend_radius_guide", "flexible_fingers",
  "channel_transition", "service_loop_retainer",
]);

type Refusal = [string, string, string];

export type StrainReliefResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

function cutZipTieSlotPair(
  component: Any,
  plane: Any,
  targetBody: Any,
  identity: ManagedIdentity,
  slotLen: Any,
  slotW: Any,
): {created: unknown[]; refusal: Refusal | null} {
  const created: unknown[] = [];
  const extrudes = component.features.extrudeFeatures;
  for (const dx of [-Number(slotLen), Number(slotLen)]) {
    const sk = makePlanarProfile(component, `sr_${identity.parameterNamespace}_slot_${created.length}`, plane, "slot",
      { length: Number(slotLen), width: Number(slotW) }, { offsetX: dx });
    if (sk !== null && sk.sketchProfiles.count > 0) {
      created.push(sk);
      const extIn = extrudes.createInput(sk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString("1.5 mm"));
      extIn.participantBodies = [targetBody];
      const feat = extrudes.add(extIn);
      if (feat === null || feat === undefined) {
        return {created,
          refusal: ["feature-create-failed", "Zip-tie slot pair cut failed.", "check slot dimensions and target body"]};
      }
      created.push(feat);
    }
  }
  return {created, refusal: null};
}

export function executeStrainReliefRecipe(
  component: Any,
  identity: ManagedIdentity,
  request: Record<string, Any>,
): StrainReliefResult {
  requireAdsk();
  const warnings: string[] = [];
  const created: unknown[] = [];
  const ns = identity.parameterNamespace;

  const srType: string = request.type ?? "zip_tie_anchor";
  if (!STRAIN_RELIEF_TYPES.has(srType)) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Unknown strain relief type: ${srType}`, "use a documented type"] };
  }
  const targetBody = request.target_body;
  if (targetBody === undefined || targetBody === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Strain relief target body not resolved.", "select an explicit target body"] };
  }
  const plane = request.placement_frame?.plane;
  if (plane === undefined || plane === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Strain relief placement plane not resolved.", "provide a sketch plane"] };
  }

  const cableSpec: Record<string, Any> | null = request.cable_spec ?? null;
  if (cableSpec === null) {
    warnings.push("No CableSpec supplied; using generic dimensions. Supply explicit cable OD and bend radius for real designs.");
  }
  const params: Record<string, Any> = request.parameters ?? {};
  const cableOd = cableSpec ? Number(cableSpec.od ?? 3.0) : 3.0;
  const bendR = cableSpec ? Number(cableSpec.bend_radius ?? 5.0) : 5.0;
  const extrudes = component.features.extrudeFeatures;

  if (srType === "zip_tie_anchor") {
    const slotW = params.slot_width ?? 2.5;
    const slotLen = params.slot_length ?? 5.0;
    const bridgeW = params.bridge_width ?? 1.5;
    // Slot pair.
    const slots = cutZipTieSlotPair(component, plane, targetBody, identity, slotLen, slotW);
    created.push(...slots.created);
    if (slots.refusal) {
      return {created, warnings, refusal: slots.refusal};
    }
    // Bridge.
    const bridgeSk = makePlanarProfile(component, `sr_${ns}_bridge`, plane, "rectangle",
      { width: bridgeW, height: Number(slotLen) * 2 + Number(slotW) });
    if (bridgeSk !== null && bridgeSk.sketchProfiles.count > 0) {
      created.push(bridgeSk);
      const extIn = extrudes.createInput(bridgeSk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
        extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString("1.5 mm"));
        const bridgeExt = extrudes.add(extIn);
        if (bridgeExt === null || bridgeExt === undefined) {
          return { created, warnings,
            refusal: ["feature-create-failed", "Zip-tie bridge extrude failed.", "check bridge dimensions"] };
        }
        {
          created.push(bridgeExt);
        const bridgeBodies = featureBodies(bridgeExt);
        if (bridgeBodies.length > 0) {
          const jf = joinExact(component, targetBody, bridgeBodies);
          if (jf) created.push(jf);
        }
      }
    }
    warnings.push("Zip-tie anchor provides no pull-force validation; physical testing required for load claims.");
  } else if (srType === "zip_tie_slot_pair") {
    const slotW = params.slot_width ?? 2.5;
    const slotLen = params.slot_length ?? 5.0;
    // Slots only: the caller supplies whatever bridge geometry they need.
    const slots = cutZipTieSlotPair(component, plane, targetBody, identity, slotLen, slotW);
    created.push(...slots.created);
    if (slots.refusal) {
      return {created, warnings, refusal: slots.refusal};
    }
  } else if (srType === "clamp_saddle") {
    const saddleW = cableOd + 2.0;
    const sk = makePlanarProfile(component, `sr_${ns}_saddle`, plane, "circle",
      { diameter: saddleW });
    if (sk !== null && sk.sketchProfiles.count > 0) {
      created.push(sk);
      const extIn = extrudes.createInput(sk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
      extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString("2 mm"));
      const saddleExt = extrudes.add(extIn);
      if (saddleExt === null || saddleExt === undefined) {
        return { created, warnings,
          refusal: ["feature-create-failed", "Clamp saddle extrude failed.", "check cable diameter and height"] };
      }
      {
        created.push(saddleExt);
        const saddleBodies = featureBodies(saddleExt);
        // Cut cable channel.
        const cableSk = makePlanarProfile(component, `sr_${ns}_cable_ch`, plane, "circle",
          { diameter: cableOd });
        if (cableSk !== null && cableSk.sketchProfiles.count > 0) {
          created.push(cableSk);
          const cableCut = extrudes.createInput(cableSk.sketchProfiles.item(0),
            adsk.fusion.FeatureOperations.CutFeatureOperation);
          cableCut.participantBodies = saddleBodies;
          cableCut.setDistanceExtent(false, adsk.core.ValueInput.createByString("2 mm"));
          const cableFeat = extrudes.add(cableCut);
          if (cableFeat === null || cableFeat === undefined) {
            return { created, warnings,
              refusal: ["feature-create-failed", "Clamp saddle cable channel cut failed.", "check cable diameter and saddle body"] };
          }
          created.push(cableFeat);
        }
        if (saddleBodies.length > 0) {
          const jf = joinExact(component, targetBody, saddleBodies);
          if (jf) created.push(jf);
        }
      }
    }
  } else if (srType === "cable_exit_support") {
    const exitDia = cableOd + 1.0;
    const sk = makePlanarProfile(component, `sr_${ns}_exit`, plane, "circle",
      { diameter: exitDia });
    if (sk !== null && sk.sketchProfiles.count > 0) {
      created.push(sk);
      const extIn = extrudes.createInput(sk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      extIn.setAllExtent(adsk.fusion.ExtentDirections.SymmetricExtentDirection);
      extIn.participantBodies = [targetBody];
      const feat = extrudes.add(extIn);
      if (feat === null || feat === undefined) {
        return { created, warnings,
          refusal: ["feature-create-failed", "Cable exit cut failed.", "check exit diameter and target body"] };
      }
      created.push(feat);
    }
    warnings.push("Cable exit support provides no pull-force validation.");
  } else if (srType === "bend_radius_guide") {
    const guideR = bendR;
    warnings.push(`Bend radius guide uses explicit radius ${guideR} mm; verify against CableSpec.`);
    // Create a simple guide wall.
    const wallSk = makePlanarProfile(component, `sr_${ns}_guide`, plane, "rectangle",
      { width: 2.0, height: guideR * 2 });
    if (wallSk !== null && wallSk.sketchProfiles.count > 0) {
      created.push(wallSk);
      const extIn = extrudes.createInput(wallSk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
      extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString("1.5 mm"));
      const wallExt = extrudes.add(extIn);
      if (wallExt === null || wallExt === undefined) {
        return { created, warnings,
          refusal: ["feature-create-failed", "Bend radius guide wall extrude failed.", "check guide radius and height"] };
      }
      {
        created.push(wallExt);
        const wallBodies = featureBodies(wallExt);
        if (wallBodies.length > 0) {
          const jf = joinExact(component, targetBody, wallBodies);
          if (jf) created.push(jf);
        }
      }
    }
  } else if (srType === "flexible_fingers") {
    warnings.push("Flexible fingers use cantilever retention primitive; fatigue proof required.");
    const subReq = { ...request };
    subReq.type = "cantilever_parallel";
    return executeRetentionRecipe(component, identity, subReq);
  } else if (srType === "retention_bridge" || srType === "service_loop_retainer") {
    const bridgeW = params.bridge_width ?? 2.0;
    const bridgeH = params.bridge_height ?? 4.0;
    const sk = makePlanarProfile(component, `sr_${ns}_bridge`, plane, "rectangle",
      { width: Number(bridgeW), height: Number(bridgeH) });
    if (sk !== null && sk.sketchProfiles.count > 0) {
      created.push(sk);
      const extIn = extrudes.createInput(sk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
      extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString("1.5 mm"));
      const bridgeExt = extrudes.add(extIn);
      if (bridgeExt === null || bridgeExt === undefined) {
        return { created, warnings,
          refusal: ["feature-create-failed", "Retention bridge extrude failed.", "check bridge dimensions"] };
      }
      {
        created.push(bridgeExt);
        const bridgeBodies = featureBodies(bridgeExt);
        if (bridgeBodies.length > 0) {
          const jf = joinExact(component, targetBody, bridgeBodies);
          if (jf) created.push(jf);
        }
      }
    }
    warnings.push("Retention bridge/service loop retainer provides no pull-force validation.");
  } else if (srType === "channel_transition") {
    const path = request.sweep_path;
    if (path === undefined || path === null) {
      return { created, warnings,
        refusal: ["feature-create-failed",
          "Channel transition requires a named tangent-continuous path.",
          "provide a tangent-continuous sweep path or use ordinary native modeling"] };
    }
    if (!validateTangentContinuity(path)) {
      return { created, warnings,
        refusal: ["feature-create-failed",
          "Channel path has non-tangent junctions.",
          "use ordinary native sweep modeling for discontinuous frames"] };
    }
    const csPlane = request.cross_section_plane;
    if (csPlane === undefined || csPlane === null) {
      return { created, warnings,
        refusal: ["target-not-found", "Cross-section plane not resolved.", "provide a start plane perpendicular to the path"] };
    }
    const chW = cableOd + 2.0;
    const chH = cableOd + 1.0;
    const csSk = makePlanarProfile(component, `sr_${ns}_cs`, csPlane, "rectangle",
      { width: chW, height: chH });
    if (csSk !== null && csSk.sketchProfiles.count > 0) {
      created.push(csSk);
      const op = adsk.fusion.FeatureOperations.CutFeatureOperation;
      const feat = makeSweep(component, csSk.sketchProfiles.item(0), path, op,
        [targetBody], `sr_${ns}_channel`);
      if (feat) created.push(feat);
    }
  }

  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}
