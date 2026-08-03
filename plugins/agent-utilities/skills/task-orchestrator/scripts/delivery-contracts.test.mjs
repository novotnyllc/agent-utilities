import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const orchestrator = readFileSync(new URL("../SKILL.md", import.meta.url), "utf8");
const delivery = readFileSync(
  new URL("../../goal-driven-delivery/SKILL.md", import.meta.url),
  "utf8",
);

test("freezes shared ownership and hash-bound test evidence", () => {
  assert.match(orchestrator, /one canonical writer for\s+each shared file/);
  assert.match(orchestrator, /both sides of the seam[\s\S]*acknowledge that exact contract/);
  assert.match(orchestrator, /component gate only when that\s+component's content hash changes/);
  assert.match(orchestrator, /one full integration gate; rerun it only when a relevant shared-code\s+fix/);
  assert.match(orchestrator, /prior hash-bound receipts[\s\S]*focused reproductions/);
  assert.match(orchestrator, /one independent reviewer per frozen lane/);
  assert.match(orchestrator, /command,\s+toolchain, input\/content hashes, result, and timestamp/);
});

test("bounds delegation and freezes expansion", () => {
  assert.match(orchestrator, /no inherited context when supported/);
  assert.match(orchestrator, /For mutable seams, include exact owned files and frozen hashes/);
  assert.match(orchestrator, /thinnest end-to-end seam canary/);
  assert.match(orchestrator, /line growth,[\s\S]*execution time,[\s\S]*fixture cost/);
  assert.match(orchestrator, /freeze scope: reject adjacent abstractions/);
});

test("classifies capability and native gates once", () => {
  assert.match(orchestrator, /preferred carrier, model, tools, and skills/);
  assert.match(orchestrator, /choose its supported fallback once/);
  assert.match(orchestrator, /capability required by the selected route blocks\s+dispatch/);
  assert.match(orchestrator, /hosted, locally runnable\s+native, interactive-elevation, or recoverable-host/);
  assert.match(orchestrator, /never infer one class from another/);
  assert.match(orchestrator, /exact local\s+toolchain and CI parity early, once/);
});

test("routes explicit boundaries without changing external carriers", () => {
  assert.match(delivery, /local\/return-to-caller boundary routes through\s+`compound-engineering:ce-work\s+mode:return-to-caller`/);
  assert.match(delivery, /unconstrained end-to-end implementation routes through\s+`compound-engineering:lfg`/);
  assert.match(delivery, /without\s+modifying or patching the carrier/);
  assert.match(delivery, /explicit later local\/return-to-caller stop halt\s+shipping/);
  assert.match(delivery, /later authorized ship instruction replace an earlier local\s+stop/);
  assert.match(delivery, /unless a higher-priority boundary still applies/);
  assert.match(delivery, /Task Orchestrator owns that routing decision/);
  assert.match(delivery, /rather\s+than inferring one from transcript history/);
});

test("enforces the frozen cadence inside a standalone delivery lane", () => {
  assert.match(delivery, /one canonical writer per shared file/);
  assert.match(delivery, /thinnest real seam canary/);
  assert.match(delivery, /component gate only when its input\s+hash changes/);
  assert.match(delivery, /one full integration gate after all writers freeze/);
  assert.match(delivery, /focused\s+reproductions instead of another full-suite run/);
  assert.match(delivery, /when the evidence still\s+matches/);
  assert.match(delivery, /Existing required React, Thermos, CE review, hosted CI, and\s+post-merge gates still apply/);
  assert.match(delivery, /one class never proves another/);
  assert.match(delivery, /required by the selected route blocks instead/);
  assert.match(delivery, /disproportionate line growth, execution time, or fixture\s+cost/);
});
