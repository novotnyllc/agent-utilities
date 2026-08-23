/**
 * Chamfer and fillet edge treatment primitives via public Fusion API.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/edge_treatments.py.
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

export function makeChamfer(component: Any, edges: Any[], distanceExpr: string): Any | null {
  const chamfers = component.features.chamferFeatures;
  const inputObj = chamfers.createInput2();
  inputObj.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
    toCollection(edges),
    adsk.core.ValueInput.createByString(distanceExpr),
  );
  return chamfers.add(inputObj);
}

export function makeFillet(component: Any, edges: Any[], radiusExpr: string): Any | null {
  const fillets = component.features.filletFeatures;
  const inputObj = fillets.createInput();
  inputObj.addConstantRadiusEdgeSet(
    toCollection(edges),
    adsk.core.ValueInput.createByString(radiusExpr),
    true,
  );
  return fillets.add(inputObj);
}
