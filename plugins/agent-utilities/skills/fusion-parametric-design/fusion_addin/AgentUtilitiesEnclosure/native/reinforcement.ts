/**
 * Reinforcement body: new-body extrude + optional draft + join last.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/reinforcement.py.
 */

import { adsk } from "@adsk/fas";
import { joinExact } from "./booleans";

type Any = any;


export function makeReinforcementBody(
  component: Any,
  sketchProfile: Any,
  targetBodies: Any[],
  heightExpr: string,
  draftAngleExpr: string = "0 deg",
): Any[] {
  const created: Any[] = [];

  const extrudes = component.features.extrudeFeatures;
  const extIn = extrudes.createInput(
    sketchProfile,
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
  extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(heightExpr));
  const ribFeat = extrudes.add(extIn);
  if (ribFeat === null || ribFeat === undefined) {
    return created;
  }
  created.push(ribFeat);

  const bodies = featureBodies(ribFeat);
  if (bodies.length === 0) {
    return created;
  }

  if (draftAngleExpr && draftAngleExpr !== "0 deg") {
    const draftFeat = tryDraft(component, bodies, draftAngleExpr);
    if (draftFeat) {
      created.push(draftFeat);
    }
  }

  const joined = joinExact(component, targetBodies[0], bodies);
  if (joined) {
    created.push(joined);
  }
  return created;
}

function featureBodies(feature: Any): Any[] {
  const bodiesColl = feature?.bodies ?? null;
  if (bodiesColl === null || bodiesColl === undefined) {
    return [];
  }
  const out: Any[] = [];
  for (let i = 0; i < bodiesColl.count; i++) {
    out.push(bodiesColl.item(i));
  }
  return out;
}

function tryDraft(component: Any, bodies: Any[], angleExpr: string): Any | null {
  const drafts = component.features.draftFeatures;
  if (drafts === null || drafts === undefined) {
    return null;
  }
  try {
    const draftIn = drafts.createInput();
    const faces = adsk.core.ObjectCollection.create();
    for (const body of bodies) {
      for (let i = 0; i < body.faces.count; i++) {
        const face = body.faces.item(i);
        const geo = face?.geometry ?? null;
        if (
          geo !== null && geo !== undefined &&
          typeof geo.objectType === "string" &&
          !geo.objectType.includes("Plane")
        ) {
          faces.add(face);
        }
      }
    }
    if (faces.count > 0) {
      const neutral = bodies[0].faces.item(0);
      const direction = adsk.core.ValueInput.createByString(angleExpr);
      draftIn.setSingleAngle(neutral, faces, false, direction);
      return drafts.add(draftIn);
    }
  } catch {
    // fall through
  }
  return null;
}
