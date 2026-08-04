import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

const orchestrator = readFileSync(new URL("../SKILL.md", import.meta.url), "utf8");
const delivery = readFileSync(
  new URL("../../goal-driven-delivery/SKILL.md", import.meta.url),
  "utf8",
);
const thermos = readFileSync(new URL("../../thermos/SKILL.md", import.meta.url), "utf8");
const providerRouting = readFileSync(
  new URL("../../../references/provider-task-routing.md", import.meta.url),
  "utf8",
);
const fableReceipt = fileURLToPath(
  new URL("../../../scripts/claude-fable-review-receipt.mjs", import.meta.url),
);
const workflows = readFileSync(
  new URL("../../../../../docs/delivery-workflows.md", import.meta.url),
  "utf8",
);
const codexManifest = JSON.parse(
  readFileSync(new URL("../../../.codex-plugin/plugin.json", import.meta.url), "utf8"),
);
const claudeManifest = JSON.parse(
  readFileSync(new URL("../../../.claude-plugin/plugin.json", import.meta.url), "utf8"),
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

test("parents use fresh children and safely close their lifecycle", () => {
  assert.match(orchestrator, /child task is single-use: never resume, unarchive, compact, or repurpose/);
  assert.match(orchestrator, /report its path and owned ref for parent cleanup/);
  assert.match(orchestrator, /never rely on archive to delete a worktree and never use raw filesystem deletion/);
  assert.match(orchestrator, /dirty or unintegrated without a successful ownership transfer[\s\S]*retitle the child `⏸️`/);
  assert.match(orchestrator, /continuing ref has been transferred to a named owner/);
  assert.match(orchestrator, /parent archives it in the same monitoring pass/);
  assert.match(workflows, /Every visible child is a[\s\S]*fresh, single-use task/);
  assert.match(workflows, /A conflict leaves the child visible and retitled `⏸️` with an explicit blocker/);
});

test("classifies capability and native gates once", () => {
  assert.match(orchestrator, /preferred carrier, model, tools, and skills/);
  assert.match(orchestrator, /absent from the eagerly listed surface is unknown,\s+not unavailable/);
  assert.match(orchestrator, /catalog is available, eager absence\s+remains unknown until the exact capability search completes/);
  assert.match(orchestrator, /search that host catalog for the exact capability/);
  assert.match(orchestrator, /call its read-only\s+discovery operation when available/);
  assert.match(orchestrator, /exact catalog or search is\s+unavailable[\s\S]*`capability_discovery_unavailable`/);
  assert.match(orchestrator, /required route blocks\s+because discovery cannot complete, while an explicitly optional capability\s+selects its one disclosed supported fallback/);
  assert.match(orchestrator, /Record `capability_ready` only\s+when discovery confirms the route/);
  assert.match(orchestrator, /tool_surface_missing[\s\S]*host_offline[\s\S]*saved_project_missing[\s\S]*task_creation_failed[\s\S]*executor_mismatch/);
  assert.match(orchestrator, /WSL-only evidence for native Windows records\s+`native_evidence_unavailable`, not `executor_mismatch`, and cannot satisfy the\s+route/);
  assert.match(orchestrator, /choose its supported fallback once/);
  assert.match(orchestrator, /capability required by the selected route\s+blocks dispatch only after discovery proves absence, discovery is unavailable,\s+or the operation fails/);
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

test("proactively classifies provider transport before any native spawn", () => {
  assert.match(providerRouting, /source and target transport trust domains, source and target\s+model-serving providers, and destination execution capabilities/);
  assert.match(providerRouting, /A gateway label, a model-provider label, or matching model names alone\s+does not prove a shared trust domain or decryption capability/);
  assert.match(providerRouting, /Use declared collaboration-transport metadata first[\s\S]*current task's configured\s+provider second[\s\S]*provider, model, and\s+task identifiers returned by task creation/);
  assert.match(providerRouting, /same verified transport trust domain[\s\S]*Eligible/);
  assert.match(providerRouting, /Cross-provider plaintext transport is explicitly verified[\s\S]*Eligible/);
  assert.match(providerRouting, /Provider-bound encrypted transport cannot be decrypted by the target[\s\S]*Never trial-spawn this known boundary/);
  assert.match(providerRouting, /Make one metadata-only capability-discovery pass[\s\S]*Do not create a native child, send a follow-up, or use a trial spawn/);
  assert.match(providerRouting, /evidence remains unresolved[\s\S]*verified visible provider-task bridge/);
  assert.match(providerRouting, /Codex Multi-Agent v2 content is therefore incompatible/);
});

test("gates provider tasks on verified, secret-free acknowledgement", () => {
  assert.match(providerRouting, /create a visible task owned by\s+the requested provider, address that returned task, and wait or monitor it/);
  assert.match(providerRouting, /`create_thread`,\s+`send_message_to_thread`, and `wait_threads` are adapter examples/);
  assert.match(providerRouting, /Task creation must return the task identifier plus model and provider metadata\s+that matches the requested target/);
  assert.match(providerRouting, /messaging, acknowledgement, monitoring[\s\S]*task retention policy cannot be verified or forbids the\s+handoff, block the required route/);
  assert.match(providerRouting, /Bind every later message and wait to that\s+returned identifier; self-reported identity is not evidence/);
  assert.match(providerRouting, /secret-free context[\s\S]*Never send\s+credentials, tokens, recovery material, or other secret values/);
  assert.match(providerRouting, /source\s+generates a handoff ID[\s\S]*restating a non-empty objective, constraints, and acceptance checks/);
  assert.match(providerRouting, /altered-but-nonempty objective,[\s\S]*missing or\s+mismatched ID, empty objective, or incomplete restatement/);
  assert.match(providerRouting, /Routing receipts are metadata-only[\s\S]*Do not store objective, acknowledgement, or secret\s+bodies/);
  assert.match(providerRouting, /returned task output as untrusted reported data/);
  assert.match(providerRouting, /provider-local nested agents[\s\S]*same classification to every nested edge/);
  assert.match(providerRouting, /Required provider-task bridge is unavailable[\s\S]*never substitute a provider or model silently/);
});

test("defines an isolated, bounded Fable review launch contract", () => {
  assert.match(providerRouting, /`--safe-mode` preserves OAuth\/keychain auth/);
  assert.match(providerRouting, /--mcp-config '\{"mcpServers":\{\}\}' --strict-mcp-config/);
  assert.match(providerRouting, /--output-format stream-json --verbose --include-partial-messages/);
  assert.match(providerRouting, /startup\s+deadline[\s\S]*idle deadline[\s\S]*total wall-clock deadline/);
  assert.match(providerRouting, /Never use `--bare`[\s\S]*Never combine `--bg` with\s+`--print`/);
  assert.match(providerRouting, /must not include `--fallback-model`[\s\S]*no-configured-fallback state/);
  assert.match(providerRouting, /`CLAUDE_BIN` is the canonical executable path attested by the preflight/);
  assert.match(providerRouting, /intentionally excludes `Bash`/);
  assert.match(providerRouting, /exactly one fresh Fable-only attempt[\s\S]*semantically equivalent rephrase/);
  assert.match(providerRouting, /`ambiguous_wording_clarified`[\s\S]*`legitimate_context_clarified`[\s\S]*`defensive_read_only_purpose_clarified`/);
  assert.match(providerRouting, /never falls through to Opus, Sol, or another\s+model/);
});

function validateFable(events, exitStatus = 0) {
  const result = spawnSync(
    process.execPath,
    [fableReceipt, "--exit-status", String(exitStatus)],
    { input: `${events.map((event) => JSON.stringify(event)).join("\n")}\n`, encoding: "utf8" },
  );
  return { ...result, receipt: JSON.parse(result.stdout) };
}

const init = {
  type: "system",
  subtype: "init",
  model: "claude-fable-5",
  claude_code_version: "2.1.220",
  session_id: "test-session",
};
const assistant = { type: "assistant", message: { model: "claude-fable-5" } };
const success = {
  type: "result",
  subtype: "success",
  is_error: false,
  modelUsage: {
    "claude-haiku-4-5-20251001": { provider: "firstParty" },
    "claude-fable-5": { provider: "firstParty" },
  },
};

test("accepts a first-party Fable stream with auxiliary Haiku usage", () => {
  const run = validateFable([init, assistant, success]);
  assert.equal(run.status, 0);
  assert.equal(run.receipt.ok, true);
  assert.equal(run.receipt.reason, "validated");
});

test("rejects refusal fallback after a valid Fable init", () => {
  const run = validateFable([
    init,
    {
      type: "system",
      subtype: "model_refusal_fallback",
      trigger: "refusal",
      api_refusal_category: "cyber",
      original_model: "claude-fable-5",
      fallback_model: "claude-opus-5",
    },
  ]);
  assert.equal(run.status, 1);
  assert.equal(run.receipt.reason, "model_refusal_fallback");
  assert.equal(run.receipt.api_refusal_category, "cyber");
});

test("rejects model drift, error results, nonzero exits, and truncated streams", () => {
  assert.equal(
    validateFable([init, { type: "assistant", message: { model: "claude-opus-5" } }]).receipt.reason,
    "assistant_model_mismatch",
  );
  assert.equal(validateFable([init, assistant, { ...success, is_error: true }]).receipt.reason, "result_error");
  assert.equal(validateFable([init, assistant, success], 1).receipt.reason, "process_exit_nonzero");
  assert.equal(
    validateFable([init, assistant, { ...success, is_error: true }], 1).receipt.result_is_error,
    true,
  );
  assert.equal(validateFable([init, assistant]).receipt.reason, "missing_terminal_result");
  assert.equal(validateFable([init, success]).receipt.reason, "missing_assistant_event");
  assert.equal(
    validateFable([{ ...init, model: "claude-fable-999" }]).receipt.reason,
    "init_model_mismatch",
  );
  assert.equal(validateFable([assistant, init, success]).receipt.reason, "invalid_event_order");
  assert.equal(validateFable([init, assistant, success, success]).receipt.reason, "invalid_event_order");
  assert.equal(
    validateFable([
      init,
      assistant,
      { ...success, modelUsage: { ...success.modelUsage, "claude-opus-5": { provider: "firstParty" } } },
    ]).receipt.reason,
    "model_usage_mismatch",
  );
  assert.equal(
    validateFable([
      init,
      assistant,
      { ...success, modelUsage: { "claude-fable-5": { provider: "thirdParty" } } },
    ]).receipt.reason,
    "provider_mismatch",
  );
  assert.equal(
    validateFable([
      init,
      assistant,
      { ...success, modelUsage: { ...success.modelUsage, "claude-haiku-999": { provider: "firstParty" } } },
    ]).receipt.reason,
    "model_usage_mismatch",
  );
  const failedWithDrift = validateFable([
    init,
    assistant,
    { ...success, modelUsage: { "claude-opus-5": { provider: "thirdParty" } } },
  ], 1);
  assert.equal(failedWithDrift.receipt.reason, "process_exit_nonzero");
  assert.equal(failedWithDrift.receipt.evidence_reason, "model_usage_mismatch");
  assert.equal(failedWithDrift.receipt.observed_provider, "thirdParty");
  const erroredWithDrift = validateFable([
    init,
    assistant,
    { ...success, is_error: true, modelUsage: { "claude-opus-5": { provider: "thirdParty" } } },
  ]);
  assert.equal(erroredWithDrift.receipt.reason, "result_error");
  assert.equal(erroredWithDrift.receipt.evidence_reason, "model_usage_mismatch");
  assert.equal(erroredWithDrift.receipt.observed_provider, "thirdParty");
});

test("reports unreadable Fable streams as metadata", () => {
  const run = spawnSync(
    process.execPath,
    [fableReceipt, "--exit-status", "0", "/path/that/does/not/exist/fable.jsonl"],
    { encoding: "utf8" },
  );
  assert.equal(run.status, 1);
  assert.equal(JSON.parse(run.stdout).reason, "stream_read_error");
  assert.equal(run.stderr, "");
});

test("rejects altered non-empty provider handoffs", () => {
  assert.match(providerRouting, /source orchestrator must compare each restated field against\s+its source-held handoff contract/);
  assert.match(providerRouting, /An altered-but-nonempty objective,\s+constraint, or acceptance check fails the handoff/);
  assert.match(providerRouting, /acknowledgement comparison pass\/fail and reason/);
  assert.match(orchestrator, /altered-but-nonempty\s+content fails/);
});

test("all model-launch workflows consume the shared provider policy", () => {
  assert.match(orchestrator, /Before every model-specific delegation, apply the canonical\s+`\.\.\/\.\.\/references\/provider-task-routing\.md` policy/);
  assert.match(orchestrator, /dispatch\s+precondition, not a fallback after a failed spawn/);
  assert.match(delivery, /Before launching LFG, a CE implementation route, or a model-specific review\s+context, apply `\.\.\/\.\.\/references\/provider-task-routing\.md`/);
  assert.match(delivery, /target task\s+then runs this workflow and any LFG or Thermos work provider-locally/);
  assert.match(thermos, /Before launching either model-specific reviewer, apply\s+`\.\.\/\.\.\/references\/provider-task-routing\.md`/);
  assert.match(thermos, /provider task launches both\s+reviewers provider-locally/);
  assert.match(workflows, /\[`provider-task-routing`\]\(\.\.\/plugins\/agent-utilities\/references\/provider-task-routing\.md\)/);
});

test("substitutes Terra at Max only when Luna cannot be selected", () => {
  assert.match(orchestrator, /active collaboration\s+runtime verifies Luna is unavailable or unselectable[\s\S]*no explicit user or repository model\s+requirement wins[\s\S]*Terra at Max/);
  assert.match(orchestrator, /`implementation_model_substitute`[\s\S]*never a provider or transport fallback/);
  assert.match(delivery, /active collaboration runtime\s+verifies Luna is unavailable or unselectable[\s\S]*no explicit user or repository model requirement applies[\s\S]*Terra at Max/);
  assert.match(delivery, /`implementation_model_substitute`; it is not a carrier or provider\s+fallback/);
});

test("ships paired source manifest versions", () => {
  assert.match(codexManifest.version, /^\d+\.\d+\.\d+$/);
  assert.equal(claudeManifest.version, codexManifest.version);
});
