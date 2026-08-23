/**
 * Pattern and mirror primitives with homogeneous-set compatibility checks.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/patterns.py.
 */

import { adsk } from "@adsk/fas";

type Any = any;


function toCollection(items: Any[]): Any {
  const coll = adsk.core.ObjectCollection.create();
  for (const item of items) {
    coll.add(item);
  }
  return coll;
}

function checkHomogeneous(features: Any[]): string {
  if (features.length === 0) {
    return "pattern-source-incompatible";
  }
  const types = new Set<string>(features.map((f) => f?.objectType ?? ""));
  if (types.size > 1) {
    return "pattern-source-incompatible";
  }
  return "";
}

export function makePattern(
  component: Any,
  sources: Any[],
  patternType: string,
  quantity: number,
  kwargs: Record<string, Any> = {},
): [Any | null, string] {
  /** Create a native pattern. Returns [feature_or_null, warning_or_empty]. */
  const err = checkHomogeneous(sources);
  if (err) {
    return [null, err];
  }

  const featuresColl = toCollection(sources);
  const feats = component.features;
  let result: Any | null = null;

  if (patternType === "rectangular") {
    const rp = feats.rectangularPatternFeatures;
    const inputObj = rp.createInput(featuresColl, null, null);
    inputObj.quantityOne = adsk.core.ValueInput.createByString(String(quantity));
    if ("spacing" in kwargs) {
      inputObj.distanceOne = adsk.core.ValueInput.createByString(kwargs.spacing);
    }
    result = rp.add(inputObj);
  } else if (patternType === "circular") {
    const cp = feats.circularPatternFeatures;
    const axis = "axis" in kwargs ? kwargs.axis : undefined;
    const inputObj = cp.createInput(featuresColl, axis);
    inputObj.quantity = adsk.core.ValueInput.createByString(String(quantity));
    if ("angle" in kwargs) {
      inputObj.totalAngle = adsk.core.ValueInput.createByString(kwargs.angle);
    }
    result = cp.add(inputObj);
  } else if (patternType === "path") {
    const pp = feats.pathPatternFeatures;
    const path = "path" in kwargs ? kwargs.path : undefined;
    const inputObj = pp.createInput(featuresColl, path);
    inputObj.quantity = adsk.core.ValueInput.createByString(String(quantity));
    result = pp.add(inputObj);
  } else {
    return [null, "pattern-source-incompatible"];
  }

  let warning = "";
  if (kwargs.handed_hardware) {
    warning = "Handed hardware in a pattern/mirror may be incorrect; verify orientation.";
  }
  return [result, warning];
}

export function makeMirror(
  component: Any,
  sources: Any[],
  mirrorPlane: Any,
): [Any | null, string] {
  const err = checkHomogeneous(sources);
  if (err) {
    return [null, err];
  }
  const mirrors = component.features.mirrorFeatures;
  const inputObj = mirrors.createInput(toCollection(sources), mirrorPlane);
  const result = mirrors.add(inputObj);
  return [result, ""];
}
