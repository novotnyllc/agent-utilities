/**
 * Frozen public type model for enclosure feature requests and results.
 *
 * Property names intentionally mirror the JSON wire contract (snake_case);
 * every as*() constructor validates untrusted input and rejects unknown
 * fields, so decoding cannot silently drop intent.
 */

import { EVIDENCE_CLASSES } from "./evidence.ts";

export const REFUSAL_TOKENS: ReadonlySet<string> = new Set([
  "unsupported-fusion-version",
  "enclosure-addin-not-installed",
  "extension-entitlement-required",
  "preview-api-unavailable",
  "native-feature-api-unavailable",
  "invalid-design-type",
  "unsaved-document",
  "target-not-found",
  "ambiguous-target",
  "assembly-context-required",
  "invalid-selection-type",
  "non-associative-selection",
  "selection-token-stale",
  "participant-body-ambiguity",
  "parameter-name-conflict",
  "invalid-parameter-expression",
  "seam-loop-open",
  "seam-nontangent-unsupported",
  "seam-self-intersection",
  "seam-segment-collapsed",
  "unsupported-nonplanar-corner",
  "insufficient-wall-thickness",
  "zero-thickness-result",
  "body-not-solid",
  "pattern-source-incompatible",
  "unsupported-conformal-cutout",
  "feature-create-failed",
  "timeline-unhealthy",
  "upstream-feature-missing",
  "cross-feature-cycle",
  "managed-dependent-exists",
  "manual-edit-prevents-update",
  "recipe-version-mismatch",
  "operation-not-safe-to-rebuild",
  "configuration-topology-changed",
  "configuration-feature-state-api-unavailable",
  "material-decision-unresolved",
  "coupon-required",
  "physical-proof-required",
]);

export const SELECTION_KINDS: ReadonlySet<string> = new Set([
  "component", "occurrence", "body", "face", "edge", "sketch",
  "profile", "point", "axis", "plane", "path", "managed_feature",
]);

export const OWNERSHIPS: ReadonlySet<string> = new Set([
  "source", "clearance", "fabrication", "design", "packing", "derived",
]);

export const ASSOCIATIVITIES: ReadonlySet<string> = new Set([
  "required", "preferred", "not-applicable",
]);

export const NORMAL_MODES: ReadonlySet<string> = new Set([
  "explicit-axis", "planar-face-normal", "surface-normal-at-point",
]);

export const RESULT_OPERATIONS: ReadonlySet<string> = new Set([
  "create", "edit", "delete", "inspect",
]);

export class EnclosureContractError extends Error {
  readonly refusalToken: string;

  constructor(message: string, refusalToken?: string) {
    const token = refusalToken ?? "feature-create-failed";
    if (!REFUSAL_TOKENS.has(token)) {
      throw new Error(`unknown refusal token: ${token}`);
    }
    super(message);
    this.name = "EnclosureContractError";
    this.refusalToken = token;
  }
}

export class QuantityError extends EnclosureContractError {
  constructor(message: string) {
    super(message, "invalid-parameter-expression");
    this.name = "QuantityError";
  }
}

export class SelectionError extends EnclosureContractError {
  constructor(message: string) {
    super(message, "invalid-selection-type");
    this.name = "SelectionError";
  }
}

export interface RecipeVersion {
  readonly recipe_id: string;
  readonly version: string;
  readonly minimum_fusion_build: string | null;
}

export interface Quantity {
  readonly expression: string | null;
  readonly value: number | null;
  readonly unit: string | null;
}

export interface EvidenceRef {
  readonly classification: string;
  readonly source_id: string | null;
  readonly confidence: string;
  readonly coupon_id: string | null;
  readonly invalidates_on: readonly string[];
}

export interface FeatureParameter {
  readonly key: string;
  readonly value: Quantity;
  readonly ownership: string;
  readonly evidence: EvidenceRef;
  readonly confirm_before_export: boolean;
  readonly physical_test_required: boolean;
}

export interface FeatureSelection {
  readonly role: string;
  readonly kind: string;
  readonly component_path: string;
  readonly entity_token: string;
  readonly expected_object_type: string;
  readonly name: string;
  readonly occurrence_path: string | null;
  readonly managed_feature_id: string | null;
  readonly associativity: string;
}

