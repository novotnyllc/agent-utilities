/**
 * Explicit-participant Boolean combine operations via public Fusion API.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/booleans.py.
 */

import { adsk } from "@adsk/fas";

type Any = any;


function makeCombine(
  component: Any,
  operation: Any,
  targetBody: Any,
  toolBodies: Any[],
): Any | null {
  const combines = component.features.combineFeatures;
  const coll = adsk.core.ObjectCollection.create();
  for (const item of toolBodies) {
    coll.add(item);
  }
  const inputObj = combines.createInput(targetBody, coll);
  inputObj.operation = operation;
  return combines.add(inputObj);
}

export function joinExact(component: Any, target: Any, tools: Any[]): Any | null {
  return makeCombine(component, adsk.fusion.FeatureOperations.JoinFeatureOperation, target, tools);
}

export function cutExact(component: Any, target: Any, tools: Any[]): Any | null {
  return makeCombine(component, adsk.fusion.FeatureOperations.CutFeatureOperation, target, tools);
}

export function intersectExact(component: Any, target: Any, tools: Any[]): Any | null {
  return makeCombine(component, adsk.fusion.FeatureOperations.IntersectFeatureOperation, target, tools);
}
