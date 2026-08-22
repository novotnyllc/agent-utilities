/**
 * Component-assigned FDM plastic-rule analogue.
 * Values live as ordinary Fusion user parameters and component attributes.
 * The Autodesk entitled Plastic Rule object is never required.
 */

export const RULE_PARAM = Object.freeze({
  wall_thickness: "des_ef_rule_wall_thickness",
  draft_angle: "des_ef_rule_draft_angle",
  nominal_radius: "des_ef_rule_nominal_radius",
  clearance: "clr_ef_rule_clearance",
  nozzle_diameter: "fab_ef_rule_nozzle_diameter",
});

export const RULE_ATTR = Object.freeze({
  polymer: "enclosure_fdm_polymer",
  assigned: "enclosure_fdm_rule_assigned",
  fit_generation: "enclosure_fdm_fit_generation",
  fit_stale: "enclosure_fdm_fit_stale",
});

export const POLYMERS = Object.freeze(["PLA", "PETG", "ASA", "PCCF"]);

export type AssignedFdmRule = {
  wall_thickness: string | null;
  draft_angle: string | null;
  nominal_radius: string | null;
  clearance: string | null;
  nozzle_diameter: string | null;
  polymer: string | null;
  fit_generation: string | null;
  fit_stale: boolean;
  assigned: boolean;
};

export function emptyAssignedRule(): AssignedFdmRule {
  return {
    wall_thickness: null,
    draft_angle: null,
    nominal_radius: null,
    clearance: null,
    nozzle_diameter: null,
    polymer: null,
    fit_generation: null,
    fit_stale: false,
    assigned: false,
  };
}

export function present(value: unknown): boolean {
  if (value === undefined || value === null) return false;
  if (typeof value === "string" && value.trim() === "") return false;
  return true;
}

/** Request override wins; otherwise use the named Fusion parameter expression. */
export function inheritExpression(override: unknown, ruleExpression: string | null): string | null {
  if (present(override)) return String(override);
  return ruleExpression;
}

export function isFitSensitiveFamily(family: string, subtype = ""): boolean {
  if (family === "retention" || family === "seam" || family === "seal" || family === "hardware") {
    return true;
  }
  return family === "boss" && /captive|heat_set|compression/.test(subtype);
}

export function inheritIntoParameters(
  family: string,
  subtype: string,
  params: Record<string, unknown>,
  rule: AssignedFdmRule,
): void {
  const setIfMissing = (key: string, expr: string | null): void => {
    if (!present(params[key]) && expr) params[key] = expr;
  };
  if (family === "reinforcement") {
    setIfMissing("height", rule.wall_thickness);
    setIfMissing("thickness", rule.wall_thickness);
    setIfMissing("draft_angle", rule.draft_angle);
    setIfMissing("root_fillet", rule.nominal_radius);
  } else if (family === "support") {
    setIfMissing("thickness", rule.wall_thickness);
    setIfMissing("draft_angle", rule.draft_angle);
  } else if (family === "operation" && (subtype === "shell" || subtype === "thicken" || subtype === "extrude")) {
    setIfMissing("thickness", rule.wall_thickness);
    setIfMissing("distance", rule.wall_thickness);
  } else if (family === "operation" && subtype === "draft") {
    setIfMissing("draft_angle", rule.draft_angle);
  }
  if (family === "boss") {
    setIfMissing("draft_angle", rule.draft_angle);
    setIfMissing("base_blend_radius", rule.nominal_radius);
  }
  if (family === "retention") {
    setIfMissing("beam_thickness", rule.wall_thickness);
    setIfMissing("root_fillet", rule.nominal_radius);
    setIfMissing("clearance", rule.clearance);
  }
  if (family === "seam") {
    setIfMissing("radial_clearance", rule.clearance);
    setIfMissing("draft_angle", rule.draft_angle);
  }
  if (family === "seal") {
    setIfMissing("clearance", rule.clearance);
  }
}

export function fitSensitiveClearanceRefusal(
  family: string,
  subtype: string,
  params: Record<string, unknown>,
  hardware: Record<string, unknown>,
  rule: AssignedFdmRule,
  sourced: boolean,
): [string, string, string] | null {
  if (!isFitSensitiveFamily(family, subtype)) return null;
  if (rule.fit_stale && !sourced) {
    return [
      "coupon-required",
      "Assigned polymer or nozzle changed; fit-sensitive values are stale until re-sourced or couponed.",
      "re-run the fit coupon or supply a sourced parameter",
    ];
  }
  const clearance = params.radial_clearance ?? params.clearance ?? hardware.across_flats;
  if ((family === "seam" || family === "retention" || family === "seal") && !present(clearance) && !sourced) {
    return [
      "coupon-required",
      "Fit-sensitive clearance is not sourced and no assigned FDM clearance exists.",
      "assign an FDM rule clearance, supply a sourced value, or record a coupon",
    ];
  }
  return null;
}

export function normalizePolymer(value: unknown): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  const upper = raw.toUpperCase();
  return POLYMERS.find((item) => item === upper) ?? raw;
}