export interface PlacementFrame {
  readonly origin: FeatureSelection;
  readonly z_axis: FeatureSelection;
  readonly x_reference: FeatureSelection | null;
  readonly rotation: Quantity | null;
  readonly normal_mode: string;
}

export interface MaterialContext {
  readonly family: string | null;
  readonly formulation: string | null;
  readonly source_id: string | null;
  readonly confidence: string | null;
}

export interface FabricationContext {
  readonly process: string;
  readonly nozzle_diameter: Quantity | null;
  readonly extrusion_width: Quantity | null;
  readonly layer_height: Quantity | null;
  readonly perimeter_count: number | null;
  readonly preferred_orientation: PlacementFrame | null;
  readonly support_policy: string | null;
  readonly slicer_profile_ids: readonly string[];
}

export interface FeatureContext {
  readonly document_id: string;
  readonly component_path: string;
  readonly occurrence_path: string | null;
  readonly active_configuration: string | null;
  readonly material: MaterialContext;
  readonly fabrication: FabricationContext;
}

export interface EnclosureFeatureRequest {
  readonly request_id: string;
  readonly recipe: RecipeVersion;
  readonly context: FeatureContext;
  readonly selections: readonly FeatureSelection[];
  readonly parameters: readonly FeatureParameter[];
  readonly upstream_feature_ids: readonly string[];
}

export interface NativeEntityRef {
  readonly entity_token: string;
  readonly expected_object_type: string;
  readonly role: string;
  readonly component_path: string;
  readonly managed_feature_id: string | null;
}

export interface NativeObservation {
  readonly kind: string;
  readonly passed: boolean;
  readonly detail: string;
  readonly subject_entity_token: string | null;
}

export interface FeatureInstance {
  readonly feature_id: string;
  readonly recipe: RecipeVersion;
  readonly component_path: string;
  readonly parameter_namespace: string;
  readonly timeline_group_names: readonly string[];
  readonly native_entities: readonly NativeEntityRef[];
  readonly upstream_feature_ids: readonly string[];
  readonly configuration_binding: string;
}

export interface FeatureWarning {
  readonly token: string;
  readonly message: string;
  readonly evidence: EvidenceRef | null;
}

export interface FeatureRefusal {
  readonly token: string;
  readonly message: string;
  readonly fusion_message: string | null;
  readonly fusion_exception_type: string | null;
  readonly recovery: string;
  readonly residue: readonly NativeEntityRef[];
}

export interface FeatureResult {
  readonly operation: string;
  readonly instance: FeatureInstance | null;
  readonly created_or_changed: readonly NativeEntityRef[];
  readonly native_observations: readonly NativeObservation[];
  readonly warnings: readonly FeatureWarning[];
  readonly refusal: FeatureRefusal | null;
}

type Fields = Record<string, unknown>;

function record(value: unknown, label: string, allowed: readonly string[]): Fields {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new EnclosureContractError(`${label} must be an object`);
  }
  const data = value as Fields;
  const unknown = Object.keys(data).filter((key) => !allowed.includes(key)).sort();
  if (unknown.length > 0) {
    throw new EnclosureContractError(
      `${label} has unknown fields: ${unknown.join(", ")}`,
    );
  }
  return data;
}

function nonEmpty(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new EnclosureContractError(`${label} must be a non-empty string`);
  }
  return value;
}

function selectionRecord(value: unknown, allowed: readonly string[]): Fields {
  try {
    return record(value, "selection", allowed);
  } catch (error) {
    if (error instanceof EnclosureContractError) {
      throw new SelectionError(error.message);
    }
    throw error;
  }
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function bool(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new EnclosureContractError(`${label} must be a boolean`);
  }
  return value;
}

function strings(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) {
    throw new EnclosureContractError(`${label} must be a list`);
  }
  return value.map((entry, index) => nonEmpty(entry, `${label}[${index}]`));
}

