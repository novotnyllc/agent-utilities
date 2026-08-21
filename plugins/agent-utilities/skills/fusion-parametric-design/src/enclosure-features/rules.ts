/**
 * Deterministic loader for the shipped enclosure rule and preset catalog.
 *
 * A numeric rule may only enter Fusion as a user parameter when it carries
 * provenance, confidence, default/export policy, and all four process
 * invalidation flags. The loader refuses anything less.
 */

import fs from "node:fs";

import {
  EVIDENCE_CLASSES,
  INVALIDATION_FLAGS,
} from "./evidence.ts";

export const RULE_SCHEMA_VERSION = 1;
const REQUIRED_METADATA_FIELDS = [
  "units",
  "classification",
  "source_id",
  "confidence",
  "safe_as_default",
  "confirm_before_export",
  ...INVALIDATION_FLAGS,
] as const;

export interface Rule {
  readonly rule_id: string;
  readonly value_expression: string | null;
  readonly value_number: number | null;
  readonly units: string | null;
  readonly classification: string;
  readonly source_id: string | null;
  readonly confidence: string;
  readonly safe_as_default: boolean;
  readonly confirm_before_export: boolean;
  readonly invalidated_by_material_change: boolean;
  readonly invalidated_by_nozzle_change: boolean;
  readonly invalidated_by_layer_height_change: boolean;
  readonly invalidated_by_orientation_change: boolean;
  readonly coupon_requirement: string | null;
  /** "rule" or "preset_parameter". */
  readonly kind: string;
}

export interface RuleCatalog {
  readonly schema_version: number;
  readonly entries: readonly Rule[];
}

export class RuleCatalogError extends Error {}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validateRule(
  ruleId: string,
  rawValue: unknown,
  kind: string,
): Rule {
  if (!isRecord(rawValue)) {
    throw new RuleCatalogError(`${kind} ${JSON.stringify(ruleId)} must be an object`);
  }
  const allowed = ["description", "expression", "value", ...REQUIRED_METADATA_FIELDS, "coupon_requirement"];
  const unknown = Object.keys(rawValue)
    .filter((key) => !allowed.includes(key))
    .sort();
  if (unknown.length > 0) {
    throw new RuleCatalogError(`${kind} ${ruleId} has unknown fields: ${unknown.join(", ")}`);
  }
  const expression = rawValue.expression;
  const value = rawValue.value;
  const hasExpression = expression !== null && expression !== undefined;
  const hasValue = value !== null && value !== undefined;
  if (hasExpression === hasValue) {
    throw new RuleCatalogError(`${kind} ${ruleId} needs exactly one of value or expression`);
  }
  const units = rawValue.units;
  let normalizedUnits: string | null = null;
  if (hasValue) {
    if (typeof value !== "number") {
      throw new RuleCatalogError(`${kind} ${ruleId} value must be numeric`);
    }
    if (!Number.isFinite(value)) {
      throw new RuleCatalogError(`${kind} ${ruleId} value must be finite`);
    }
    if (typeof units !== "string" || units.length === 0) {
      throw new RuleCatalogError(`${kind} ${ruleId} numeric value requires explicit units`);
    }
    normalizedUnits = units;
  } else if (units !== null && units !== undefined && typeof units !== "string") {
    throw new RuleCatalogError(`${kind} ${ruleId} units must be a string`);
  } else if (units !== null && units !== undefined) {
    normalizedUnits = units;
  }
  const classification = rawValue.classification;
  if (typeof classification !== "string" || !EVIDENCE_CLASSES.has(classification)) {
    throw new RuleCatalogError(`${kind} ${ruleId} lacks a valid evidence classification`);
  }
  for (const field of ["source_id", "confidence"] as const) {
    const entry = rawValue[field];
    if (typeof entry !== "string" || entry.length === 0) {
      throw new RuleCatalogError(`${kind} ${ruleId} requires non-empty ${field}`);
    }
  }
  const couponRequirement = rawValue.coupon_requirement;
  if (
    couponRequirement !== null
    && couponRequirement !== undefined
    && typeof couponRequirement !== "string"
  ) {
    throw new RuleCatalogError(`${kind} ${ruleId} coupon_requirement must be a string or null`);
  }
  const flags = {} as Record<(typeof INVALIDATION_FLAGS)[number], boolean>;
  for (const flag of INVALIDATION_FLAGS) {
    if (typeof rawValue[flag] !== "boolean") {
      throw new RuleCatalogError(`${kind} ${ruleId} requires boolean ${flag}`);
    }
    flags[flag] = rawValue[flag] as boolean;
  }
  for (const field of ["safe_as_default", "confirm_before_export"] as const) {
    if (typeof rawValue[field] !== "boolean") {
      throw new RuleCatalogError(`${kind} ${ruleId} requires boolean ${field}`);
    }
  }
  return Object.freeze({
    rule_id: ruleId,
    value_expression: typeof expression === "string" ? expression : null,
    value_number: hasValue ? Number(value) : null,
    units: normalizedUnits,
    classification,
    source_id: typeof rawValue.source_id === "string" ? rawValue.source_id : null,
    confidence: rawValue.confidence as string,
    safe_as_default: rawValue.safe_as_default as boolean,
    confirm_before_export: rawValue.confirm_before_export as boolean,
    ...flags,
    coupon_requirement: typeof couponRequirement === "string" ? couponRequirement : null,
    kind,
  });
}

