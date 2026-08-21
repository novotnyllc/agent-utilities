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

// Unambiguously this skill's artifacts, wherever they land.
const FUSION_SMELLS = [
  /(^|[\\/])fusion-project\.json$/i,
  /(^|[\\/])fusion-design-report-[^\\/]*\.json$/i,
];

// Common names that only smell of Fusion work in a Fusion context: other
// projects legitimately have DESIGN-STATE files, transactions/ dirs, and
// verify reports, so these fire only when the path or the written content
// carries a Fusion signal. Scopes the nudge to active Fusion work instead of
// nagging every repo the plugin is enabled in.
const CONTEXT_SMELLS = [
  /(^|[\\/])DESIGN-STATE\.md$/i,
  /(^|[\\/])transactions[\\/]/i,
  /(^|[\\/])verif(y|ication)-report[^\\/]*\.json$/i,
];
const FUSION_CONTEXT = /fusion|FUSION_DESIGN_REPORT|fusion_document|adsk\./i;

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
    const content =
      typeof input.tool_input.content === "string"
        ? input.tool_input.content
        : typeof input.tool_input.new_string === "string"
          ? input.tool_input.new_string
          : "";
    const smells =
      FUSION_SMELLS.some((pattern) => pattern.test(filePath)) ||
      (CONTEXT_SMELLS.some((pattern) => pattern.test(filePath)) &&
        (FUSION_CONTEXT.test(filePath) || FUSION_CONTEXT.test(content)));
    if (smells) {
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
