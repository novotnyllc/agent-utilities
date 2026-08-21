/**
 * Seal recipes: gasket channels, O-ring grooves, perimeter channels, compression stops.
 */

import { adsk } from "@adsk/fas";
import { makeOffsetProfile, makePlanarProfile } from "../native/sketches";
import { validateTangentContinuity, makeSweep } from "../native/paths";
import { joinExact } from "../native/booleans";
import { stampAttributes, ManagedIdentity } from "../identity";
import { AddInNotRunningError } from "../dispatch";

export const SEAL_TYPES = new Set([
  "flat_gasket_channel", "gasket_land", "o_ring_groove",
  "perimeter_channel", "interrupted_channel", "compression_stop",
]);

type Refusal = [string, string, string];

export type SealRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

function requireAdsk(): void {
  if (!adsk || !adsk.core || !adsk.fusion) {
    throw new AddInNotRunningError("adsk not available.");
  }
}

/** Python: float("1.5 mm".replace(" mm", "")) */
function mmToFloat(expr: string): number {
  return parseFloat(String(expr).replace(" mm", ""));
}

export function executeSealRecipe(
  component: any,
  identity: ManagedIdentity,
  request: Record<string, any>,
): SealRecipeResult {
  requireAdsk();
  const warnings: string[] = [];
  const created: unknown[] = [];
  const ns = identity.parameterNamespace;

  const stype: string = request.type ?? "flat_gasket_channel";
  if (!SEAL_TYPES.has(stype)) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Unknown seal type: ${stype}`, "use a documented seal type"] };
  }
  const targetBody = request.target_body;
  if (targetBody === undefined || targetBody === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Seal target body not resolved.", "select an explicit target body"] };
  }

  const params: Record<string, any> = request.parameters ?? {};
  const width = String(params.cross_section_width ?? "1.5 mm");
  const depth = String(params.cross_section_depth ?? "0.8 mm");
  const pathSketch = request.path_sketch;
  const sweepPath = request.sweep_path;
  const sealSpec = request.seal_spec;

  if (stype === "compression_stop") {
    return compressionStops(component, identity, request, created, warnings);
  }

  // No universal gland numbers -- require sourced or provisional-labeled dimensions.
  if (stype === "o_ring_groove") {
    if (!sealSpec || !sealSpec.source_id) {
      const provisional = params.provisional ?? true;
      if (provisional !== true) {
        return { created, warnings,
          refusal: ["coupon-required",
            "O-ring groove dimensions must cite a standard/manufacturer source or be explicitly labeled provisional.",
            "supply a seal_spec with a source_id, or set provisional=true"] };
      }
      warnings.push("O-ring groove dimensions are PROVISIONAL; no water/dust ingress claim is supported.");
    } else {
      warnings.push(`Seal dimensions sourced from ${sealSpec.source_id}; physical testing still required for ingress claims.`);
    }
  }

  const extrudes = component.features.extrudeFeatures;
  const pathMode: string = request.path_mode ?? "planar_closed_loop";

  if ((pathMode === "planar_closed_loop" || pathMode === "planar_partial") && pathSketch !== undefined && pathSketch !== null) {
    // Planar annular extrude cut for the channel.
    const channelOffset = `(${width})`;
    const chSk = makeOffsetProfile(component, `seal_${ns}_channel`, pathSketch, channelOffset);
    if (chSk !== null && chSk.sketchProfiles.count > 0) {
      created.push(chSk);
      const extIn = extrudes.createInput(chSk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(depth));
      extIn.participantBodies = [targetBody];
      const feat = extrudes.add(extIn);
      if (feat) created.push(feat);
    } else {
      return { created, warnings,
        refusal: ["seam-segment-collapsed",
          "Seal channel offset collapsed; check corner radii and width.",
          "reduce cross_section_width or increase corner radius"] };
    }
  } else if (sweepPath !== undefined && sweepPath !== null) {
    // Explicit sweep cut for nonplanar paths.
    if (!validateTangentContinuity(sweepPath)) {
      return { created, warnings,
        refusal: ["seam-nontangent-unsupported",
          "Seal sweep path has non-tangent junctions.",
          "split into explicit segments at sharp corners"] };
    }
    const csPlane = request.cross_section_plane;
    if (csPlane === undefined || csPlane === null) {
      return { created, warnings,
        refusal: ["target-not-found", "Cross-section plane not resolved.", "provide a start plane perpendicular to the sweep path"] };
    }
    const wVal = mmToFloat(width);
    const dVal = mmToFloat(depth);
    const csSk = makePlanarProfile(component, `seal_${ns}_cs`, csPlane, "rectangle", { width: wVal, height: dVal });
    if (csSk !== null && csSk.sketchProfiles.count > 0) {
      const op = adsk.fusion.FeatureOperations.CutFeatureOperation;
      const feat = makeSweep(component, csSk.sketchProfiles.item(0), sweepPath, op, [targetBody], `seal_${ns}`);
      if (feat) created.push(feat);
    }
  } else {
    return { created, warnings,
      refusal: ["target-not-found", "No seal path sketch or sweep path provided.", "provide a path_sketch for planar or a sweep_path for nonplanar seals"] };
  }

  // Gasket land (additive).
  if (stype === "gasket_land") {
    const landHeight = String(params.land_height ?? "0.3 mm");
    const landWidth = String(params.land_width ?? "2.0 mm");
    if (pathSketch) {
      const landSk = makeOffsetProfile(component, `seal_${ns}_land`, pathSketch, landWidth);
      if (landSk !== null && landSk.sketchProfiles.count > 0) {
        created.push(landSk);
        const extIn = extrudes.createInput(landSk.sketchProfiles.item(0),
          adsk.fusion.FeatureOperations.JoinFeatureOperation);
        extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(landHeight));
        extIn.participantBodies = [targetBody];
        const feat = extrudes.add(extIn);
        if (feat) created.push(feat);
      }
    }
  }

  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}

function compressionStops(
  component: any,
  identity: ManagedIdentity,
  request: Record<string, any>,
  created: unknown[],
  warnings: string[],
): SealRecipeResult {
  requireAdsk();
  const ns = identity.parameterNamespace;
  const targetBody = request.target_body;
  const plane = (request.placement_frame ?? {}).plane;
  const stops: any[] = request.compression_stops ?? [];
  if (stops.length === 0) {
    return { created, warnings,
      refusal: ["target-not-found", "No compression stop positions provided.", "supply explicit stop placements"] };
  }
  const extrudes = component.features.extrudeFeatures;
  for (let i = 0; i < stops.length; i++) {
    const stop = stops[i];
    const pos = stop.center_point;
    const w = Number(stop.width ?? 2.0);
    const h = String(stop.height ?? "0.5 mm");
    if (pos === undefined || pos === null || plane === undefined || plane === null || targetBody === undefined || targetBody === null) {
      continue;
    }
    const sk = makePlanarProfile(component, `comp_stop_${ns}_${i}`, plane, "rectangle", { width: w, height: 1.5 });
    if (sk !== null && sk.sketchProfiles.count > 0) {
      created.push(sk);
      const extIn = extrudes.createInput(sk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
      extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(h));
      const stopExt = extrudes.add(extIn);
      if (stopExt) {
        created.push(stopExt);
        const coll = stopExt.bodies;
        const stopBodies: unknown[] = coll ? Array.from({ length: coll.count }, (_, j) => coll.item(j)) : [];
        if (stopBodies.length > 0) {
          const joinFeat = joinExact(component, targetBody, stopBodies);
          if (joinFeat) created.push(joinFeat);
        }
      }
    }
  }
  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}
