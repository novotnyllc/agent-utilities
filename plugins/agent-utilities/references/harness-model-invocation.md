# Harness defaults and cross-harness model invocation

This reference names the per-harness session defaults, the task shapes each
model is the right answer for, and the concrete host-local mechanisms for
reaching a model on each harness. It is invocation and suitability guidance for
the owning workflow and the human operator.

It does not replace `agent-utilities/model-routing/v1`. The resolver in
[`model-routing.md`](model-routing.md) still owns admission, transport
attestation, budget, and receipts, and nothing here grants a route it has not
admitted.

## Two distinct layers

Keep these separate. Conflating them is the usual source of routing confusion.

| Layer | What it means | Harness-specific? |
| --- | --- | --- |
| Session model | The model the interactive harness runs as for the current turn | Yes |
| Delegated carrier route | The model the router resolves for bounded work handed to a carrier | No |

The router's no-config profile is harness-independent: bounded implementation
resolves to Luna at `max` with `implementationEngine.target:"codex"`, and
orchestration or independent review resolves to Sol, whichever harness asked. A
Claude session that delegates implementation still receives the Luna route.

## Effort is part of the default, not a separate knob

A model name without an effort is an incomplete route. Each row below is a
model-plus-effort pair, and the escalation column is the condition that
justifies moving up.

### Codex / ChatGPT

| Work | Default | Escalate when |
| --- | --- | --- |
| Orchestration, routine review, steering | Sol at `medium` | `high` for genuinely difficult review or cross-cutting planning; `xhigh` for dense multi-constraint reasoning; `max` for high or critical risk and explicitly complex work |
| Implementation | Luna at `max` | already the ceiling |
| Implementation when Luna is unavailable or unselectable | Terra at `max` | already the ceiling; disclosed as `implementation_model_substitute` |
| Long-running orchestration paired with a separate implementation context | Sol at `medium`/`high` driving Terra at `max` | Terra and Sol pair well: Sol holds the plan and review context while Terra carries the bounded implementation |

Sol at `medium` is the working default because most orchestration and steering
turns are not reasoning-bound, and paying `high` on all of them wastes budget
that difficult review turns actually need. Escalate deliberately rather than
starting high.

Terra at `max` is both the attested Luna substitute and the natural
implementation partner for a Sol orchestration context. The resolver never
invents a Terra slug, and no catalog, request, or environment variable can
nominate Terra or mark Luna unavailable; only the trusted host-runtime attestor
can.

### Claude Code

| Work | Default | Escalate when |
| --- | --- | --- |
| Orchestration, interactive depth, difficult cross-family review | Fable at `high` | `xhigh` for difficult review; `max` only with high-risk justification and budget headroom |
| Alternate for the same review role | Opus at `high`/`xhigh` | lower-priority alternate to Fable, not a silent fallback |
| Implementation | Opus at `high` | `xhigh` for dense or cross-cutting work |
| Bounded mechanical implementation | Sonnet | escalate to Opus when ambiguity or risk turns out higher than scoped |

Fable ranks above Opus for appropriate difficult cross-family review; that
ordering is this user's policy, not a universal benchmark claim. Claude review
model identities stay inside the Fable/Opus family aliases, and a numeric
version alone can never cross from Fable to Opus or the reverse. Claude has no
Terra equivalent.

## Published rates and what they imply

Rates are policy input and go stale; every catalog rate carries its source URL,
checked timestamp, and a default 30-day freshness limit. The figures below were
checked 2026-08-05 against provider and OpenRouter listings and are list prices
in USD per million tokens. Re-check before relying on them.

| Model | Input | Output | Context |
| --- | --- | --- | --- |
| `gpt-5.6-luna` | 0.20 | 1.20 | 1M |
| `claude-haiku-4-5` | 1.00 | 5.00 | 200K |
| `glm-5.2` (Z.ai direct API) | 1.40 | 4.40 | 1M |
| `gpt-5.6-terra` | 2.00 | 12.00 | 1M |
| `claude-sonnet-5` | 3.00 | 15.00 | 1M |
| `gpt-5.6-sol` | 5.00 | 30.00 | 1M |
| `claude-opus-5` | 5.00 | 25.00 | 1M |
| `claude-fable-5` | 10.00 | 50.00 | 1M |

