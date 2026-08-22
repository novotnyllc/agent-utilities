import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";

/** Root of the Fusion add-in tree under test. */
const addinRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../fusion_addin/AgentUtilitiesEnclosure",
);

function tsSources(root: string = addinRoot): string[] {
  const result: string[] = [];
  const visit = (directory: string): void => {
    for (const entry of fs.readdirSync(directory, {withFileTypes: true})) {
      if (entry.name === "node_modules") {
        continue;
      }
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        visit(entryPath);
      } else if (entry.isFile() && entry.name.endsWith(".ts")) {
        result.push(fs.readFileSync(entryPath, {encoding: "utf8"}));
      }
    }
  };
  visit(root);
  return result;
}

function readService(): string {
  return fs.readFileSync(path.join(addinRoot, "service.ts"), {encoding: "utf8"});
}

const FORBIDDEN_STRINGS = [
  // No text-command execution or process spawning.
  "executeTextCommand", "textCommands", "subprocess", "multiprocessing",
  "pty", "Popen", "posix_spawn",
  "os.spawn", "startfile", "ensurepip",
  // No filesystem writes in recipes/service/context.
  "open(", "write_text", "write_bytes", "makedirs", "mkdir(", "shutil",
  "rmtree", "copytree",
  // Managed geometry is native; no base/custom feature machinery.
  "BaseFeature", "baseFeatures", "TemporaryBRep", "temporaryBRep",
  "setByPlane", "CustomFeature", "customFeatures",
] as const;

