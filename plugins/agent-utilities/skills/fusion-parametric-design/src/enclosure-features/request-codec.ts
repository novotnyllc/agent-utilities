/**
 * Versioned JSON wire codec for enclosure feature requests and results.
 *
 * Unknown fields are rejected so schema drift fails closed at the boundary
 * instead of silently dropping intent inside Fusion.
 */

import {
  asEnclosureFeatureRequest,
  asFeatureResult,
  type EnclosureFeatureRequest,
  type FeatureInstance,
  type FeatureRefusal,
  type FeatureResult,
  type FeatureWarning,
  type FabricationContext,
  type FeatureContext,
  type MaterialContext,
  type NativeEntityRef,
  type NativeObservation,
  type PlacementFrame,
} from "./contracts.ts";

export const WIRE_SCHEMA_VERSION = 1;

export class WireCodecError extends Error {}

type WireObject = Record<string, unknown>;

function isRecord(value: unknown): value is WireObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function rejectUnknown(data: unknown, allowed: readonly string[], label: string): void {
  if (!isRecord(data)) {
    throw new WireCodecError(`${label} must be an object`);
  }
  const unknown = Object.keys(data)
    .filter((field) => !allowed.includes(field))
    .sort();
  if (unknown.length > 0) {
    throw new WireCodecError(`${label} has unknown fields: ${unknown.join(", ")}`);
  }
}

/** JSON.stringify with recursively sorted object keys, like json.dumps(sort_keys=True). */
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (!isRecord(value)) {
    return JSON.stringify(value);
  }
  const body = Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
    .join(",");
  return `{${body}}`;
}

function parsePayload(payload: string | Buffer | Uint8Array, label: string): unknown {
  try {
    const text = typeof payload === "string"
      ? payload
      : Buffer.from(payload).toString("utf8");
    return JSON.parse(text);
  } catch (error) {
    throw new WireCodecError(`${label} payload is not valid JSON: ${(error as Error).message}`);
  }
}

const REQUEST_FIELDS = [
  "schema_version", "request_id", "recipe", "context", "selections",
  "parameters", "upstream_feature_ids",
] as const;

/** Encode one request with a versioned, deterministic wire representation. */
export function encodeRequest(request: EnclosureFeatureRequest): string {
  return stableStringify({
    schema_version: WIRE_SCHEMA_VERSION,
    request_id: request.request_id,
    recipe: {...request.recipe},
    context: {
      document_id: request.context.document_id,
      component_path: request.context.component_path,
      occurrence_path: request.context.occurrence_path,
      active_configuration: request.context.active_configuration,
      material: {...request.context.material},
      fabrication: {
        process: request.context.fabrication.process,
        nozzle_diameter: request.context.fabrication.nozzle_diameter,
        extrusion_width: request.context.fabrication.extrusion_width,
        layer_height: request.context.fabrication.layer_height,
        perimeter_count: request.context.fabrication.perimeter_count,
        preferred_orientation: request.context.fabrication.preferred_orientation,
        support_policy: request.context.fabrication.support_policy,
        slicer_profile_ids: [...request.context.fabrication.slicer_profile_ids],
      },
    },
    selections: request.selections.map((selection) => ({...selection})),
    parameters: request.parameters.map((parameter) => ({
      ...parameter,
      value: {...parameter.value},
      evidence: {
        ...parameter.evidence,
        invalidates_on: [...parameter.evidence.invalidates_on],
      },
    })),
    upstream_feature_ids: [...request.upstream_feature_ids],
  });
}

/** Decode and validate exactly one versioned request envelope. */
export function decodeRequest(
  payload: string | Buffer | Uint8Array,
): EnclosureFeatureRequest {
  const data = parsePayload(payload, "request");
  rejectUnknown(data, REQUEST_FIELDS, "request");
  const recordData = data as WireObject;
  if (recordData.schema_version !== WIRE_SCHEMA_VERSION) {
    throw new WireCodecError("request schema_version must be 1");
  }
  rejectUnknown(recordData.context, [
    "document_id", "component_path", "occurrence_path",
    "active_configuration", "material", "fabrication",
  ], "context");
  rejectUnknown(recordData.recipe, [
    "recipe_id", "version", "minimum_fusion_build",
  ], "recipe");
  if (
    !Array.isArray(recordData.selections)
    || !Array.isArray(recordData.parameters)
  ) {
    throw new WireCodecError("selections and parameters must be lists");
  }
  if (!Array.isArray(recordData.upstream_feature_ids)) {
    throw new WireCodecError("upstream_feature_ids must be a list");
  }
  return asEnclosureFeatureRequest({
    request_id: recordData.request_id,
    recipe: recordData.recipe,
    context: recordData.context,
    selections: recordData.selections,
    parameters: recordData.parameters,
    upstream_feature_ids: recordData.upstream_feature_ids,
  });
}

const RESULT_FIELDS = [
  "schema_version", "operation", "instance", "created_or_changed",
  "native_observations", "warnings", "refusal",
] as const;

/** Encode one result with the same versioned envelope discipline. */
export function encodeResult(result: FeatureResult): string {
  return stableStringify({
    schema_version: WIRE_SCHEMA_VERSION,
    operation: result.operation,
    instance: result.instance,
    created_or_changed: result.created_or_changed,
    native_observations: result.native_observations,
    warnings: result.warnings,
    refusal: result.refusal,
  });
}

/** Decode and validate exactly one versioned result envelope. */
export function decodeResult(
  payload: string | Buffer | Uint8Array,
): FeatureResult {
  const data = parsePayload(payload, "result") as WireObject;
  rejectUnknown(data, RESULT_FIELDS, "result");
  if (data.schema_version !== WIRE_SCHEMA_VERSION) {
    throw new WireCodecError("result schema_version must be 1");
  }
  return asFeatureResult({
    operation: data.operation,
    instance: data.instance ?? null,
    created_or_changed: Array.isArray(data.created_or_changed) ? data.created_or_changed : [],
    native_observations: Array.isArray(data.native_observations) ? data.native_observations : [],
    warnings: Array.isArray(data.warnings) ? data.warnings : [],
    refusal: data.refusal ?? null,
  });
}

// Keep the domain types importable from the codec without widening its API.
export type {
  EnclosureFeatureRequest,
  FabricationContext,
  FeatureContext,
  FeatureInstance,
  FeatureRefusal,
  FeatureResult,
  FeatureWarning,
  MaterialContext,
  NativeEntityRef,
  NativeObservation,
  PlacementFrame,
};
