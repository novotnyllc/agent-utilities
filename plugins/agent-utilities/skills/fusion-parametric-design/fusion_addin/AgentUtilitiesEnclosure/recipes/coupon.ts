/**
 * Fit coupon recipes: explicit finite candidate list ONLY; no search or scoring.
 */

import { adsk } from "@adsk/fas";
import { makePlanarProfile } from "../native/sketches";
import { makeParameter } from "../native/parameters";
import { stampAttributes, ManagedIdentity } from "../identity";
import { AddInNotRunningError } from "../dispatch";

export const COUPON_TYPES = new Set([
  "sliding_clearance", "press_fit", "pin_hole", "captive_nut",
  "heat_set_insert", "lip_groove", "snap_engagement", "dovetail",
  "connector_cutout",
]);

type Refusal = [string, string, string];

export type CouponRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

function requireAdsk(): void {
  if (!adsk || !adsk.core || !adsk.fusion) {
    throw new AddInNotRunningError("adsk not available.");
  }
}

function getDesign(): any {
  try {
    return (adsk.core.Application.get() as any).activeDocument?.design ?? null;
  } catch {
    return null;
  }
}

/** Python float(candidate): numbers pass through, strings strip "mm". */
function toFloat(value: any): number {
  if (typeof value === "number") return value;
  return parseFloat(String(value).replace("mm", "").trim());
}

function featureBodies(feature: any): unknown[] {
  const coll = feature?.bodies;
  if (!coll) return [];
  const out: unknown[] = [];
  for (let i = 0; i < coll.count; i++) out.push(coll.item(i));
  return out;
}

export function executeCouponRecipe(
  component: any,
  identity: ManagedIdentity,
  request: Record<string, any>,
): CouponRecipeResult {
  requireAdsk();
  const warnings: string[] = [];
  const created: unknown[] = [];
  const ns = identity.parameterNamespace;

  const ctype: string = request.coupon_type ?? "sliding_clearance";
  if (!COUPON_TYPES.has(ctype)) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Unknown coupon type: ${ctype}`, "use a documented coupon type"] };
  }
  const candidates = request.candidates;
  if (!candidates || !Array.isArray(candidates) || candidates.length === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed",
        "Coupon requires an explicit finite candidate list.",
        "supply values like [-0.10, 0.00, +0.10, +0.20]"] };
  }
  if (candidates.length > 20) {
    return { created, warnings,
      refusal: ["feature-create-failed", `Too many candidates (${candidates.length}); max 20.`, "reduce the list"] };
  }

  const params: Record<string, any> = request.parameters ?? {};
  const stationPitch = Number(params.station_pitch ?? 8.0);
  const stationSize = Number(params.station_size ?? 5.0);
  const bodyThickness = String(params.body_thickness ?? "3 mm");
  const plane = (request.placement_frame ?? {}).plane;
  const extrudes = component.features.extrudeFeatures;

  const totalLen = candidates.length * stationPitch + stationPitch;
  const couponSk = makePlanarProfile(component, `coupon_${ns}_body`, plane, "rectangle",
    { width: totalLen, height: stationSize + stationPitch });
  if (couponSk === null || couponSk.sketchProfiles.count === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Coupon body sketch failed.", "check plane and dimensions"] };
  }
  created.push(couponSk);

  const extIn = extrudes.createInput(couponSk.sketchProfiles.item(0),
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
  extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(bodyThickness));
  const couponExt = extrudes.add(extIn);
  if (couponExt === null || couponExt === undefined) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Coupon body extrude failed.", "check thickness"] };
  }
  created.push(couponExt);

  const couponBodies = featureBodies(couponExt);
  const design = getDesign();

  for (let i = 0; i < candidates.length; i++) {
    const cval = toFloat(candidates[i]);
    const pname = `des_ef_${ns}_coupon_station_${i}`;
    if (design !== null) {
      makeParameter(design, pname, `${cval} mm`, "mm",
        `Station ${i}: ${cval} mm (${identity.displaySuffix})`);
    }
    const holeDia = Math.max(0.1, stationSize + cval);
    const stName = `coupon_${ns}_station_${i}`;
    const stSk = makePlanarProfile(component, stName, plane, "circle", { diameter: holeDia });
    if (stSk !== null && stSk.sketchProfiles.count > 0) {
      created.push(stSk);
      const stExt = extrudes.createInput(stSk.sketchProfiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation);
      stExt.setDistanceExtent(false, adsk.core.ValueInput.createByString(bodyThickness));
      stExt.participantBodies = couponBodies;
      const feat = extrudes.add(stExt);
      if (feat) created.push(feat);
    }
  }

  for (const body of couponBodies) {
    stampAttributes(body, identity, "fit_coupon");
  }
  stampCouponStatus(identity, "generated");
  warnings.push("Coupon status is generated; physical printing and measurement required.");
  return { created, warnings, refusal: null };
}

export function recordCouponResult(
  identity: ManagedIdentity,
  resultState: string,
  chosenValue: number | null,
  userObservation: string,
): [boolean, string] {
  if (!["accepted", "rejected", "stale", "printed", "measured"].includes(resultState)) {
    return [false, `Invalid state: ${resultState}`];
  }
  if (resultState === "accepted" && chosenValue === null) {
    return [false, "Accepting requires a user-observed chosen value."];
  }
  if (!userObservation) {
    return [false, "Requires a user observation string."];
  }
  stampCouponStatus(identity, resultState);
  if (resultState === "accepted" && chosenValue !== null) {
    updateRuleParam(identity, chosenValue);
  }
  return [true, `Recorded as ${resultState} with value ${chosenValue}.`];
}

function stampCouponStatus(identity: ManagedIdentity, state: string): void {
  try {
    requireAdsk();
  } catch {
    return; // ImportError equivalent: no-op offline.
  }
  const design = (adsk.core.Application.get() as any).activeDocument?.design ?? null;
  if (!design) return;
  const root = design.rootComponent;
  if (!root) return;
  const attrs = root.attributes;
  const key = `enclosure_coupon_status_${identity.displaySuffix}`;
  const existing = attrs.itemByName("fusion_parametric_design", key);
  if (existing) {
    existing.value = state;
  } else {
    attrs.add("fusion_parametric_design", key, state);
  }
}

function updateRuleParam(identity: ManagedIdentity, value: number): void {
  try {
    requireAdsk();
  } catch {
    return;
  }
  const design = (adsk.core.Application.get() as any).activeDocument?.design ?? null;
  if (!design) return;
  const name = `des_ef_${identity.parameterNamespace}_accepted_fit_value`;
  const pmgr = design.userParameters;
  const existing = pmgr.itemByName(name);
  if (existing) {
    existing.expression = String(value);
  } else {
    pmgr.add(name, adsk.core.ValueInput.createByReal(value),
      design.unitsManager.distanceFormat,
      `Accepted fit value from coupon ${identity.displaySuffix}`);
  }
}
