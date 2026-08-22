/**
 * Ordinary-feature inheritance targets: extrude, shell, thicken, draft.
 * These are operations, not Autodesk PlasticRule objects.
 */

import { adsk } from "@adsk/fas";
import { stampAttributes, ManagedIdentity } from "../identity";
import { requireAdsk } from "./shared";

type Any = any;
type Refusal = [string, string, string];

export type SolidRecipeResult = {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
};

export function executeSolidRecipe(
  component: Any,
  identity: ManagedIdentity,
  request: Record<string, Any>,
): SolidRecipeResult {
  requireAdsk();
  const created: unknown[] = [];
  const warnings: string[] = [];
  const op = String(request.type ?? request.variant ?? "");
  const params: Record<string, Any> = request.parameters ?? {};
  const targetBody = request.target_body;
  if (targetBody == null) {
    return {created, warnings, refusal: ["target-not-found", "Solid operation needs a target body.", "select the body"]};
  }

  if (op === "extrude") {
    const profile = request.profile ?? request.resolved_entities?.profile;
    if (profile == null) {
      return {created, warnings, refusal: ["target-not-found", "Extrude needs a profile.", "select a sketch profile"]};
    }
    const distance = String(params.distance ?? params.thickness ?? "");
    if (!distance) {
      return {created, warnings, refusal: ["invalid-parameter-expression", "Extrude needs distance or an assigned FDM wall thickness.", "assign an FDM rule or supply distance"]};
    }
    const extrudes = component.features.extrudeFeatures;
    const extIn = extrudes.createInput(profile, adsk.fusion.FeatureOperations.JoinFeatureOperation);
    extIn.setDistanceExtent(false, adsk.core.ValueInput.createByString(distance));
    extIn.participantBodies = [targetBody];
    const feat = extrudes.add(extIn);
    if (!feat) {
      return {created, warnings, refusal: ["feature-create-failed", "Extrude failed.", "check profile and distance"]};
    }
    created.push(feat);
  } else if (op === "shell") {
    const thickness = String(params.thickness ?? "");
    if (!thickness) {
      return {created, warnings, refusal: ["invalid-parameter-expression", "Shell needs thickness or an assigned FDM wall thickness.", "assign an FDM rule or supply thickness"]};
    }
    const shells = component.features.shellFeatures;
    if (!shells) {
      return {created, warnings, refusal: ["native-feature-api-unavailable", "ShellFeatures API is unavailable.", "use an ordinary shell in Fusion"]};
    }
    const faces = adsk.core.ObjectCollection.create();
    const openFace = request.open_face ?? request.resolved_entities?.open_face;
    if (openFace) faces.add(openFace);
    const shellIn = shells.createInput(faces, adsk.core.ValueInput.createByString(thickness));
    try { shellIn.participantBodies = [targetBody]; } catch { /* optional */ }
    const feat = shells.add(shellIn);
    if (!feat) {
      return {created, warnings, refusal: ["feature-create-failed", "Shell failed.", "select an open face and thickness"]};
    }
    created.push(feat);
  } else if (op === "thicken") {
    const thickness = String(params.thickness ?? "");
    if (!thickness) {
      return {created, warnings, refusal: ["invalid-parameter-expression", "Thicken needs thickness or an assigned FDM wall thickness.", "assign an FDM rule or supply thickness"]};
    }
    const thickens = component.features.thickenFeatures;
    if (!thickens) {
      return {created, warnings, refusal: ["native-feature-api-unavailable", "ThickenFeatures API is unavailable.", "use an ordinary thicken in Fusion"]};
    }
    const faces = adsk.core.ObjectCollection.create();
    const face = request.face ?? request.resolved_entities?.face;
    if (face) faces.add(face);
    else {
      try {
        for (let i = 0; i < targetBody.faces.count; i++) faces.add(targetBody.faces.item(i));
      } catch { /* fall through */ }
    }
    if (faces.count === 0) {
      return {created, warnings, refusal: ["target-not-found", "Thicken needs faces.", "select a face"]};
    }
    const thickIn = thickens.createInput(faces, adsk.core.ValueInput.createByString(thickness), true, adsk.fusion.FeatureOperations.NewBodyFeatureOperation);
    const feat = thickens.add(thickIn);
    if (!feat) {
      return {created, warnings, refusal: ["feature-create-failed", "Thicken failed.", "check faces and thickness"]};
    }
    created.push(feat);
  } else if (op === "draft") {
    const angle = String(params.draft_angle ?? "");
    if (!angle) {
      return {created, warnings, refusal: ["invalid-parameter-expression", "Draft needs an angle or an assigned FDM draft.", "assign an FDM rule or supply draft_angle"]};
    }
    const drafts = component.features.draftFeatures;
    if (!drafts) {
      return {created, warnings, refusal: ["native-feature-api-unavailable", "DraftFeatures API is unavailable.", "use an ordinary draft in Fusion"]};
    }
    const faces = adsk.core.ObjectCollection.create();
    const srcFaces = request.faces ?? request.resolved_entities?.faces;
    if (Array.isArray(srcFaces)) {
      for (const face of srcFaces) faces.add(face);
    } else if (srcFaces) {
      faces.add(srcFaces);
    } else {
      try {
        for (let i = 0; i < targetBody.faces.count; i++) {
          const face = targetBody.faces.item(i);
          const geo = face?.geometry;
          if (geo && typeof geo.objectType === "string" && !geo.objectType.includes("Plane")) {
            faces.add(face);
          }
        }
      } catch { /* fall through */ }
    }
    if (faces.count === 0) {
      return {created, warnings, refusal: ["target-not-found", "Draft needs side faces.", "select faces to draft"]};
    }
    const draftIn = drafts.createInput();
    const neutral = request.neutral_plane ?? request.resolved_entities?.neutral_plane ?? targetBody.faces.item(0);
    draftIn.setSingleAngle(neutral, faces, false, adsk.core.ValueInput.createByString(angle));
    const feat = drafts.add(draftIn);
    if (!feat) {
      return {created, warnings, refusal: ["feature-create-failed", "Draft failed.", "check faces and angle"]};
    }
    created.push(feat);
  } else {
    return {created, warnings, refusal: ["feature-create-failed", `Unknown solid operation: ${op}`, "use extrude, shell, thicken, or draft"]};
  }

  for (const feat of created) stampAttributes(feat, identity);
  return {created, warnings, refusal: null};
}
