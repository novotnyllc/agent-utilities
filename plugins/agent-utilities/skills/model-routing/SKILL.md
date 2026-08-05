---
name: model-routing
description: "Resolve one bounded model, effort, transport, and budget decision through agent-utilities/model-routing/v1. Use before model-specific task, subagent, provider-review, or steering actions."
---

# Model routing

`agent-utilities:model-routing` is the only public model, effort, budget, and
transport-policy entrypoint. It returns a frozen decision or receipt; it never
creates a task, invokes a provider, runs a browser, or executes a command on a
provider's behalf.

Read [`../../references/model-routing.md`](../../references/model-routing.md)
before using this skill. Its transport phase incorporates the normative
provider-task policy; consumers do not invoke a second router or copy a model
table.

For per-harness session defaults, the concrete GLM-5.2 and cross-harness
invocations, and the capability-preservation rule, see
[`../../references/harness-model-invocation.md`](../../references/harness-model-invocation.md).

## Activation

Resolve `SKILL_DIR` from the activated skill path, then use the sibling plugin
script. Do not infer an installed-cache path or a source checkout.

```bash
ROUTER="$SKILL_DIR/../../scripts/model-routing.mjs"
printf '%s\n' '<request JSON>' | node "$ROUTER"
```

Every request has exact `"contractVersion":"agent-utilities/model-routing/v1"`.
Diagnostics are secret-free; do not put prompts, task titles, paths, source,
files, acknowledgements, tokens, cookies, endpoints, or command text in a
request.

## Lifecycle

1. Classify the bounded destination work: role, categorical work shape,
   adapter/dispatch kind, scope, and privacy. Do not put runtime or transport
   facts in caller JSON: those are fixed in-process attestor facts. Machine
   Utilities may add only the closed content-free `r52` readiness record from
   the reference, with separate execution-host and target-platform identities.
   All three readiness facts must be `ready`; missing, blocked, or unknown
   readiness returns `model_routing_capability_unavailable`.
2. `resolve` reads one immutable policy snapshot. A no-config request uses Sol
   High/Max for orchestration/review and Luna at Max for implementation. Terra
   is returned only after the fixed trusted host-runtime attestor says Luna is
   unavailable or unselectable and identifies a supported Terra-at-Max
   substitute. A catalog, request, or environment variable cannot nominate
   Terra or mark Luna unavailable.
3. For configured work-starting actions, use `admit` with a stable
   caller-generated `requestId`, a frozen ordinary-artifact digest, and every
   applicable task/run/project scope; then use `claim-dispatch` immediately
   before one carrier dispatch. A claim is one-way and cannot authorize a
   retry spawn.
4. The owning workflow invokes only the selected fixed adapter/carrier and
   reconciles its trusted adapter receipt through the embedding's fixed
   in-process receipt importer. The importer must read private adapter evidence
   and bind the complete receipt to the claim's host/account/dispatch/session/
   tool identity. Model output and ordinary caller-authored JSON are not
   receipts. The public CLI has only the source-owned private `receiptId`
   bridge for `oracle-browser` or `oracle-homebrew-lifecycle`. Public stdin and
   `CODEX_*` environment variables are caller-controlled and cannot mint
   visible-task authority or import Codex/native receipts. It does not accept a
   callback, command, module path, executable, or arbitrary adapter importer;
   configured adapters outside those bridges return `transport_unsupported`.
5. Use `status`, `inspect-claim`, local-only `refresh`, and `learning inspect|clear|disable|enable`
   only through this contract. `refresh` never probes a remote provider.

Read the decision's `disclosure` and any `fallbackReceipt` / settlement
disclosure as the content-free R28 record. Its facets explicitly distinguish
requested, configured, observed, and not-applicable values with provenance; do
not reconstruct it from provider output.