export function asRecipeVersion(value: unknown): RecipeVersion {
  const data = record(value, "recipe version", [
    "recipe_id", "version", "minimum_fusion_build",
  ]);
  return Object.freeze({
    recipe_id: nonEmpty(data.recipe_id, "recipe_id"),
    version: nonEmpty(data.version, "version"),
    minimum_fusion_build: optionalString(data.minimum_fusion_build),
  });
}

export function asQuantity(value: unknown): Quantity {
  const data = record(value, "quantity", ["expression", "value", "unit"]);
  const hasExpression = data.expression !== null && data.expression !== undefined;
  const hasValue = data.value !== null && data.value !== undefined;
  if (hasExpression === hasValue) {
    throw new QuantityError("quantity needs exactly one of expression or value");
  }
  let normalizedValue: number | null = null;
  const unit = optionalString(data.unit);
  if (hasValue) {
    if (typeof data.value !== "number" || !Number.isFinite(data.value)) {
      throw new QuantityError("quantity value must be finite and numeric");
    }
    normalizedValue = data.value;
    if (unit === null || unit.length === 0) {
      throw new QuantityError("a numeric quantity requires an explicit unit");
    }
  }
  let expression: string | null = null;
  if (hasExpression) {
    if (typeof data.expression !== "string" || data.expression.trim().length === 0) {
      throw new QuantityError("quantity expression must be a non-empty string");
    }
    expression = data.expression;
  }
  return Object.freeze({expression, value: normalizedValue, unit});
}

export function asEvidenceRef(value: unknown): EvidenceRef {
  const data = record(value, "evidence", [
    "classification", "source_id", "confidence", "coupon_id", "invalidates_on",
  ]);
  const classification = nonEmpty(data.classification, "classification");
  if (!EVIDENCE_CLASSES.has(classification)) {
    throw new EnclosureContractError(
      `unknown evidence classification: ${classification}`,
      "physical-proof-required",
    );
  }
  return Object.freeze({
    classification,
    source_id: optionalString(data.source_id),
    confidence: nonEmpty(data.confidence, "confidence"),
    coupon_id: optionalString(data.coupon_id),
    invalidates_on: Object.freeze(strings(data.invalidates_on ?? [], "invalidates_on")),
  });
}

export function asFeatureParameter(value: unknown): FeatureParameter {
  const data = record(value, "parameter", [
    "key", "value", "ownership", "evidence",
    "confirm_before_export", "physical_test_required",
  ]);
  const ownership = nonEmpty(data.ownership, "parameter ownership");
  if (!OWNERSHIPS.has(ownership)) {
    throw new EnclosureContractError(`unknown parameter ownership: ${ownership}`);
  }
  return Object.freeze({
    key: nonEmpty(data.key, "parameter key"),
    value: asQuantity(data.value),
    ownership,
    evidence: asEvidenceRef(data.evidence),
    confirm_before_export: bool(data.confirm_before_export, "confirm_before_export"),
    physical_test_required: bool(data.physical_test_required, "physical_test_required"),
  });
}

export function asFeatureSelection(value: unknown): FeatureSelection {
  const data = selectionRecord(value, [
    "role", "kind", "component_path", "entity_token", "expected_object_type",
    "name", "occurrence_path", "managed_feature_id", "associativity",
  ]);
  const kind = nonEmpty(data.kind, "selection kind");
  if (!SELECTION_KINDS.has(kind)) {
    throw new SelectionError(`unknown selection kind: ${kind}`);
  }
  const associativity = data.associativity === undefined || data.associativity === null
    ? "required"
    : nonEmpty(data.associativity, "associativity");
  if (!ASSOCIATIVITIES.has(associativity)) {
    throw new SelectionError(`unknown associativity: ${associativity}`);
  }
  return Object.freeze({
    role: nonEmpty(data.role, "selection role"),
    kind,
    component_path: nonEmpty(data.component_path, "component_path"),
    entity_token: optionalString(data.entity_token) ?? "",
    expected_object_type: optionalString(data.expected_object_type) ?? "",
    name: optionalString(data.name) ?? "",
    occurrence_path: optionalString(data.occurrence_path),
    managed_feature_id: optionalString(data.managed_feature_id),
    associativity,
  });
}

