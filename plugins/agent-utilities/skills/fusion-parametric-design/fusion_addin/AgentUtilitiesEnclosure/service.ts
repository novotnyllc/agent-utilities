/**
 * One-request lifecycle for managed enclosure features.
 *
 * Create: validate -> resolve context -> reject non-parametric -> allocate ID
 * -> params -> datums -> recipe -> timeline group -> attrs -> Compute All
 * -> inspect direct results -> FeatureResult.
 * Edit: parameter-first; controlled rebuild only when safe states hold.
 * Delete: resolve by attrs, reverse dependency, params last.
 * Inspect: five managed states per design spec.
 * Upgrade: never auto-migrates; explicit hook refusing unsafe cases.
 *
 * Uses the top-level `import { adsk } from "@adsk/fas"`; JSON wire shape is
 * identical to the Python original (snake_case, same refusal tokens).
 */

import { adsk } from "@adsk/fas";

import { resolveDesignContext, validateParametricDesign } from "./context.ts";
import { allocateIdentity, findManagedEntities, stampAttributes, ATTRIBUTE_GROUP, type ManagedIdentity } from "./identity.ts";
import { classifyInspection, inspectDirectResult } from "./inspect.ts";

type Any = any;

export const RECIPE_REGISTRY: Readonly<Record<string, string>> = Object.freeze({
  boss: "executeBossRecipe",
  seam: "executeSeamRecipe",
  retention: "executeRetentionRecipe",
  support: "executeSupportRecipe",
  reinforcement: "executeReinforcementRecipe",
  cutout: "executeCutoutRecipe",
  strain_relief: "executeStrainReliefRecipe",
  seal: "executeSealRecipe",
  vent: "executeVentRecipe",
  fit_coupon: "executeCouponRecipe",
});

