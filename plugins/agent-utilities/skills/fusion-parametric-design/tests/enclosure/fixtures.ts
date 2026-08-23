import type {
  EnclosureFeatureRequest,
  FeatureResult,
} from "../../src/enclosure-features/contracts.ts";

export function fixtureRequest(): EnclosureFeatureRequest {
  return {
    request_id: "req-1",
    recipe: {recipe_id: "boss.support", version: "1.0.0", minimum_fusion_build: null},
    context: {
      document_id: "doc",
      component_path: "root",
      occurrence_path: null,
      active_configuration: null,
      material: {family: "PETG", formulation: null, source_id: null, confidence: null},
      fabrication: {
        process: "fff",
        nozzle_diameter: {expression: null, value: 0.4, unit: "mm"},
        extrusion_width: null,
        layer_height: null,
        perimeter_count: 3,
        preferred_orientation: null,
        support_policy: null,
        slicer_profile_ids: ["generic"],
      },
    },
    selections: [{
      role: "target_body", kind: "body", component_path: "root",
      entity_token: "tok", expected_object_type: "BRepBody", name: "body",
      occurrence_path: null, managed_feature_id: null, associativity: "required",
    }],
    parameters: [{
      key: "wall", ownership: "design",
      value: {expression: "des_wall", value: null, unit: null},
      evidence: {
        classification: "user-preference", source_id: "user", confidence: "user-owned",
        coupon_id: null, invalidates_on: [],
      },
      confirm_before_export: true, physical_test_required: false,
    }],
    upstream_feature_ids: ["upstream-1"],
  };
}

export function fixtureResult(): FeatureResult {
  return {
    operation: "create",
    instance: {
      feature_id: "fid",
      recipe: {recipe_id: "boss.support", version: "1.0.0", minimum_fusion_build: null},
      component_path: "root",
      parameter_namespace: "ns",
      timeline_group_names: ["Enclosure / Boss / abc123"],
      native_entities: [],
      upstream_feature_ids: [],
      configuration_binding: "base",
    },
    created_or_changed: [],
    native_observations: [{
      kind: "solid", passed: true, detail: "isSolid true", subject_entity_token: null,
    }],
    warnings: [{token: "coupon-required", message: "print coupon", evidence: null}],
    refusal: null,
  };
}
