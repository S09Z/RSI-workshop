#!/bin/bash
# Link the RSI workshop pieces into a Claude config dir. Dry-run by default.
# Usage: install.sh [--apply] [--target DIR]     (target defaults to $HOME/.claude)
# Never touches hooks/ or settings.json.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
TARGET="$HOME/.claude"
APPLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --target) [ $# -ge 2 ] || { echo "--target needs a directory" >&2; exit 2; }; TARGET="$2"; shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP="$TARGET/backups/rsi-workshop-$TS"
[ "$APPLY" -eq 1 ] && echo "MODE: apply -> $TARGET" || echo "MODE: dry-run (use --apply to make changes) -> $TARGET"

# link SRC DEST
link() {
  local src="$1" dest="$2" rel
  rel="${dest#"$TARGET"/}"
  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
    echo "skip   $rel (already linked)"
    return
  fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    echo "backup $rel -> backups/rsi-workshop-$TS/$rel"
    if [ "$APPLY" -eq 1 ]; then
      mkdir -p "$(dirname "$BACKUP/$rel")"
      mv "$dest" "$BACKUP/$rel"
    fi
  fi
  echo "link   $rel -> $src"
  if [ "$APPLY" -eq 1 ]; then
    mkdir -p "$(dirname "$dest")"
    ln -s "$src" "$dest"
  fi
}

for f in "$ROOT"/agents/*.md; do
  [ -e "$f" ] || continue
  link "$f" "$TARGET/agents/$(basename "$f")"
done

link "$ROOT/memory/advisor" "$TARGET/agent-memory/advisor"

nskills=0
for s in "$ROOT"/skills/*; do
  [ -e "$s" ] || continue
  [ "$(basename "$s")" = "README.md" ] && continue
  link "$s" "$TARGET/skills/$(basename "$s")"
  nskills=$((nskills+1))
done
[ "$nskills" -eq 0 ] && echo "skills: none to link (only README.md present)"

[ "$APPLY" -eq 1 ] || echo "dry-run complete; nothing changed."
exit 0
