/**
 * Entity and occurrence-context resolution via public Fusion API.
 *
 * Translated from fusion_addin/AgentUtilitiesEnclosure/native/selections.py.
 */

import { acquireEntity } from "../identity";

type Any = any;


export function resolveEntity(selection: Any, component: Any): [Any | null, string] {
  /** Resolve one FeatureSelection to a live Fusion entity.
   * Returns [entity_or_null, refusal_token_or_empty]. */
  const token = selection?.entity_token ?? "";
  const identity = selection?._managed_identity ?? null;
  const expectedType = selection?.expected_object_type ?? "";
  const role = selection?.role ?? "";

  if (identity !== null && identity !== undefined) {
    return acquireEntity(token, identity, expectedType, component, role);
  }

  // User-owned selection: token-only reacquisition (topology rule 4: never guess).
  if (token) {
    try {
      const design = component?.parentDesign ?? null;
      if (design !== null && design !== undefined) {
        const entity = design.findEntityByToken(token);
        if (entity !== null && entity !== undefined) {
          if (
            expectedType &&
            typeof entity.objectType === "string" &&
            !entity.objectType.includes(expectedType)
          ) {
            return [null, "invalid-selection-type"];
          }
          return [entity, ""];
        }
        return [null, "selection-token-stale"];
      }
    } catch {
      return [null, "selection-token-stale"];
    }
  }

  return [null, "target-not-found"];
}

export function resolveOccurrenceContext(selection: Any, root: Any): [Any | null, string] {
  /** Resolve the correct Fusion occurrence for cross-component geometry. */
  const path = selection?.occurrence_path ?? null;
  if (!path) {
    return [root, ""];
  }

  // Walk the occurrence path string (colon-separated occurrence names).
  let occ = root;
  for (const part of String(path).split(":")) {
    let found = false;
    for (let i = 0; i < occ.childOccurrences.count; i++) {
      const child = occ.childOccurrences.item(i);
      if (child.name === part) {
        occ = child;
        found = true;
        break;
      }
    }
    if (!found) {
      return [null, "assembly-context-required"];
    }
  }
  return [occ, ""];
}
