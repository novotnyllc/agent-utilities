#!/usr/bin/env bash
set -euo pipefail

force=false
if [[ ${1:-} == "--force" ]]; then
  force=true
  shift
fi

if [[ $# -ne 1 ]]; then
  echo "usage: $0 [--force] <agent-skills-directory>" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
skills_root="$1"
source_skill="$root"
destination="$skills_root/fusion-parametric-design"

if [[ -e "$skills_root" && ! -d "$skills_root" ]]; then
  echo "skills path is not a directory: $skills_root" >&2
  exit 2
fi
mkdir -p "$skills_root"

if [[ -e "$destination" && "$force" != true ]]; then
  echo "destination already exists: $destination (rerun with --force to replace it)" >&2
  exit 2
fi

stage="$(mktemp -d "$skills_root/.fusion-parametric-design.install.XXXXXX")"
cleanup() {
  rm -rf "$stage"
}
trap cleanup EXIT
payload=(
  .gitignore
  LICENSE
  README.md
  SHA256SUMS.source
  SKILL.md
  THIRD_PARTY_NOTICES.md
  pyproject.toml
  docs
  examples
  references
  schema
  scripts
  src
  templates
  tests
)
for item in "${payload[@]}"; do
  cp -R "$source_skill/$item" "$stage/"
done
find "$stage" -type d \( -name __pycache__ -o -name '*.egg-info' \) -prune -exec rm -rf {} +
find "$stage" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name .DS_Store \) -delete

if [[ "$force" == true ]]; then
  rm -rf "$destination"
fi
mv "$stage" "$destination"
trap - EXIT

echo "Installed fusion-parametric-design at $destination"
