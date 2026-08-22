/**
 * Extrusion extent helpers: distance, to-entity, to-body.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/extents.py.
 */

import { adsk } from "@adsk/fas";

type Any = any;


export function extentDistance(
  extrudeInput: Any,
  expression: string,
  direction: string = "positive",
): void {
  extrudeInput.setDistanceExtent(false, adsk.core.ValueInput.createByString(expression));
}

export function extentToEntity(extrudeInput: Any, entity: Any): void {
  extrudeInput.setOneSideToEntityExtent(entity, false);
}

export function extentToBody(extrudeInput: Any, body: Any): void {
  extrudeInput.setOneSideToEntityExtent(body, false);
}
