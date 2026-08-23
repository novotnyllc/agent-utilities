/**
 * Human-facing Fusion command definitions for the enclosure feature toolkit.
 *
 * Each command consumes a staged nonce (or opens a minimal textbox for pasted
 * request JSON), calls service.executeOnce, and reports success/refusal text.
 * Uses the top-level `import { adsk } from "@adsk/fas"`.
 */

import { adsk } from "@adsk/fas";

import { EnclosureFeatureService } from "./service.ts";

export const COMMAND_SPECS: ReadonlyArray<readonly [string, string, string]> = Object.freeze([
  ["AddEnclosureBoss", "Add Enclosure Boss", "Create a managed boss feature"] as const,
  ["AddSeam", "Add Seam", "Create a managed seam feature"] as const,
  ["AddRetention", "Add Retention", "Create a managed retention feature"] as const,
  ["AddSupport", "Add Support", "Create a managed support feature"] as const,
  ["AddReinforcement", "Add Reinforcement", "Create a managed reinforcement feature"] as const,
  ["AddCutout", "Add Cutout", "Create a managed cutout feature"] as const,
  ["AddStrainRelief", "Add Strain Relief", "Create a managed strain relief feature"] as const,
  ["AddSeal", "Add Seal", "Create a managed seal feature"] as const,
  ["AddVent", "Add Vent", "Create a managed vent feature"] as const,
  ["AddFitCoupon", "Add Fit Coupon", "Create a fit coupon with explicit candidate stations"] as const,
  ["PatternFeature", "Pattern Feature", "Create a managed pattern of an existing source feature"] as const,
  ["MirrorFeature", "Mirror Feature", "Create a managed mirror of an existing source feature"] as const,
  ["EditEnclosureFeature", "Edit Enclosure Feature", "Edit parameters of a managed enclosure feature"] as const,
  ["DeleteEnclosureFeature", "Delete Enclosure Feature", "Delete a managed enclosure feature"] as const,
  ["InspectEnclosureFeature", "Inspect Enclosure Feature", "Inspect state of a managed enclosure feature"] as const,
  ["RecordCouponResult", "Record Coupon Result", "Record user-observed coupon result and chosen value"] as const,
]);

const _registeredDefinitions: any[] = [];

/** Minimal valid request skeletons, pre-filled into each create command's
 * request_json textbox. Selection tokens are realistic dummies; replace them
 * (or delete the selections array) with tokens for the active document. */
export const COMMAND_EXAMPLES: Readonly<Record<string, string>> = Object.freeze({
  AddEnclosureBoss: JSON.stringify({
    request_id: "boss-example",
    recipe_family: "boss",
    recipe_id: "boss.support",
    variant: "support",
    parameters: {outer_diameter: "6 mm", height: "5 mm"},
    hardware: {bore_diameter: "3.2 mm"},
    selections: [
      {role: "target_body", entity_token: "TOKEN_TARGET_BODY"},
      {role: "plane", entity_token: "TOKEN_PLACEMENT_PLANE"},
    ],
  }, null, 2),
  AddSeam: JSON.stringify({
    request_id: "seam-example",
    recipe_family: "seam",
    recipe_id: "seam.lip_groove",
    variant: "lip_groove",
    parameters: {
      lip_width: "1.0 mm",
      engagement_depth: "0.8 mm",
      radial_clearance: "0.15 mm",
    },
    selections: [
      {role: "side_a_body", entity_token: "TOKEN_SIDE_A_BODY"},
      {role: "side_b_body", entity_token: "TOKEN_SIDE_B_BODY"},
      {role: "path", entity_token: "TOKEN_PARTING_PATH_SKETCH"},
    ],
  }, null, 2),
  AddCutout: JSON.stringify({
    request_id: "cutout-example",
    recipe_family: "cutout",
    recipe_id: "cutout.rectangle",
    shape: "rectangle",
    dimensions: {width: 20.0, height: 12.0},
    extent: "through_all",
    recess: {width: 24.0, height: 16.0, depth: "1 mm", clearance: 1.0},
    selections: [
      {role: "target_body", entity_token: "TOKEN_TARGET_BODY"},
      {role: "plane", entity_token: "TOKEN_WALL_PLANE"},
    ],
  }, null, 2),
  AddVent: JSON.stringify({
    request_id: "vent-example",
    recipe_family: "vent",
    recipe_id: "vent.rectangular",
    pattern: "rectangular_holes",
    boundary_policy: "clip",
    parameters: {aperture: 2.0, pitch: 4.0, count_x: 6, count_y: 3},
    selections: [
      {role: "target_body", entity_token: "TOKEN_TARGET_BODY"},
      {role: "plane", entity_token: "TOKEN_VENT_PLANE"},
      {role: "mask_body", entity_token: "TOKEN_MASK_BODY"},
    ],
  }, null, 2),
});

const DOCS_TOOLTIP_SUFFIX = "\n\nDocs: references/enclosure-features.md";

let _service: EnclosureFeatureService | null = null;

function getService(): EnclosureFeatureService {
  if (_service === null) {
    _service = new EnclosureFeatureService();
  }
  return _service;
}

function prop(obj: any, name: string): any {
  return obj != null ? obj[name] : undefined;
}

