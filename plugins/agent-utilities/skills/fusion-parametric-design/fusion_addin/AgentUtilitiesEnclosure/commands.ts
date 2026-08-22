/**
 * Human-facing Fusion command definitions for the enclosure feature toolkit.
 *
 * Humans get ordinary Fusion CommandInputs. Requests are assembled internally
 * and sent to the same EnclosureFeatureService used by agent dispatch.
 */

import { adsk } from "@adsk/fas";

import { consumePending, lastConsumedNonce, storeResult } from "./dispatch.ts";
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
  ["AssignFdmRule", "Assign FDM Rule", "Assign wall, draft, clearance, and material rules"] as const,
  ["AddSolidExtrude", "Add Solid Extrude", "Create an ordinary solid extrude"] as const,
  ["AddSolidShell", "Add Solid Shell", "Create an ordinary solid shell"] as const,
  ["AddSolidThicken", "Add Solid Thicken", "Create an ordinary solid thicken"] as const,
  ["AddSolidDraft", "Add Solid Draft", "Create an ordinary solid draft"] as const,
]);

const DOCS_TOOLTIP_SUFFIX = "\n\nDocs: references/enclosure-features.md";
const _registeredDefinitions: any[] = [];
let _service: EnclosureFeatureService | null = null;

function getService(): EnclosureFeatureService {
  if (_service === null) _service = new EnclosureFeatureService();
  return _service;
}

function prop(obj: any, name: string): any {
  return obj != null ? obj[name] : undefined;
}

function inputById(inputs: any, id: string): any {
  try { return inputs.itemById(id); } catch { return null; }
}

function setTooltip(input: any, tooltip: string): any {
  try { input.toolTip = tooltip; } catch { /* optional API property */ }
  try { input.tooltip = tooltip; } catch { /* optional API property */ }
  return input;
}

function addSelection(inputs: any, id: string, name: string, tooltip: string,
  filter?: string, maximum = 1): any {
  const input = setTooltip(inputs.addSelectionInput(id, name, tooltip), tooltip);
  try { input.setSelectionLimits(0, maximum); } catch { /* optional */ }
  if (filter) {
    try { input.addSelectionFilter(filter); } catch { /* optional */ }
  }
  return input;
}

function addValue(inputs: any, id: string, name: string, units: string,
  fallback: string, tooltip: string): any {
  const value = adsk.core.ValueInput.createByString(fallback);
  return setTooltip(inputs.addValueInput(id, name, units, value), tooltip);
}

function addString(inputs: any, id: string, name: string, fallback: string,
  tooltip: string): any {
  return setTooltip(inputs.addStringValueInput(id, name, fallback), tooltip);
}

function addDropDown(inputs: any, id: string, name: string, values: string[],
  fallback: string, tooltip: string): any {
  const styles = (adsk.core as any).DropDownStyles;
  const style = styles?.TextListDropDownStyle ?? 0;
  const input = setTooltip(inputs.addDropDownCommandInput(id, name, style), tooltip);
  for (const value of values) {
    try { input.listItems.add(value, value === fallback, ""); } catch { /* optional */ }
  }
  return input;
}

function selectionToken(inputs: any, id: string): string | null {
  const input = inputById(inputs, id);
  const selection = input?.selection?.(0) ?? input?.selection0 ?? null;
  const entity = selection?.entity ?? selection;
  return entity?.entityToken ?? entity?.persistentId ?? null;
}

function selectionTokens(inputs: any, id: string): string[] {
  const input = inputById(inputs, id);
  const count = Number(input?.selectionCount ?? input?.count ?? 0);
  const result: string[] = [];
  for (let i = 0; i < (Number.isFinite(count) ? count : 0); i++) {
    const selection = input?.selection?.(i) ?? input?.[`selection${i}`] ?? null;
    const entity = selection?.entity ?? selection;
    const token = entity?.entityToken ?? entity?.persistentId;
    if (token) result.push(String(token));
  }
  return result;
}

function valueRaw(inputs: any, id: string, fallback: string): string {
  const input = inputById(inputs, id);
  const raw = input?.expression ?? input?.value ?? input?.text;
  return raw == null || raw === "" ? fallback : String(raw);
}

function valueMm(inputs: any, id: string, fallback: string): string {
  const raw = valueRaw(inputs, id, fallback);
  return /^\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*$/u.test(raw) ? `${raw} mm` : raw;
}

