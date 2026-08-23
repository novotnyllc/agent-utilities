import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const script = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fusion-script-gate.js",
);

function run(stdin, env = {}) {
  const input = typeof stdin === "string" ? stdin : JSON.stringify(stdin);
  return spawnSync(process.execPath, [script], {
    input,
    encoding: "utf8",
    env: { ...process.env, ...env },
  });
}

const execute = (payload) => ({
  tool_name: "mcp__fusion__fusion_mcp_execute",
  tool_input: { featureType: "script", object: payload },
});

test("blocks every process-invoking construct, marker or not", () => {
  for (const fragment of [
    "import subprocess",
    "os.system('open -a Fusion')",
    "os.execv(path, args)",
    "os.popen('echo hi')",
    "os.spawnl(os.P_NOWAIT, exe)",
    "os.posix_spawn(exe, argv, env)",
    "import pty; pty.spawn(['sh'])",
    "from os import system",
    "from os import path, popen",
    "os . system('echo spaced')",
    "os\n  .\n  execv(path, args)",
    "from posix_things import posix_spawnp\nposix_spawnp(exe, argv, env)",
    "fork()",
    "import os as platform_api\nplatform_api.system('echo hi')",
    "from os import system as run_it",
    "__import__('os').system('echo hi')",
    "from multiprocessing import Pool",
    "Popen(['ls'])",
  ]) {
    const marked = `FUSION_DESIGN_REPORT_BEGIN\n${fragment}\n`;
    const result = run(execute({ script: marked }));
    assert.equal(result.status, 2, fragment);
    assert.match(result.stderr, /second Fusion instance/);
  }
});

test("ensurepip is blocked ad hoc but allowed in shipped lane transactions", () => {
  // The shipped capability probe imports ensurepip by name purely to report
  // whether the module exists; its emitted script carries the lane marker.
  const adhoc = run(execute({ script: "import ensurepip" }));
  assert.equal(adhoc.status, 2);
  const probe = run(
    execute({ script: 'REPORT_BEGIN = "FUSION_DESIGN_REPORT_BEGIN"\nimport ensurepip\n' }),
  );
  assert.equal(probe.status, 0);
});

test("process names in strings, comments, and docstrings are data, not spawns", () => {
  for (const script of [
    "PROJECT_NAME = 'subprocess fixture'\nprint(PROJECT_NAME)",
    "# subprocess would be blocked in code position\nx = 1",
    `"""Docs mention os.system('echo') here."""\nx = 1`,
    "label = \"uses multiprocessing\"  # and Popen in a comment",
  ]) {
    const result = run(execute({ script }));
    assert.equal(result.status, 0, script.slice(0, 40));
    assert.equal(result.stderr, "", script.slice(0, 40));
  }
  // The same token in code position still blocks.
  const real = run(execute({ script: "name = 'harmless'\nimport subprocess" }));
  assert.equal(real.status, 2);
});

test("f-string interpolation expressions are code; literal f-string text is data", () => {
  // The interpolation region executes, so a spawn inside it blocks.
  const hostile = run(
    execute({ script: 'msg = f"result: {os.system(\'echo hi\')}"' }),
  );
  assert.equal(hostile.status, 2);
  // Harmless interpolation and literal text (including {{literal}} braces and
  // process names in the literal part) pass.
  for (const script of [
    'msg = f"count: {len(bodies)} solids"',
    'msg = f"{{literal}} subprocess text stays data"',
  ]) {
    const result = run(execute({ script }));
    assert.equal(result.status, 0, script);
  }
});

test("parenthesized multiline from-os imports still block; benign lists pass", () => {
  const hostile = run(
    execute({ script: "from os import (\n    system,\n)\nsystem('echo hi')" }),
  );
  assert.equal(hostile.status, 2);
  const benign = run(execute({ script: "from os import (\n    path,\n    sep,\n)" }));
  assert.equal(benign.status, 0);
});

test("wildcard os imports block; named benign imports pass", () => {
  const hostile = run(
    execute({ script: "from os import *\nsystem('echo hi')" }),
  );
  assert.equal(hostile.status, 2);
  assert.match(hostile.stderr, /wildcard os import/);
  const benign = run(execute({ script: "from os import path\nprint(path.sep)" }));
  assert.equal(benign.status, 0);
});

test("with stripping disabled the gate degrades to a conservative raw scan", () => {
  const result = run(
    execute({ script: "PROJECT_NAME = 'subprocess fixture'" }),
    { FUSION_GATE_NO_STRIP: "1" },
  );
  assert.equal(result.status, 2);
  assert.match(result.stderr, /DEGRADED: comment\/string stripping unavailable/);
});

test("blocks an oversized ad hoc script with an actionable message", () => {
  const monolith = Array.from({ length: 300 }, (_, i) => `x${i} = ${i}`).join("\n");
  const result = run(execute({ script: monolith }));
  assert.equal(result.status, 2);
  assert.match(result.stderr, /thin-transport bound/);
  assert.match(result.stderr, /one visible edit per snippet/);
  assert.match(result.stderr, /shipped lane tooling/);
});

test("exempts oversized scripts carrying the shipped emitters' marker shape", () => {
  // Pinned against real emitted output: the transaction prelude declares
  // REPORT_BEGIN (single-quoted, near the top), the bootstrap opens with its
  // header comment.
  const prelude =
    "import json\nimport os\nimport adsk.core\n\n" +
    "PROJECT_NAME = 'pod'\nMANIFEST_SHA256 = 'abc'\n" +
    "REPORT_BEGIN = 'FUSION_DESIGN_REPORT_BEGIN'\n";
  for (const head of [
    prelude,
    "# Generated by fusion-design; pass this source to Fusion's Python execution capability.\n",
  ]) {
    const long = head + "y = 1\n".repeat(400);
    const result = run(execute({ script: long }));
    assert.equal(result.status, 0, head.slice(0, 30));
  }
});

