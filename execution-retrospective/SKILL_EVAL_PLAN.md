# Skill Evaluation Plan

## Purpose

Evaluate whether SC-01 through SC-08 reduce wall time, rework, model/tool cost, and human intervention while preserving or improving correctness, security, verification, and skill compliance. The evaluation must not count fewer tokens as faster unless critical-path wall time also falls.

## Comparison design

Use a controlled A/B protocol:

- **A — baseline:** current Agent Utilities 0.5.5.
- **B — candidate:** 0.5.5 plus the proposed changes.
- Run each scenario at least three times per variant when practical, alternating A/B order.
- Pin repository snapshot, task prompt, model availability, reasoning effort, host class, network/cache warmness, concurrency cap, and native-host availability.
- Record model/provider receipts rather than inferred labels.
- Do not reuse A’s implementation in B except where the scenario explicitly tests resume/recovery.
- Use the same terminal acceptance oracle for both variants.
- A security/correctness failure is not offset by speed or cost improvement.
- Report medians and ranges; for low sample sizes, avoid significance claims.

## Common event schema

Every run should emit a machine-readable event stream with:

```yaml
run:
  variant: A-or-B
  scenario: E1
  start: timestamp
  end: timestamp
  repo_base: sha
  models: []
lanes:
  - id: lane
    owner: model-and-effort
    dependencies: []
    first_receipt_ms: 0
    first_consumed_output_ms: 0
    stopped_reason: completed-or-superseded-or-blocked
gates:
  - command: exact-command
    cwd: exact-cwd
    input_hashes: []
    duration_ms: 0
    result: pass-fail-unavailable
    invalidated_by: null
artifacts:
  - producer: lane
    consumer: lane-or-runtime
    consumed: true
```

## Metrics

### Wall time and critical path

- End-to-end wall-clock duration to the same terminal state.
- Critical-path duration derived from lane dependencies.
- Active model time, tool/process time, external wait, human wait, orchestration wait, and unexplained gaps.
- Time to first meaningful validation: first check that crosses the real integration/runtime boundary, not syntax alone.
- Time from final source mutation to settled verification.

### Duplication and rework

- Duplicate work units: same objective and overlapping inputs with no distinct consumed output.
- Spawned lanes, unique agents, interrupted/superseded lanes, and lanes whose output was never consumed.
- Repeated repository/skill reads after a valid checkpoint.
- Avoidable retries: wrong cwd, wrong toolchain, stale selector, unavailable provider, unclosed stdin, unchanged polling.
- Expensive gate reruns and whether input hashes actually invalidated prior evidence.
- Lines/files reverted or replaced because a prerequisite was discovered late.
- Post-integration fixes and evidence invalidations.

### Model and tool efficiency

- Model usage by functional tier and effort.
- Tokens/cost by lane when available; report unknown rather than infer.
- Time/token to first consumed output.
- No-output budget violations and redirect count.
- Tool calls by category: read/search, edit, test/build, process polling, agent messaging, thread operations.
- Polls returning unchanged state and total polling wall time.

### Human intervention

- Number of outcome-changing questions.
- Number of repeated questions caused by missing state/context.
- Time awaiting required authority versus avoidable clarification.
- User corrections of scope, status, architecture, or completion claims.

### Correctness, completeness, and compliance

- Acceptance criteria passed, including negative security cases.
- Required hosted, native, packaging, installation, upgrade/rollback, release, and post-release gates passed or correctly reported unavailable.
- Residual defects by severity from a blind independent review.
- Plan/objective closure accuracy.
- Skill compliance: correct route, model disclosure, lane ownership, artifact receipt, validation reuse, review independence, terminal-state vocabulary, and no unauthorized mutation.
- False-ready rate: any run labeled complete/review-ready while a required gate is failed, missing, stale, or structurally impossible.

## Scenarios

### E1 — Simple anti-over-orchestration task

**Task:** In a small CLI repository, update one documented default string and its existing focused assertion. No release artifact, schema, native code, or cross-repository coupling changes.

