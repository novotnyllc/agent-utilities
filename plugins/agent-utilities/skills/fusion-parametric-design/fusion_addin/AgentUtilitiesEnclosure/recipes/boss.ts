/**
 * Boss recipe: all variants including coordinated_pair with shared axis.
 */

import { adsk } from "@adsk/fas";
import { makePlanarProfile } from "../native/sketches";
import { joinExact } from "../native/booleans";
import { makeHole, makeInsertBore, makePolygonPocket } from "../native/holes_threads";
import { makeReinforcementBody } from "../native/reinforcement";
import { makeParameter, ownedParamName } from "../native/parameters";
import { stampAttributes, identityRole, ManagedIdentity } from "../identity";
import { featureBodies, requireAdsk } from "./shared";

export const BOSS_VARIANTS = new Set([
  "support", "screw", "heat_set_insert", "captive_square_nut",
  "captive_hex_nut", "thread_forming", "tapped", "pcb_standoff",
  "coordinated_pair", "compression",
]);

type Refusal = [string, string, string];

export type BossRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

function getDesign(): any {
  try {
    return (adsk.core.Application.get() as any).activeDocument?.design ?? null;
  } catch {
    return null;
  }
}


function deriveBossAxis(bossBody: any): [any, any] | null {
  /** Center + axis from the boss's cylindrical side face, for bores that need
   * an explicit point/axis when the request omitted them. */
  try {
    const faces = bossBody?.faces;
    if (!faces) return null;
    for (let i = 0; i < faces.count; i++) {
      const face = faces.item(i);
      const geo = face?.geometry ?? null;
      if (geo && typeof geo.objectType === "string" && geo.objectType.includes("Cylinder")) {
        return [geo.origin ?? null, geo.axis ?? null];
      }
    }
  } catch { /* fall through */ }
  return null;
}