/** Load and validate the shipped catalog; deterministic by sorted keys. */
export function loadRuleCatalog(path: string): RuleCatalog {
  let data: unknown;
  try {
    data = JSON.parse(fs.readFileSync(path, {encoding: "utf8"}));
  } catch (error) {
    throw new RuleCatalogError(`cannot read valid rule catalog: ${(error as Error).message}`);
  }
  if (!isRecord(data)) {
    throw new RuleCatalogError("rule catalog must be a JSON object");
  }
  if (data.schema_version !== RULE_SCHEMA_VERSION) {
    throw new RuleCatalogError("rule catalog schema_version must be 1");
  }
  const rulesSection = data.rules;
  const presetsSection = data.named_presets;
  if (!Array.isArray(rulesSection) || !Array.isArray(presetsSection)) {
    throw new RuleCatalogError("rule catalog needs rules and named_presets lists");
  }
  const entries: Rule[] = [];
  const seenIds = new Set<string>();
  for (const rawRule of rulesSection) {
    if (!isRecord(rawRule) || typeof rawRule.rule_id !== "string") {
      throw new RuleCatalogError("every rule needs a string rule_id");
    }
    const ruleId = rawRule.rule_id;
    if (seenIds.has(ruleId)) {
      throw new RuleCatalogError(`duplicate rule id: ${ruleId}`);
    }
    seenIds.add(ruleId);
    const payload = {...rawRule};
    delete payload.rule_id;
    entries.push(validateRule(ruleId, payload, "rule"));
  }
  for (const rawPreset of presetsSection) {
    if (!isRecord(rawPreset) || typeof rawPreset.preset_id !== "string") {
      throw new RuleCatalogError("every preset needs a string preset_id");
    }
    const presetId = rawPreset.preset_id;
    const parameters = rawPreset.parameters;
    if (!Array.isArray(parameters)) {
      throw new RuleCatalogError(`preset '${presetId}' needs a parameters list`);
    }
    for (const rawParameter of parameters) {
      if (!isRecord(rawParameter) || typeof rawParameter.rule_id !== "string") {
        throw new RuleCatalogError(`preset '${presetId}' parameter needs a rule_id`);
      }
      const payload = {...rawParameter};
      const parameterRuleId = payload.rule_id as string;
      delete payload.rule_id;
      entries.push(validateRule(`${presetId}/${parameterRuleId}`, payload, "preset_parameter"));
    }
  }
  // Sorted output keeps loading byte-stable across hosts.
  entries.sort((left, right) =>
    left.kind.localeCompare(right.kind) || left.rule_id.localeCompare(right.rule_id),
  );
  return {schema_version: RULE_SCHEMA_VERSION, entries};
}