test("a forged marker buried mid-script exempts nothing", () => {
  const forged =
    "y = 1\n".repeat(400) +
    'note = "REPORT_BEGIN = \'FUSION_DESIGN_REPORT_BEGIN\'"\n';
  const result = run(execute({ script: forged }));
  assert.equal(result.status, 2);
  assert.match(result.stderr, /thin-transport bound/);
});

test("allows a small clean snippet silently", () => {
  const result = run(execute({ script: "import adsk.core\nprint('ok')" }));
  assert.equal(result.status, 0);
  assert.equal(result.stderr, "");
});

test("a realistic tiny enclosure-dispatcher snippet passes the ordinary lane", () => {
  // The shipped add-in owns the geometry; the MCP side stages one request,
  // executes one command definition, and reads one result. No marker needed.
  const snippet = [
    "import json, uuid",
    "import adsk.core, adsk.fusion",
    "",
    "app = adsk.core.Application.get()",
    "design = adsk.fusion.Design.cast(app.activeProduct)",
    "request = {",
    "    'request_id': str(uuid.uuid4()),",
    "    'recipe': {'recipe_id': 'boss.support', 'version': '1.0.0'},",
    "    'context': {'document_id': design.document.name, 'component_path': 'Base'},",
    "    'selections': [",
    "        {'role': 'target_body', 'kind': 'body', 'component_path': 'Base'},",
    "        {'role': 'placement_origin', 'kind': 'point',",
    "         'component_path': 'Base', 'name': 'Boss Placement'},",
    "        {'role': 'z_axis', 'kind': 'axis', 'component_path': 'Base'},",
    "    ],",
    "    'parameters': [",
    "        {'key': 'outer_diameter',",
    "         'value': {'expression': 'des_boss_od'}, 'ownership': 'design'},",
    "        {'key': 'height', 'value': {'value': 8.0, 'unit': 'mm'},",
    "         'ownership': 'source'},",
    "    ],",
    "}",
    "nonce = _au_enclosure_dispatch_stage(request)",
    "cmd = app.commandDefinitions.itemById('AgentUtilitiesEnclosureAddBoss')",
    "cmd.execute()",
    "result = _au_enclosure_dispatch_result(nonce)",
    "print(json.dumps({'feature_id': result['instance']['feature_id']}))",
  ].join("\n");
  const result = run(execute({ script: snippet }));
  assert.equal(result.status, 0);
  assert.equal(result.stderr, "");
});

test("an oversized whole-enclosure generator attempt stays blocked without a marker", () => {
  const lines = [
    "# whole-enclosure generator: base, lid, seams, bosses, vents, coupons",
    "import adsk.core, adsk.fusion",
    "app = adsk.core.Application.get()",
  ];
  // Push past both the 120-line and 8192-byte ad hoc limits.
  for (let i = 0; i < 300; i += 1) {
    lines.push(`boss_${i} = sketch_circles.addByCenterRadius(plane, ${i})`);
  }
  const result = run(execute({ script: lines.join("\n") }));
  assert.equal(result.status, 2);
  assert.match(result.stderr, /thin-transport bound/);
  assert.match(result.stderr, /one visible edit per snippet/);
});

test("ignores non-fusion and non-execute tools and script-free calls", () => {
  for (const input of [
    { tool_name: "Bash", tool_input: { command: "subprocess" } },
    { tool_name: "mcp__fusion__fusion_mcp_read", tool_input: { queryType: "licensing" } },
    execute({ operation: "open" }),
  ]) {
    const result = run(input);
    assert.equal(result.status, 0);
  }
});

test("fails open with a DEGRADED note on unparseable input", () => {
  const result = run("not json {");
  assert.equal(result.status, 0);
  assert.match(result.stderr, /DEGRADED/);
});

test("reads a top-level tool_input.script too", () => {
  const result = run({
    tool_name: "mcp__fusion360__execute_script",
    tool_input: { script: "import subprocess" },
  });
  assert.equal(result.status, 2);
});

test("ui.messageBox in execute script is always blocked", () => {
  const result = run({
    tool_name: "mcp__fusion__fusion_mcp_execute",
    tool_input: { featureType: "script", object: { script: 'ui.messageBox("hi")' } },
  });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /messageBox/);
});

test("ui.selectEntity in execute script is always blocked", () => {
  const result = run({
    tool_name: "mcp__fusion__fusion_mcp_execute",
    tool_input: { featureType: "script", object: { script: 'ui.selectEntity("Pick a face", "Faces")' } },
  });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /selectEntity/);
});

test("createFileDialog in execute script is always blocked", () => {
  const result = run({
    tool_name: "mcp__fusion__fusion_mcp_execute",
    tool_input: { featureType: "script", object: { script: 'ui.createFileDialog()' } },
  });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /createFileDialog/);
});

test("FileDialog.showSave in execute script is always blocked", () => {
  const result = run({
    tool_name: "mcp__fusion__fusion_mcp_execute",
    tool_input: { featureType: "script", object: { script: 'fileDialog.showSave()' } },
  });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /showSave/);
});

test("receiver-independent messageBox is always blocked", () => {
  const result = run({
    tool_name: "mcp__fusion__fusion_mcp_execute",
    tool_input: { featureType: "script", object: { script: 'app.userInterface.messageBox("hi")' } },
  });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /messageBox/);
});

test("clean print script passes the UI gate", () => {
  const result = run({
    tool_name: "mcp__fusion__fusion_mcp_execute",
    tool_input: { featureType: "script", object: { script: 'def run(ctx): print(42)' } },
  });
  assert.equal(result.status, 0);
});
