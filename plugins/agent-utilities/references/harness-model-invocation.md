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

Same work rows on both sides, same escalation ladder, so the two columns are
actually comparable:

| Work | Codex / ChatGPT | Claude Code |
| --- | --- | --- |
| Routine orchestration, steering, status | Sol `medium` | Opus `medium` |
| Bounded mechanical implementation | Luna `medium` | Sonnet `medium` |
| General implementation and agentic coding | Luna `max` | Opus `xhigh` |
| Difficult review, cross-cutting planning | Sol `high` | Fable `high` |
| Highest-stakes reasoning, critical risk | Sol `max` | Fable `max` |
| Long-running implementation under a separate orchestration context | Terra `max` driven by Sol | Opus `xhigh` driven by Fable |

`medium` is the workhorse on both sides, not `high`. Most orchestration and
steering turns are not reasoning-bound, and paying `high` on all of them spends
budget that the genuinely difficult turns need. Escalate deliberately.

That `medium` default is a session-turn statement, not the delegated route.
The router's no-config route for an orchestration or independent-review
handoff stays Sol `high` per the contract: a bounded delegated unit is closer
to the difficult-review row than to an interactive steering turn, and the
resolver's frozen default is code, not this table.

The rows line up because the tiers do: **Fable `high` maps to Sol `high`** —
both are the "this is actually hard" step, not the default. Opus sits where Sol
sits for routine work and where Luna sits for implementation; Sonnet and Luna
share the mechanical tier.

Two places the published guidance overrides a naive symmetry, and both are
worth respecting:

- **Opus at `xhigh` for coding**, not `high`. Anthropic's own guidance is to
  start coding and agentic work at `xhigh`, then sweep down — `low` and
  `medium` punch above their weight on Opus 5, so the sweep is worth running,
  but the starting point is `xhigh`. This is the analog of Luna at `max`.
- **`max` is not a default anywhere.** On both sides it is for critical risk or
  genuinely hardest reasoning, and it can show diminishing returns and
  overthinking. Luna at `max` is the one standing exception: it is the shipped
  implementation route and already at its ceiling.

Terra at `max` is both the Luna substitute and the natural implementation
partner under a Sol orchestration context — Sol holds the plan and review
context while Terra carries the bounded implementation. Fable-over-Opus for
difficult review is this user's ordering, not a benchmark claim; Claude review
identities stay inside the Fable/Opus family aliases, and a version number
alone never crosses between them.

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

## Availability

This section is about direct invocation: the `claude-glm` alias, the
`glm-task` agent, and one-off `codex exec` runs. The router's claimed
`glm-5-2-scout`/`glm-5-2-engineer` carrier routes are a separate layer — the
resolver still fails closed with `transport_unsupported` until its fixed
in-process attestor supplies profile evidence, and nothing here changes that.

For direct invocation, GLM is available when its configuration is present, and
there is no precondition to satisfy before using it:

- **Claude Code** — `ZAI_API_KEY` in the environment. The `claude-glm` alias and
  the `glm-task` agent both read it directly.
- **Codex** — the `zai_litellm` provider block in `config.toml`, plus the local
  LiteLLM proxy running on port 4141.

If the key or the proxy is missing, the command fails with a normal error and
you fix the config. Don't build a detection or caching layer in front of that;
a failed command is the detection, and the configuration is the source of
truth.

## Reaching each model

### GLM-5.2 from Claude Code

Z.ai serves an Anthropic-compatible endpoint, so Claude Code reaches GLM-5.2 by
environment alone. With the Z.ai key in the environment as `ZAI_API_KEY`:

```bash
CLAUDE_CONFIG_DIR="$HOME/.claude-glm" \
ANTHROPIC_BASE_URL="https://api.z.ai/api/anthropic" \
ANTHROPIC_AUTH_TOKEN="$ZAI_API_KEY" \
ANTHROPIC_DEFAULT_OPUS_MODEL="glm-5.2" \
ANTHROPIC_DEFAULT_SONNET_MODEL="glm-5.2" \
ANTHROPIC_DEFAULT_HAIKU_MODEL="glm-4.7" \
claude
```

