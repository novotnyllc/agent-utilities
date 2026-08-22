import assert from "node:assert/strict";
import test from "node:test";

import {
  emptyAssignedRule,
  fitSensitiveClearanceRefusal,
  inheritExpression,
  inheritIntoParameters,
  isFitSensitiveFamily,
  normalizePolymer,
} from "../../fusion_addin/AgentUtilitiesEnclosure/fdm-rule.ts";

test("rib without override inherits assigned wall thickness expression", () => {
  const rule = emptyAssignedRule();
  rule.assigned = true;
  rule.wall_thickness = "des_ef_rule_wall_thickness";
  rule.draft_angle = "des_ef_rule_draft_angle";
  rule.polymer = "PETG";
  rule.nozzle_diameter = "fab_ef_rule_nozzle_diameter";
  const params: Record<string, unknown> = {};
  inheritIntoParameters("reinforcement", "straight_rib", params, rule);
  assert.equal(params.height, "des_ef_rule_wall_thickness");
  assert.equal(params.draft_angle, "des_ef_rule_draft_angle");
});

test("request override wins over assigned rule thickness", () => {
  const rule = emptyAssignedRule();
  rule.wall_thickness = "des_ef_rule_wall_thickness";
  const params: Record<string, unknown> = {height: "3 mm"};
  inheritIntoParameters("reinforcement", "straight_rib", params, rule);
  assert.equal(params.height, "3 mm");
  assert.equal(inheritExpression("3 mm", "des_ef_rule_wall_thickness"), "3 mm");
});

test("shell and draft inherit the same assigned rule parameters", () => {
  const rule = emptyAssignedRule();
  rule.wall_thickness = "des_ef_rule_wall_thickness";
  rule.draft_angle = "des_ef_rule_draft_angle";
  const shell: Record<string, unknown> = {};
  inheritIntoParameters("operation", "shell", shell, rule);
  assert.equal(shell.thickness, "des_ef_rule_wall_thickness");
  const draft: Record<string, unknown> = {};
  inheritIntoParameters("operation", "draft", draft, rule);
  assert.equal(draft.draft_angle, "des_ef_rule_draft_angle");
});

test("fit-sensitive pocket without sourced clearance refuses", () => {
  const rule = emptyAssignedRule();
  const refusal = fitSensitiveClearanceRefusal("seam", "lip_groove", {}, {}, rule, false);
  assert.ok(refusal);
  assert.equal(refusal[0], "coupon-required");
});

test("stale polymer or nozzle invalidates fit-sensitive claims", () => {
  const rule = emptyAssignedRule();
  rule.assigned = true;
  rule.fit_stale = true;
  rule.clearance = "clr_ef_rule_clearance";
  const refusal = fitSensitiveClearanceRefusal(
    "retention",
    "cantilever_parallel",
    {clearance: "clr_ef_rule_clearance"},
    {},
    rule,
    false,
  );
  assert.ok(refusal);
  assert.match(refusal[1], /stale/);
});

test("sourced fit values are allowed even without a rule", () => {
  const rule = emptyAssignedRule();
  const refusal = fitSensitiveClearanceRefusal(
    "seam",
    "lip_groove",
    {radial_clearance: "0.20 mm"},
    {},
    rule,
    true,
  );
  assert.equal(refusal, null);
});

test("safe_as_default is not a waiver for captive hardware", () => {
  assert.equal(isFitSensitiveFamily("boss", "captive_hex_nut"), true);
  assert.equal(isFitSensitiveFamily("boss", "support"), false);
  assert.equal(normalizePolymer("petg"), "PETG");
  assert.equal(normalizePolymer("Nylon 12"), "Nylon 12");
});
