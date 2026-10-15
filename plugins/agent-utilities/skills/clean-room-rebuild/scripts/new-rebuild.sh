#!/usr/bin/env bash
# Scaffold a two-room clean-room rebuild: reader/ (Room A), builder/ (Room B), wall/.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: new-rebuild.sh <root-dir> <feature-slug>" >&2
  exit 2
fi

skill_dir="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$1"
root="$(cd "$1" && pwd -P)"
slug="$2"

if [ -e "$root/reader" ] || [ -e "$root/builder" ]; then
  echo "refusing: $root already has reader/ or builder/" >&2
  exit 1
fi

mkdir -p "$root/reader/evidence" "$root/builder/src" "$root/builder/tests" \
  "$root/builder/oracle/mutants" "$root/wall"

cp "$skill_dir/templates/SPEC.md" "$root/reader/SPEC.md"
cp "$skill_dir/templates/NOTES.md" "$root/reader/NOTES.md"
cp "$skill_dir/templates/NOTES.md" "$root/builder/NOTES.md"

cat > "$root/wall/denylist.txt" <<'EOF'
# One entry per line: original symbol names, product names, strings, file names
# that must never appear in SPEC.md or the builder. Lines starting with # are ignored.
EOF

for room in reader builder; do
  sed "s/__SLUG__/$slug/g" "$skill_dir/templates/$room-AGENTS.md" > "$root/$room/AGENTS.md"
  ln -s AGENTS.md "$root/$room/CLAUDE.md"
done

for room in reader builder; do
  (cd "$root/$room" && git init -q && git add -A && git commit -qm "Scaffold $room room for $slug")
done

cat <<EOF
Scaffolded $root
  Room A: start an agent session in $root/reader   (REA investigation -> SPEC.md)
  Wall:   bash "$skill_dir/scripts/cross-wall.sh" "$root"
  Room B: start a fresh session in $root/builder  (SPEC.md only)
Prompts: $skill_dir/prompts.md
EOF
