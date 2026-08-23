/**
 * Direct-result inspection for managed enclosure features.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/inspect.py.
 */

import { adsk } from "@adsk/fas";

type Any = any;


/** Wire-format view with snake_case keys, matching the Python dataclass field names. */
export interface InspectionStateWire {
  state: string;
  feature_health: string;
  body_exists: boolean;
  body_is_solid: boolean | null;
  expected_body_count: number | null;
  actual_body_count: number | null;
  observations: string[];
}

export class InspectionState {
  state: string = "managed-intact";
  featureHealth: string = "unknown";
  bodyExists: boolean = true;
  bodyIsSolid: boolean | null = null;
  expectedBodyCount: number | null = null;
  actualBodyCount: number | null = null;
  observations: string[] = [];

  constructor(init?: Partial<Pick<InspectionState, "expectedBodyCount">>) {
    if (init?.expectedBodyCount !== undefined) {
      this.expectedBodyCount = init.expectedBodyCount;
    }
  }

  toWire(): InspectionStateWire {
    return {
      state: this.state,
      feature_health: this.featureHealth,
      body_exists: this.bodyExists,
      body_is_solid: this.bodyIsSolid,
      expected_body_count: this.expectedBodyCount,
      actual_body_count: this.actualBodyCount,
      observations: [...this.observations],
    };
  }
}

export function classifyInspection(
  paramEdited: boolean = false,
  nativeEdited: boolean = false,
  definitionDiverged: boolean = false,
  objectsMissing: boolean = false,
): string {
  if (objectsMissing) return "managed-object-missing";
  if (definitionDiverged) return "managed-definition-diverged";
  if (nativeEdited) return "managed-native-edit-observed";
  if (paramEdited) return "managed-parameter-edited";
  return "managed-intact";
}

function healthOk(): Any {
  try {
    return adsk.fusion.FeatureHealthStates.OKFeatureHealthState;
  } catch {
    return "ok";
  }
}

function getRootComponent(): Any {
  try {
    const app = adsk.core.Application.get();
    const design = app?.activeDocument?.design ?? null;
    return design ? design.rootComponent : null;
  } catch {
    return null;
  }
}

export function inspectDirectResult(
  createdFeatures: Any[],
  targetBody: Any,
  expectedBodyCount?: number | null,
): InspectionState {
  const state = new InspectionState(
    expectedBodyCount !== undefined ? { expectedBodyCount } : undefined);
  const ok = healthOk();

  const unhealthy: string[] = [];
  for (const feat of createdFeatures) {
    const health = feat?.healthState ?? null;
    if (health !== null && health !== undefined && health !== ok) {
      unhealthy.push(feat?.name ?? "<unnamed>");
    }
  }
  state.featureHealth = unhealthy.length > 0 ? "unhealthy" : "ok";
  if (unhealthy.length > 0) {
    state.observations.push("Unhealthy features detected.");
  }

  if (targetBody !== null && targetBody !== undefined) {
    state.bodyExists = !targetBody.isDeleted;
    if (state.bodyExists) {
      state.bodyIsSolid = targetBody.isSolid ?? null;
      if (state.bodyIsSolid === false) {
        state.observations.push("Target body is not solid.");
      }
    }
  } else {
    state.bodyExists = false;
    state.observations.push("Target body reference missing.");
  }

  if (state.expectedBodyCount !== null && state.expectedBodyCount !== undefined) {
    const root = getRootComponent();
    if (root !== null && root !== undefined) {
      state.actualBodyCount = root.bRepBodies.count;
      if (state.actualBodyCount !== state.expectedBodyCount) {
        state.observations.push(
          `Expected ${state.expectedBodyCount} bodies, found ${state.actualBodyCount}.`);
      }
    }
  }

  if (!state.bodyExists) {
    state.state = "managed-object-missing";
  } else if (state.featureHealth !== "ok") {
    state.state = "managed-native-edit-observed";
  } else if (state.bodyIsSolid === false) {
    state.state = "managed-definition-diverged";
  }
  return state;
}