**Expected candidate behavior:**

- Goal Driven Delivery selects the explicit tiny/direct route.
- One agent reads the owning file/caller/test, makes the smallest edit, runs one focused check, and reports.
- No Task Orchestrator DAG, Thermos swarm, runtime-artifact receipt, or model escalation.

**Failure indicators:**

- More than one implementation lane.
- A task manifest larger than the change.
- Broad suite or review swarm without repository requirement.
- SC-01 false positive.

**Primary metrics:** Wall time, tool calls, spawned lanes, prompt/token overhead, correctness, skill compliance.

**Success criterion:** B is not materially slower than A, uses no additional human intervention, and preserves exact correctness. A small fixed overhead under one minute is acceptable only if it comes from a cheap route check.

### E2 — Complex parallel cross-platform plugin delivery

**Task:** Add one typed privileged action to Linux and native Windows in a plugin. The Windows implementation consumes a generated per-RID executable. A supplied plan intentionally omits whether the executable is packaged, and one platform exclusion conflicts with the high-level outcome.

**Expected candidate behavior:**

- SC-02 identifies the platform contradiction before edits.
- SC-01 blocks or repairs the missing build→package→install chain before runtime implementation expands.
- SC-03 produces no more than four durable lanes with clear consumers and one integration owner.
- Shared catalog parsers run before lifecycle suites.
- Final proof includes package/install smoke, hosted CI, and explicitly classified native gates.

**Failure indicators:**

- Runtime feature code grows before artifact closure.
- Three or more scouts return unused work.
- Shared catalog drift is found only by a long platform suite.
- Review-ready is claimed without installable payload or native gate disposition.

**Primary metrics:** Critical-path wall time, first runtime validation, unused lanes, integration fixes, expensive reruns, false-ready rate, final correctness.

**Success criterion:** B reaches a correct blocker or complete delivery faster than A, with zero loss of negative security coverage. A correct early blocker beats a long incomplete implementation.

### E3 — Strong-model escalation task

**Task:** Design and implement a crash-safe credential-rotation state machine spanning a root broker and unprivileged client. The initial requirements contain two conflicting recovery guarantees.

**Expected candidate behavior:**

- Fast model maps repository and existing transaction patterns.
- Sol Max resolves the security/product contradiction and returns a decision artifact.
- Luna Max or verified Terra fallback implements after the contract freezes.
- Independent Sol High/Max reviews the frozen state machine.
- Progress budget is extended for the architecture lane because it produces a decision artifact.

**Failure indicators:**

- Fast model makes the trust decision unaudited.
- Strong model performs mechanical scans/fixtures for most of the run.
- Progress budget kills productive architecture reasoning.
- Multiple reviewers ask the same question.

**Primary metrics:** Model-tier allocation, time to frozen contract, rework after implementation, review findings, security oracle score, wall time.

**Success criterion:** B uses strong models where judgment affects trust, not everywhere; security results equal or exceed A with no material wall-time regression.

### E4 — Fast-model-majority task

**Task:** Update 40 independent versioned fixtures and manifest references after a stable schema version bump. One shared parser assertion and one final integration test exist.

**Expected candidate behavior:**

- One fast/economical mapper emits the mechanical work list.
- One or two non-overlapping fast writers perform the updates.
- Shared parser canary runs immediately; one final integration test runs after freeze.
- Strong model is used only if the parser reveals a semantic ambiguity.

**Failure indicators:**

- Sol Max used for most mechanical edits.
- Per-fixture review/test duplication.
- More lanes than independent file groups.
- Full suite repeated without hash invalidation.

**Primary metrics:** Cost by tier, wall time, duplicate units, gate count, first validation, final correctness.

**Success criterion:** B reduces strong-model usage and cost without increasing critical-path time or fixture defects.

### E5 — Failure, restart, and recovery task

**Task:** Midway through a three-lane delivery, simulate: a no-output implementation worker, provider authentication loss for an optional reviewer, app-server restart after compaction, upstream advancing by five commits, and one long test with observable progress.

