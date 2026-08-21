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
    const result = await svc.executeOnce(requestJson);
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
function onCommandCreated(args: any): void {
  try {
    const command = args.command;
    const inputs = command.commandInputs;
    inputs.addTextBoxCommandInput(
      "request_json",
      "Request JSON:",
      "",
      5,
      true,
    );
    command.execute.add((execArgs: any) => {
      void executeHandler(execArgs);
    });
  } catch {
    // Swallow like the Python bare except.
  }
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
    const resourceCollection = typeof (adsk.core as any).ResourceCollection !== "undefined"
      ? (adsk.core as any).ResourceCollection.create() : null;
    const cmdDef = cmdMgr.addButton(
      fullId,
      resourceCollection,
      displayName,
      description,
      description,
    );
    if (cmdDef == null) {
      continue;
    }
    // Add a textbox input for pasting JSON requests.
    cmdDef.commandCreated.add(onCommandCreated);
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