**Authentication needs a config profile with no login in it.** On a host with
an active `claude.ai` login, that credential outranks any token in the
environment and is sent to Z.ai, which rejects it with a 401 after roughly 210
seconds. The symptom is a command that hangs for minutes and then reports an
authentication failure, which is easy to misread as slowness rather than an
auth fault.

Credential source is not the lever, and neither are the obvious settings:
`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, an `apiKeyHelper` supplied through
`--settings`, `forceLoginMethod`, and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`
all fail identically, because `claude auth status` still reports
`loggedIn: true, authMethod: claude.ai` in every one of them. What works is
removing the login from the profile the process reads: with
`CLAUDE_CONFIG_DIR` pointed at a directory whose `.claude.json` has no
`oauthAccount`, the same command reports `loggedIn: false` and uses the
environment token. Measured here: 401 after 210s without it, a completed reply
in about 10s with it.

Build that profile once (`claude-glm-setup` in the shell config does this):
symlink `plugins` and `skills` from the real config directory, copy
`settings.json`, and copy `.claude.json` with `oauthAccount` removed. Rebuild it
after changing plugins or MCP servers.

`--bare` also fixes the auth precedence and is the wrong tool for it: it drops
plugins, MCP servers, hooks, and `CLAUDE.md` outright, loading no MCP servers
and about three tools. The isolated profile keeps them.

Operators bind this to a `claude-glm` shell alias beside the normal `claude`
alias, so an entire session can run on GLM without disturbing the
Anthropic-backed default. The mapping variables map Claude's tier names onto
Z.ai models: the Opus and Sonnet tiers resolve to `glm-5.2`, and the Haiku tier
resolves to `glm-4.7`, which is what background and title-generation traffic
uses. Environment variables are read at launch, so start a new session.

The cost of `--bare` is real: it also skips plugins, MCP servers, hooks, and
`CLAUDE.md` discovery, so a bare session starts with about three tools and no
MCP servers rather than the full surface. Restore what a given session needs
explicitly with `--mcp-config`, `--plugin-dir`, `--agents`, and `--add-dir`.
There is currently no way to get both keychain-free auth and the implicit full
surface in one flag.

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

## Capability surface

Changing the model should change the model and nothing else. The isolated
profile mostly holds that: measured here, a GLM session through
`~/.claude-glm` loads 5 MCP servers and 60 tools, against 0 and 3 under
`--bare`. It is not yet the full 27 servers and ~475 tools of the default
session — plugin-provided MCP servers need more of the profile reproduced than
symlinked `plugins` and `skills` alone supply. Treat the gap as a known,
closable limitation rather than a property of running on GLM, and do not
describe a GLM session as carrying the identical surface until the profile
actually reproduces it.

Never add `--safe-mode`, `--strict-mcp-config`, `--mcp-config
'{"mcpServers":{}}'`, or `--tools` to ordinary GLM work. Those belong to the
isolated review and canary contracts in
[`provider-task-routing.md`](provider-task-routing.md), where stripping
customization is the point.

## Boundaries this reference does not move

- The Claude subscription Fable review preflight still blocks when
  `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, or any
  other third-party provider selector is present in the launch environment. A
  GLM-aliased shell is exactly what that preflight exists to reject, so launch
  subscription reviews from an unaliased one. This is correct behavior, not an
  obstacle to work around.
- GLM runs as its own process, not as a model value handed to another harness's
  selector. Never pass `glm-5.2` to a Codex model field, `spawn_agent`, or a
  native-subagent override — those select among the models the current session
  already talks to, and GLM is reached by pointing a separate process at Z.ai.
  The `glm-task` agent is the supported way to delegate to it from Claude Code.