**Expected candidate behavior:**

- SC-04 diagnoses and redirects the no-output worker once.
- Optional cross-model review preflight fails quickly; mandatory Sol review continues.
- SC-06 resumes from the provenance/checkpoint receipt without broad reread.
- Healthy long test is preserved, not killed by the progress budget.
- Integration owner checks branch currency at seam freeze and reruns only invalidated gates.

**Failure indicators:**

- Trial-spawn or repeated redirect loops.
- Thread ID accepted without objective/cwd/branch binding.
- Full repo and skills reread after restart.
- Healthy process terminated because it exceeded a wall timer.
- Old evidence reused after conflicting upstream integration.

**Primary metrics:** Recovery time, reread/tool calls, redirects, unchanged polls, evidence invalidations, final correctness, human interventions.

**Success criterion:** B resumes within a bounded interval using the named next command, incurs no duplicate implementation lane, and reaches the same or better final proof than A.

### E6 — Source-only artifact-control scenario

**Task:** Add a pure Python module included by the repository's existing wheel package; no generated/native bytes.

**Expected candidate behavior:** SC-01 records that the ordinary package path already owns the source and proceeds without a special release pipeline.

**Failure indicators:** Candidate blocks merely because packaging exists or demands a signed binary receipt.

**Primary metrics:** False-positive gate rate and wall-time overhead.

## Oracles and blind review

- Product acceptance tests are fixed before A/B execution.
- A blind independent reviewer receives only final repository state, plan, and evidence receipts—not the variant label.
- For security tasks, the oracle includes negative privilege, identity, replay, crash, rollback, and artifact-substitution cases.
- For packaging tasks, the oracle installs from the actual release/plugin mechanism into a clean environment and verifies runtime bytes and version.
- Native requirements must run natively or be reported unavailable; WSL cannot satisfy native Windows proof.

## Analysis method

1. Reject any run with unauthorized mutation or weakened verification.
2. Compare correctness/completeness and false-ready rate first.
3. Compare median critical-path wall time, then end-to-end wall time.
4. Attribute changes to active model, tool/process, external wait, human wait, and orchestration wait.
5. Compare cost only after wall-time and correctness outcomes.
6. Inspect outliers for provider/tool incidents rather than hiding them in averages.
7. Evaluate each change independently where possible, then the full bundle for interaction regressions.

## Regression risks

| Risk | Detection | Mitigation |
| --- | --- | --- |
| Plan admission over-blocks clear work | E1/E6 false blockers | Trigger only on objective-level contradiction or omission |
| Artifact closure becomes release bureaucracy | E1/E6 wall overhead | Skip when ordinary package path already carries runtime source |
| Fewer agents miss independent evidence | E2/E3 defect rate | Preserve unique-output scouts and mandatory independent review |
| Progress budget interrupts deep analysis | E3 artifact quality | Permit declared longer budget with decision receipt |
| Fewer reviews miss security defects | Blind review severity | Keep correctness/security and code-quality purposes distinct |
| Checkpoint manifest becomes stale | E5 resume mismatch | Update only at material transitions and validate hashes on resume |
| Hash reuse hides semantic invalidation | E2/E5 oracle failures | Dependency map includes schema/catalog/public/security boundaries |
| Branch-currency checkpoints create churn | Merge count and rework | Integrate at seam freeze and pre-PR only |
| Optional provider preflight reduces diversity | Cross-model finding delta | Add provider review for a distinct unresolved question when available |

## Promotion criteria

Promote the bundle only if:

- No scenario regresses correctness, security, completeness, or required native/release verification.
- False-ready rate is zero in B.
- E1 and E6 show no material over-orchestration.
- E2 demonstrates earlier artifact/scope failure detection and fewer late rework units.
- E3 preserves strong-model judgment and independent review.
- E4 shifts the majority of mechanical work to economical models without more defects.
- E5 reduces recovery rereads/duplication and does not kill a healthy long process.
- Aggregate median critical-path wall time improves, or remains neutral with a material reliability gain.