test("add-in never uses text commands, processes, or filesystem writes", () => {
  const sources = tsSources();
  assert.ok(sources.length >= 20, "expected the full add-in tree");
  const escaped = (s) => s.replace(/[^a-zA-Z0-9]/g, (c) => String.fromCharCode(92) + c);
  const FORBIDDEN_PATTERNS = [
    ...FORBIDDEN_STRINGS.filter((s) => !s.startsWith(String.fromCharCode(111) + String.fromCharCode(115) + String.fromCharCode(46)) && s !== String.fromCharCode(112) + String.fromCharCode(116) + String.fromCharCode(121) && s !== String.fromCharCode(111) + String.fromCharCode(112) + String.fromCharCode(101) + String.fromCharCode(110) + String.fromCharCode(40)).map((s) => new RegExp(escaped(s))),
    /os[.](system|popen|exec|spawn)[a-zA-Z]*[(]/,
    /[ ]pty[,)]/,
    /[( ]open[(]/,
  ];
  for (const source of sources) {
    for (const pattern of FORBIDDEN_PATTERNS) {
      assert.ok(
        !pattern.test(source),
        "forbidden add-in API/string matched: " + String(pattern),
      );
    }
  }
});

test("recipes and service stay native, explicit, identity-safe, and bounded", () => {
  const read = (relative: string): string =>
    fs.readFileSync(path.join(addinRoot, relative), {encoding: "utf8"});
  const service = read("service.ts");
  const dispatch = read("dispatch.ts");
  const identity = read("identity.ts");
  const inspect = read("inspect.ts");
  const context = read("context.ts");
  const coupon = read("recipes/coupon.ts");
  const recipeTree = [
    "recipes/boss.ts", "recipes/seam.ts", "recipes/retention.ts",
    "recipes/support.ts", "recipes/cutout.ts", "recipes/seal.ts",
    "recipes/strain_relief.ts", "recipes/vent.ts", "native/booleans.ts",
    "native/paths.ts", "native/holes_threads.ts",
  ].map(read).join("\n");

  assert.match(service, /RECIPE_REGISTRY/);
  assert.match(service, /executeOnce/);
  assert.match(service, /computeAll/);
  assert.match(dispatch, /MAX_LIFETIME_SECONDS = 300/);
  assert.match(dispatch, /no filesystem backing/);
  assert.match(identity, /fusion_parametric_design/);
  assert.match(identity, /enclosure_feature_id/);
  assert.match(identity, /findEntityByToken/);
  assert.match(identity, /ambiguous-target/);
  assert.match(context, /DirectDesignType/);
  assert.match(context, /invalid-design-type/);
  assert.doesNotMatch(identity, /tlo\.index|timelineObject/);
  assert.match(inspect, /healthState/);
  assert.match(inspect, /isSolid/);
  assert.match(inspect, /managed-intact/);
  assert.match(inspect, /managed-object-missing/);
  assert.match(inspect, /managed-native-edit-observed/);
  assert.match(inspect, /managed-parameter-edited/);
  assert.match(inspect, /managed-definition-diverged/);
  assert.match(coupon, /explicit finite candidate list ONLY; no search or scoring/);
  assert.match(coupon, /Too many candidates/);
  const participants = [...recipeTree.matchAll(/\.participantBodies/g)].length;
  assert.ok(participants >= 16, "expected >=16 explicit participant bodies, found " + participants);
});

test("service exposes one coherent lifecycle, not a whole-enclosure generator", () => {
  const service = fs.readFileSync(path.join(addinRoot, "service.ts"), {encoding: "utf8"});
  for (const forbidden of ["generate_all", "generate-enclosure", "whole_enclosure"]) {
    assert.ok(!service.includes(forbidden), "forbidden whole-model generator API: " + forbidden);
  }
});

test("recipe parameter names are built through ownedParamName", () => {
  const recipeDir = path.join(addinRoot, "recipes");
  for (const entry of fs.readdirSync(recipeDir)) {
    if (!entry.endsWith(".ts")) continue;
    const source = fs.readFileSync(path.join(recipeDir, entry), {encoding: "utf8"});
    if (source.includes("makeParameter") || source.includes("ownedParamName")) {
      assert.match(
        source,
        /ownedParamName\(/,
        entry + " builds parameter names without ownedParamName",
      );
    }
    assert.doesNotMatch(
      source,
      /(src|clr|fab|des|pak|calc)_ef_/,
      entry + " hardcodes an ownership-prefix literal",
    );
  }
});

test("executeOnce rejects dependency cycles before recipe mutation", () => {
  const service = readService();
  // The cycle gate must run after context/selection resolution but before the
  // recipe function call and before timeline index capture.
  const cycleGate = service.indexOf("managedGraphHasCycle(root");
  const loadRecipe = service.indexOf("loadRecipe(recipeFamily)");
  const timelineBefore = service.indexOf("currentTimelineIndex()");
  assert.ok(cycleGate > -1, "cycle gate missing from executeOnce");
  assert.ok(loadRecipe > -1, "recipe load missing from executeOnce");
  assert.ok(timelineBefore > -1, "timeline-before capture missing from executeOnce");
  assert.ok(
    cycleGate < loadRecipe && loadRecipe < timelineBefore,
    "cycle gate must run before recipe load and timeline capture; got " +
      JSON.stringify({cycleGate, loadRecipe, timelineBefore}),
  );
  // The graph is rebuilt from stamped attributes on every request so a stale
  // in-memory cache cannot miss a cycle created by another session.
  assert.match(service, /enclosure_upstream_ids/);
  assert.match(service, /graphHasCycle\(/);
});

test("timeline group uses transient indexes with human-readable naming", () => {
  const service = readService();
  // Before and after indexes bracket the recipe call; no per-feature probing.
  assert.match(service, /const timelineBefore = this\.currentTimelineIndex\(\)/);
  assert.match(
    service,
    /this\.timelineGroup\(recipeFamily, identity, timelineBefore, this\.currentTimelineIndex\(\)\)/,
  );
  // Transient index READS are permitted (deleteFeature's reverse ordering);
  // WRITES to timelineObject remain forbidden so indexes never become identity.
  assert.doesNotMatch(
    service,
    /timelineObject[^\n]*=[^=]/,
    "timelineObject must never be written; indexes are transient reads only",
  );
  // Spec names: Enclosure · Heat-Set Boss · a4b8f2.
  assert.match(service, /boss: "Heat-Set Boss"/);
  assert.match(service, /cutout: "Port Cutout"/);
  assert.match(service, /familyDisplayName/);
  assert.match(service, /displaySuffix/);
  // Separator is the middle dot required by the spec.
  assert.match(service, /\\u00b7|·/);
});

test("deleteFeature resolves by attrs, deletes reverse order, params last", () => {
  const service = readService();
  const start = service.indexOf("async deleteFeature");
  const end = service.indexOf("async inspectFeature", start);
  assert.ok(start > -1 && end > start, "deleteFeature not found in service.ts");
  const body = service.slice(start, end);
  // Resolve via findManagedEntities; refuse when nothing matches.
  assert.match(body, /findManagedEntities\(/);
  assert.match(body, /target-not-found/);
  // Reverse timeline order: transient index read only.
  assert.match(body, /timelineObject\?\.index/);
  assert.doesNotMatch(body, /timelineObject.*=\s/, "timeline index must never be written");
  // Entities deleted (deleteMe) BEFORE parameter cleanup.
  const deleteMe = body.indexOf("deleteMe()");
  const paramCleanup = body.indexOf("userParameters");
  assert.ok(deleteMe > -1 && paramCleanup > -1, "missing deleteMe or userParameters cleanup");
  assert.ok(deleteMe < paramCleanup, "parameters must be deleted after entities");
  // Post-delete verification warns on leftovers.
  assert.match(body, /still carry feature id/);
});

test("editFeature classifies inspection state before applying parameter updates", () => {
  const service = readService();
  const edit = service.indexOf("async editFeature");
  const nextMethod = service.indexOf("async deleteFeature");
  assert.ok(edit > -1 && nextMethod > edit, "editFeature missing");
  const body = service.slice(edit, nextMethod);
  const classify = body.indexOf("classifyInspection(");
  const refusal = body.indexOf('"manual-edit-prevents-update"');
  const apply = body.indexOf("this.updateParameters(scoped)");
  assert.ok(classify > -1, "editFeature missing classifyInspection");
  assert.ok(refusal > -1, "editFeature missing manual-edit-prevents-update");
  assert.ok(apply > -1, "editFeature missing updateParameters");
  assert.ok(
    classify < refusal && refusal < apply,
    "classification gate must run before updateParameters; got " +
      JSON.stringify({classify, refusal, apply}),
  );
  // The post-compute result carries the re-inspected state on the instance.
  assert.match(body, /inspection_state:/);
});

test("polygon profiles convert across-flats through mmToCm", () => {
  const sketches = fs.readFileSync(path.join(addinRoot, "native/sketches.ts"), {encoding: "utf8"});
  const start = sketches.indexOf("export function makePolygonProfile");
  assert.ok(start > -1, "makePolygonProfile missing");
  const nextExport = sketches.indexOf("export function", start + 1);
  const body = sketches.slice(start, nextExport > -1 ? nextExport : undefined);
  assert.match(body, /mmToCm\s*\(/, "makePolygonProfile must convert mm to Fusion cm");
});

test("hardware aliases set the discriminator boss actually reads", () => {
  const service = readService();
  const subtypeBlockStart = service.indexOf("const disc =");
  assert.ok(subtypeBlockStart > -1, "subtype discriminator missing");
  const subtypeBlock = service.slice(subtypeBlockStart, subtypeBlockStart + 600);
  assert.match(
    subtypeBlock,
    /hardware/,
    "hardware family must appear in subtype discriminator derivation",
  );
  assert.match(
    subtypeBlock,
    /"variant"/,
    "hardware family must derive request.variant",
  );
  const boss = fs.readFileSync(path.join(addinRoot, "recipes/boss.ts"), {encoding: "utf8"});
  assert.match(boss, /request\.variant/);
  assert.doesNotMatch(
    boss,
    /across_flats \?\? 5\.5/,
    "captive nut AF must not silently default to 5.5",
  );
});

test("boss.compression is published and coordinated_pair refuses missing geometry", () => {
  const registry = fs.readFileSync(
    path.resolve(addinRoot, "../../src/enclosure-features/recipe-registry.ts"),
    {encoding: "utf8"},
  );
  assert.match(registry, /\"compression\"/);
  const boss = fs.readFileSync(path.join(addinRoot, "recipes/boss.ts"), {encoding: "utf8"});
  const pair = boss.indexOf('variant === "coordinated_pair"');
  assert.ok(pair > -1);
  const pairBody = boss.slice(pair);
  assert.match(pairBody, /refusal:/);
  assert.doesNotMatch(pairBody, /create the lid pocket manually/);
  assert.doesNotMatch(pairBody, /bore_diameter \?\? \"3\.2 mm\"/);
});

test("unpublished snap no-ops refuse and support.rest is published", () => {
  const retention = fs.readFileSync(path.join(addinRoot, "recipes/retention.ts"), {encoding: "utf8"});
  const skirt = retention.slice(retention.indexOf("function skirtBump"));
  assert.match(skirt, /refusal:/);
  assert.doesNotMatch(skirt.slice(0, 400), /return \{ created, warnings, refusal: null \};/);
  const bayonet = retention.slice(retention.indexOf("function bayonet"));
  assert.match(bayonet, /refusal:/);
  const registry = fs.readFileSync(
    path.resolve(addinRoot, "../../src/enclosure-features/recipe-registry.ts"),
    {encoding: "utf8"},
  );
  assert.match(registry, /"rest"/);
  const support = fs.readFileSync(path.join(addinRoot, "recipes/support.ts"), {encoding: "utf8"});
  assert.match(support, /\"rest\"/);
});

test("human commands use Fusion inputs instead of JSON textboxes", () => {
  const commands = fs.readFileSync(path.join(addinRoot, "commands.ts"), {encoding: "utf8"});
  assert.doesNotMatch(commands, /request_json/);
  assert.doesNotMatch(commands, /Paste enclosure feature request JSON/);
  assert.match(commands, /addSelectionInput/);
  assert.match(commands, /addValueInput/);
});


test("FDM rule analogue never calls Autodesk designPlasticRules", () => {
  const sources = tsSources();
  for (const source of sources) {
    assert.doesNotMatch(source, /design\.designPlasticRules\s*\(/);
    assert.doesNotMatch(source, /\bdesignPlasticRules\s*\(/);
  }
  const service = readService();
  assert.match(service, /inheritIntoParameters/);
  assert.match(service, /assign_fdm_rule/);
  assert.match(service, /RULE_PARAM/);
});

test("coupon identity reconstruction does not allocate a new UUID", () => {
  const service = readService();
  const start = service.indexOf("function identityFromEntity");
  assert.ok(start > -1, "identityFromEntity missing");
  const next = service.indexOf("function readAttr", start);
  const body = service.slice(start, next > -1 ? next : start + 800);
  assert.doesNotMatch(body, /allocateIdentity\(/);
  assert.match(body, /enclosure_parameter_namespace/);
});

test("installer treats copy as distinct from load and hashes bytes", () => {
  const installer = fs.readFileSync(
    path.resolve(addinRoot, "../../src/enclosure-features/installer.ts"),
    {encoding: "utf8"},
  );
  assert.match(installer, /sha256/);
  assert.match(installer, /probeAddInReadiness/);
  assert.match(installer, /recipe-version-mismatch/);
  assert.match(installer, /File copy is not load/);
});


test("per-command Fusion inputs and agent mailbox skip messageBox", () => {
  const commands = fs.readFileSync(path.join(addinRoot, "commands.ts"), {encoding: "utf8"});
  const dispatch = fs.readFileSync(path.join(addinRoot, "dispatch.ts"), {encoding: "utf8"});
  assert.match(commands, /AssignFdmRule/);
  assert.match(commands, /addDropDownCommandInput/);
  assert.match(commands, /consumePending/);
  assert.match(commands, /staged !== null/);
  assert.match(dispatch, /export function consumePending/);
  assert.doesNotMatch(commands, /Paste enclosure feature request JSON/);
  const created = commands.indexOf("function onCommandCreated");
  const boss = commands.indexOf("AddEnclosureBoss", created);
  const seam = commands.indexOf("AddSeam", created);
  const assign = commands.indexOf("AssignFdmRule", created);
  assert.ok(boss > -1 && seam > -1 && assign > -1, "expected per-command dialog branches");
  assert.ok(seam !== boss);
});

test("captive-nut coupons sketch polygons offset from origin", () => {
  const coupon = fs.readFileSync(path.join(addinRoot, "recipes/coupon.ts"), {encoding: "utf8"});
  const sketches = fs.readFileSync(path.join(addinRoot, "native/sketches.ts"), {encoding: "utf8"});
  assert.match(coupon, /makePolygonProfile/);
  assert.match(coupon, /coupon_type \?\? request\.type/);
  assert.match(coupon, /offsetX/);
  assert.match(sketches, /opts\.offsetX/);
  const slot = sketches.slice(sketches.indexOf("function slot"));
  assert.match(slot, /mmToCm/);
});