export function asPlacementFrame(value: unknown): PlacementFrame {
  const data = record(value, "placement frame", [
    "origin", "z_axis", "x_reference", "rotation", "normal_mode",
  ]);
  const normalMode = nonEmpty(data.normal_mode, "normal_mode");
  if (!NORMAL_MODES.has(normalMode)) {
    throw new SelectionError(`unknown placement normal mode: ${normalMode}`);
  }
  return Object.freeze({
    origin: asFeatureSelection(data.origin),
    z_axis: asFeatureSelection(data.z_axis),
    x_reference: data.x_reference ? asFeatureSelection(data.x_reference) : null,
    rotation: data.rotation ? asQuantity(data.rotation) : null,
    normal_mode: normalMode,
  });
}

export function asMaterialContext(value: unknown): MaterialContext {
  const data = record(value, "material context", [
    "family", "formulation", "source_id", "confidence",
  ]);
  return Object.freeze({
    family: optionalString(data.family),
    formulation: optionalString(data.formulation),
    source_id: optionalString(data.source_id),
    confidence: optionalString(data.confidence),
  });
}

export function asFabricationContext(value: unknown): FabricationContext {
  const data = record(value, "fabrication context", [
    "process", "nozzle_diameter", "extrusion_width", "layer_height",
    "perimeter_count", "preferred_orientation", "support_policy",
    "slicer_profile_ids",
  ]);
  const process = nonEmpty(data.process, "fabrication process");
  if (process !== "fff") {
    throw new EnclosureContractError(`unsupported fabrication process: ${process}`);
  }
  const perimeter = data.perimeter_count;
  if (perimeter !== null && perimeter !== undefined) {
    if (typeof perimeter !== "number" || !Number.isInteger(perimeter) || perimeter < 0) {
      throw new EnclosureContractError("perimeter_count must be a non-negative integer");
    }
  }
  return Object.freeze({
    process,
    nozzle_diameter: data.nozzle_diameter ? asQuantity(data.nozzle_diameter) : null,
    extrusion_width: data.extrusion_width ? asQuantity(data.extrusion_width) : null,
    layer_height: data.layer_height ? asQuantity(data.layer_height) : null,
    perimeter_count: typeof perimeter === "number" ? perimeter : null,
    preferred_orientation: data.preferred_orientation
      ? asPlacementFrame(data.preferred_orientation)
      : null,
    support_policy: optionalString(data.support_policy),
    slicer_profile_ids: Object.freeze(strings(data.slicer_profile_ids ?? [], "slicer_profile_ids")),
  });
}

export function asFeatureContext(value: unknown): FeatureContext {
  const data = record(value, "context", [
    "document_id", "component_path", "occurrence_path",
    "active_configuration", "material", "fabrication",
  ]);
  return Object.freeze({
    document_id: nonEmpty(data.document_id, "document_id"),
    component_path: nonEmpty(data.component_path, "component_path"),
    occurrence_path: optionalString(data.occurrence_path),
    active_configuration: optionalString(data.active_configuration),
    material: asMaterialContext(data.material),
    fabrication: asFabricationContext(data.fabrication),
  });
}

export function asEnclosureFeatureRequest(value: unknown): EnclosureFeatureRequest {
  const data = record(value, "request", [
    "request_id", "recipe", "context", "selections", "parameters",
    "upstream_feature_ids",
  ]);
  if (!Array.isArray(data.selections) || !Array.isArray(data.parameters)) {
    throw new EnclosureContractError("selections and parameters must be lists");
  }
  return Object.freeze({
    request_id: nonEmpty(data.request_id, "request_id"),
    recipe: asRecipeVersion(data.recipe),
    context: asFeatureContext(data.context),
    selections: Object.freeze(data.selections.map(asFeatureSelection)),
    parameters: Object.freeze(data.parameters.map(asFeatureParameter)),
    upstream_feature_ids: Object.freeze(strings(data.upstream_feature_ids ?? [], "upstream_feature_ids")),
  });
}

