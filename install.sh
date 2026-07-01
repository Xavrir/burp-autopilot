#!/usr/bin/env bash
# install.sh - link the skill into your agent's skills directory.
#
# The link name MUST match the skill's `name:` frontmatter
# (controlling-burpsuite-autonomously) so the runner discovers it.
#
# Override the destination root with SKILLS_DIR (default ~/.claude/skills).
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
SRC="$REPO/skill"
NAME="controlling-burpsuite-autonomously"
SKILLS_DIR="${SKILLS_DIR:-$HOME/.claude/skills}"
DEST="$SKILLS_DIR/$NAME"

[[ -f "$SRC/SKILL.md" ]] || { echo "error: $SRC/SKILL.md not found" >&2; exit 1; }
mkdir -p "$SKILLS_DIR"

if [[ -L "$DEST" ]]; then
  echo "note: replacing existing symlink at $DEST"
  rm "$DEST"
elif [[ -e "$DEST" ]]; then
  echo "error: $DEST already exists and is not a symlink; move it aside first" >&2
  exit 1
fi

ln -s "$SRC" "$DEST"
echo "linked $DEST -> $SRC"
echo "verify: python3 \"$SRC/scripts/burp_client.py\" ping"
