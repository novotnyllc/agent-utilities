/**
 * Managed feature identity, attribute stamping, and entity reacquisition.
 *
 * Identity is UUID + 6-char display suffix. Attributes live in the
 * fusion_parametric_design group. Reacquisition follows topology rules 1-7.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/identity.py.
 */

import { adsk } from "@adsk/fas";
import { randomUUID } from "crypto";

type Any = any;


export const ATTRIBUTE_GROUP = "fusion_parametric_design";

export const ATTRIBUTE_KEYS: readonly string[] = [
  "enclosure_feature_id",
  "enclosure_recipe_id",
  "enclosure_recipe_version",
  "enclosure_role",
  "enclosure_parameter_namespace",
  "enclosure_upstream_ids",
] as const;

export const PARAM_PREFIXES: Readonly<Record<string, string>> = {
  "source": "src_ef_",
  "clearance": "clr_ef_",
  "fabrication": "fab_ef_",
  "design": "des_ef_",
  "packing": "pak_ef_",
  "derived": "calc_ef_",
};

export interface ManagedIdentity {
  readonly featureId: string;
  readonly displaySuffix: string;
  readonly recipeId: string;
  readonly recipeVersion: string;
  readonly parameterNamespace: string;
  readonly upstreamIds: readonly string[];
}

/** Wire-format view with snake_case keys, matching the Python dataclass field names. */
export interface ManagedIdentityWire {
  readonly feature_id: string;
  readonly display_suffix: string;
  readonly recipe_id: string;
  readonly recipe_version: string;
  readonly parameter_namespace: string;
  readonly upstream_ids: readonly string[];
}

export function identityRole(identity: Pick<ManagedIdentity, "recipeId">): string {
  return identity.recipeId.includes(".")
    ? identity.recipeId.split(".")[0]
    : identity.recipeId;
}

function identityToWire(identity: ManagedIdentity): ManagedIdentityWire {
  return {
    feature_id: identity.featureId,
    display_suffix: identity.displaySuffix,
    recipe_id: identity.recipeId,
    recipe_version: identity.recipeVersion,
    parameter_namespace: identity.parameterNamespace,
    upstream_ids: [...identity.upstreamIds],
  };
}

void identityToWire; // exported shape kept for serialization-boundary parity

export function allocateIdentity(
  recipeId: string,
  recipeVersion: string,
  upstreamIds: readonly string[] = [],
): ManagedIdentity {
  const fid = randomUUID();
  const suffix = fid.replace(/-/g, "").slice(0, 6);
  return {
    featureId: fid,
    displaySuffix: suffix,
    recipeId,
    recipeVersion,
    parameterNamespace: suffix,
    upstreamIds: [...upstreamIds],
  };
}

/** Lookup probe: featureId is the SEARCH KEY, not a new UUID. */
export function probeIdentity(featureId: string): ManagedIdentity {
  return {
    featureId,
    displaySuffix: "",
    recipeId: "",
    recipeVersion: "",
    parameterNamespace: "",
    upstreamIds: [],
  };
}

export function stampAttributes(entity: Any, identity: ManagedIdentity, role: string = ""): void {
  /** Stamp managed attributes onto a Fusion entity. No-op if entity has no attributes. */
  const attrs = entity?.attributes ?? null;
  if (attrs === null || attrs === undefined) {
    return;
  }
  const values: Record<string, string> = {
    enclosure_feature_id: identity.featureId,
    enclosure_recipe_id: identity.recipeId,
    enclosure_recipe_version: identity.recipeVersion,
    enclosure_role: role || identityRole(identity),
    enclosure_parameter_namespace: identity.parameterNamespace,
    enclosure_upstream_ids:
      identity.upstreamIds.length > 0 ? identity.upstreamIds.join(",") : "",
  };
  for (const [key, val] of Object.entries(values)) {
    if (!attrs.itemByName(ATTRIBUTE_GROUP, key)) {
      attrs.add(ATTRIBUTE_GROUP, key, val);
    }
  }
  void adsk; // adsk referenced for API-parity; direct calls happen through the entity proxy
}

export function findManagedEntities(
  component: Any,
  identity: ManagedIdentity,
  expectedRole: string = "",
): Any[] {
  /** Search component for entities with the managed feature ID and role.
   * Callers enforce exactly-one-match per topology rule 3. */
  const results: Any[] = [];
  const roleFilter = expectedRole || identityRole(identity);
  const collNames = [
    "bRepBodies", "sketches", "constructionPlanes",
    "constructionAxes", "constructionPoints", "features",
  ];
  for (const collName of collNames) {
    const coll = component?.[collName] ?? null;
    if (coll === null || coll === undefined) {
      continue;
    }
    for (let i = 0; i < coll.count; i++) {
      const obj = coll.item(i);
      const attrs = obj?.attributes ?? null;
      if (attrs === null || attrs === undefined) {
        continue;
      }
      const fid = attrs.itemByName(ATTRIBUTE_GROUP, "enclosure_feature_id");
      const role = attrs.itemByName(ATTRIBUTE_GROUP, "enclosure_role");
      if (fid && fid.value === identity.featureId) {
        if (!roleFilter || (role && role.value === roleFilter)) {
          results.push(obj);
        }
      }
    }
  }
  return results;
}

export function acquireEntity(
  token: string,
  identity: ManagedIdentity,
  expectedType: string,
  component: Any,
  expectedRole: string = "",
): [Any | null, string] {
  /** Reacquire entity per topology policy rules 1-7. */
  let entity: Any | null = null;
  if (token) {
    try {
      const design = component?.parentDesign ?? null;
      if (design !== null && design !== undefined) {
        entity = design.findEntityByToken(token);
      }
    } catch {
      return [null, "selection-token-stale"];
    }
  }

  if (entity !== null && entity !== undefined) {
    if (
      expectedType &&
      typeof entity.objectType === "string" &&
      !entity.objectType.includes(expectedType)
    ) {
      entity = null;
    } else if (
      component !== null && component !== undefined &&
      entity.parentComponent !== component
    ) {
      entity = null;
    }
  }

  if (entity !== null && entity !== undefined) {
    return [entity, ""];
  }

  const matches = findManagedEntities(component, identity, expectedRole);
  if (matches.length === 1) {
    return [matches[0], ""];
  }
  if (matches.length === 0) {
    return [null, "target-not-found"];
  }
  return [null, "ambiguous-target"];
}
