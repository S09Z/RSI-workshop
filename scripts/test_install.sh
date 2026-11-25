#!/bin/bash
# Tests for install.sh. Always passes --target <mktemp dir>; never touches ~/.claude.
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)"
ROOT="$(cd "$HERE/.." && pwd -P)"
INSTALL="$HERE/install.sh"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
FAILS=0
check() { if [ "$1" = ok ]; then echo "PASS: $2"; else echo "FAIL: $2"; FAILS=$((FAILS+1)); fi; }
t() { if "$@" >/dev/null 2>&1; then return 0; else return 1; fi; }

[ -f "$INSTALL" ] || { echo "FAIL: scripts/install.sh missing"; exit 1; }

# (a) dry-run creates nothing
bash "$INSTALL" --target "$T" >/dev/null 2>&1
[ -z "$(ls -A "$T")" ] && check ok "dry-run creates nothing" || check no "dry-run creates nothing"

# (c) pre-existing real worker.md
mkdir -p "$T/agents"
echo "ORIGINAL-WORKER" > "$T/agents/worker.md"

# (b) apply creates symlinks into repo
bash "$INSTALL" --apply --target "$T" >/dev/null 2>&1
ok=ok
for a in orchestrator worker advisor; do
  [ -L "$T/agents/$a.md" ] && [ "$(readlink "$T/agents/$a.md")" = "$ROOT/agents/$a.md" ] || ok=no
done
check $ok "apply links 3 agents into repo"
[ -L "$T/agent-memory/advisor" ] && [ "$(readlink "$T/agent-memory/advisor")" = "$ROOT/memory/advisor" ] && check ok "memory/advisor linked" || check no "memory/advisor linked"

# (c) backup
B="$(ls -d "$T"/backups/rsi-workshop-* 2>/dev/null | head -1)"
[ -n "$B" ] && [ "$(cat "$B/agents/worker.md" 2>/dev/null)" = "ORIGINAL-WORKER" ] && check ok "real worker.md backed up with content" || check no "real worker.md backed up with content"

# (d) idempotent
n1="$(ls "$T/backups" | wc -l | tr -d ' ')"
out="$(bash "$INSTALL" --apply --target "$T" 2>&1)"
n2="$(ls "$T/backups" | wc -l | tr -d ' ')"
[ "$n1" = "$n2" ] && check ok "second apply creates no new backup dir" || check no "second apply creates no new backup dir"
echo "$out" | grep -qi "skip" && check ok "second apply reports skips" || check no "second apply reports skips"
[ "$(readlink "$T/agents/worker.md")" = "$ROOT/agents/worker.md" ] && check ok "links intact after rerun" || check no "links intact after rerun"

# (e) no settings.json or hooks
[ ! -e "$T/settings.json" ] && [ ! -e "$T/hooks" ] && check ok "no settings.json or hooks in target" || check no "no settings.json or hooks in target"

[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILED"; exit 1; }