For a budget-neutral status/narrowing message, use `resolve` with
`budgetEffect:"none"`, a stable `actionId`, and the exact prior route binding;
it returns a no-model-start receipt, not a reservation. The binding includes
the derived `workClassDigest`, matching `priorWorkClassDigest`, reservation /
claim IDs, selected carrier/model/effort, prior adapter/version, and current
policy digest. Unknown or changed work class blocks inheritance rather than
silently reusing a route. Scope-expanding steering uses `adjust_active`, the
active reservation, and that same binding before sending. Both paths return
the closed action receipt with selected/observed identity, capability
freshness, inheritance/fallback, and bounded budget facts. A neutral message
has `startsWork:false`; an active top-up has `startsWork:true`. The
closed `codex-task-create` to `codex-task-message` transition is supported;
other adapter changes are not. With no resolver-owned live prior route and
work class, including no-config continuation attempts, both forms fail closed
with `prior_route_unknown`.

## Fixed transports

- Native task creation may carry `contextFork:"none"` or a positive decimal
  turn count from `"1"` through `"999"`; `all`, `full-history`, zero, padded,
  numeric, and unknown forms are rejected.
- `glm-5-2-scout` and `glm-5-2-engineer` are separate-task profiles, never
  Codex selector or native-subagent values. Until a callable, host-attested
  profile mechanism exists, they return `transport_unsupported`.
- Fable/Opus are configured review intents only through the selected supported
  Compound Engineering Claude `-p` adapter. This skill does not create a
  parallel Claude runner.
- Oracle uses fixed `oracle-browser`, requested channel
  `chatgpt_current_pro`, and execution surface `chatgpt_standard`. Unknown
  browser authentication can be an admitted attempt when policy permits; a
  login/account-selection result stops with `auth_context_unavailable`. Oracle
  API is unsupported here.
- Oracle lifecycle is a separate `oracle-homebrew-lifecycle` carrier/adapter
  with `lifecycle_action` on `local_host`, never a reused review claim. A
  successful mutation requires an all-zero charged-meter receipt and creates a
  fresh host/account/policy-bound review requirement before review settlement.
- A visible task create needs a one-use `mint-task-authority` receipt from the
  fixed trusted in-process user-turn attestor, with an explicit-user-instruction
  digest. The public CLI cannot mint this authority from stdin or `CODEX_*`
  environment variables; a trusted in-process embedding must provide the
  attestor. Authority, admission, claim, and receipt evidence bind that exact controller plus objective and
  instruction digests, sender, destination, current turn, policy,
  carrier/adapter, and dispatch identity before consuming the sole use. Native
  evidence permits only `started`, `ambiguous`, or `settled`. This is
  cooperative private-state integrity, not a hostile-handoff proof.
- A visible-provider bridge is selected only by the fixed trusted transport
  attestor. Its bootstrap acknowledgement and activation must have the exact
  same host/account/dispatch/session/tool identity; caller transport booleans
  cannot choose or unlock it.

## Harness defaults and GLM

The router's frozen no-config route is harness-independent: implementation
resolves to Luna at `max`, orchestration and review to Sol. That is a
delegation decision, separate from the model the current session runs as.

Session defaults differ by harness, and effort is part of the default. On
Codex/ChatGPT, Sol at `medium` is the working default for orchestration,
routine review, and steering, escalating to `high`/`xhigh` for difficult
reasoning and `max` for high or critical risk; implementation is Luna at `max`;
Terra at `max` is both the attested Luna substitute and the natural
implementation partner for a Sol orchestration context. On Claude Code, Fable
at `high` leads for orchestration and difficult cross-family review with
`xhigh` for hard review and `max` only on high-risk justification plus budget
headroom, Opus is the lower-priority alternate for that role and the default
for implementation, and Sonnet covers bounded mechanical work.

On sticker rate, "route to GLM-5.2 to save money" does not hold after OpenAI's
2026-07-30 change — Luna lists roughly 7x cheaper on input. But a rate table
settles little else: it is not cost per completed task (thinking tokens,
retries, and extra turns are what get billed), Luna at `max` and GLM at `xhigh`
are not the same unit of work, and this host's GLM route bills in Z.ai Coding
Plan credits, which do not convert to USD at all. Treat list prices as one
bounded input, never the decision, and prefer measured local outcomes from the
learning subsystem. GLM's real case is subscription headroom — marginal cost
inside already-paid quota is zero — plus provider diversity when the primary is
rate-limited or degraded.