export function asNativeEntityRef(value: unknown): NativeEntityRef {
  const data = record(value, "native entity", [
    "entity_token", "expected_object_type", "role", "component_path",
    "managed_feature_id",
  ]);
  return Object.freeze({
    entity_token: nonEmpty(data.entity_token, "entity_token"),
    expected_object_type: nonEmpty(data.expected_object_type, "object type"),
    role: nonEmpty(data.role, "entity role"),
    component_path: nonEmpty(data.component_path, "component_path"),
    managed_feature_id: optionalString(data.managed_feature_id),
  });
}

export function asNativeObservation(value: unknown): NativeObservation {
  const data = record(value, "native observation", [
    "kind", "passed", "detail", "subject_entity_token",
  ]);
  return Object.freeze({
    kind: nonEmpty(data.kind, "observation kind"),
    passed: bool(data.passed, "passed"),
    detail: nonEmpty(data.detail, "observation detail"),
    subject_entity_token: optionalString(data.subject_entity_token),
  });
}

export function asFeatureInstance(value: unknown): FeatureInstance {
  const data = record(value, "feature instance", [
    "feature_id", "recipe", "component_path", "parameter_namespace",
    "timeline_group_names", "native_entities", "upstream_feature_ids",
    "configuration_binding",
  ]);
  return Object.freeze({
    feature_id: nonEmpty(data.feature_id, "feature_id"),
    recipe: asRecipeVersion(data.recipe),
    component_path: nonEmpty(data.component_path, "instance component_path"),
    parameter_namespace: nonEmpty(data.parameter_namespace, "parameter_namespace"),
    timeline_group_names: Object.freeze(strings(data.timeline_group_names ?? [], "timeline_group_names")),
    native_entities: Object.freeze(
      (Array.isArray(data.native_entities) ? data.native_entities : []).map(asNativeEntityRef),
    ),
    upstream_feature_ids: Object.freeze(strings(data.upstream_feature_ids ?? [], "upstream ids")),
    configuration_binding: nonEmpty(data.configuration_binding, "configuration_binding"),
  });
}

export function asFeatureWarning(value: unknown): FeatureWarning {
  const data = record(value, "warning", ["token", "message", "evidence"]);
  return Object.freeze({
    token: nonEmpty(data.token, "warning token"),
    message: nonEmpty(data.message, "warning message"),
    evidence: data.evidence ? asEvidenceRef(data.evidence) : null,
  });
}

export function asFeatureRefusal(value: unknown): FeatureRefusal {
  const data = record(value, "refusal", [
    "token", "message", "fusion_message", "fusion_exception_type", "recovery",
    "residue",
  ]);
  const token = nonEmpty(data.token, "refusal token");
  if (!REFUSAL_TOKENS.has(token)) {
    throw new EnclosureContractError(`unknown refusal token: ${token}`);
  }
  return Object.freeze({
    token,
    message: nonEmpty(data.message, "refusal message"),
    fusion_message: optionalString(data.fusion_message),
    fusion_exception_type: optionalString(data.fusion_exception_type),
    recovery: nonEmpty(data.recovery, "recovery guidance"),
    residue: Object.freeze(
      (Array.isArray(data.residue) ? data.residue : []).map(asNativeEntityRef),
    ),
  });
}

export function asFeatureResult(value: unknown): FeatureResult {
  const data = record(value, "result", [
    "operation", "instance", "created_or_changed", "native_observations",
    "warnings", "refusal",
  ]);
  const operation = nonEmpty(data.operation, "operation");
  if (!RESULT_OPERATIONS.has(operation)) {
    throw new EnclosureContractError(`unknown result operation: ${operation}`);
  }
  return Object.freeze({
    operation,
    instance: data.instance ? asFeatureInstance(data.instance) : null,
    created_or_changed: Object.freeze(
      (Array.isArray(data.created_or_changed) ? data.created_or_changed : []).map(asNativeEntityRef),
    ),
    native_observations: Object.freeze(
      (Array.isArray(data.native_observations) ? data.native_observations : []).map(asNativeObservation),
    ),
    warnings: Object.freeze(
      (Array.isArray(data.warnings) ? data.warnings : []).map(asFeatureWarning),
    ),
    refusal: data.refusal ? asFeatureRefusal(data.refusal) : null,
  });
}
