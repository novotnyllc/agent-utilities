/**
 * Document/component context resolution for managed enclosure features.
 *
 * Uses the top-level `import { adsk } from "@adsk/fas"`; this module only
 * runs inside Fusion so no lazy-import discipline is needed.
 */

import { adsk } from "@adsk/fas";

import { AddInNotRunningError } from "./dispatch.ts";

export interface DesignContext {
  document_id: string;
  component_path: string;
  occurrence_path: string | null;
  active_configuration: string | null;
  design_type: "parametric" | "direct";
  is_direct: boolean;
  root_component: any; // adsk.fusion.Component, typed loosely for API tolerance
}

const _contextCache = new Map<string, DesignContext>();

/** Discard cached external references (topology policy rule 7). */
export function invalidateCaches(): void {
  _contextCache.clear();
}

function prop(obj: any, name: string): any {
  return obj != null ? obj[name] : undefined;
}

export function resolveDesignContext(design?: any): DesignContext {
  let app: any;
  try {
    app = adsk.core.Application.get();
  } catch {
    throw new AddInNotRunningError("Fusion API (adsk) not available.");
  }
  if (design == null) {
    const doc = app.activeDocument;
    design = doc ? doc.design : null;
  }
  if (design == null) {
    throw new Error("No active Fusion design document.");
  }

  const designType = prop(design, "designType");
  let isDirect = false;
  if (designType != null) {
    try {
      isDirect = designType === (adsk.fusion as any).DesignTypes.DirectDesignType;
    } catch {
      // AttributeError equivalent in Python; leave isDirect false.
    }
  }

  const root = prop(design, "rootComponent");
  const ctx: DesignContext = {
    document_id: prop(prop(design, "parentDocument"), "name") || "",
    component_path: prop(root, "name") || "",
    occurrence_path: null,
    active_configuration: null,
    root_component: root,
    design_type: isDirect ? "direct" : "parametric",
    is_direct: isDirect,
  };
  _contextCache.set("last", ctx);
  return ctx;
}

/** Returns [token, message] when invalid, or null when the design is usable. */
export function validateParametricDesign(ctx: DesignContext): [string, string] | null {
  if (ctx.is_direct) {
    return ["invalid-design-type", "Direct-design documents cannot host managed enclosure features."];
  }
  if (ctx.root_component == null) {
    return ["invalid-design-type", "No root component available."];
  }
  return null;
}
