#!/bin/bash
# Link the RSI workshop pieces into a Claude config dir. Dry-run by default.
# Usage: install.sh [--apply] [--target DIR] [--source DIR] [--migrate-memory]
#   --target DIR       Claude config dir (default $HOME/.claude)
#   --source DIR       repo root to link from (default: this script's repo; env RSI_REPO_ROOT)
#   --migrate-memory   copy a non-empty real agent-memory/advisor/ into the repo before linking
# Never touches hooks/ or settings.json.
set -euo pipefail

ROOT="${RSI_REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd -P)}"
TARGET="$HOME/.claude"
APPLY=0
MIGRATE=0
REFUSED=0

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --migrate-memory) MIGRATE=1 ;;
    --target) [ $# -ge 2 ] || { echo "--target needs a directory" >&2; exit 2; }; TARGET="$2"; shift ;;
    --source) [ $# -ge 2 ] || { echo "--source needs a directory" >&2; exit 2; }; ROOT="$2"; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
[ -d "$ROOT/agents" ] || { echo "source $ROOT has no agents/ folder" >&2; exit 2; }
ROOT="$(cd "$ROOT" && pwd -P)"

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP="$TARGET/backups/rsi-workshop-$TS"
[ "$APPLY" -eq 1 ] && echo "MODE: apply -> $TARGET (source $ROOT)" || echo "MODE: dry-run (use --apply to make changes) -> $TARGET (source $ROOT)"

# The owner's installer (headless-dashboard/install.sh) runs `cp claude-home/agents/*.md ~/.claude/agents/`.
# cp follows our symlinks and overwrites the repo's agents/*.md. Warn when that installer is present.
if [ -e "$TARGET/hooks/log_event.py" ]; then
  cat <<EOF
WARNING: $TARGET/hooks/log_event.py exists, so the owner's installer (headless-dashboard/install.sh) has run here.
WARNING: that installer copies agents/*.md into $TARGET/agents/ with cp, and cp follows symlinks.
WARNING: once this script has made those files symlinks into $ROOT/agents/, the owner's installer
WARNING: overwrites the repo's agents/*.md and silently reverts accepted RSI changes.
WARNING: remedy: after every owner-installer run, check 'git diff -- agents/' in $ROOT and restore with
WARNING: 'git checkout -- agents/', then rerun this script; or edit the owner's installer to skip
WARNING: destinations that are symlinks.
WARNING: single source of truth for agents/, skills/ and memory/advisor/ is this repo (README.md).
EOF
fi

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

# True when the repo file is tracked and identical to HEAD, i.e. an untouched stub that is safe to replace.
is_pristine_stub() {
  git -C "$ROOT" ls-files --error-unmatch -- "$1" >/dev/null 2>&1 \
    && git -C "$ROOT" diff --quiet HEAD -- "$1" 2>/dev/null
}

# Advisor memory: never move a non-empty real memory folder aside unless --migrate-memory is given.
link_memory() {
  local src="$ROOT/memory/advisor" dest="$TARGET/agent-memory/advisor" rel f
  local -a conflicts=()
  rel="agent-memory/advisor"
  if [ -L "$dest" ] || [ ! -d "$dest" ] || [ -z "$(ls -A "$dest")" ]; then
    link "$src" "$dest"
    return
  fi
  if [ "$MIGRATE" -eq 0 ]; then
    echo "REFUSE $rel: real, non-empty memory folder; the Advisor would start with no memory."
    echo "REFUSE   rerun with --migrate-memory to copy it into $src first, or move it yourself."
    REFUSED=1
    return
  fi
  while IFS= read -r f; do
    if [ -e "$src/$f" ] && ! cmp -s "$dest/$f" "$src/$f" && ! is_pristine_stub "$src/$f"; then
      conflicts+=("$f")
    fi
  done < <(cd "$dest" && find . -type f | sed 's|^\./||' | sort)
  if [ "${#conflicts[@]}" -gt 0 ]; then
    echo "REFUSE $rel: --migrate-memory conflict; these files differ in $src and would be overwritten:"
    for f in "${conflicts[@]}"; do echo "REFUSE   conflict: $f"; done
    echo "REFUSE   merge them into the repo copy by hand, then rerun. Nothing was copied or moved."
    REFUSED=1
    return
  fi
  while IFS= read -r f; do
    if [ -e "$src/$f" ] && cmp -s "$dest/$f" "$src/$f"; then
      echo "same   $rel/$f (identical in repo)"
      continue
    fi
    echo "copy   $rel/$f -> $src/$f$([ -e "$src/$f" ] && echo ' (replaces unmodified repo stub; recoverable via git)')"
    if [ "$APPLY" -eq 1 ]; then
      mkdir -p "$(dirname "$src/$f")"
      cp -p "$dest/$f" "$src/$f"
    fi
  done < <(cd "$dest" && find . -type f | sed 's|^\./||' | sort)
  echo "WARNING: Advisor memories are now in the git working tree at $src."
  echo "WARNING: projects/ and topics/ are gitignored; MEMORY.md is tracked. Review before committing."
  link "$src" "$dest"
}

for f in "$ROOT"/agents/*.md; do
  [ -e "$f" ] || continue
  link "$f" "$TARGET/agents/$(basename "$f")"
done

link_memory

nskills=0
for s in "$ROOT"/skills/*; do
  [ -e "$s" ] || continue
  [ "$(basename "$s")" = "README.md" ] && continue
  link "$s" "$TARGET/skills/$(basename "$s")"
  nskills=$((nskills+1))
done
[ "$nskills" -eq 0 ] && echo "skills: none to link (only README.md present)"

[ "$APPLY" -eq 1 ] || echo "dry-run complete; nothing changed."
[ "$REFUSED" -eq 0 ] || { echo "some items were refused (see REFUSE lines)."; exit 3; }
exit 0