function valueNumber(inputs: any, id: string, fallback: number): number {
  const raw = Number(valueRaw(inputs, id, String(fallback)).replace(/mm|deg/giu, "").trim());
  return Number.isFinite(raw) ? raw : fallback;
}

function stringValue(inputs: any, id: string, fallback = ""): string {
  return valueRaw(inputs, id, fallback);
}

function dropdownValue(inputs: any, id: string, fallback: string): string {
  const input = inputById(inputs, id);
  const selected = input?.selectedItem?.name ?? input?.selectedItem?.text;
  return selected == null || selected === "" ? fallback : String(selected);
}

function addSelectionEntry(selections: any[], inputs: any, id: string, role: string): void {
  const token = selectionToken(inputs, id);
  if (token) selections.push({role, entity_token: token});
}

function candidateValues(raw: string): number[] {
  return raw.split(",").map((item) => Number(item.trim().replace(/mm$/iu, "")))
    .filter((item) => Number.isFinite(item));
}

function requestJsonFromNativeInputs(cmdId: string, inputs: any): string {
  const suffix = cmdId.replace("AgentUtilitiesEnclosure_", "");
  const selections: any[] = [];
  const addTarget = (): void => addSelectionEntry(selections, inputs, "target_body", "target_body");
  const addPlane = (id = "plane", role = "plane"): void => addSelectionEntry(selections, inputs, id, role);
  const request: Record<string, any> = {selections};

  if (suffix === "AddEnclosureBoss") {
    const variant = dropdownValue(inputs, "variant", "support");
    request.recipe_family = "boss";
    request.recipe_id = `boss.${variant}`;
    request.variant = variant;
    request.parameters = {outer_diameter: valueMm(inputs, "outer_diameter", "6 mm"), height: valueMm(inputs, "height", "5 mm")};
    request.hardware = {across_flats: valueMm(inputs, "across_flats", ""), depth: valueMm(inputs, "pocket_depth", ""), bore_diameter: valueMm(inputs, "bore_diameter", "")};
    request.context = {material: {family: dropdownValue(inputs, "polymer", "PLA")}, fabrication: {nozzle_diameter: valueMm(inputs, "nozzle_diameter", "0.4 mm")}};
    addTarget(); addPlane(); addSelectionEntry(selections, inputs, "mating_body", "mating_body");
    return JSON.stringify(request);
  }

  if (suffix === "AddSeam") {
    const variant = dropdownValue(inputs, "variant", "lip_groove");
    request.recipe_family = "seam"; request.recipe_id = `seam.${variant}`; request.variant = variant; request.path_mode = "planar_closed_loop";
    request.parameters = {lip_width: valueMm(inputs, "lip_width", "1 mm"), engagement_depth: valueMm(inputs, "engagement_depth", "0.8 mm"), radial_clearance: valueMm(inputs, "radial_clearance", "0.15 mm")};
    addSelectionEntry(selections, inputs, "side_a_body", "side_a_body"); addSelectionEntry(selections, inputs, "side_b_body", "side_b_body"); addSelectionEntry(selections, inputs, "path", "path");
    return JSON.stringify(request);
  }

  if (suffix === "AddRetention") {
    const type = dropdownValue(inputs, "type", "cantilever_parallel");
    request.recipe_family = "retention"; request.recipe_id = `retention.${type}`; request.type = type;
    request.parameters = {beam_length: valueMm(inputs, "beam_length", "5 mm"), beam_width: valueMm(inputs, "beam_width", "2 mm"), beam_thickness: valueMm(inputs, "beam_thickness", "1 mm"), hook_height: valueMm(inputs, "hook_height", "1 mm")};
    addTarget(); addSelectionEntry(selections, inputs, "receiver_body", "receiver_body"); addPlane();
    return JSON.stringify(request);
  }

  if (suffix === "AddSupport") {
    const type = dropdownValue(inputs, "type", "shelf");
    request.recipe_family = "support"; request.recipe_id = `support.${type}`; request.type = type; request.shape = dropdownValue(inputs, "shape", "rectangle");
    request.parameters = {thickness: valueMm(inputs, "thickness", "2 mm"), draft_angle: valueRaw(inputs, "draft_angle", "0 deg")};
    request.dimensions = {width: valueNumber(inputs, "width", 10), height: valueNumber(inputs, "height", 5)};
    addTarget(); addSelectionEntry(selections, inputs, "profile_plane", "profile_plane");
    return JSON.stringify(request);
  }

  if (suffix === "AddReinforcement") {
    const type = dropdownValue(inputs, "type", "straight_rib");
    request.recipe_family = "reinforcement"; request.recipe_id = `reinforcement.${type}`; request.type = type; request.shape = dropdownValue(inputs, "shape", "rectangle");
    request.parameters = {height: valueMm(inputs, "height", "3 mm"), draft_angle: valueRaw(inputs, "draft_angle", "0 deg")};
    request.dimensions = {width: valueNumber(inputs, "width", 2), height: valueNumber(inputs, "profile_height", 5)};
    addTarget(); addSelectionEntry(selections, inputs, "profile_plane", "profile_plane");
    return JSON.stringify(request);
  }

  if (suffix === "AddFitCoupon") {
    const couponType = dropdownValue(inputs, "coupon_type", "sliding_clearance");
    request.recipe_family = "fit_coupon"; request.recipe_id = `fit_coupon.${couponType}`; request.coupon_type = couponType;
    request.parameters = {station_pitch: valueNumber(inputs, "station_pitch", 8), station_size: valueNumber(inputs, "station_size", 5), body_thickness: valueMm(inputs, "body_thickness", "3 mm")};
    request.candidates = candidateValues(stringValue(inputs, "candidates", "-0.1, 0, 0.1, 0.2"));
    addPlane();
    return JSON.stringify(request);
  }

  if (["EditEnclosureFeature", "DeleteEnclosureFeature", "InspectEnclosureFeature"].includes(suffix)) {
    request.feature_id = stringValue(inputs, "feature_id");
    request.operation = suffix.startsWith("Edit") ? "edit" : suffix.startsWith("Delete") ? "delete" : "inspect";
    if (suffix === "EditEnclosureFeature") request.parameter_updates = {};
    return JSON.stringify(request);
  }

  if (suffix === "RecordCouponResult") {
    request.feature_id = stringValue(inputs, "feature_id"); request.result_state = dropdownValue(inputs, "result_state", "measured"); request.chosen_value = valueNumber(inputs, "chosen_value", 0); request.user_observation = stringValue(inputs, "user_observation"); request.operation = "record_coupon_result";
    return JSON.stringify(request);
  }

  if (suffix === "PatternFeature" || suffix === "MirrorFeature") {
    request.operation = suffix === "MirrorFeature" ? "mirror" : "pattern"; request.source_feature_id = stringValue(inputs, "source_feature_id"); request.quantity = valueNumber(inputs, "count", 2); request.pattern_type = dropdownValue(inputs, "pattern_type", "rectangular");
    const axis = selectionToken(inputs, "axis"); const mirrorPlane = selectionToken(inputs, "mirror_plane");
    if (axis) request.axis = axis; if (mirrorPlane) request.mirror_plane = mirrorPlane;
    return JSON.stringify(request);
  }

  if (suffix === "AddCutout") {
    const shape = dropdownValue(inputs, "variant", "rectangle");
    request.recipe_family = "cutout"; request.recipe_id = `cutout.${shape}`; request.shape = shape; request.extent = dropdownValue(inputs, "extent", "through_all"); request.dimensions = {width: valueNumber(inputs, "width", 20), height: valueNumber(inputs, "height", 12)};
    addTarget(); addPlane(); if (shape === "named_profile") addSelectionEntry(selections, inputs, "profile_reference", "profile_reference");
    return JSON.stringify(request);
  }

  if (suffix === "AddVent") {
    const pattern = dropdownValue(inputs, "variant", "rectangular_holes");
    request.recipe_family = "vent"; request.recipe_id = `vent.${pattern}`; request.pattern = pattern; request.boundary_policy = dropdownValue(inputs, "boundary_policy", "clip");
    request.parameters = {aperture: valueNumber(inputs, "aperture", 2), pitch: valueNumber(inputs, "pitch", 4), count_x: valueNumber(inputs, "count_x", 6), count_y: valueNumber(inputs, "count_y", 3)};
    addTarget(); addPlane(); addSelectionEntry(selections, inputs, "mask_body", "mask_body");
    return JSON.stringify(request);
  }

  if (suffix === "AddStrainRelief") {
    const type = dropdownValue(inputs, "variant", "zip_tie_anchor"); const od = valueNumber(inputs, "cable_od", 3);
    request.recipe_family = "strain_relief"; request.recipe_id = `strain_relief.${type}`; request.type = type;
    request.parameters = {slot_width: valueNumber(inputs, "slot_width", 2.5), slot_length: valueNumber(inputs, "slot_length", 5), bridge_width: valueNumber(inputs, "bridge_width", 1.5), bridge_height: valueNumber(inputs, "bridge_height", 4)}; request.cable_spec = {od, bend_radius: valueNumber(inputs, "bend_radius", 5)};
    addTarget(); addPlane();
    return JSON.stringify(request);
  }

  if (suffix === "AddSeal") {
    const type = dropdownValue(inputs, "variant", "flat_gasket_channel");
    request.recipe_family = "seal"; request.recipe_id = `seal.${type}`; request.type = type; request.path_mode = "planar_closed_loop"; request.parameters = {cross_section_width: valueMm(inputs, "cross_section_width", "1.5 mm"), cross_section_depth: valueMm(inputs, "cross_section_depth", "0.8 mm")};
    addTarget(); addPlane(); addSelectionEntry(selections, inputs, "path", "path"); addSelectionEntry(selections, inputs, "sweep_path", "sweep_path"); addSelectionEntry(selections, inputs, "cross_section_plane", "cross_section_plane");
    return JSON.stringify(request);
  }

  if (suffix === "AssignFdmRule") {
    request.recipe_family = "operation"; request.recipe_id = "operation.assign_fdm_rule"; request.parameters = {wall_thickness: valueMm(inputs, "wall_thickness", "2 mm"), draft_angle: valueRaw(inputs, "draft_angle", "0 deg"), nominal_radius: valueMm(inputs, "nominal_radius", "0.5 mm"), clearance: valueMm(inputs, "clearance", "0.15 mm"), polymer: dropdownValue(inputs, "polymer", "PLA"), nozzle_diameter: valueMm(inputs, "nozzle_diameter", "0.4 mm")};
    return JSON.stringify(request);
  }

  const solidOps: Record<string, string> = {AddSolidExtrude: "extrude", AddSolidShell: "shell", AddSolidThicken: "thicken", AddSolidDraft: "draft"};
  if (suffix in solidOps) {
    const type = solidOps[suffix]; request.recipe_family = "operation"; request.recipe_id = `operation.${type}`; request.type = type;
    request.parameters = type === "draft" ? {draft_angle: valueRaw(inputs, "draft_angle", "5 deg")} : {thickness: valueMm(inputs, "thickness", "2 mm"), distance: valueMm(inputs, "distance", "2 mm")};
    addTarget(); if (type === "extrude") addSelectionEntry(selections, inputs, "profile", "profile"); if (type === "shell") addSelectionEntry(selections, inputs, "open_face", "open_face"); if (type === "thicken") addSelectionEntry(selections, inputs, "face", "face"); if (type === "draft") { addSelectionEntry(selections, inputs, "neutral_plane", "neutral_plane"); for (const token of selectionTokens(inputs, "faces")) selections.push({role: "faces", entity_token: token}); }
    return JSON.stringify(request);
  }

  request.recipe_family = suffix.replace(/^Add/, "").toLowerCase(); request.recipe_id = request.recipe_family; addTarget(); addPlane();
  return JSON.stringify(request);
}

