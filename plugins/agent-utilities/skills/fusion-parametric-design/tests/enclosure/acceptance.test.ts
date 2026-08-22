import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";

import {
  decodeResult,
  encodeResult,
} from "../../src/enclosure-features/request-codec.ts";
import {fixtureResult} from "./fixtures.ts";

/** Root of the Fusion add-in tree under test. */
const addinRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../fusion_addin/AgentUtilitiesEnclosure",
);

function readService(): string {
  return fs.readFileSync(path.join(addinRoot, "service.ts"), {encoding: "utf8"});
}

function readIdentity(): string {
  return fs.readFileSync(path.join(addinRoot, "identity.ts"), {encoding: "utf8"});
}

function readContext(): string {
  return fs.readFileSync(path.join(addinRoot, "context.ts"), {encoding: "utf8"});
}

function readCouponRecipe(): string {
  return fs.readFileSync(path.join(addinRoot, "recipes/coupon.ts"), {encoding: "utf8"});
}

test("direct-design documents are refused before managed creation", () => {
  const service = readService();
  const context = readContext();
  // validateParametricDesign owns the design-type policy; executeOnce must call
  // it before any recipe load or mutation.
  assert.match(
    context,
    /DirectDesignType[\s\S]*invalid-design-type/,
    "context must classify DirectDesignType as invalid-design-type",
  );
  const gate = service.indexOf("validateParametricDesign(ctx)");
  const recipeLoad = service.indexOf("loadRecipe(recipeFamily)");
  assert.ok(gate > -1, "executeOnce must gate on validateParametricDesign");
  assert.ok(recipeLoad > gate, "design-type gate must precede recipe execution");
});

test("deletion refuses while managed dependents exist unless cascaded", () => {
  const service = readService();
  // The guard must run before the destructive-operation warning.
  const dependentGuard = service.indexOf('"managed-dependent-exists"');
  const destructiveWarning = service.indexOf(
    "Destructive operations require Undo acceptance",
  );
  assert.ok(dependentGuard > -1, "deleteFeature missing managed-dependent-exists");
  assert.ok(destructiveWarning > dependentGuard);
  assert.match(service, /deps\.length > 0 && !cascade/);
});

test("unsafe upgrades are refused as manual-edit-prevents-update", () => {
  const service = readService();
  const upgrade = service.indexOf("async upgradeFeature");
  const refusal = service.indexOf('"manual-edit-prevents-update"', upgrade);
  assert.ok(upgrade > -1, "upgradeFeature missing");
  assert.ok(refusal > upgrade);
  assert.match(service, /manual_divergence_detected/);
});

test("upgrade reads the stamped version attribute, not the request claim", () => {
  const service = readService();
  const upgrade = service.indexOf("async upgradeFeature");
  assert.ok(upgrade > -1);
  const stamped = service.indexOf('"enclosure_recipe_version"', upgrade);
  assert.ok(stamped > -1, "upgrade must read enclosure_recipe_version");
  assert.doesNotMatch(
    service.slice(upgrade, stamped),
    /request\.current_version/,
    "stamped lookup must not trust request.current_version",
  );
});

test("unknown recipe families fail closed through feature-create-failed", () => {
  const service = readService();
  const registryCheck = service.indexOf("!(recipeFamily in RECIPE_REGISTRY)");
  const refusal = service.indexOf('"feature-create-failed"', registryCheck);
  assert.ok(registryCheck > -1, "executeOnce must consult RECIPE_REGISTRY");
  assert.ok(refusal > registryCheck);
});

test("unparseable request JSON maps to invalid-parameter-expression", () => {
  const service = readService();
  const parse = service.indexOf("JSON.parse(requestJson)");
  const refusal = service.indexOf('"invalid-parameter-expression"', parse);
  assert.ok(parse > -1 && refusal > parse);
  assert.match(service, /Invalid JSON/);
});

test("identity acquisition and patterns refuse ambiguous targets", () => {
  const identity = readIdentity();
  const service = readService();
  const acquire = identity.indexOf("export function acquireEntity");
  assert.ok(acquire > -1, "identity acquisition missing");
  assert.match(identity.slice(acquire), /findManagedEntities\(component, identity/);
  assert.ok(
    identity.indexOf('"ambiguous-target"', acquire) > acquire,
    "acquireEntity must refuse ambiguous targets",
  );
  const pattern = service.indexOf("async patternOrMirrorFeature");
  const ambiguous = service.indexOf('"ambiguous-target"', pattern);
  assert.ok(pattern > -1);
  assert.ok(ambiguous > pattern);
  assert.match(service.slice(pattern), /Multiple managed features match/);
});

test("patterns accept only rectangular, circular, or path types", () => {
  const service = readService();
  const pattern = service.slice(service.indexOf("async patternOrMirrorFeature"));
  assert.match(
    pattern,
    /\["rectangular", "circular", "path"\]\.includes\(ptype\)/,
  );
  assert.match(pattern, /rectangular\|circular\|path/);
});

test("coupon records require a valid user-observed result", () => {
  const service = readService();
  const coupon = readCouponRecipe();
  const record = service.indexOf("async recordCouponFeature");
  const refusal = service.indexOf('"coupon-required"', record);
  assert.ok(record > -1);
  assert.ok(refusal > record);
  assert.match(coupon, /userObservation/);
  assert.match(coupon, /Accepting requires a user-observed chosen value/);
});

test("wire codec round trip preserves refusal tokens exactly", () => {
  const result = fixtureResult() as {
    warnings: Array<{token: string; message: string; evidence: null}>;
    refusal: null | {
      token: string; message: string; fusion_message: null;
      fusion_exception_type: null; recovery: string; residue: never[];
    };
  };
  result.warnings[0].token = "physical-proof-required";
  result.refusal = {
    token: "coupon-required",
    message: "print and measure the coupon first",
    fusion_message: null,
    fusion_exception_type: null,
    recovery: "record an accepted coupon observation",
    residue: [],
  };
  const roundTrip = decodeResult(encodeResult(result as never));
  assert.deepEqual(roundTrip, result);
  assert.equal(roundTrip.refusal?.token, "coupon-required");
  assert.equal(roundTrip.warnings[0]?.token, "physical-proof-required");
  assert.match(encodeResult(result as never), /"token":"coupon-required"/);
});

// Live-Fusion-only acceptance checks from the spec matrix. They require a real
// document session and cannot be exercised by offline contract tests.
test("Compute All finishes with no new warning/error in the managed group", () => {
  test.skip(); // live-Fusion-only: Compute All clean across positive recipes
});

test("claimed output bodies satisfy BRepBody.isSolid", () => {
  test.skip(); // live-Fusion-only: BRepBody.isSolid inspection of real geometry
});

test("save/reopen retains managed feature relationships", () => {
  test.skip(); // live-Fusion-only: persistence across a real save/reopen cycle
});