Published benchmark placements are deliberately not a selection criterion — no
eligibility or ranking rule derives from one. Route on hard constraints, meter,
and measured local outcomes. `glm-5-2-scout` is `high` for research and
investigation; `glm-5-2-engineer` is `xhigh` for mechanical and bounded
implementation; the 200,000-token ceiling both carry is this host adapter
profile's limit, not the model's (GLM-5.2 advertises 1M).

Availability is cached host evidence, not a per-decision probe: discovery's
scoped negative evidence and reason-class TTLs own that, and positive
attestation still requires the trusted in-process host attestor, so the GLM
carriers return `transport_unsupported` until then. Changing the model changes
only the model — a GLM session keeps every MCP server, skill, plugin, and hook,
so never add the isolated review contract's `--safe-mode` or
`--strict-mcp-config` flags to ordinary GLM work. Across harnesses, Claude
reaches Codex models through the `codex` plugin's `codex:rescue` forwarder and
Codex reaches Claude models through `claude -p`. The reference above has the
exact commands, suitability rules, and boundaries.

## Carrier-neutral work-contract metadata

Use `build-work-contract` when a carrier-neutral execution envelope is needed.
Supply only digests for objective, source of truth, scope, constraints,
authorization, acceptance, and stop condition, then select one fixed
carrier/model/effort. The result preserves one invariant digest and adds only
one source-owned presentation overlay: GPT/Sol gets a lean bounded brief; Opus
gets the complete specification and explicit scope/delegation/progress limits;
Fable gets autonomy, pause, evidence, and long-run-memory boundaries; GLM gets
repository standards plus plan/impact/risk/verification; Oracle gets a
self-contained one-shot briefing with complete selected-file context. Direct
user and applicable repository instructions outrank the overlay. The command
never accepts caller or catalog prompt text and never calls a provider. If a
previously frozen invariant digest is supplied and the semantic inputs differ,
it returns `invariant_contract_mutation`.

## Runtime override for unchanged Compound Engineering

Do not edit Compound Engineering to use a route. Instead, the Agent Utilities
owning agent first obtains a frozen decision containing its closed `ceSeam`
object (`id`, fixed CE skill, ordinary artifact schema, and artifact digest)
and `executionOverride`, then attaches the following runtime replacement clause
to that ordinary CE invocation:

> When this unchanged CE instruction normally dispatches its default
> `<executor-or-reviewer>` for the bounded `<seam>`, perform that one step by
> the claimed `<carrier>` path instead. Preserve the same bounded objective,
> input envelope, constraints, and stop condition. Return only the ordinary CE
> `<artifact-schema>` at the same seam, then resume CE unchanged.

The selected carrier may be a GLM separate task or the supported CE Claude
`-p` path. The clause replaces only the one claimed execution mechanism named
by the frozen decision. It is accepted only for the closed artifact-bound
plan/work/debug/code-review/doc-review/POV/PR-review seam catalog and its
listed role/carrier pair. It never changes
CE workflow/persona, plan or legitimacy decisions, canonical writer, review
or merge authority, security/tool policy, artifact contract, verification,
or terminal boundary. It cannot add a child dispatch, commit, push, merge,
credentials, broader filesystem/network authority, or a fallback not in the
frozen decision.

Examples of bounded substitutions are CE research/investigation work through a
claimed GLM scout profile, a pre-legitimized bounded implementation step through
a claimed GLM engineer profile, or an existing read-only CE review seam through
its claimed Claude `-p` binding. If the exact carrier/CE seam is not attested,
return `transport_unsupported` or the disclosed policy fallback/block; do not
try a selector value, a raw `claude -p` command, or an installed CE cache.

## Completion truth

`offline_implementation_ready`, `host_capability_attested`, and
`live_carrier_verified` are distinct. Offline tests prove only the first. The
public CLI cannot mint positive capability evidence from JSON: its fixed local
Oracle probe can attest only the private receipt bridge source and reports
model/auth as `unknown`. It has no native/Codex receipt importer. A closed host
attestor or a bound successful trusted in-process adapter receipt is needed
for stronger evidence. Never call an optional route live-verified without its
separately authorized minimal canary or equivalently bound trusted receipt.
