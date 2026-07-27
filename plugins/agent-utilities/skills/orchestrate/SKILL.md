---
name: orchestrate
description: Coordinate multiple agents on large-scope tasks. Use whenever the work is substantial; trivial tasks do not require this skill.
---

# Orchestrate

Remain available to the user while delegating substantive work. Give each agent distinct ownership, prevent overlapping assignments, instruct leaf workers not to delegate, integrate the results, and keep approvals with the user.

On Codex, run narrow, read-only scouts in parallel with `reasoning_effort: "low"` and `fork_turns: "none"`. Use `reasoning_effort: "medium"` for routine implementation and `"high"` for difficult work.

On Claude Code, use the native subagent tool with the closest available model tier and isolated context. Use fast models for narrow read-only scouts, the default model for routine implementation, and the strongest available model for difficult work.
