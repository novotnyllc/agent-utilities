/**
 * Path creation, tangent-continuity validation, and sweep primitives.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/paths.py.
 */

import { adsk } from "@adsk/fas";

type Any = any;


export function makeSweepPath(component: Any, name: string, entities: Any[]): Any | null {
  const coll = adsk.core.ObjectCollection.create();
  for (const e of entities) {
    coll.add(e);
  }
  return adsk.fusion.Path.create(coll, adsk.fusion.ChainedCurveOptions.tangentChainedCurves);
}

export function validateTangentContinuity(path: Any): boolean {
  try {
    return path.isContinuous;
  } catch {
    return true;
  }
}

export function makeSweep(
  component: Any,
  profile: Any,
  path: Any,
  operation: Any,
  participantBodies: Any[],
  name: string = "",
): Any | null {
  const sweeps = component.features.sweepFeatures;
  const inputObj = sweeps.createInput(profile, path, operation);
  inputObj.participantBodies = participantBodies;
  const result = sweeps.add(inputObj);
  if (result && name) {
    result.name = name;
  }
  return result;
}
