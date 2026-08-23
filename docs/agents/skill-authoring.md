# Skill authoring

- Keep skills usable by both Codex and Claude Code unless a skill explicitly
  documents an agent-specific branch.
- Keep each skill self-contained: its references and scripts live inside its
  own directory. A skill that reaches into a sibling skill, the router, or
  fleet config belongs in another repository — see
  [charter](charter.md).
- Do not hard-code maintainer-local secrets, host names, vault names, or
  machine inventory. Use environment variables or user-owned config paths.
- Preserve upstream attribution when copying or refreshing skills — see
  [upstream attribution](upstream-attribution.md).
- Validate both plugin manifests and each skill's YAML frontmatter before
  committing.
