# Charter and boundaries

`agent-utilities` is the toolbox: self-contained craft skills any single agent
session can pick up — how to drive a browser, design a CLI or a frontend,
profile a native app, handle 1Password secrets, or audit skills.

## Belongs here

Skills that are useful on their own, carry their own references and scripts
inside their skill directory, and have no coupling to routing, orchestration,
or the fleet.

## Belongs elsewhere

Everything about delivering work — model routing, delivery, orchestration,
cross-machine placement, review gates, Oracle, and Codex runtime hygiene —
lives in [`railyard`](https://github.com/novotnyllc/railyard). Fleet
readiness, machine administration, and UniFi live in
[`roundhouse`](https://github.com/novotnyllc/roundhouse).

If a new skill needs the router, the fleet CLI, or dispatch semantics, it
goes there, not here.
