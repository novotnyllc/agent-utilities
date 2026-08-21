/**
 * Boss recipe: all variants including coordinated_pair with shared axis.
 */

import { adsk } from "@adsk/fas";
import { makePlanarProfile } from "../native/sketches";
import { joinExact } from "../native/booleans";
import { makeHole, makeInsertBore, makePolygonPocket } from "../native/holes_threads";
import { makeReinforcementBody } from "../native/reinforcement";
import { makeParameter } from "../native/parameters";
import { stampAttributes, ManagedIdentity } from "../identity";
import { AddInNotRunningError } from "../dispatch";

export const BOSS_VARIANTS = new Set([
  "support", "screw", "heat_set_insert", "captive_square_nut",
  "captive_hex_nut", "thread_forming", "tapped", "pcb_standoff",
  "coordinated_pair",
]);

type Refusal = [string, string, string];

export type BossRecipeResult = {
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

function featureBodies(feature: any): unknown[] {
  const coll = feature?.bodies;
  if (!coll) return [];
  const out: unknown[] = [];
  for (let i = 0; i < coll.count; i++) out.push(coll.item(i));
  return out;
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

  const outerDia = params.outer_diameter ?? "6 mm";
  const height = params.height ?? "5 mm";
  const design = getDesign();
  if (design !== null) {
    makeParameter(design, `des_ef_${ns}_boss_outer_diameter`, String(outerDia),
      "mm", `Boss outer diameter (${identity.displaySuffix})`);
    makeParameter(design, `calc_ef_${ns}_boss_height`, String(height),
      "mm", `Boss height (${identity.displaySuffix})`);
  }

  // Python: numeric passthrough, else default 6.0.
  const diaVal = typeof outerDia === "number" ? outerDia : 6.0;
  const bossSketch = makePlanarProfile(component, `boss_${ns}_outer`, plane, "circle", { diameter: diaVal });
  if (bossSketch === null || bossSketch.sketchProfiles.count === 0) {
    return { created, warnings,
      refusal: ["feature-create-failed", "Boss profile sketch failed.", "check placement plane and diameter"] };
  }
  created.push(bossSketch);

  const extrudes = component.features.extrudeFeatures;
  const profile = bossSketch.sketchProfiles.item(0);
  const extIn = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
  extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(String(height)));
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

  if (variant === "heat_set_insert" && hardware.insert_spec) {
    created.push(...makeInsertBore(component, targetBody, centerPt, direction, hardware.insert_spec));
  } else if (variant === "captive_square_nut" || variant === "captive_hex_nut") {
    const sides = variant === "captive_square_nut" ? 4 : 6;
    const af = Number(hardware.across_flats ?? 5.5);
    const depth = hardware.depth ?? "2.5 mm";
    const slot = hardware.slot_width ?? "";
    created.push(...makePolygonPocket(component, targetBody, plane, sides, af, depth, slot));
  } else if (
    variant === "screw" || variant === "tapped" || variant === "thread_forming" ||
    variant === "support" || variant === "pcb_standoff"
  ) {
    const boreDia = hardware.bore_diameter ?? (variant !== "pcb_standoff" ? "3.2 mm" : "2.2 mm");
    const boreDepth = hardware.bore_depth ?? "";
    const holeType = hardware.hole_type ?? "simple";
    const feat = makeHole(component, targetBody, centerPt, direction, boreDia, boreDepth, holeType);
    if (feat) created.push(feat);
  } else if (variant === "coordinated_pair") {
    warnings.push("Coordinated pair requires explicit mating body and shared axis datum.");
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

  for (const feat of created) {
    stampAttributes(feat, identity);
  }
  return { created, warnings, refusal: null };
}