Two of these carry promotions with their own expiry: Terra and Luna are listed
at 50% off, and Sonnet 5 has introductory pricing through 2026-08-31. A
promotional rate is not the rate to plan against.

### What these rates do and do not settle

The one claim they do settle: after OpenAI's 2026-07-30 change, **"route to
GLM-5.2 to save money" is not true as a sticker-price argument** — Luna lists
roughly 7x cheaper on input and 3.7x on output.

They settle very little else, and a rate table must not be read as a ranking:

- **Rate is not cost per completed task.** What gets billed is tokens consumed
  to finish the work, including thinking tokens, retries, and extra turns. A
  higher-rate model that finishes in one pass can cost less than a cheaper one
  that needs three.
- **The operating points are not comparable.** Luna at `max` and GLM at `xhigh`
  are different amounts of work per request. Dividing two sticker rates
  compares units that were never the same.
- **The meters are not the same type.** USD per token and Z.ai plan credits do
  not convert (below), so for this host's GLM route there is no shared scalar
  to compare against Luna at all.
- **Cache rates, not list input rates, dominate agentic spend.** These harnesses
  send large stable prefixes every turn — system prompt, tool definitions,
  repository context — so most input tokens are cache reads, billed far below
  list. Anthropic reads at roughly 0.1x with writes at 1.25x (5-minute TTL) or
  2x (1-hour); OpenAI bills cached input at one tenth of standard input with
  writes at 1.25x; Z.ai's Coding Plan credit formula carries its own separate
  cached-input multiplier, and Z.ai's own plan sizing assumes about a 90% cache
  hit rate. A comparison built on uncached list input rates is therefore
  measuring the case that least resembles the actual workload, and the ranking
  it produces can invert once cache behavior is included.

Cache behavior is a property of the workload and the harness, not of the price
list: prefix stability, how often tools or the system prompt change, and TTL
choice move it more than the provider does. That is another reason the decision
belongs with measured outcomes rather than published rates.

So treat the table as one bounded input, never as the decision. Cost ranking
runs only after hard eligibility, and the authority on actual cost is measured
local outcomes — which is what the resolver's learning subsystem accumulates,
keyed by carrier, effort, and billing surface with duration, validated usage,
retry, and verification. Prefer that evidence over arithmetic on list prices.

## What GLM-5.2 is for

Its case does not rest on being cheaper per token, and does not need to:

- **Subscription headroom.** This host reaches GLM through the Z.ai Coding Plan
  (`api/coding/paas/v4`), a monthly subscription metered in plan credits with
  5-hour and weekly ceilings — not per-token USD. Within a quota already paid
  for, marginal token cost is zero. That makes GLM attractive for high-volume
  work *inside* remaining quota, and unattractive the moment the comparison is
  drawn in USD.
- **Provider diversity.** A second independent provider is worth having when
  the primary is rate-limited, degraded, or unavailable.

Credits and USD are different meter types. The router does not convert or add
across meter types without explicit user policy, and it must not: "cheaper in
credits" says nothing about USD, and vice versa. Model GLM on its credit meter,
not by converting to dollars.

Deliberately **not** a selection criterion: published benchmark placements.
Cross-model benchmark claims are weak evidence for routing, they move with
every release, and no eligibility or ranking rule here derives from one. Route
on hard constraints, meter, and measured local outcomes instead.

Its two fixed profiles:

| Profile | Effort | Roles | Adapter context ceiling |
| --- | --- | --- | --- |
| `glm-5-2-scout` | `high` | research, investigation, secondary review | 200,000 tokens |
| `glm-5-2-engineer` | `xhigh` | mechanical implementation, bounded fixes | 200,000 tokens |

The 200,000-token figure is this **host adapter profile's** ceiling, not the
model's capability — GLM-5.2 itself advertises a 1M context window. It is still
a hard eligibility constraint for work routed through these profiles: context
that does not fit the profile is ineligible regardless of cost. Do not restate
it as a model limit.

## Availability detection and caching

GLM availability is host evidence, and it should be discovered once and cached,
not re-checked on every routing decision. The resolver's existing discovery
machinery is the mechanism: negative evidence is scoped to carrier/version,
adapter/version, host/account, and policy digest, with fixed reason classes and
TTLs — transient 60 seconds, auth 5 minutes, missing binary 1 hour, unsupported
24 hours — bounded by `discovery.negativeTtls` and
`discovery.retryAfterMaxSeconds`.