function commandResultRoute(commandName: string): "edit" | "delete" | "inspect" | "pattern" | "coupon" | "create" {
  if (commandName === "EditEnclosureFeature") return "edit";
  if (commandName === "DeleteEnclosureFeature") return "delete";
  if (commandName === "InspectEnclosureFeature") return "inspect";
  if (commandName === "PatternFeature" || commandName === "MirrorFeature") return "pattern";
  if (commandName === "RecordCouponResult") return "coupon";
  return "create";
}

async function runCommandRequest(requestJson: string, commandName = ""): Promise<Record<string, any>> {
  const svc = getService();
  switch (commandResultRoute(commandName)) {
    case "edit": return svc.editFeature(requestJson);
    case "delete": return svc.deleteFeature(requestJson);
    case "inspect": return svc.inspectFeature(requestJson);
    case "pattern": return svc.patternOrMirrorFeature(requestJson);
    case "coupon": return svc.recordCouponFeature(requestJson);
    default: return svc.executeOnce(requestJson);
  }
}

/** Non-modal request entry point for agents and tests. */
export async function runRequest(requestJson: string): Promise<Record<string, any>> {
  let commandName = "";
  try {
    const request = JSON.parse(requestJson);
    if (request?.operation === "edit") commandName = "EditEnclosureFeature";
    else if (request?.operation === "delete") commandName = "DeleteEnclosureFeature";
    else if (request?.operation === "inspect") commandName = "InspectEnclosureFeature";
    else if (request?.operation === "mirror" || request?.operation === "pattern" || request?.pattern_type) commandName = "PatternFeature";
    else if (request?.operation === "record_coupon_result" || request?.result_state) commandName = "RecordCouponResult";
  } catch { /* service returns the normal invalid-request refusal */ }
  return runCommandRequest(requestJson, commandName);
}

