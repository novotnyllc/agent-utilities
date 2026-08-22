/**
 * Hole, thread, insert-bore, polygon-pocket, and spot-face primitives.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/holes_threads.py.
 */

import { adsk } from "@adsk/fas";
import { makePolygonProfile, makePlanarProfile } from "./sketches";
import { extentDistance } from "./extents";
import { makeNamedPlane } from "./datums";

type Any = any;


export function makeHole(
  component: Any,
  targetBody: Any,
  centerPoint: Any,
  direction: Any,
  diameterExpr: string,
  depthExpr: string = "",
  holeType: string = "simple",
  kwargs: Record<string, Any> = {},
): Any | null {
  /** Create a HoleFeature with version-gated modern APIs. */
  const holes = component.features.holeFeatures;
  const inputObj = holes.createInput(
    adsk.core.ValueInput.createByString(diameterExpr),
    targetBody,
    centerPoint,
    direction,
  );
  if (depthExpr) {
    inputObj.setDistanceExtent(adsk.core.ValueInput.createByString(depthExpr));
  } else {
    inputObj.setAllExtent(adsk.fusion.HoleExtentTypes.AllHoleExtentType);
  }

  if (holeType === "counterbore" && "cb_diameter" in kwargs) {
    inputObj.holeType = adsk.fusion.HoleTypes.CounterboreHoleType;
    inputObj.counterboreDiameter = adsk.core.ValueInput.createByString(kwargs.cb_diameter);
    if ("cb_depth" in kwargs) {
      inputObj.counterboreDepth = adsk.core.ValueInput.createByString(kwargs.cb_depth);
    }
  } else if (holeType === "countersink" && "cs_diameter" in kwargs) {
    inputObj.holeType = adsk.fusion.HoleTypes.CountersinkHoleType;
    inputObj.countersinkDiameter = adsk.core.ValueInput.createByString(kwargs.cs_diameter);
    if ("cs_angle" in kwargs) {
      inputObj.countersinkAngle = adsk.core.ValueInput.createByString(kwargs.cs_angle);
    }
  }

  // Modern clearance/tapped API: version-gated with feature detection per design.
  if (holeType === "clearance" && typeof inputObj.setToClearanceHole === "function") {
    inputObj.setToClearanceHole();
  } else if (holeType === "tapped" && typeof inputObj.setToTappedHole === "function") {
    const ti = kwargs.thread_info ?? null;
    if (ti !== null && ti !== undefined) {
      inputObj.setToTappedHole(ti);
    }
  }
  return holes.add(inputObj);
}

export function makeThread(
  component: Any,
  face: Any,
  threadInfo: Any,
  modeled: boolean = false,
): Any | null {
  const threads = component.features.threadFeatures;
  const inputObj = threads.createInput(face, threadInfo);
  inputObj.isModeled = modeled;
  return threads.add(inputObj);
}

export function makeInsertBore(
  component: Any,
  targetBody: Any,
  centerPoint: Any,
  direction: Any,
  insertSpec: Record<string, Any>,
): Any[] {
  /** Heat-set insert bore from explicit InsertSpec. Dimensions must be sourced. */
  const feats: Any[] = [];
  const pilotDia = insertSpec.pilot_diameter ?? "";
  const pilotDepth = insertSpec.pilot_depth ?? "";
  if (pilotDia) {
    const f = makeHole(component, targetBody, centerPoint, direction, pilotDia, pilotDepth, "simple");
    if (f) feats.push(f);
  }
  const cbDia = insertSpec.counterbore_diameter ?? "";
  const cbDepth = insertSpec.counterbore_depth ?? "";
  if (cbDia && cbDepth) {
    const f = makeHole(component, targetBody, centerPoint, direction, cbDia, cbDepth, "simple");
    if (f) feats.push(f);
  }
  return feats;
}

function isNumeric(expr: string): boolean {
  const stripped = expr.replace(".", "");
  return stripped.length > 0 && /^\d+$/.test(stripped);
}

export function makePolygonPocket(
  component: Any,
  targetBody: Any,
  plane: Any,
  sides: number,
  acrossFlats: number,
  depthExpr: string,
  slotWidthExpr: string = "",
): Any[] {
  /** Square or hex nut pocket with optional side-loading slot. */
  const feats: Any[] = [];
  const sketch = makePolygonProfile(component, `nut_pocket_${sides}s`, plane, sides, acrossFlats);
  if (sketch === null || sketch.sketchProfiles.count === 0) {
    return feats;
  }
  const extrudes = component.features.extrudeFeatures;
  const extIn = extrudes.createInput(
    sketch.sketchProfiles.item(0),
    adsk.fusion.FeatureOperations.CutFeatureOperation,
  );
  extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(depthExpr));
  extIn.participantBodies = [targetBody];
  const f = extrudes.add(extIn);
  if (f) feats.push(f);

  if (slotWidthExpr) {
    const sw = isNumeric(slotWidthExpr) ? parseFloat(slotWidthExpr) : 1.0;
    const slotSk = makePlanarProfile(
      component, `nut_pocket_${sides}s_slot`, plane, "slot", { length: sw * 3, width: sw });
    if (slotSk !== null && slotSk.sketchProfiles.count > 0) {
      const slotExt = extrudes.createInput(
        slotSk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      slotExt.setDistanceExtent(false, adsk.core.ValueInput.createByString(depthExpr));
      slotExt.participantBodies = [targetBody];
      const sf = extrudes.add(slotExt);
      if (sf) feats.push(sf);
    }
  }
  return feats;
}

export function makeSpotFace(
  component: Any,
  targetBody: Any,
  axis: Any,
  diameterExpr: string,
  depthExpr: string,
): Any | null {
  /** Spot face: axis-normal plane + shallow circular cut along screw axis. */
  const plane = makeNamedPlane(component, "spot_face_plane", "plane_normal", { face: axis });
  if (plane === null || plane === undefined) {
    return null;
  }
  const sketches = component.sketches;
  const sk = sketches.add(plane);
  const dia = isNumeric(diameterExpr) ? parseFloat(diameterExpr) : 4.0;
  sk.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(0, 0, 0), dia / 2);
  if (sk.sketchProfiles.count === 0) {
    return null;
  }
  const extrudes = component.features.extrudeFeatures;
  const extIn = extrudes.createInput(
    sk.sketchProfiles.item(0),
    adsk.fusion.FeatureOperations.CutFeatureOperation);
  extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(depthExpr));
  extIn.participantBodies = [targetBody];
  return extrudes.add(extIn);
}
