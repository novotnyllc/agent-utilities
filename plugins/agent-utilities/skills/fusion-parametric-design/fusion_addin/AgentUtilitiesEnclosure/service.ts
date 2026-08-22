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
import { allocateIdentity, findManagedEntities, probeIdentity, stampAttributes, ATTRIBUTE_GROUP, PARAM_PREFIXES, type ManagedIdentity } from "./identity.ts";
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
  // Wire aliases: coupon.* publishes under the coupon family; standalone
  // hardware bores reuse the boss recipe hardware path.
  coupon: "executeCouponRecipe",
  hardware: "executeBossRecipe",
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

interface RecipeOutput {
  created: unknown[];
  warnings: string[];
  refusal: [string, string, string] | null;
}

type RecipeFn = (root: any, identity: ManagedIdentity, enriched: Record<string, any>) =>
  RecipeOutput;

/** Recipe loader: resolves RECIPE_REGISTRY names against ./recipes/index.ts. */
/**
 * Recipe loader: resolves wire-family names against recipes/index.ts RECIPES.
 * RECIPES is the single registry source; RECIPE_REGISTRY remains only as the
 * public wire-name list used by request validation.
 */
async function loadRecipe(family: string): Promise<RecipeFn> {
  const {RECIPES} = await import("./recipes/index.ts");
  const wireFamily = family === "fit_coupon" ? "coupon"
    : family === "hardware" ? "boss" : family;
  const fn: unknown = (RECIPES as Record<string, unknown>)[wireFamily];
  if (typeof fn !== "function") {
    throw new Error(`Recipe function not found for family: ${family}`);
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

function readManagedFlag(entity: Any, key: string): boolean {
  /** Read a stamped boolean attribute; absent attribute means false. */
  const attrs = entity?.attributes ?? null;
  if (attrs == null) return false;
  const attr = attrs.itemByName(ATTRIBUTE_GROUP, key);
  if (!attr) return false;
  const v = String(attr.value ?? "").toLowerCase();
  return v === "true" || v === "1";
}

function stampManagedFlag(entity: Any, key: string, value: string): void {
  /** Stamp one lifecycle-flag attribute; no-op unless the value changes. */
  const attrs = entity?.attributes ?? null;
  if (attrs == null) return;
  const existing = attrs.itemByName(ATTRIBUTE_GROUP, key);
  if (!existing || String(existing.value ?? "") !== value) {
    attrs.add(ATTRIBUTE_GROUP, key, value);
  }
}

async function resolveManagedEntity(
  fid: string,
): Promise<[Any | null, [string, string] | null]> {
  /** Resolve the single managed entity for feature_id, or the refusal. */
  let root: Any = null;
  try {
    const ctx = resolveDesignContext();
    const derr = validateParametricDesign(ctx);
    if (derr) return [null, derr];
    root = ctx.root_component;
  } catch {
    // Offline/no-Fusion: fall through to target-not-found below.
  }
  if (root == null) {
    return [null, ["target-not-found", "No active design to search."]];
  }
  const matches = findManagedEntities(root, probeIdentity(fid));
  if (matches.length === 0) {
    return [null, ["target-not-found", `No managed feature ${fid}.`]];
  }
  if (matches.length > 1) {
    return [null, ["ambiguous-target", `Multiple managed features match ${fid}.`]];
  }
  return [matches[0], null];
}

const EDIT_FLAG_KEYS = [
  "enclosure_param_edited",
  "enclosure_native_edited",
  "enclosure_definition_diverged",
  "enclosure_objects_missing",
] as const;

// Command IDs registered by commands.ts share this wire prefix.
export const COMMAND_PREFIX = "AgentUtilitiesEnclosure_";

function parseRequest(requestJson: string): Record<string, any> | null {
  /** Parse a lifecycle request; non-object payloads and malformed JSON refuse. */
  try {
    const r = JSON.parse(requestJson);
    return (typeof r === "object" && r !== null && !Array.isArray(r)) ? r : null;
  } catch {
    return null;
  }
}

/** Reconstruct a ManagedIdentity from an entity's stamped attributes. */
function identityFromEntity(entity: Any): ManagedIdentity {
  const attrs = entity?.attributes ?? null;
  const read = (key: string): string => {
    try {
      const a = attrs ? attrs.itemByName(ATTRIBUTE_GROUP, key) : null;
      return a ? String(a.value) : "";
    } catch { return ""; }
  };
  return allocateIdentity(
    read("enclosure_feature_id"),
    read("enclosure_recipe_version") || "0",
    String(read("enclosure_upstream_ids") || "").split(",").filter(Boolean),
  );
}

/** Human-readable family names required by the timeline-group naming spec. */
const FAMILY_DISPLAY_NAMES: Readonly<Record<string, string>> = Object.freeze({
  boss: "Heat-Set Boss",
  cutout: "Port Cutout",
  seam: "Seam Interruption",
  seal: "Seal Path",
});

function familyDisplayName(family: string): string {
  const named = FAMILY_DISPLAY_NAMES[family];
  if (named) {
    return named;
  }
  return family.replace(/_/g, " ")
    .replace(/\b\w/g, (ch: string) => ch.toUpperCase());
}

function graphHasCycle(edges: ReadonlyArray<readonly [string, string]>): boolean {
  /** Kahn peeling: leftover nodes after peeling mean a cycle remains. */
  const adjacency = new Map<string, Set<string>>();
  const indegree = new Map<string, number>();
  for (const [up, down] of edges) {
    if (up === down) {
      return true;
    }
    if (!adjacency.has(up)) {
      adjacency.set(up, new Set());
    }
    const outs = adjacency.get(up)!;
    if (!outs.has(down)) {
      outs.add(down);
      indegree.set(down, (indegree.get(down) ?? 0) + 1);
    }
    if (!indegree.has(up)) {
      indegree.set(up, indegree.get(up) ?? 0);
    }
  }
  let remaining = indegree.size;
  const ready = [...indegree.entries()]
    .filter(([, degree]) => degree === 0).map(([node]) => node);
  while (ready.length > 0) {
    const node = ready.pop()!;
    remaining -= 1;
    for (const down of adjacency.get(node) ?? []) {
      const left = (indegree.get(down) ?? 1) - 1;
      indegree.set(down, left);
      if (left === 0) {
        ready.push(down);
      }
    }
  }
  return remaining > 0;
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
    // Accept the published codec envelope {recipe:{recipe_id,version,...}} and
    // the legacy flat shape; derive recipe_family from recipe_id's first segment.
    if (!request.recipe_family && request.recipe && typeof request.recipe === "object") {
      const rid = String(request.recipe.recipe_id ?? "");
      request = {...request,
        recipe_family: rid.split(".")[0],
        recipe_id: rid || undefined,
        recipe_version: String(request.recipe.version ?? "0.1.0")};
    }
    // Derive the subtype discriminator (variant/type/pattern/shape) from the
    // dotted recipe id when the caller did not send it explicitly.
    const ridForSubtype = String(request.recipe_id ?? "");
    const subtype = ridForSubtype.includes(".")
      ? ridForSubtype.split(".").slice(1).join(".") : "";
    if (subtype) {
      const subtypeFamily = String(request.recipe_family ?? "");
      const disc = subtypeFamily === "boss" ? "variant"
        : subtypeFamily === "vent" ? "pattern"
        : ["seam", "retention"].includes(subtypeFamily) ? "type"
        : subtypeFamily === "cutout" ? "shape" : "type";
      if (request[disc] === undefined) {
        request[disc] = subtype;
      }
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
    // Reject unresolvable upstream references BEFORE any mutation or cycle
    // probe so a typo cannot leave partial residue behind.
    try {
      for (const up of upstreamIds) {
        if (findManagedEntities(root, probeIdentity(up)).length === 0) {
          result.refusal = makeRefusal(
            "upstream-feature-missing",
            `Upstream feature ${up} does not match any managed entity.`,
            null,
            "create the upstream feature first or correct its feature_id");
          result.operation = "create";
          return result.toDict();
        }
      }
    } catch (exc) {
      result.refusal = makeRefusal(
        "timeline-unhealthy", String(exc), null, "inspect the document and retry");
      result.operation = "create";
      return result.toDict();
    }
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

    // Convert the wire parameters array ({key,value:{expression|value,unit}})
    // into a keyed object recipes can read as params.outer_diameter etc.,
    // while keeping a legacy flat parameters object working unchanged.
    const wireParams: any[] = Array.isArray(request.parameters)
      ? request.parameters : [];
    const paramObj: Record<string, any> = {
      ...(request.parameters && !Array.isArray(request.parameters)
        ? request.parameters : {}),
    };
    for (const p of wireParams) {
      if (!p || typeof p !== "object" || !p.key) continue;
      let v = p.value;
      if (v && typeof v === "object") {
        // {expression} wins; otherwise numeric value + unit.
        v = v.expression !== undefined
          ? String(v.expression)
          : (typeof v.value === "number" ? `${v.value} ${v.unit ?? "mm"}`.trim() : v.value);
      }
      paramObj[String(p.key)] = v;
    }
    const enriched: Record<string, any> = {...request, parameters: paramObj};
    Object.assign(enriched, resolved);
    // Recipes read role names directly (mask_body, profile_reference,
    // pattern_axis); mirror each resolved selection onto its role field too.
    for (const [role, entity] of Object.entries(resolved.resolved_entities ?? {})) {
      enriched[role] = entity;
    }
    try {
      if (this.managedGraphHasCycle(root, identity.featureId, upstreamIds)) {
        result.refusal = makeRefusal(
          "cross-feature-cycle",
          `Upstream dependencies for ${identity.featureId} would close a managed cycle.`,
          null,
          "remove the upstream reference that closes the cycle");
        result.operation = "create";
        return result.toDict();
      }
    } catch (exc) {
      result.refusal = makeRefusal(
        "timeline-unhealthy", String(exc), null, "inspect the document and retry");
      result.operation = "create";
      return result.toDict();
    }
    let created: any[] = [];
    let fn: RecipeFn;
    try {
      fn = await loadRecipe(recipeFamily);
    } catch (exc) {
      result.refusal = makeRefusal("feature-create-failed", String(exc));
      result.operation = "create";
      return result.toDict();
    }
    const timelineBefore = this.currentTimelineIndex();
    let refusal: [string, string, string] | null = null;
    try {
      const output = fn(root, identity, enriched);
      created = [...output.created];
      result.warnings = [...output.warnings];
      result.created_or_changed = created.map((item) => safeDict(item));
      refusal = output.refusal;
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

    this.timelineGroup(recipeFamily, identity, timelineBefore, this.currentTimelineIndex());
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

  private timelineGroup(
    family: string, identity: ManagedIdentity, before: number | null, after: number | null,
  ): void {
    try {
      const tl = this.timeline();
      // A transient contiguous span is required; per-feature index probing is
      // deliberately avoided so indexes never leak into managed identity.
      if (tl == null || before == null || after == null || after <= before) {
        return;
      }
      const gname = ["Enclosure", familyDisplayName(family), identity.displaySuffix].join(" \u00b7 ");
      const groups = tl.timelineGroups;
      groups.add(before, after);
      groups.item(groups.count - 1).name = gname;
    } catch {
      // Timeline grouping is best-effort, like the bare except in Python.
    }
  }

  private currentTimelineIndex(): number | null {
    try {
      const tl = this.timeline();
      return tl ? Number(tl.currentIndex) : null;
    } catch {
      return null;
    }
  }

  private timeline(): Any | null {
    const app = adsk.core.Application.get();
    const design = app.activeDocument ? app.activeDocument.design : null;
    return design ? design.timeline : null;
  }

  private managedGraphHasCycle(root: Any, featureId: string, upstreamIds: string[]): boolean {
    /** Build the graph from existing managed entities' stamped upstream IDs.
     * Mirrors src/enclosure-features/dependencies.ts cycle policy. */
    try {
      const edges: Array<[string, string]> = [];
      const collNames = [
        "bRepBodies", "sketches", "constructionPlanes",
        "constructionAxes", "constructionPoints", "features",
      ];
      for (const collName of collNames) {
        const coll = root?.[collName] ?? null;
        if (!coll) continue;
        for (let i = 0; i < coll.count; i++) {
          const attrs = coll.item(i)?.attributes ?? null;
          const fidAttr = attrs ? attrs.itemByName(ATTRIBUTE_GROUP, "enclosure_feature_id") : null;
          const upAttr = attrs ? attrs.itemByName(ATTRIBUTE_GROUP, "enclosure_upstream_ids") : null;
          if (!fidAttr || !fidAttr.value) continue;
          for (const up of String(upAttr?.value ?? "").split(",").filter(Boolean)) {
            edges.push([String(fidAttr.value), up]);
          }
        }
      }
      for (const up of upstreamIds) {
        edges.push([featureId, up]);
      }
      return graphHasCycle(edges);
    } catch (exc) {
      // Probe failure is not "no cycle": refuse loudly rather than create
      // through an unverified graph (spec: cycles are rejected before mutation).
      throw new Error(`dependency graph probe failed: ${exc}`);
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
    const request = parseRequest(requestJson);
    if (!request) {
      result.refusal = makeRefusal("invalid-parameter-expression", "Invalid JSON");
      return result.toDict();
    }
    const fid = String(request.feature_id ?? "");
    if (!fid) {
      result.refusal = makeRefusal("target-not-found", "Edit requires feature_id.");
      return result.toDict();
    }
    const [entity, refusal] = await resolveManagedEntity(fid);
    if (refusal) {
      result.refusal = makeRefusal(refusal[0], refusal[1]);
      return result.toDict();
    }
    // Inspect before mutating: manual divergence makes controlled rebuild
    // unsafe and must refuse before any parameter update is applied.
    const pre = classifyInspection(
      readManagedFlag(entity, EDIT_FLAG_KEYS[0]),
      readManagedFlag(entity, EDIT_FLAG_KEYS[1]),
      readManagedFlag(entity, EDIT_FLAG_KEYS[2]),
      readManagedFlag(entity, EDIT_FLAG_KEYS[3]),
    );
    if (
      pre === "managed-definition-diverged" ||
      pre === "managed-object-missing"
    ) {
      result.refusal = makeRefusal(
        "manual-edit-prevents-update",
        `Cannot safely edit ${fid}: inspection state is ${pre}.`);
      return result.toDict();
    }
    const updates: Record<string, any> = request.parameter_updates ?? {};
    if (Object.keys(updates).length > 0) {
      // Scope edits to this feature's stamped namespace: a crafted or mistaken
      // update must not mutate an unrelated feature or ordinary user parameter.
      let ownedNs = "";
      try {
        const ctxE = resolveDesignContext();
        const rootE = ctxE.root_component;
        if (rootE != null) {
          const matchesE = findManagedEntities(rootE, probeIdentity(fid));
          if (matchesE.length === 1) {
            const attrsE = matchesE[0].attributes;
            const nsAttr = attrsE?.itemByName(ATTRIBUTE_GROUP, "enclosure_parameter_namespace");
            ownedNs = nsAttr ? String(nsAttr.value) : "";
          }
        }
      } catch { /* offline: no scoping available */ }
      const scoped: Record<string, any> = {};
      let skipped = 0;
      const prefixes = Object.values(PARAM_PREFIXES) as string[];
      for (const [name, expr] of Object.entries(updates)) {
        const owned = ownedNs !== "" && prefixes.some((p) => name.startsWith(p + ownedNs + "_"));
        if (owned) scoped[name] = expr; else skipped += 1;
      }
      if (skipped > 0) {
        result.warnings.push(`Skipped ${skipped} parameter(s) not owned by feature ${fid}.`);
      }
      if (Object.keys(scoped).length === 0) {
        if (skipped > 0) {
          result.refusal = makeRefusal(
            "invalid-parameter-expression",
            "No parameter_updates owned by this feature's namespace.");
          return result.toDict();
        }
        result.refusal = makeRefusal(
          "manual-edit-prevents-update", "Non-parameter edits require manual review.");
        return result.toDict();
      }
      this.updateParameters(scoped);
      this.computeAll();
      result.warnings.push("Parameter-only edit applied.");
      stampManagedFlag(entity, EDIT_FLAG_KEYS[0], "true");
      const post = classifyInspection(
        readManagedFlag(entity, EDIT_FLAG_KEYS[0]),
        readManagedFlag(entity, EDIT_FLAG_KEYS[1]),
        readManagedFlag(entity, EDIT_FLAG_KEYS[2]),
        readManagedFlag(entity, EDIT_FLAG_KEYS[3]),
      );
      result.instance = {
        feature_id: fid,
        inspection_state: post,
      };
    } else {
      result.refusal = makeRefusal(
        "manual-edit-prevents-update", "Non-parameter edits require manual review.");
    }
    return result.toDict();
  }

  async deleteFeature(requestJson: string, cascade = false): Promise<Record<string, any>> {
    const result = new FeatureResult();
    result.operation = "delete";
    const request = parseRequest(requestJson);
    if (!request) {
      result.refusal = makeRefusal("invalid-parameter-expression", "Invalid JSON");
      return result.toDict();
    }
    const fid = String(request.feature_id ?? "");
    if (!fid) {
      result.refusal = makeRefusal("target-not-found", "Delete requires feature_id.");
      return result.toDict();
    }
    // Discover dependents from the stamped upstream graph; never trust the
    // caller alone (spec: deletion refuses while a managed dependent exists).
    const discovered: string[] = [];
    try {
      const ctxD = resolveDesignContext();
      const rootD = ctxD.root_component;
      if (rootD != null) {
        for (const collName of ["bRepBodies", "sketches", "features"]) {
          const coll = rootD[collName];
          if (!coll) continue;
          for (let i = 0; i < coll.count; i++) {
            const obj = coll.item(i);
            const attrs = obj?.attributes ?? null;
            if (!attrs) continue;
            const fidA = attrs.itemByName(ATTRIBUTE_GROUP, "enclosure_feature_id");
            const upA = attrs.itemByName(ATTRIBUTE_GROUP, "enclosure_upstream_ids");
            if (!fidA || String(fidA.value) === fid) continue;
            const ups = String(upA?.value ?? "").split(",").filter(Boolean);
            if (ups.includes(fid)) discovered.push(String(fidA.value));
          }
        }
      }
    } catch { /* offline: fall back to caller-supplied list only */ }
    const deps: any[] = [...new Set([...(request.managed_dependents ?? []), ...discovered])];
    if (deps.length > 0 && !cascade) {
      result.refusal = makeRefusal(
        "managed-dependent-exists",
        `Cannot delete: ${deps.length} managed dependent(s).`,
        null, "set cascade=true");
      return result.toDict();
    }
    // Resolve all managed entities by attribute; delete in reverse timeline
    // order (transient index read, never persisted); parameters LAST per spec.
    let root: Any = null;
    try {
      const ctx = resolveDesignContext();
      root = ctx.root_component;
    } catch { /* offline: matches stays empty -> target-not-found */ }
    if (root == null) {
      result.refusal = makeRefusal("target-not-found", "No active design to search.");
      return result.toDict();
    }
    const managed = findManagedEntities(root, probeIdentity(fid));
    if (managed.length === 0) {
      result.refusal = makeRefusal("target-not-found", `No managed feature ${fid}.`);
      return result.toDict();
    }
    const ordered = [...managed].sort((a, b) => {
      const ta = Number(a?.timelineObject?.index ?? 0);
      const tb = Number(b?.timelineObject?.index ?? 0);
      return tb - ta;
    });
    /** Delete entities for one feature id in reverse timeline order.
      * Returns per-entity failure messages. */
    const deleteEntitiesFor = (entities: any[]): string[] => {
      const errs: string[] = [];
      const orderedDeps = [...entities].sort((a2, b2) => {
        const ta = Number(a2?.timelineObject?.index ?? 0);
        const tb = Number(b2?.timelineObject?.index ?? 0);
        return tb - ta;
      });
      for (const entity of orderedDeps) {
        try {
          entity.deleteMe();
        } catch (exc) {
          errs.push(String(exc).slice(0, 120));
        }
      }
      return errs;
    };
    /** Clean one feature namespace from user parameters; best-effort. */
    const cleanupParamsFor = (nsAttrEntity: Any, targetFid: string): void => {
      try {
        const design = adsk.core.Application.get()?.activeDocument?.design ?? null;
        const pmgr = design?.userParameters ?? null;
        if (!pmgr) return;
        const prefixes = Object.values(PARAM_PREFIXES) as string[];
        const attrs = nsAttrEntity?.attributes ?? null;
        const nsAttr = attrs ? attrs.itemByName(ATTRIBUTE_GROUP, "enclosure_parameter_namespace") : null;
        let namespace = nsAttr ? String(nsAttr.value ?? "") : "";
        if (!namespace) {
          namespace = String(targetFid).slice(0, 6);
          result.warnings.push(
            `No stamped parameter namespace found for ${targetFid}; falling back to feature id prefix for cleanup.`);
        }
        for (let i = pmgr.count - 1; i >= 0; i--) {
          const p = pmgr.item(i);
          const name = String(p?.name ?? "");
          for (const prefix of prefixes) {
            const owned = prefix + namespace + "_";
            if (name.startsWith(owned)) {
              try { p.deleteMe(); } catch { /* best-effort */ }
              break;
            }
          }
        }
      } catch { /* parameter cleanup is best-effort */ }
    };
    /** Discover managed dependents of fid from stamped upstream graph. */
    const discoverDependents = (ofFid: string): string[] => {
      const found: string[] = [];
      try {
        for (const collName of ["bRepBodies", "sketches", "features"]) {
          const coll = root[collName];
          if (!coll) continue;
          for (let i = 0; i < coll.count; i++) {
            const obj = coll.item(i);
            const attrs = obj?.attributes ?? null;
            if (!attrs) continue;
            const fidA = attrs.itemByName(ATTRIBUTE_GROUP, "enclosure_feature_id");
            const upA = attrs.itemByName(ATTRIBUTE_GROUP, "enclosure_upstream_ids");
            if (!fidA || String(fidA.value) === ofFid) continue;
            const ups = String(upA?.value ?? "").split(",").filter(Boolean);
            if (ups.includes(ofFid)) found.push(String(fidA.value));
          }
        }
      } catch { /* discovery is best-effort */ }
      return [...new Set(found)];
    };
    /** Recursively resolve + delete dependent features (depth-bounded). */
    const cascadeDependents = (depIds: string[], depth: number): void => {
      if (depth > 5 || depIds.length === 0) return;
      for (const depId of depIds) {
        let depMatches: any[] = [];
        try {
          depMatches = findManagedEntities(root, probeIdentity(depId));
        } catch { /* probe failure leaves matches empty */ }
        if (depMatches.length === 0) continue;
        // Discover grandchildren BEFORE deleting so the cascade is complete.
        const grandDeps = discoverDependents(depId);
        cascadeDependents(grandDeps, depth + 1);
        const depErrs = deleteEntitiesFor(depMatches);
        for (const e of depErrs) {
          result.warnings.push(`Cascade delete ${depId}: ${e}`);
        }
        cleanupParamsFor(depMatches[0], depId);
      }
    };
    if (cascade && deps.length > 0) {
      cascadeDependents(deps, 1);
    }
    const failed: string[] = [];
    for (const entity of ordered) {
      try {
        entity.deleteMe();
      } catch (exc) {
        failed.push(String(exc).slice(0, 120));
      }
    }
    if (failed.length > 0) {
      result.warnings.push(`Failed to delete ${failed.length} entity/entities.`);
    }
    try {
      const design = adsk.core.Application.get()?.activeDocument?.design ?? null;
      const pmgr = design?.userParameters ?? null;
      if (pmgr) {
        const prefixes = Object.values(PARAM_PREFIXES) as string[];
        // The namespace is the one stamped at create time; fid.slice is only
        // a fallback for entities created before namespace stamping existed.
        const attrs = ordered[0]?.attributes ?? null;
        const nsAttr = attrs ? attrs.itemByName(ATTRIBUTE_GROUP, "enclosure_parameter_namespace") : null;
        let namespace = nsAttr ? String(nsAttr.value ?? "") : "";
        if (!namespace) {
          namespace = fid.slice(0, 6);
          result.warnings.push(
            "No stamped parameter namespace found; falling back to feature id prefix for cleanup.");
        }
        for (let i = pmgr.count - 1; i >= 0; i--) {
          const p = pmgr.item(i);
          const name = String(p?.name ?? "");
          for (const prefix of prefixes) {
            const owned = prefix + namespace + "_";
            if (name.startsWith(owned)) {
              try { p.deleteMe(); } catch { /* best-effort */ }
              break;
            }
          }
        }
      }
    } catch { /* parameter cleanup is best-effort */ }
    try {
      const remaining = findManagedEntities(root, probeIdentity(fid));
      if (remaining.length > 0) {
        result.warnings.push(
          `${remaining.length} entity/entities still carry feature id ${fid}; manual cleanup may be required.`);
      }
    } catch { /* verification is best-effort */ }
    result.warnings.push("Destructive operations require Undo acceptance before enabling.");
    return result.toDict();
  }

  async inspectFeature(requestJson: string): Promise<Record<string, any>> {
    const result = new FeatureResult();
    result.operation = "inspect";
    const request = parseRequest(requestJson);
    if (!request) {
      result.refusal = makeRefusal("invalid-parameter-expression", "Invalid JSON");
      return result.toDict();
    }
    const fidI = String(request.feature_id ?? "");
    if (!fidI) {
      result.refusal = makeRefusal("target-not-found", "Inspect requires feature_id.");
      return result.toDict();
    }
    // Derive state from Fusion first; request booleans are fallback-only so a
    // client cannot dictate an inspection verdict for a real instance.
    let objectsMissing = false;
    let definitionDiverged = false;
    let paramEdited = false;
    let nativeEdited = false;
    let derivedFrom = "request";
    try {
      const ctxI = resolveDesignContext();
      const rootI = ctxI.root_component;
      if (rootI != null) {
        const matchesI = findManagedEntities(rootI, probeIdentity(fidI));
        if (matchesI.length === 0) {
          objectsMissing = true;
          derivedFrom = "fusion";
        } else {
          derivedFrom = "fusion";
          for (const ent of matchesI) {
            const tlObj = ent?.timelineObject ?? null;
            let healthOk = true;
            try { healthOk = tlObj == null ? false : Number(tlObj.healthState) === 0 || String(tlObj.healthState) === "OKFeatureHealthState"; } catch { healthOk = false; }
            if (!healthOk) { definitionDiverged = true; break; }
          }
          const readFlag = (ent: Any, key: string): boolean => {
            try {
              const a = ent?.attributes?.itemByName(ATTRIBUTE_GROUP, key);
              return a ? String(a.value) === "true" : false;
            } catch { return false; }
          };
          paramEdited = matchesI.some((e: Any) => readFlag(e, EDIT_FLAG_KEYS[0]));
          nativeEdited = matchesI.some((e: Any) => readFlag(e, EDIT_FLAG_KEYS[1]));
        }
      }
    } catch { /* offline: keep request fallbacks */ }
    if (derivedFrom !== "fusion") {
      paramEdited = paramEdited || Boolean(request.param_edited);
      nativeEdited = nativeEdited || Boolean(request.native_edited);
      definitionDiverged = definitionDiverged || Boolean(request.definition_diverged);
      objectsMissing = objectsMissing || Boolean(request.objects_missing);
    }
    const state = classifyInspection(paramEdited, nativeEdited, definitionDiverged, objectsMissing);
    result.instance = {
      feature_id: fidI,
      inspection_state: state,
    };
    if (derivedFrom === "request") {
      result.warnings.push("Fusion state unavailable; classification used request-supplied flags.");
    }
    return result.toDict();
  }

  async upgradeFeature(requestJson: string): Promise<Record<string, any>> {
    const result = new FeatureResult();
    result.operation = "upgrade";
    const request = parseRequest(requestJson);
    if (!request) {
      result.refusal = makeRefusal("invalid-parameter-expression", "Invalid JSON");
      return result.toDict();
    }
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
        const probe = probeIdentity(fid);
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
    const request = parseRequest(requestJson);
    if (!request) {
      result.refusal = makeRefusal("invalid-parameter-expression", "Invalid JSON");
      return result.toDict();
    }
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
    const identity = probeIdentity(fid);
    const matches = findManagedEntities(root, identity);
    if (matches.length === 0) {
      result.refusal = makeRefusal("target-not-found", `No managed feature ${fid}.`);
      return result.toDict();
    }
    if (matches.length > 1) {
      result.refusal = makeRefusal("ambiguous-target", `Multiple managed features match ${fid}.`);
      return result.toDict();
    }
    // Pattern-of-pattern chains multiply instances invisibly to the managed
    // graph; refuse rather than create an untracked cascade.
    const srcType = String(matches[0]?.objectType ?? "");
    if (srcType.includes("Pattern") || srcType.includes("Mirror")) {
      result.refusal = makeRefusal("pattern-source-incompatible",
        "Source is itself a pattern/mirror; chain them manually if truly needed.",
        null, "pattern the original source feature instead");
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
    const request = parseRequest(requestJson);
    if (!request) {
      result.refusal = makeRefusal("invalid-parameter-expression", "Invalid JSON");
      return result.toDict();
    }
    const fid = String(request.feature_id ?? "");
    if (!fid) {
      result.refusal = makeRefusal("target-not-found", "record_coupon_result requires feature_id.");
      return result.toDict();
    }
    const state = String(request.result_state ?? "");
    const chosenValue = request.chosen_value === undefined ? null : Number(request.chosen_value);
    const observation = String(request.user_observation ?? "");
    const {recordCouponResult} = await import("./recipes/coupon.ts");
    // Bind the observation to the REQUESTED coupon's stamped identity — a
    // fresh random namespace would orphan the result from its instance.
    const ctx0 = resolveDesignContext();
    const root0 = ctx0.root_component;
    if (root0 == null) {
      result.refusal = makeRefusal("target-not-found", "No active design to search.");
      return result.toDict();
    }
    const matches0 = findManagedEntities(root0, probeIdentity(fid));
    if (matches0.length === 0) {
      result.refusal = makeRefusal("target-not-found", `No managed feature ${fid}.`);
      return result.toDict();
    }
    if (matches0.length > 1) {
      result.refusal = makeRefusal("ambiguous-target", `Multiple managed features match ${fid}.`);
      return result.toDict();
    }
    const identity = identityFromEntity(matches0[0]);
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
