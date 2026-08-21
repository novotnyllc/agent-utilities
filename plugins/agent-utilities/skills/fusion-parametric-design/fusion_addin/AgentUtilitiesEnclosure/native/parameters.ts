/**
 * Fusion user-parameter creation with explicit units and comments.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/parameters.py.
 */

import { adsk } from "@adsk/fas";

type Any = any;


export function makeParameter(
  design: Any,
  name: string,
  expression: string,
  unitType: string = "mm",
  comment: string = "",
): Any | null {
  const params = design.userParameters;
  const existing = params.itemByName(name);
  if (existing !== null && existing !== undefined) {
    if (expression) {
      existing.expression = expression;
    }
    if (comment) {
      existing.comment = comment;
    }
    return existing;
  }

  const units = design.unitsManager;
  const unitEnum = resolveUnitEnum(units, unitType);
  const valueInput = adsk.core.ValueInput.createByString(expression);
  return params.add(name, valueInput, unitEnum, comment);
}

function resolveUnitEnum(unitsMgr: Any, unitType: string): Any {
  /**
   * Map a unit string to the Fusion UnitTypes enum value.
   *
   * Fusion's unitsManager handles expression strings; the unit_type controls
   * display. For simplicity, use the design's default distance/angle format.
   */
  const mapping: Record<string, string> = {
    "mm": "MillimeterDecimalFormat",
    "cm": "CentimeterDecimalFormat",
    "m": "MeterDecimalFormat",
    "in": "InchDecimalFormat",
    "deg": "DegreeDecimalFormat",
    "rad": "RadianDecimalFormat",
  };
  void mapping; // kept for documentation parity with Python source
  if (unitType === "deg" || unitType === "rad") {
    return unitsMgr.angleFormat;
  }
  return unitsMgr.distanceFormat;
}
