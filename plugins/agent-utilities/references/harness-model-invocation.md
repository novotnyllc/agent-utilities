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

## What GLM-5.2 is for

GLM-5.2 is not a manual opt-in for work that would otherwise go to Luna. It is
a suitability-and-cost route: when the work shape fits and the budget component
sees a materially cheaper eligible route, GLM should be selected implicitly,
the same way any other eligible cheaper candidate is.

Select GLM-5.2 when the work is:

- large-volume but routine
- repetitive or mechanical
- well-specified, with the decisions already made
- cleanly decomposable into independent units
- low-ambiguity and low-novelty
- bounded-risk
- strongly verifiable by deterministic checks

Do not select GLM-5.2 — and never let a cheaper GLM route outrank Luna, Terra,
or a current GPT/Claude route — when the work requires architecture, ambiguous
synthesis, novel design, weak or subjective verification, security judgment,
high semantic risk, or workflow authority outside its declared profile. Cost
ranking applies only after hard role, carrier, effort, context, work-shape, and
privacy eligibility have already been satisfied.

Its two fixed profiles:

| Profile | Effort | Roles | Context ceiling |
| --- | --- | --- | --- |
| `glm-5-2-scout` | `high` | research, investigation, secondary review | 200,000 tokens |
| `glm-5-2-engineer` | `xhigh` | mechanical implementation, bounded fixes | 200,000 tokens |

The 200,000-token ceiling is a hard eligibility constraint, not a soft
preference: work whose context does not fit is ineligible regardless of cost.

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