export function executeBossRecipe(
  component: any,
  identity: ManagedIdentity,
  request: Record<string, any>,
): BossRecipeResult {
  requireAdsk();
  const warnings: string[] = [];
  const created: unknown[] = [];
  const ns = identity.parameterNamespace;

  const variant: string = request.variant ?? "support";
  if (!BOSS_VARIANTS.has(variant)) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Unknown boss variant: ${variant}`, "use a documented variant"] };
  }

  const params: Record<string, any> = request.parameters ?? {};
  const targetBody = request.target_body;
  if (targetBody === undefined || targetBody === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Boss target body not resolved.", "select an explicit target body"] };
  }

  const placement: Record<string, any> = request.placement_frame ?? {};
  const plane = placement.plane;
  if (plane === undefined || plane === null) {
    return { created, warnings,
      refusal: ["target-not-found", "Boss placement plane not resolved.", "provide an explicit placement plane"] };
  }

  const hardwareEarly: Record<string, any> = request.hardware ?? {};
  if (variant === "heat_set_insert" && !hardwareEarly.insert_spec) {
    return { created, warnings,
      refusal: ["coupon-required",
        "heat_set_insert requires hardware.insert_spec (pilot diameter/depth from the insert datasheet).",
        "supply the manufacturer InsertSpec or run a heat-set fit coupon first"] };
  }

  const outerDia = params.outer_diameter ?? "6 mm";
  const height = params.height ?? "5 mm";
  const design = getDesign();
  if (design !== null) {
    makeParameter(design, ownedParamName(identity, "design", "boss_outer_diameter"), String(outerDia),
      "mm", `Boss outer diameter (${identity.displaySuffix})`);
    makeParameter(design, ownedParamName(identity, "derived", "boss_height"), String(height),
      "mm", `Boss height (${identity.displaySuffix})`);
  }

  let diaVal: number | string = typeof outerDia === "number" ? outerDia : NaN;
  if (Number.isNaN(diaVal)) {
    const raw = String(outerDia);
    const parsed = parseFloat(raw);
    if (!Number.isNaN(parsed) && /^\s*[\d.]+\s*(mm|cm|in)?\s*$/i.test(raw)) {
      const unit = raw.toLowerCase();
      if (unit.includes("in")) {
        diaVal = parsed * 25.4; // 1 in = 25.4 mm (Fusion internal units)
      } else if (unit.includes("cm")) {
        diaVal = parsed * 10.0; // 1 cm = 10 mm (Fusion internal units)
      } else {
        diaVal = parsed;
      }
    } else {
      return { created, warnings,
        refusal: ["invalid-parameter-expression",
          `outer_diameter '${outerDia}' is not a plain number with optional unit.`,
          "send a number (mm) or a '<value> <unit>' expression"] };
    }
  }
  const bossSketch = makePlanarProfile(component, `boss_${ns}_outer`, plane, "circle", { diameter: diaVal });
  if (bossSketch === null || bossSketch.sketchProfiles.count === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Boss profile sketch failed.", "check placement plane and diameter"] };
  }
  created.push(bossSketch);

  const extrudes = component.features.extrudeFeatures;
  const profile = bossSketch.sketchProfiles.item(0);
  const extIn = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
  // Spec: height = distance | to_face | to_body. Entity extents keep the boss
  // associative to the mating face instead of baking a measured gap.
  const heightMode = String(params.height_mode ?? (typeof height === "object" ? "to_entity" : "distance"));
  const extentEntity = params.height_to_entity ?? (typeof height === "object" ? height.to_entity : null) ?? null;
  if ((heightMode === "to_face" || heightMode === "to_body" || heightMode === "to_entity") && extentEntity != null) {
    try {
      extIn.setOneSideToEntityExtent(extentEntity, false);
    } catch (exc) {
      return { created, warnings,
        refusal: ["target-not-found", `Height extent entity not usable: ${exc}`, "select an explicit face/body for the boss top"] };
    }
  } else if ((heightMode === "to_face" || heightMode === "to_body") && extentEntity == null) {
    return { created, warnings,
      refusal: ["target-not-found", `height_mode ${heightMode} requires height_to_entity.`, "provide the face/body the boss should meet"] };
  } else {
    extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(String(height)));
  }
  const bossExt = extrudes.add(extIn);
  if (bossExt === null || bossExt === undefined) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Boss extrude failed.", "check height and plane"] };
  }
  created.push(bossExt);

  const bossBodies = featureBodies(bossExt);
  if (bossBodies.length === 0) {
    return { created, warnings,
      refusal: ["zero-thickness-result", "Boss body empty after extrude.", "undo and check parameters"] };
  }

  const joinFeat = joinExact(component, targetBody, bossBodies);
  if (joinFeat) created.push(joinFeat);

  const hardware: Record<string, any> = request.hardware ?? {};
  const centerPt = placement.center_point;
  const direction = placement.direction;

  if (variant === "heat_set_insert") {
    let boreCenter = centerPt;
    let boreDir = direction;
    if (boreCenter == null || boreDir == null) {
      // Derive axis from the new boss's cylindrical side face when possible.
      const derived = deriveBossAxis(bossBodies[0]);
      if (derived !== null) { boreCenter = derived[0]; boreDir = derived[1]; }
    }
    if (boreCenter == null || boreDir == null) {
      return { created, warnings,
        refusal: ["target-not-found", "Heat-set bore needs placement.center_point and direction.",
          "provide the point+axis selections or sketch the profile on an explicit plane"] };
    }
    created.push(...makeInsertBore(component, targetBody, boreCenter, boreDir, hardware.insert_spec));
  } else if (variant === "captive_square_nut" || variant === "captive_hex_nut") {
    const sides = variant === "captive_square_nut" ? 4 : 6;
    if (hardware.across_flats === undefined || hardware.across_flats === null || hardware.across_flats === "") {
      return { created, warnings,
        refusal: ["invalid-parameter-expression",
          "captive nut requires sourced hardware.across_flats.",
          "supply the nut AF from the datasheet; do not guess 5.5 mm"] };
    }
    if (hardware.depth === undefined || hardware.depth === null || hardware.depth === "") {
      return { created, warnings,
        refusal: ["invalid-parameter-expression",
          "captive nut requires sourced hardware.depth.",
          "supply pocket depth from the nut thickness plus print clearance"] };
    }
    const af = Number(hardware.across_flats);
    if (!Number.isFinite(af) || af <= 0) {
      return { created, warnings,
        refusal: ["invalid-parameter-expression",
          `across_flats '${hardware.across_flats}' is not a positive number.`,
          "send AF in millimeters"] };
    }
    const depth = hardware.depth;
    const slot = hardware.slot_width ?? "";
    const depthVal = parseFloat(String(depth).replace("mm", "").trim());
    const heightVal = parseFloat(String(height).replace("mm", "").trim());
    if (Number.isFinite(depthVal) && Number.isFinite(heightVal) && depthVal >= heightVal) {
      warnings.push(
        `Pocket depth ${depth} mm meets/exceeds boss height ${height} mm; verify the pocket opens through the intended face.`);
    }
    created.push(...makePolygonPocket(component, targetBody, plane, sides, af, depth, slot));
  } else if (variant === "compression") {
    // Hollow compression boss: annular wall with compliant slot fingers that
    // flex when a mating part is pressed in. Requires sourced dimensions.
    const outerD = Number(params.outer_diameter ?? 0);
    const boreD = Number(hardware.bore_diameter ?? 0);
    const fingerCount = Number(hardware.finger_count ?? 4);
    const slotWidth = String(hardware.slot_width ?? "1 mm");
    if (!outerD || !boreD) {
      return { created, warnings,
        refusal: ["invalid-parameter-expression",
          "compression boss requires numeric outer_diameter and hardware.bore_diameter.",
          "source both from the mating part datasheet"] };
    }
    if (boreD >= outerD) {
      return { created, warnings,
        refusal: ["insufficient-wall-thickness",
          `bore_diameter ${boreD} must be smaller than outer_diameter ${outerD}.`,
          "leave wall for the compliant fingers"] };
    }
    // Annular bore through the boss (the hollow).
    const boreFeat = makeHole(component, targetBody, centerPt, direction,
      String(boreD) + " mm", "", "simple");
    if (boreFeat) created.push(boreFeat);
    // Relief slots from the bore outward create the compressible fingers.
    const slotDepth = Number(hardware.slot_depth ?? Math.round((outerD - boreD) / 2 + 1));
    // Finger relief slots: rectangles sketched on the placement plane, one
    // edge on the bore wall (radius = parsed bore radius), extending radially
    // outward to slotDepth at each finger's angle. Coordinates are database cm;
    // parse mm inputs and divide by 10.
    const slotWVal = parseFloat(slotWidth) || 1.0; // ponytail: unit-suffix widths fall back to 1 mm; tighten if recipes send strings
    const boreRcm = boreD / 2 / 10;
    const slotWcm = slotWVal / 10;
    const depthCm = slotDepth / 10;
    const extrudesFinger = component.features.extrudeFeatures;
    for (let s = 0; s < fingerCount; s++) {
      const angleDeg = (360 / fingerCount) * s;
      const ang = (angleDeg * Math.PI) / 180;
      const cosA = Math.cos(ang);
      const sinA = Math.sin(ang);
      const fingerSk = component.sketches.add(plane);
      fingerSk.name = `boss_${ns}_finger_${s}`;
      const flines = fingerSk.sketchCurves.sketchLines;
      // Radial frame: u along the finger axis, v across it. Inner edge sits ON
      // the bore wall so every finger is attached until its slot is cut.
      const innerU = boreRcm - 0.05 / 10;
      const outerU = boreRcm + depthCm;
      const corners: Array<[number, number]> = [
        [innerU, -slotWcm / 2], [outerU, -slotWcm / 2],
        [outerU, slotWcm / 2], [innerU, slotWcm / 2],
      ];
      // Sketch space is local to the sketch plane origin — adding the model-
      // space centerPt here double-transforms on non-XY planes. Keep corners
      // in local rotated frame; add a warning for non-planar placements.
      if (centerPt && typeof centerPt.z === "number" && Math.abs(centerPt.z) > 1e-6) {
        warnings.push("Compression finger slots assume a planar XY placement; verify slot orientation on angled/curved walls.");
      }
      const world = corners.map(([u, v]) =>
        adsk.core.Point3D.create(u * cosA - v * sinA, u * sinA + v * cosA, 0));
      for (let ci = 0; ci < 4; ci++) {
        flines.addByTwoPoints(world[ci], world[(ci + 1) % 4]);
      }
      created.push(fingerSk);
      if (fingerSk.sketchProfiles.count > 0 && slotDepth > 0) {
        const finExtIn = extrudesFinger.createInput(
          fingerSk.sketchProfiles.item(0),
          adsk.fusion.FeatureOperations.CutFeatureOperation);
        finExtIn.setDistanceExtent(false, adsk.core.ValueInput.createByReal(depthCm));
        finExtIn.participantBodies = [targetBody];
        const fingerFeat = extrudesFinger.add(finExtIn);
        if (fingerFeat) {
          created.push(fingerFeat);
        } else {
          warnings.push(`Compression finger ${s + 1} cut failed; verify manually.`);
        }
      } else {
        warnings.push(`Compression finger ${s + 1} profile failed; create the relief slot manually.`);
      }
      warnings.push(`Compression finger ${s + 1}/${fingerCount} at ${angleDeg} deg: relief slot width ${slotWidth}, depth ${slotDepth} mm — verify finger flexibility after print.`);
    }
    warnings.push("Compression bosses are coupon-sensitive: print a fit coupon for the mating part before production.");
  } else if (
    variant === "screw" || variant === "tapped" || variant === "thread_forming" ||
    variant === "support" || variant === "pcb_standoff"
  ) {
    const boreDia = hardware.bore_diameter ?? (variant !== "pcb_standoff" ? "3.2 mm" : "2.2 mm");
    const endOpen = String(request.end ?? "blind") === "open";
    const boreDepth = endOpen ? "" : (hardware.bore_depth ?? "");
    if (!endOpen && !hardware.bore_depth) {
      warnings.push("Blind bore without explicit bore_depth defaults to through; supply depth for a controlled blind hole.");
    }
    // Head seating: explicit counterbore/countersink objects win, then screw_head
    // shorthand, then legacy hole_type. Socket/button heads sit IN a counterbore
    // below the surface; flat heads countersink flush.
    let holeType = String(hardware.hole_type ?? "simple");
    const seatKwargs: Record<string, any> = {};
    if (hardware.counterbore && typeof hardware.counterbore === "object") {
      holeType = "counterbore";
      seatKwargs.cb_diameter = hardware.counterbore.diameter;
      seatKwargs.cb_depth = hardware.counterbore.depth;
    } else if (hardware.countersink && typeof hardware.countersink === "object") {
      holeType = "countersink";
      seatKwargs.cs_diameter = hardware.countersink.diameter;
      seatKwargs.cs_angle = hardware.countersink.angle;
    } else {
      const head = String(hardware.screw_head ?? "").toLowerCase();
      if (head === "socket" || head === "button" || head === "pan") {
        holeType = "counterbore";
        seatKwargs.cb_diameter = hardware.head_diameter;
        seatKwargs.cb_depth = hardware.head_height;
        if (!seatKwargs.cb_diameter || !seatKwargs.cb_depth) {
          return { created, warnings,
            refusal: ["invalid-parameter-expression",
              `screw_head '${head}' needs head_diameter and head_height for the counterbore seat.`,
              "source both from the fastener datasheet"] };
        }
      } else if (head === "flat" || head === "countersunk") {
        holeType = "countersink";
        seatKwargs.cs_diameter = hardware.head_diameter;
        seatKwargs.cs_angle = hardware.head_angle ?? "90 deg";
        if (!seatKwargs.cs_diameter) {
          return { created, warnings,
            refusal: ["invalid-parameter-expression",
              "screw_head 'flat' needs head_diameter for the countersink seat.",
              "source it from the fastener datasheet"] };
        }
      }
    }
    const feat = makeHole(component, targetBody, centerPt, direction, boreDia, boreDepth, holeType, seatKwargs);
    if (feat) {
      created.push(feat);
      if (holeType === "counterbore" || holeType === "countersink") {
        warnings.push(
          `Verify the ${holeType} seats the head flush/below the visible top face; the cut runs along the placement direction.`);
      }
    }
  } else if (variant === "coordinated_pair") {
    const matingBody = request.mating_body;
    if (matingBody == null || matingBody === undefined) {
      return { created, warnings,
        refusal: ["target-not-found", "coordinated_pair requires mating_body.",
          "provide the second enclosure half as mating_body"] };
    }
    // Shared-axis pair: base boss on target, receiver pocket in the lid on the
    // same axis. One connection instance, two child roles.
    if (hardware.bore_diameter === undefined || hardware.bore_diameter === null || hardware.bore_diameter === "") {
      return { created, warnings,
        refusal: ["invalid-parameter-expression",
          "coordinated_pair requires sourced hardware.bore_diameter.",
          "supply the screw clearance from the datasheet"] };
    }
    const baseBore = makeHole(component, targetBody, centerPt, direction,
      hardware.bore_diameter, "", "simple");
    if (baseBore) created.push(baseBore);
    if (hardware.receiver_diameter === undefined || hardware.receiver_diameter === null) {
      return { created, warnings,
        refusal: ["invalid-parameter-expression",
          "coordinated_pair requires sourced hardware.receiver_diameter.",
          "supply the lid pocket diameter"] };
    }
    const receiverDia = Number(hardware.receiver_diameter);
    const receiverDepth = hardware.receiver_depth;
    if (!receiverDepth) {
      return { created, warnings,
        refusal: ["invalid-parameter-expression",
          "coordinated_pair requires sourced hardware.receiver_depth.",
          "supply the lid pocket depth"] };
    }
    const rxSketch = makePlanarProfile(matingBody.component ?? component,
      `boss_${ns}_receiver`, request.mating_plane ?? plane, "circle", { diameter: receiverDia });
    if (rxSketch !== null && rxSketch.sketchProfiles.count > 0) {
      created.push(rxSketch);
      const mExts = (matingBody.component ?? component).features.extrudeFeatures;
      const rxIn = mExts.createInput(rxSketch.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      rxIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(String(receiverDepth)));
      rxIn.participantBodies = [matingBody];
      const rxCut = mExts.add(rxIn);
      if (rxCut) {
        created.push(rxCut);
        warnings.push("Coordinated pair: verify receiver engagement depth against the lid wall at assembly.");
      }
    } else {
      return { created, warnings,
        refusal: ["feature-create-failed",
          "Receiver profile failed on mating body.",
          "check mating_plane and receiver diameter"] };
    }
  }

  const ribSpec = request.rib_spec;
  if (ribSpec && ribSpec.profile !== undefined && ribSpec.profile !== null) {
    created.push(...makeReinforcementBody(
      component, ribSpec.profile, [targetBody],
      ribSpec.height ?? "3 mm",
      ribSpec.draft_angle ?? "0 deg"));
  }

  const baseBlend = params.base_blend_radius ?? "";
  if (baseBlend) {
    warnings.push("Base blend radius requires explicit edge selection after boss creation.");
  }

  // Role stamping: exactly ONE canonical entity carries the bare feature id
  // (the combine/join feature when present, else the extrude). Dependents get
  // suffixed ids + explicit roles so probeIdentity(fid)/findManagedEntities
  // resolve unambiguously; deleteFeature finds dependents via the fid prefix.
  const canonical = joinFeat ?? bossExt;
  const fid = identity.featureId;
  for (const feat of created) {
    if (!feat) continue;
    if (feat === canonical) {
      stampAttributes(feat, identity);
    } else if (feat === bossSketch) {
      stampAttributes(feat, { ...identity, featureId: fid + "_profile_sketch" }, "boss_profile_sketch");
    } else if (feat === bossExt) {
      stampAttributes(feat, { ...identity, featureId: fid + "_extrude" }, "boss_extrude");
    } else if (feat === joinFeat) {
      stampAttributes(feat, { ...identity, featureId: fid + "_join" }, "boss_join");
    } else {
      // Bore/pocket/rib children keep the family prefix but distinct ids so
      // they never multi-match a bare probe.
      stampAttributes(feat, { ...identity,
        featureId: fid + "_" + identityRole(identity) + "_child" });
    }
  }
  return { created, warnings, refusal: null };
}
