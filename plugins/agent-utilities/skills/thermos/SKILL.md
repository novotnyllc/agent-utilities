---
name: thermos
description: "Launch both thermo-nuclear review subagents in parallel, then synthesize their findings. Use for thermos, double thermo review, or combined bug/security and code-quality branch audits."
---

# Thermos

Run the two thermo review passes as async background subagents in parallel, then synthesize their results.

## Provider-task routing

Before launching either model-specific reviewer, apply
`../../references/provider-task-routing.md`. A compatible provider route keeps
the native parallel reviewers below. For an encrypted incompatible or unresolved
cross-provider route, first verify a visible task owned by the target provider,
send its secret-free review contract through the returned task identifier, and
wait for the integrity acknowledgement. That provider task launches both
reviewers provider-locally within its inherited bounds; return its results only
through the same native message and wait path. Never trial-spawn a foreign
reviewer, and block if the required provider task cannot be created, messaged,
acknowledged, or monitored.

## Workflow

1. Determine the review scope from the user request, PR, current branch, or relevant changed files.
2. Gather the diff and any file/context excerpts needed for reviewers to evaluate the change without guessing.
3. Launch both review passes in parallel:
   - Cursor: launch both subagents in the same message with `run_in_background: true`:
     - `subagent_type: "thermo-nuclear-review-subagent"` for bugs, breakages, security, devex regressions, feature-flag leaks, and other branch-audit risks.
     - `subagent_type: "thermo-nuclear-code-quality-review-subagent"` for maintainability, structure, file-size growth, spaghetti, abstractions, and codebase-health risks.
   - Codex: spawn two `explorer` subagents in parallel.
     - For the correctness/security agent, attach or pass the `thermo-nuclear-review` skill. If structured skill attachments are unavailable, read `../thermo-nuclear-review/SKILL.md` relative to this skill and include its instructions in the subagent prompt.
     - For the maintainability agent, attach or pass the `thermo-nuclear-code-quality-review` skill. If structured skill attachments are unavailable, read `../thermo-nuclear-code-quality-review/SKILL.md` relative to this skill and include its instructions in the subagent prompt.
     - Codex spawn calls are background work; wait for both with the available wait tool, then synthesize.
4. Pass each subagent the same scoped diff/file context and ask it to return prioritized findings with file references and evidence.
5. After both finish, synthesize the results with findings first, deduplicated across reviewers. Weight overlapping findings more heavily, resolve disagreements with your own judgment, and keep summaries brief.

If individual background summaries are already visible to the user, do not restate them wholesale. Surface the unified verdict, the highest-signal findings, and any remaining uncertainty.
