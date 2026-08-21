import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const script = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fusion-artifact-nudge.js",
);

function run(stdin) {
  const input = typeof stdin === "string" ? stdin : JSON.stringify(stdin);
  return spawnSync(process.execPath, [script], { input, encoding: "utf8" });
}

const write = (file_path) => ({ tool_name: "Write", tool_input: { file_path } });

test("nudges on ordinary-modeling artifact smells outside the skill tree", () => {
  for (const p of [
    "/Users/someone/dev/LEDs/power-pod/fusion-project.json",
    "/Users/someone/dev/LEDs/DESIGN-STATE.md",
    "/Users/someone/dev/LEDs/transactions/09_lid.py",
    "/tmp/build/fusion-design-report-verification-abc123-1.json",
    "/tmp/verify-report.json",
  ]) {
    const result = run(write(p));
    assert.equal(result.status, 0, p);
    assert.match(result.stderr, /no persistent artifacts anywhere/, p);
    assert.match(result.stderr, /automation\/release lane/, p);
  }
});

test("stays silent inside the skill's own tree and on unrelated files", () => {
  for (const p of [
    "/repo/plugins/agent-utilities/skills/fusion-parametric-design/examples/electronics-enclosure/fusion-project.json",
    "/repo/plugins/agent-utilities/skills/fusion-parametric-design/templates/DESIGN-STATE.md",
    "/Users/someone/dev/app/src/main.py",
    "/Users/someone/dev/app/README.md",
  ]) {
    const result = run(write(p));
    assert.equal(result.status, 0, p);
    assert.equal(result.stderr, "", p);
  }
});

test("ignores other tools and never blocks", () => {
  const bash = run({ tool_name: "Bash", tool_input: { command: "touch DESIGN-STATE.md" } });
  assert.equal(bash.status, 0);
  assert.equal(bash.stderr, "");
  const garbage = run("{{{");
  assert.equal(garbage.status, 0);
});