const REFUSAL_TOKENS: ReadonlySet<string> = new Set([
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

export interface FeatureRefusal {
  token: string;
  message: string;
  fusion_exception_type: string | null;
  fusion_message: string | null;
  recovery: string;
  residue: string[];
}

export function makeRefusal(
  token: string,
  message: string,
  fusionMsg: string | null = null,
  recovery = "",
  residue?: unknown[],
): FeatureRefusal {
  if (!REFUSAL_TOKENS.has(token)) {
    throw new Error(`unknown refusal token: ${token}`);
  }
  return {
    token,
    message,
    fusion_exception_type: fusionMsg ? Error.name : null,
    fusion_message: fusionMsg,
    recovery,
    residue: (residue ?? []).map((r) => String(r)),
  };
}

function safeDict(obj: any): any {
  if (obj == null || typeof obj === "string" || typeof obj === "number"
    || typeof obj === "boolean") {
    return obj;
  }
  if (typeof obj.to_dict === "function") {
    return obj.to_dict();
  }
  if (typeof obj === "object") {
    const safe: Record<string, any> = {};
    for (const [k, v] of Object.entries(obj)) {
      try {
        JSON.stringify(v);
        safe[k] = v;
      } catch {
        safe[k] = String(v);
      }
    }
    return safe;
  }
  return String(obj);
}

export class FeatureResult {
  operation = "";
  instance: any = null;
  created_or_changed: any[] = [];
  native_observations: any[] = [];
  warnings: any[] = [];
  refusal: FeatureRefusal | null = null;

  toDict(): Record<string, any> {
    return {
      operation: this.operation,
      instance: safeDict(this.instance),
      created_or_changed: this.created_or_changed.map((x) => safeDict(x)),
      native_observations: this.native_observations.map((x) => String(x)),
      warnings: [...this.warnings],
      refusal: safeDict(this.refusal),
    };
  }
}

function prop(obj: any, name: string): any {
  return obj != null ? obj[name] : undefined;
}

type RecipeFn = (root: any, identity: ManagedIdentity, enriched: Record<string, any>) =>
  [any[], any[], [string, string, string] | null];

/** Recipe loader: resolves RECIPE_REGISTRY names against ./recipes/index.ts. */
async function loadRecipe(family: string): Promise<RecipeFn> {
  const attr = RECIPE_REGISTRY[family] as string | undefined;
  if (!attr) {
    throw new Error(`Recipe function not found: ${attr}`);
  }
  const recipes = await import("./recipes/index.ts");
  const fn = (recipes as Record<string, unknown>)[attr];
  if (typeof fn !== "function") {
    throw new Error(`Recipe function not found: ${attr}`);
  }
  return fn as RecipeFn;
}

function collectFeatureBodies(entity: Any): Any[] {
  /** Collect b-rep bodies from a managed feature or body entity. */
  if (entity == null) return [];
  const coll = entity.bodies ?? null;
  if (coll != null && typeof coll.count === "number") {
    const out: Any[] = [];
    for (let i = 0; i < coll.count; i++) out.push(coll.item(i));
    return out;
  }
  // The entity itself may be a body.
  if (typeof entity.objectType === "string" && entity.objectType.includes("BRepBody")) {
    return [entity];
  }
  return [];
}

export class EnclosureFeatureService {
  async executeOnce(requestJson: string): Promise<Record<string, any>> {
    const result = new FeatureResult();
    let request: Record<string, any>;
    try {
      request = JSON.parse(requestJson);
    } catch (exc) {
      result.refusal = makeRefusal("invalid-parameter-expression", `Invalid JSON: ${(exc as Error).message}`);
      result.operation = "create";
      return result.toDict();
    }
    if (typeof request !== "object" || request === null || Array.isArray(request)) {
      result.refusal = makeRefusal("invalid-parameter-expression", "Invalid JSON: request must be an object");
      result.operation = "create";
      return result.toDict();
    }
    const recipeFamily = String(request.recipe_family ?? "");
    if (!(recipeFamily in RECIPE_REGISTRY)) {
      result.refusal = makeRefusal("feature-create-failed", `Unknown family: ${recipeFamily}`);
      result.operation = "create";
      return result.toDict();
    }

    let ctx;
    try {
      ctx = resolveDesignContext();
    } catch (exc) {
      result.refusal = makeRefusal("enclosure-addin-not-installed", String(exc));
      result.operation = "create";
      return result.toDict();
    }
    const derr = validateParametricDesign(ctx);
    if (derr) {
      result.refusal = makeRefusal(derr[0], derr[1]);
      result.operation = "create";
      return result.toDict();
    }
    const root = ctx.root_component;
    if (root == null) {
      result.refusal = makeRefusal("invalid-design-type", "No root component.");
      result.operation = "create";
      return result.toDict();
    }

    const upstreamIds = Array.isArray(request.upstream_feature_ids)
      ? request.upstream_feature_ids.map(String) : [];
    const identity = allocateIdentity(
      String(request.recipe_id ?? recipeFamily),
      String(request.recipe_version ?? "0.1.0"),
      upstreamIds,
    );

    const resolved = this.resolveSelections(request, root);
    if (Array.isArray(resolved)) {
      result.refusal = makeRefusal(resolved[0], resolved[1]);
      result.operation = "create";
      return result.toDict();
    }

    const enriched: Record<string, any> = {...request};
    Object.assign(enriched, resolved);
    let created: any[] = [];
    let fn: RecipeFn;
    try {
      fn = await loadRecipe(recipeFamily);
    } catch (exc) {
      result.refusal = makeRefusal("feature-create-failed", String(exc));
      result.operation = "create";
      return result.toDict();
    }
    let refusal: [string, string, string] | null = null;
    try {
      const [c, warnings, recipeRefusal] = fn(root, identity, enriched);
      created = c;
      result.warnings = warnings;
      result.created_or_changed = created.map((item) => safeDict(item));
      refusal = recipeRefusal ?? null;
    } catch (exc) {
      result.refusal = makeRefusal(
        "feature-create-failed", String(exc), String(exc), "undo the operation");
      result.operation = "create";
      return result.toDict();
    }
    if (refusal) {
      const [tok, msg, rec] = refusal;
      result.refusal = makeRefusal(tok, msg, null, rec);
      result.operation = "create";
      return result.toDict();
    }

    this.timelineGroup(created, identity);
    this.computeAll();
    const tb = enriched.target_body ?? null;
    const ecRaw = request.expected_body_count;
    const ec = ecRaw != null ? Number(ecRaw) : null;
    const insp = this.inspect(created, tb, Number.isFinite(ec as number) ? ec : null);
    result.native_observations = insp.observations ?? [];
    result.instance = {
      feature_id: identity.featureId,
      display_suffix: identity.displaySuffix,
      recipe_id: identity.recipeId,
      recipe_version: identity.recipeVersion,
      parameter_namespace: identity.parameterNamespace,
    };
    result.operation = "create";
    return result.toDict();
  }

  /** Returns a resolved-entries object, or [refusal_token, message] on failure. */
  private resolveSelections(request: Record<string, any>, root: any):
    Record<string, any> | [string, string] {
    const resolved: Record<string, any> = {};
    for (const sel of (request.selections ?? [])) {
      const role = String(sel.role ?? "");
      const token = String(sel.entity_token ?? "");
      const expType = String(sel.expected_object_type ?? "");
      if (!token) {
        continue;
      }
      let entity: any = null;
      try {
        const design = prop(root, "parentDesign");
        entity = design ? design.findEntityByToken(token) : null;
      } catch {
        continue;
      }
      if (entity == null) {
        return ["selection-token-stale", `Token stale for role: ${role}`];
      }
      if (expType && entity.objectType != null && !String(entity.objectType).includes(expType)) {
        return ["invalid-selection-type", `Expected ${expType} for role: ${role}`];
      }
      const keymap: Record<string, string> = {
        target_body: "target_body",
        side_a_body: "side_a_body",
        side_b_body: "side_b_body",
        receiver_body: "receiver_body",
      };
      if (role in keymap) {
        resolved[keymap[role]] = entity;
      } else if (role === "plane") {
        if (!resolved.placement_frame) {
          resolved.placement_frame = {};
        }
        resolved.placement_frame.plane = entity;
      } else if (role === "path") {
        resolved.path_sketch = entity;
      } else if (role === "sweep_path") {
        resolved.sweep_path = entity;
      } else {
        if (!resolved.resolved_entities) {
          resolved.resolved_entities = {};
        }
        resolved.resolved_entities[role] = entity;
      }
    }
    return resolved;
  }

  private timelineGroup(created: any[], identity: ManagedIdentity): void {
    try {
      const app = adsk.core.Application.get();
      const design = app.activeDocument ? app.activeDocument.design : null;
      const tl = design ? design.timeline : null;
      if (tl == null || created.length < 2) {
        return;
      }
      let startIdx: number | null = null;
      let endIdx: number | null = null;
      for (const feat of created) {
        const tlo = prop(feat, "timelineObject");
        if (tlo != null) {
          const idx = tlo.index;
          if (startIdx == null || idx < startIdx) {
            startIdx = idx;
          }
          if (endIdx == null || idx > endIdx) {
            endIdx = idx;
          }
        }
      }
      if (startIdx != null && endIdx != null && endIdx > startIdx) {
        const display = identity.recipeId.split(".")[0].replace(/_/g, " ")
          .replace(/\b\w/g, (ch: string) => ch.toUpperCase());
        const gname = `Enclosure / ${display} / ${identity.displaySuffix}`;
        const groups = tl.timelineGroups;
        groups.add(startIdx, endIdx);
        groups.item(groups.count - 1).name = gname;
      }
    } catch {
      // Timeline grouping is best-effort, like the bare except in Python.
    }
  }

  private computeAll(): void {
    try {
      const app = adsk.core.Application.get();
      const design = app.activeDocument ? app.activeDocument.design : null;
      if (design) {
        design.computeAll();
      }
    } catch {
      // Best-effort compute, like the bare except in Python.
    }
  }

  private inspect(created: any[], targetBody: any, expectedCount: number | null):
    {state: string; observations: string[]} {
    try {
      const state = inspectDirectResult(created, targetBody, expectedCount);
      return {state: state.state, observations: state.observations};
    } catch {
      return {state: "unknown", observations: ["Inspection failed."]};
    }
  }

  async editFeature(requestJson: string): Promise<Record<string, any>> {
    const result = new FeatureResult();
    result.operation = "edit";
    const request = JSON.parse(requestJson);
    const fid = String(request.feature_id ?? "");
    if (!fid) {
      result.refusal = makeRefusal("target-not-found", "Edit requires feature_id.");
      return result.toDict();
    }
    const updates: Record<string, any> = request.parameter_updates ?? {};
    if (Object.keys(updates).length > 0) {
      this.updateParameters(updates);
      this.computeAll();
      result.warnings.push("Parameter-only edit applied.");
    } else {
      result.refusal = makeRefusal(
        "manual-edit-prevents-update", "Non-parameter edits require manual review.");
    }
    return result.toDict();
  }

  async deleteFeature(requestJson: string, cascade = false): Promise<Record<string, any>> {
    const result = new FeatureResult();
    result.operation = "delete";
    const request = JSON.parse(requestJson);
    const fid = String(request.feature_id ?? "");
    if (!fid) {
      result.refusal = makeRefusal("target-not-found", "Delete requires feature_id.");
      return result.toDict();
    }
    const deps: any[] = request.managed_dependents ?? [];
    if (deps.length > 0 && !cascade) {
      result.refusal = makeRefusal(
        "managed-dependent-exists",
        `Cannot delete: ${deps.length} managed dependent(s).`,
        null, "set cascade=true");
      return result.toDict();
    }
    result.warnings.push("Destructive operations require Undo acceptance before enabling.");
    return result.toDict();
  }

  async inspectFeature(requestJson: string): Promise<Record<string, any>> {
    const result = new FeatureResult();
    result.operation = "inspect";
    const request = JSON.parse(requestJson);
    const state = classifyInspection(
      Boolean(request.param_edited),
      Boolean(request.native_edited),
      Boolean(request.definition_diverged),
      Boolean(request.objects_missing),
    );
    result.instance = {
      feature_id: String(request.feature_id ?? ""),
      inspection_state: state,
    };
    return result.toDict();
  }

  async upgradeFeature(requestJson: string): Promise<Record<string, any>> {
    const result = new FeatureResult();
    result.operation = "upgrade";
    const request = JSON.parse(requestJson);
    // Read the stamped recipe version from Fusion attributes, never trust
    // the request's claimed current_version (spec: version is stamped at
    // creation).
    const fid = String(request.feature_id ?? "");
    if (!fid) {
      result.refusal = makeRefusal("target-not-found", "Upgrade requires feature_id.");
      return result.toDict();
    }
    let cv = "";
    try {
      const ctx = resolveDesignContext();
      const root = ctx.root_component;
      if (root != null) {
        const probe = allocateIdentity(fid, "", []);
        const matches = findManagedEntities(root, probe);
        if (matches.length === 1) {
          const attrs = matches[0].attributes;
          const attr = attrs?.itemByName(ATTRIBUTE_GROUP, "enclosure_recipe_version");
          cv = attr ? String(attr.value) : "";
        }
      }
    } catch {
      // Offline/no-Fusion: fall through to refusal below.
    }
    if (!cv) {
      result.refusal = makeRefusal(
        "target-not-found", `Could not resolve stamped version for ${fid}.`);
      return result.toDict();
    }
    const tv = String(request.target_version ?? "");
    if (!tv) {
      result.refusal = makeRefusal(
        "recipe-version-mismatch", "Upgrade requires target_version.");
      return result.toDict();
    }
    if (request.manual_divergence_detected) {
      result.refusal = makeRefusal(
        "manual-edit-prevents-update", "Cannot safely upgrade due to manual edits.");
      return result.toDict();
    }
    if (cv === tv) {
      result.warnings.push("Instance is already at the target version.");
      return result.toDict();
    }
    // Declared migration lookup: parameter-only preferred. No migrators ship
    // yet; refusing is a correct outcome per spec.
    result.refusal = makeRefusal(
      "recipe-version-mismatch",
      `No declared migration for (${cv} -> ${tv}).`,
      null,
      "declare a migrator or recreate the instance");
    return result.toDict();
  }

  /** Pattern or mirror an existing managed source feature (native patterns). */
  async patternOrMirrorFeature(requestJson: string): Promise<Record<string, any>> {
    const result = new FeatureResult();
    result.operation = "create";
    const request = JSON.parse(requestJson);
    const {makePattern, makeMirror} = await import("./native/patterns.ts");
    const ctx = resolveDesignContext();
    const derr = validateParametricDesign(ctx);
    if (derr) {
      result.refusal = makeRefusal(derr[0], derr[1]);
      return result.toDict();
    }
    const root = ctx.root_component;
    if (root == null) {
      result.refusal = makeRefusal("invalid-design-type", "No root component.");
      return result.toDict();
    }
    const fid = String(request.source_feature_id ?? "");
    if (!fid) {
      result.refusal = makeRefusal("target-not-found", "Pattern/mirror requires source_feature_id.");
      return result.toDict();
    }
    // Resolve the source feature by managed attribute.
    const identity = allocateIdentity(fid, "0", []);
    const matches = findManagedEntities(root, identity);
    if (matches.length === 0) {
      result.refusal = makeRefusal("target-not-found", `No managed feature ${fid}.`);
      return result.toDict();
    }
    if (matches.length > 1) {
      result.refusal = makeRefusal("ambiguous-target", `Multiple managed features match ${fid}.`);
      return result.toDict();
    }
    const sources = collectFeatureBodies(matches[0]);
    if (sources.length === 0) {
      result.refusal = makeRefusal("pattern-source-incompatible", "Source has no bodies to pattern.");
      return result.toDict();
    }
    const upstreamIds = Array.isArray(request.upstream_feature_ids)
      ? request.upstream_feature_ids.map(String) : [];
    const opIdentity = allocateIdentity(
      String(request.recipe_id ?? "pattern"),
      String(request.recipe_version ?? "0.1.0"), upstreamIds);

    let created: Any = null;
    if (request.operation === "mirror") {
      const plane = request.mirror_plane ?? null;
      if (!plane) {
        result.refusal = makeRefusal("target-not-found", "Mirror requires mirror_plane.");
        return result.toDict();
      }
      const [feat, warn] = makeMirror(root, sources, plane);
      if (warn) result.warnings.push(warn);
      created = feat;
    } else {
      const ptype = String(request.pattern_type ?? "");
      if (!["rectangular", "circular", "path"].includes(ptype)) {
        result.refusal = makeRefusal(
          "feature-create-failed", `Unknown pattern_type: ${ptype}`, "rectangular|circular|path");
        return result.toDict();
      }
      const qty = Number(request.quantity ?? 2);
      const kwargs: Record<string, Any> = {};
      for (const k of ["spacing", "angle", "axis", "path"]) {
        if (request[k] !== undefined) kwargs[k] = request[k];
      }
      const [feat, warn] = makePattern(root, sources, ptype, qty, kwargs);
      if (warn) result.warnings.push(warn);
      created = feat;
    }
    if (created == null) {
      result.refusal = makeRefusal("feature-create-failed", "Pattern/mirror creation failed.");
      return result.toDict();
    }
    stampAttributes(created, opIdentity);
    this.computeAll();
    result.instance = {
      feature_id: opIdentity.featureId,
      display_suffix: opIdentity.displaySuffix,
      recipe_id: opIdentity.recipeId,
      recipe_version: opIdentity.recipeVersion,
    };
    result.created_or_changed = [created];
    return result.toDict();
  }

  /** Record user coupon observation and chosen value; never auto-accepts. */
  async recordCouponFeature(requestJson: string): Promise<Record<string, any>> {
    const result = new FeatureResult();
    result.operation = "edit";
    const request = JSON.parse(requestJson);
    const fid = String(request.feature_id ?? "");
    if (!fid) {
      result.refusal = makeRefusal("target-not-found", "record_coupon_result requires feature_id.");
      return result.toDict();
    }
    const state = String(request.result_state ?? "");
    const chosenValue = request.chosen_value === undefined ? null : Number(request.chosen_value);
    const observation = String(request.user_observation ?? "");
    const {recordCouponResult} = await import("./recipes/coupon.ts");
    const identity = allocateIdentity(String(request.recipe_id ?? "coupon"), "0", []);
    const probe = allocateIdentity(fid, "0", []);
    void probe;
    const [ok, message] = recordCouponResult(identity, state, chosenValue, observation);
    if (!ok) {
      result.refusal = makeRefusal("coupon-required", message);
      return result.toDict();
    }
    result.warnings.push(message);
    return result.toDict();
  }

  private updateParameters(updates: Record<string, unknown>): void {
    try {
      const app = adsk.core.Application.get();
      const design = app.activeDocument ? app.activeDocument.design : null;
      if (design == null) {
        return;
      }
      const pmgr = design.userParameters;
      for (const [name, expr] of Object.entries(updates)) {
        const param = pmgr.itemByName(name);
        if (param) {
          param.expression = String(expr);
        }
      }
    } catch {
      // Parameter update is best-effort, like the bare except in Python.
    }
  }
}