function humanMessage(result: Record<string, any>): string {
  const refusal = result.refusal;
  if (refusal) {
    let message = `Refused [${refusal.token ?? "unknown"}]: ${refusal.message ?? ""}`;
    if (refusal.recovery) message += `\nRecovery: ${refusal.recovery}`;
    if (refusal.fusion_message) message += `\nFusion: ${refusal.fusion_message}`;
    return message;
  }
  const instance = result.instance ?? {};
  let message = `Created enclosure feature ${instance.display_suffix ?? "?"} (${Array.isArray(result.warnings) ? result.warnings.length : 0} warnings).`;
  for (const warning of result.warnings ?? []) message += `\nWarning: ${warning}`;
  return message;
}

/** Shared handler: staged agent requests never open a modal Fusion dialog. */
async function executeHandler(eventArgs: any): Promise<void> {
  const app = adsk.core.Application.get();
  const ui = app.userInterface;
  const cmdDef = prop(prop(eventArgs, "firingEvent"), "sender");
  const commandName = String(cmdDef?.id ?? "").replace("AgentUtilitiesEnclosure_", "");
  const commandInputs = eventArgs.command?.commandInputs ?? cmdDef?.commandInputs ?? null;
  const nonceInput = commandInputs ? inputById(commandInputs, "dispatch_nonce") : null;
  const nonceHint = nonceInput ? stringValue(commandInputs, "dispatch_nonce") : "";
  let staged: string | null = null;
  try {
    staged = consumePending(nonceHint || undefined);
  } catch (exc) {
    try { ui.messageBox(`Dispatch error: ${exc}`); } catch { /* no UI */ }
    return;
  }
  if (staged !== null) {
    const nonce = lastConsumedNonce();
    try {
      const result = await runCommandRequest(staged, commandName);
      if (nonce) storeResult(nonce, result);
    } catch (exc) {
      if (nonce) {
        try { storeResult(nonce, {operation: "error", refusal: {token: "feature-create-failed", message: String(exc)}}); } catch { /* mailbox may have expired */ }
      }
    }
    return;
  }
  try {
    if (!commandInputs) return;
    const requestJson = requestJsonFromNativeInputs(String(cmdDef?.id ?? ""), commandInputs);
    const result = await runCommandRequest(requestJson, commandName);
    ui.messageBox(humanMessage(result));
  } catch (exc) {
    try { ui.messageBox(`Command error: ${exc}`); } catch { /* no UI */ }
  }
}