Positive `host_capability_attested` evidence cannot be minted from JSON by the
public CLI; it requires the fixed in-process trusted host attestor and is bound
to carrier/version, adapter/version, host/account, policy digest, expiry,
resolved model, and scoped capabilities. Until that attestation exists,
`glm-5-2-scout` and `glm-5-2-engineer` return `transport_unsupported` and other
work proceeds unaffected. A working shell alias or provider entry is
operator-level evidence that the host mechanism exists; it is not resolver
admission by itself.

## Reaching each model

### GLM-5.2 from Claude Code

Z.ai serves an Anthropic-compatible endpoint, so Claude Code reaches GLM-5.2 by
environment alone. With the Z.ai key in the environment as `ZAI_API_KEY`:

```bash
ANTHROPIC_BASE_URL="https://api.z.ai/api/anthropic" \
ANTHROPIC_AUTH_TOKEN="$ZAI_API_KEY" \
ANTHROPIC_DEFAULT_OPUS_MODEL="glm-5.2" \
ANTHROPIC_DEFAULT_SONNET_MODEL="glm-5.2" \
ANTHROPIC_DEFAULT_HAIKU_MODEL="glm-4.7" \
claude
```

Operators bind this to a `claude-glm` shell alias beside the normal `claude`
alias, so an entire session can run on GLM without disturbing the
Anthropic-backed default. The mapping variables map Claude's tier names onto
Z.ai models: the Opus and Sonnet tiers resolve to `glm-5.2`, and the Haiku tier
resolves to `glm-4.7`, which is what background and title-generation traffic
uses. Environment variables are read at launch, so start a new session.

### GLM-5.2 from Codex

Codex reaches the same model through a configured provider rather than a base
URL:

```toml
[model_providers.zai_litellm]
name = "Z.ai Coding Plan via LiteLLM"
base_url = "http://127.0.0.1:4141/v1"
env_key = "LITELLM_PROXY_API_KEY"
wire_api = "responses"
```

Select it for one invocation without changing the shipped default:

```bash
codex exec -m glm-5.2 -c model_provider=zai_litellm '<prompt>'
```

The local LiteLLM proxy must be running. Its loopback address is a bridge,
never local inference, provider entitlement, or live usage proof.

### Across harnesses

| Direction | Mechanism | Notes |
| --- | --- | --- |
| Claude Code to Codex models | the `codex` plugin's `codex:rescue` skill, forwarding one `task` call to the Codex companion runtime | The rescue subagent is a forwarder, not an orchestrator: one invocation, return its output unchanged. Leave model and effort unset unless the request names them. |
| Codex to Claude models | `claude -p --model <claude-model-id>` | For a read-only Claude subscription review, use only the supported Compound Engineering `-p` adapter and its full contract; do not build a second Claude runner. |

Because both harnesses can reach every model, choosing one is a routing
decision, not a capability constraint.

## Preserve the full capability surface

Changing the model changes the model and nothing else. The session invocations
above intentionally carry no isolation flags, so a GLM session keeps every MCP
server, skill, plugin, hook, and `CLAUDE.md`/`AGENTS.md` instruction the default
session would have loaded. A verified `claude-glm` launch on this host reported
`model: glm-5.2` with 27 MCP servers and 475 tools — the same surface as the
default session.

Do not add `--safe-mode`, `--strict-mcp-config`, `--mcp-config '{"mcpServers":{}}'`,
or `--tools` to a general-purpose GLM session. Those belong to the isolated
review and canary contracts in
[`provider-task-routing.md`](provider-task-routing.md), where stripping
customization is the point. Reusing them for ordinary work silently removes the
capabilities the operator expects.

## Boundaries this reference does not move

- The Claude subscription Fable review preflight still blocks when
  `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, or any
  other third-party provider selector is present in the launch environment. A
  GLM-aliased shell is exactly what that preflight exists to reject, so launch
  subscription reviews from an unaliased one. This is correct behavior, not an
  obstacle to work around.
- GLM is a separate-task profile carrier. Never pass `glm-5.2` to a Codex model
  selector field, `spawn_agent`, or a native-subagent override merely because
  the catalog contains it.
- A documented mechanism is not `live_carrier_verified`. That still requires a
  separately authorized minimal canary or an equivalently bound successful
  adapter receipt.
