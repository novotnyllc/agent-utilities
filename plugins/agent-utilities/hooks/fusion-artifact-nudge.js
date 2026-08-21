#!/usr/bin/env node
// PreToolUse on Write/Edit: a warn-only reminder of the fusion doctrine's
// artifact rule — ordinary modeling creates no agent-authored persistent host
// artifact anywhere; manifests, DESIGN-STATE files, transaction scripts, and
// verification reports belong to a locked automation/release lane.
//
// Warn only, never block: the lanes are legitimate and this hook cannot know
// which lane is active. Writes inside the skill's own tree (its examples,
// templates, and tests) are its own business and stay silent. Doctrine
// (SKILL.md §1) is the cross-harness authority; this hook is a Claude-side
// mechanical nudge.

const SMELLS = [
  /(^|[\\/])fusion-project\.json$/i,
  /(^|[\\/])DESIGN-STATE\.md$/i,
  /(^|[\\/])transactions[\\/]/i,
  /(^|[\\/])fusion-design-report-[^\\/]*\.json$/i,
  /(^|[\\/])verif(y|ication)-report[^\\/]*\.json$/i,
];

const SKILL_TREE = /skills[\\/]fusion-parametric-design[\\/]/;

function main(raw) {
  try {
    const input = JSON.parse(raw);
    const toolName = typeof input.tool_name === "string" ? input.tool_name : "";
    if (!/^(Write|Edit)$/.test(toolName)) process.exit(0);
    const filePath =
      input.tool_input && typeof input.tool_input.file_path === "string"
        ? input.tool_input.file_path
        : "";
    if (!filePath || SKILL_TREE.test(filePath)) process.exit(0);
    if (SMELLS.some((pattern) => pattern.test(filePath))) {
      process.stderr.write(
        `[fusion-artifact-nudge] ${filePath}: ordinary Fusion modeling writes ` +
          "no persistent artifacts anywhere — confirm an automation/release " +
          "lane is locked before creating this (SKILL.md §1).\n",
      );
    }
  } catch {
    // Warn-only hook: silence on its own confusion.
  }
  process.exit(0);
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  raw += chunk;
});
process.stdin.on("end", () => main(raw));