/** Shared handler: consume staged nonce or prompt for pasted request JSON. */
async function executeHandler(eventArgs: any): Promise<void> {
  try {
    const app = adsk.core.Application.get();
    const ui = app.userInterface;
    // eventArgs.firingEvent.sender is the CommandDefinition in Fusion.
    const cmdDef = prop(prop(eventArgs, "firingEvent"), "sender");
    let nonce: string | null = null; // reserved for future staged-nonce input lookup
    let requestJson: string | null = null;
    void nonce;

    const inputs = cmdDef && typeof cmdDef.commandInputs !== "undefined"
      ? cmdDef.commandInputs : null;
    if (inputs) {
      for (let i = 0; i < inputs.count; i++) {
        const inp = inputs.item(i);
        if (inp.id === "request_json") {
          requestJson = typeof inp.expression === "string" ? inp.expression : String(inp.value);
        }
      }
    }
    if (!requestJson) {
      // Minimal textbox input for pasted request JSON.
      const result = ui.inputBox(
        "Paste enclosure feature request JSON:", "Agent Utilities Enclosure", "");
      if (Array.isArray(result)) {
        requestJson = result[0];
      } else if (result) {
        requestJson = String(result);
      }
    }
    if (!requestJson) {
      return;
    }
    const svc = getService();
    // Dispatch to the service method matching this command's operation.
    // Create-family commands use executeOnce; the rest map 1:1.
    const cmdId: string = String(cmdDef?.id ?? "");
    const op = cmdId.replace("AgentUtilitiesEnclosure_", "");
    let result: Record<string, any>;
    if (["EditEnclosureFeature"].includes(op)) {
      result = await svc.editFeature(requestJson);
    } else if (op === "DeleteEnclosureFeature") {
      result = await svc.deleteFeature(requestJson);
    } else if (op === "InspectEnclosureFeature") {
      result = await svc.inspectFeature(requestJson);
    } else if (op === "PatternFeature" || op === "MirrorFeature") {
      result = await svc.patternOrMirrorFeature(requestJson);
    } else if (op === "RecordCouponResult") {
      result = await svc.recordCouponFeature(requestJson);
    } else {
      result = await svc.executeOnce(requestJson);
    }
    const refusal = result.refusal;
    if (refusal) {
      const token = refusal.token ?? "unknown";
      const message = refusal.message ?? "";
      let msg = "Refused [" + token + "]: " + message;
      const recovery = refusal.recovery ?? "";
      if (recovery) {
        msg += "\nRecovery: " + recovery;
      }
      const fusionMsg = refusal.fusion_message;
      if (fusionMsg) {
        msg += "\nFusion: " + fusionMsg;
      }
      ui.messageBox(msg);
    } else {
      const instance = result.instance ?? {};
      const fid = instance.display_suffix ?? "?";
      const warnCount = Array.isArray(result.warnings) ? result.warnings.length : 0;
      let msg = `Created enclosure feature ${fid} (${warnCount} warnings).`;
      for (const w of result.warnings ?? []) {
        msg += "\nWarning: " + w;
      }
      ui.messageBox(msg);
    }
  } catch (exc) {
    try {
      adsk.core.Application.get().userInterface.messageBox(`Command error: ${exc}`);
    } catch {
      // No UI available; swallow like the Python bare except.
    }
  }
}

/** Set up command inputs when a command is created by the user. */
function onCommandCreated(cmdIdSuffix: string) {
  return (args: any): void => {
    try {
      const command = args.command;
      const inputs = command.commandInputs;
      const example = COMMAND_EXAMPLES[cmdIdSuffix] ?? "";
      inputs.addTextBoxCommandInput(
        "request_json",
        "Request JSON:",
        example,
        example ? Math.max(5, example.split("\n").length + 1) : 5,
        false,
      );
      command.execute.add((execArgs: any) => {
        void executeHandler(execArgs);
      });
    } catch {
      // Swallow like the Python bare except.
    }
  };
}

/** Register all enclosure commands in Fusion UI. Throws when adsk unavailable. */
export function registerCommands(_context?: any): void {
  const app = adsk.core.Application.get();
  const ui = app.userInterface;
  const cmdMgr = ui.commandDefinitions;

  for (const [cmdIdSuffix, displayName, description] of COMMAND_SPECS) {
    const fullId = `AgentUtilitiesEnclosure_${cmdIdSuffix}`;
    let existing: any = null;
    try {
      existing = cmdMgr.itemById(fullId);
    } catch {
      // itemById may throw on some API versions.
    }
    if (existing != null) {
      continue; // already registered (e.g. re-run without stop)
    }
    let tooltip = description + DOCS_TOOLTIP_SUFFIX;
    if (COMMAND_EXAMPLES[cmdIdSuffix]) {
      tooltip += "\n\nThe request box is pre-filled with an example; edit the TOKEN_* placeholders to match your document.";
    }
    // Fusion API: addButtonDefinition(id, name, tooltip, resourceFolder).
    // No icon resources ship; omitting resourceFolder uses the default.
    const cmdDef = cmdMgr.addButtonDefinition(
      fullId,
      displayName,
      tooltip,
    );
    if (cmdDef == null) {
      continue;
    }
    // Add a textbox input for pasting JSON requests.
    cmdDef.commandCreated.add(onCommandCreated(cmdIdSuffix));
    _registeredDefinitions.push(cmdDef);
  }
}

/** Remove registered commands on add-in shutdown. */
export function unregisterCommands(_context?: any): void {
  try {
    const app = adsk.core.Application.get();
    const ui = app.userInterface;
    const cmdMgr = ui.commandDefinitions;
    for (const cmdDef of _registeredDefinitions) {
      try {
        cmdMgr.remove(cmdDef);
      } catch {
        // Already gone or invalid handle; keep going.
      }
    }
    _registeredDefinitions.length = 0;
  } catch {
    // Shutdown must not crash even without UI access.
  }
}
