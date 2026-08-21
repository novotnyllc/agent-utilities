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
  for (const input of [
    write("/Users/someone/dev/LEDs/power-pod/fusion-project.json"),
    write("/Users/someone/dev/LEDs/power-pod-fusion/DESIGN-STATE.md"),
    write("/Users/someone/dev/LEDs/power-pod-fusion/transactions/09_lid.py"),
    write("/tmp/build/fusion-design-report-verification-abc123-1.json"),
    // Content signal: a generic path whose written content smells of Fusion.
    {
      tool_name: "Write",
      tool_input: {
        file_path: "/tmp/build/verify-report.json",
        content: '{"kind": "verification", "fusion_document": "Pod"}',
      },
    },
    // Edit carries its signal in new_string, not content.
    {
      tool_name: "Edit",
      tool_input: {
        file_path: "/repo/product/DESIGN-STATE.md",
        old_string: "- Fusion document: Not recorded.",
        new_string: "- Fusion document: White Coat - 12V Pod",
      },
    },
  ]) {
    const result = run(input);
    const p = input.tool_input.file_path;
    assert.equal(result.status, 0, p);
    // The model-visible channel: PreToolUse additionalContext JSON on stdout.
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.hookSpecificOutput.hookEventName, "PreToolUse", p);
    assert.match(
      payload.hookSpecificOutput.additionalContext,
      /no persistent artifacts anywhere/,
      p,
    );
    assert.match(
      payload.hookSpecificOutput.additionalContext,
      /automation\/release lane/,
      p,
    );
    // The human channel keeps the same line.
    assert.match(result.stderr, /no persistent artifacts anywhere/, p);
  }
});

test("stays silent inside the skill tree, on unrelated files, and on common names without a Fusion signal", () => {
  for (const p of [
    "/repo/plugins/agent-utilities/skills/fusion-parametric-design/examples/electronics-enclosure/fusion-project.json",
    "/repo/plugins/agent-utilities/skills/fusion-parametric-design/templates/DESIGN-STATE.md",
    "/Users/someone/dev/app/src/main.py",
    "/Users/someone/dev/app/README.md",
    // Other projects legitimately keep these names; without a Fusion signal
    // in the path or content, the nudge stays out of the way.
    "/Users/someone/dev/webapp/DESIGN-STATE.md",
    "/Users/someone/dev/bank/transactions/2026-08.csv",
    "/Users/someone/dev/ci/verify-report.json",
  ]) {
    const result = run(write(p));
    assert.equal(result.status, 0, p);
    assert.equal(result.stdout, "", p);
    assert.equal(result.stderr, "", p);
  }
});

test("ignores other tools and never blocks", () => {
  const bash = run({ tool_name: "Bash", tool_input: { command: "touch DESIGN-STATE.md" } });
  assert.equal(bash.status, 0);
  assert.equal(bash.stdout, "");
  assert.equal(bash.stderr, "");
  const garbage = run("{{{");
  assert.equal(garbage.status, 0);
  assert.equal(garbage.stdout, "");
});