function onCommandCreated(cmdIdSuffix: string) {
  return (args: any): void => {
    try {
      const command = args.command;
      const inputs = command.commandInputs;
      const bodies = adsk.fusion.BRepBody.classType?.() ?? "BRepBody";
      const planes = "ConstructionPlane,BRepFace";
      const faces = "BRepFace";
      const addTarget = (): void => addSelection(inputs, "target_body", "Target body", "Select the body this feature modifies.", bodies);
      const addPlane = (id = "plane", label = "Placement plane"): void => addSelection(inputs, id, label, "Select a face or construction plane.", planes);

      if (cmdIdSuffix === "AddEnclosureBoss") {
        addDropDown(inputs, "variant", "Variant", ["support", "screw", "heat_set_insert", "captive_hex_nut", "captive_square_nut", "coordinated_pair", "compression", "tapped", "thread_forming", "pcb_standoff"], "support", "Choose the managed boss hardware variant.");
        addTarget(); addPlane(); addSelection(inputs, "mating_body", "Mating body", "Optional body used as the mating/receiver reference.", bodies);
        addValue(inputs, "outer_diameter", "Outer diameter", "mm", "6 mm", "Boss outside diameter."); addValue(inputs, "height", "Height", "mm", "5 mm", "Boss height or associative extent distance."); addValue(inputs, "across_flats", "Across flats", "mm", "", "Sourced captive-nut across-flats; leave empty to refuse."); addValue(inputs, "pocket_depth", "Pocket depth", "mm", "", "Sourced captive-nut pocket depth; leave empty to refuse."); addValue(inputs, "bore_diameter", "Bore diameter", "mm", "", "Sourced bore diameter; leave empty unless the variant needs it."); addDropDown(inputs, "polymer", "Polymer", ["PLA", "PETG", "ASA", "PCCF", "named"], "PLA", "Material family used for fit-rule inheritance."); addValue(inputs, "nozzle_diameter", "Nozzle diameter", "mm", "0.4 mm", "Fabrication nozzle diameter.");
      } else if (cmdIdSuffix === "AddSeam") {
        addDropDown(inputs, "variant", "Variant", ["lip", "groove", "lip_groove"], "lip_groove", "Seam lip/groove geometry."); addSelection(inputs, "side_a_body", "Side A body", "Select the body receiving the lip.", bodies); addSelection(inputs, "side_b_body", "Side B body", "Select the body receiving the groove.", bodies); addSelection(inputs, "path", "Seam path", "Select the closed-loop seam sketch.", "Sketch"); addValue(inputs, "lip_width", "Lip width", "mm", "1 mm", "Nominal lip width."); addValue(inputs, "engagement_depth", "Engagement depth", "mm", "0.8 mm", "Lip/groove engagement depth."); addValue(inputs, "radial_clearance", "Radial clearance", "mm", "0.15 mm", "Measured or assigned print clearance.");
      } else if (cmdIdSuffix === "AddRetention") {
        addDropDown(inputs, "type", "Type", ["cantilever_parallel", "cantilever_perpendicular", "cantilever_hidden"], "cantilever_parallel", "Retention primitive."); addTarget(); addSelection(inputs, "receiver_body", "Receiver body", "Optional mating receiver body.", bodies); addPlane(); addValue(inputs, "beam_length", "Beam length", "mm", "5 mm", "Cantilever beam length."); addValue(inputs, "beam_width", "Beam width", "mm", "2 mm", "Cantilever beam width."); addValue(inputs, "beam_thickness", "Beam thickness", "mm", "1 mm", "Cantilever beam thickness."); addValue(inputs, "hook_height", "Hook height", "mm", "1 mm", "Retention hook height.");
      } else if (cmdIdSuffix === "AddSupport") {
        addDropDown(inputs, "type", "Type", ["pcb_edge", "pcb_corner", "support_point", "shelf", "landing_pad", "saddle", "cylindrical_cradle", "profile_ledge", "rest"], "shelf", "Support/rest primitive."); addTarget(); addSelection(inputs, "profile_plane", "Profile plane", "Select the support profile plane.", planes); addDropDown(inputs, "shape", "Profile shape", ["rectangle", "circle", "slot", "triangle"], "rectangle", "Sketch profile shape."); addValue(inputs, "thickness", "Thickness", "mm", "2 mm", "Support wall thickness."); addValue(inputs, "draft_angle", "Draft angle", "deg", "0 deg", "Support draft angle."); addValue(inputs, "width", "Width", "mm", "10 mm", "Support profile width."); addValue(inputs, "height", "Height", "mm", "5 mm", "Support profile height.");
      } else if (cmdIdSuffix === "AddReinforcement") {
        addDropDown(inputs, "type", "Type", ["straight_rib", "triangular_web", "gusset", "radial_boss_rib", "wall_floor_rib", "boss_wall_rib", "support_reinforcement"], "straight_rib", "Rib/web/gusset primitive."); addTarget(); addSelection(inputs, "profile_plane", "Profile plane", "Select the reinforcement profile plane.", planes); addDropDown(inputs, "shape", "Profile shape", ["rectangle", "triangle", "trapezoid"], "rectangle", "Sketch profile shape."); addValue(inputs, "height", "Height", "mm", "3 mm", "Reinforcement extrusion height."); addValue(inputs, "draft_angle", "Draft angle", "deg", "0 deg", "Reinforcement draft angle."); addValue(inputs, "width", "Width", "mm", "2 mm", "Profile width."); addValue(inputs, "profile_height", "Profile height", "mm", "5 mm", "Profile height.");
      } else if (cmdIdSuffix === "AddFitCoupon") {
        addDropDown(inputs, "coupon_type", "Coupon type", ["sliding_clearance", "press_fit", "pin_hole", "captive_nut", "heat_set_insert", "lip_groove", "snap_engagement", "dovetail", "connector_cutout"], "sliding_clearance", "Fit-coupon family."); addPlane(); addValue(inputs, "station_pitch", "Station pitch", "mm", "8 mm", "Distance between candidate stations."); addValue(inputs, "station_size", "Station size", "mm", "5 mm", "Nominal station size."); addValue(inputs, "body_thickness", "Body thickness", "mm", "3 mm", "Coupon body thickness."); addString(inputs, "candidates", "Candidates", "-0.1, 0, 0.1, 0.2", "Comma-separated finite candidate offsets in mm.");
      } else if (["EditEnclosureFeature", "DeleteEnclosureFeature", "InspectEnclosureFeature"].includes(cmdIdSuffix)) {
        addString(inputs, "feature_id", "Feature ID", "", "Managed feature identifier.");
      } else if (cmdIdSuffix === "RecordCouponResult") {
        addString(inputs, "feature_id", "Feature ID", "", "Managed coupon feature identifier."); addDropDown(inputs, "result_state", "Result state", ["accepted", "rejected", "stale", "printed", "measured"], "measured", "Observed coupon state."); addValue(inputs, "chosen_value", "Chosen value", "mm", "0 mm", "User-observed selected candidate."); addString(inputs, "user_observation", "Observation", "", "Describe the printed/measured result.");
      } else if (cmdIdSuffix === "PatternFeature" || cmdIdSuffix === "MirrorFeature") {
        addString(inputs, "source_feature_id", "Source feature ID", "", "Managed feature to pattern or mirror."); addValue(inputs, "count", "Count", "unitless", "2", "Pattern instance count."); addDropDown(inputs, "pattern_type", "Pattern type", ["rectangular", "circular", "path"], "rectangular", "Native pattern type."); addSelection(inputs, "axis", "Pattern axis", "Select the pattern axis.", "ConstructionAxis,BRepEdge"); addSelection(inputs, "mirror_plane", "Mirror plane", "Select the mirror plane.", planes);
      } else if (cmdIdSuffix === "AddCutout") {
        addDropDown(inputs, "variant", "Variant", ["rectangle", "rounded_rectangle", "circle", "named_profile"], "rectangle", "Cutout profile shape."); addTarget(); addPlane(); addValue(inputs, "width", "Width", "mm", "20 mm", "Cutout width/diameter."); addValue(inputs, "height", "Height", "mm", "12 mm", "Cutout height."); addDropDown(inputs, "extent", "Extent", ["through_all", "distance", "to_entity"], "through_all", "Cutout extent mode."); addSelection(inputs, "profile_reference", "Named profile", "Existing sketch profile for named-profile cutouts.", "SketchProfile");
      } else if (cmdIdSuffix === "AddVent") {
        addDropDown(inputs, "variant", "Variant", ["linear_slots", "rectangular_holes", "circular_holes", "hexagonal"], "rectangular_holes", "Vent pattern."); addTarget(); addPlane(); addDropDown(inputs, "boundary_policy", "Boundary policy", ["clip", "refuse"], "clip", "Mask boundary handling."); addValue(inputs, "aperture", "Aperture", "mm", "2 mm", "Vent opening size."); addValue(inputs, "pitch", "Pitch", "mm", "4 mm", "Vent pattern pitch."); addValue(inputs, "count_x", "Count X", "unitless", "6", "Vent count along X."); addValue(inputs, "count_y", "Count Y", "unitless", "3", "Vent count along Y."); addSelection(inputs, "mask_body", "Mask body", "Optional clipping mask body.", bodies);
      } else if (cmdIdSuffix === "AddStrainRelief") {
        addDropDown(inputs, "variant", "Variant", ["zip_tie_anchor", "clamp_saddle", "cable_exit_support", "bend_radius_guide", "flexible_fingers", "retention_bridge", "service_loop_retainer", "channel_transition"], "zip_tie_anchor", "Strain-relief primitive."); addTarget(); addPlane(); addValue(inputs, "slot_width", "Slot width", "mm", "2.5 mm", "Zip-tie slot width."); addValue(inputs, "slot_length", "Slot length", "mm", "5 mm", "Zip-tie slot length."); addValue(inputs, "bridge_width", "Bridge width", "mm", "1.5 mm", "Bridge width."); addValue(inputs, "bridge_height", "Bridge height", "mm", "4 mm", "Bridge height."); addValue(inputs, "cable_od", "Cable OD", "mm", "3 mm", "Cable outside diameter."); addValue(inputs, "bend_radius", "Bend radius", "mm", "5 mm", "Cable minimum bend radius.");
      } else if (cmdIdSuffix === "AddSeal") {
        addDropDown(inputs, "variant", "Variant", ["flat_gasket_channel", "o_ring_groove", "compression_stop", "gasket_land"], "flat_gasket_channel", "Seal primitive."); addTarget(); addPlane(); addSelection(inputs, "path", "Seal path", "Select a planar seal path sketch.", "Sketch"); addSelection(inputs, "sweep_path", "Sweep path", "Select a sweep path for non-planar seals.", "SketchCurve"); addSelection(inputs, "cross_section_plane", "Cross-section plane", "Select the seal cross-section plane.", planes); addValue(inputs, "cross_section_width", "Cross-section width", "mm", "1.5 mm", "Seal channel width."); addValue(inputs, "cross_section_depth", "Cross-section depth", "mm", "0.8 mm", "Seal channel depth.");
      } else if (cmdIdSuffix === "AssignFdmRule") {
        addValue(inputs, "wall_thickness", "Wall thickness", "mm", "2 mm", "Assigned FDM wall thickness."); addValue(inputs, "draft_angle", "Draft angle", "deg", "0 deg", "Assigned FDM draft angle."); addValue(inputs, "nominal_radius", "Nominal radius", "mm", "0.5 mm", "Assigned nominal radius."); addValue(inputs, "clearance", "Clearance", "mm", "0.15 mm", "Assigned fit clearance."); addDropDown(inputs, "polymer", "Polymer", ["PLA", "PETG", "ASA", "PCCF", "named"], "PLA", "Assigned material family."); addValue(inputs, "nozzle_diameter", "Nozzle diameter", "mm", "0.4 mm", "Assigned nozzle diameter.");
      } else if (cmdIdSuffix === "AddSolidExtrude" || cmdIdSuffix === "AddSolidShell" || cmdIdSuffix === "AddSolidThicken" || cmdIdSuffix === "AddSolidDraft") {
        addTarget(); if (cmdIdSuffix === "AddSolidExtrude") addSelection(inputs, "profile", "Profile", "Select the sketch profile to extrude.", "SketchProfile"); if (cmdIdSuffix === "AddSolidShell") addSelection(inputs, "open_face", "Open face", "Select the face to remove for the shell.", faces); if (cmdIdSuffix === "AddSolidThicken") addSelection(inputs, "face", "Face", "Select the face to thicken.", faces); if (cmdIdSuffix === "AddSolidDraft") { addSelection(inputs, "neutral_plane", "Neutral plane", "Select the neutral plane.", planes); addSelection(inputs, "faces", "Faces", "Select faces to draft.", faces, 20); } addValue(inputs, cmdIdSuffix === "AddSolidDraft" ? "draft_angle" : "thickness", cmdIdSuffix === "AddSolidDraft" ? "Draft angle" : "Thickness", cmdIdSuffix === "AddSolidDraft" ? "deg" : "mm", cmdIdSuffix === "AddSolidDraft" ? "5 deg" : "2 mm", "Ordinary Fusion operation value."); if (cmdIdSuffix === "AddSolidExtrude") addValue(inputs, "distance", "Distance", "mm", "2 mm", "Extrude distance.");
      }

      const nonceInput = addString(inputs, "dispatch_nonce", "Dispatch nonce", "", "Hidden agent dispatch nonce.");
      try { nonceInput.isVisible = false; } catch { /* optional */ }
      command.execute.add((execArgs: any) => { void executeHandler(execArgs); });
    } catch {
      // Fusion command registration is best-effort across API versions.
    }
  };
}

export function registerCommands(_context?: any): void {
  const app = adsk.core.Application.get();
  const ui = app.userInterface;
  const cmdMgr = ui.commandDefinitions;
  for (const [cmdIdSuffix, displayName, description] of COMMAND_SPECS) {
    const fullId = `AgentUtilitiesEnclosure_${cmdIdSuffix}`;
    let existing: any = null;
    try { existing = cmdMgr.itemById(fullId); } catch { /* API version */ }
    if (existing != null) continue;
    const cmdDef = cmdMgr.addButtonDefinition(fullId, displayName, description + DOCS_TOOLTIP_SUFFIX + "\nSelect native inputs; agents use the same service without a modal dialog.");
    if (cmdDef == null) continue;
    cmdDef.commandCreated.add(onCommandCreated(cmdIdSuffix));
    _registeredDefinitions.push(cmdDef);
  }
}

export function unregisterCommands(_context?: any): void {
  try {
    const cmdMgr = adsk.core.Application.get().userInterface.commandDefinitions;
    for (const cmdDef of _registeredDefinitions) {
      try { cmdMgr.remove(cmdDef); } catch { /* already removed */ }
    }
    _registeredDefinitions.length = 0;
  } catch {
    // Shutdown must never crash the host.
  }
}
