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
