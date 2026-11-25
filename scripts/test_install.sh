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

# (f) owner's installer present -> cp-through-symlink WARNING
T2="$(mktemp -d)"; T3="$(mktemp -d)"; T4="$(mktemp -d)"; S="$(mktemp -d)"
trap 'rm -rf "$T" "$T2" "$T3" "$T4" "$S"' EXIT
mkdir -p "$T2/hooks"; echo "# owner hook" > "$T2/hooks/log_event.py"
out="$(bash "$INSTALL" --target "$T2" 2>&1)"
echo "$out" | grep -q "WARNING" && echo "$out" | grep -q "log_event.py" && check ok "owner installer detected -> WARNING" || check no "owner installer detected -> WARNING"
echo "$out" | grep -qi "symlink" && check ok "WARNING explains cp-through-symlink risk" || check no "WARNING explains cp-through-symlink risk"
out="$(bash "$INSTALL" --target "$T" 2>&1)"
echo "$out" | grep -q "WARNING" && check no "no WARNING without owner hook" || check ok "no WARNING without owner hook"

# (g) non-empty real memory dir, no --migrate-memory: refused, untouched, other links made
mkdir -p "$T3/agent-memory/advisor/projects"
echo "REAL-INDEX" > "$T3/agent-memory/advisor/MEMORY.md"
echo "REAL-ENTRY" > "$T3/agent-memory/advisor/projects/p.md"
out="$(bash "$INSTALL" --apply --target "$T3" 2>&1)"; rc=$?
[ ! -L "$T3/agent-memory/advisor" ] && [ "$(cat "$T3/agent-memory/advisor/MEMORY.md")" = "REAL-INDEX" ] && [ "$(cat "$T3/agent-memory/advisor/projects/p.md")" = "REAL-ENTRY" ] && check ok "real memory refused and untouched without flag" || check no "real memory refused and untouched without flag"
echo "$out" | grep -qi "refuse" && echo "$out" | grep -q -- "--migrate-memory" && check ok "refusal names --migrate-memory" || check no "refusal names --migrate-memory"
[ -L "$T3/agents/worker.md" ] && check ok "other links still made after memory refusal" || check no "other links still made after memory refusal"
[ ! -d "$T3/backups" ] || [ -z "$(ls -A "$T3/backups"/*/agent-memory 2>/dev/null)" ] && check ok "no memory backup move without flag" || check no "no memory backup move without flag"
[ "$rc" -ne 0 ] && check ok "refusal exits nonzero" || check no "refusal exits nonzero"

# (h) --migrate-memory against a temp copy of the repo (--source), never the real repo
mkdir -p "$S/memory"
cp -R "$ROOT/agents" "$ROOT/skills" "$S/"
cp -R "$ROOT/memory/advisor" "$S/memory/advisor"
mkdir -p "$T4/agent-memory/advisor/projects" "$T4/agent-memory/advisor/topics"
echo "REAL-ENTRY" > "$T4/agent-memory/advisor/projects/p.md"
echo "REAL-TOPIC" > "$T4/agent-memory/advisor/topics/t.md"
before="$(cd "$ROOT/memory/advisor" && find . -type f | sort)"
out="$(bash "$INSTALL" --apply --migrate-memory --source "$S" --target "$T4" 2>&1)"
[ "$(cat "$S/memory/advisor/projects/p.md" 2>/dev/null)" = "REAL-ENTRY" ] && [ "$(cat "$S/memory/advisor/topics/t.md" 2>/dev/null)" = "REAL-TOPIC" ] && check ok "migrate copies contents into repo copy" || check no "migrate copies contents into repo copy"
[ -L "$T4/agent-memory/advisor" ] && [ "$(readlink "$T4/agent-memory/advisor")" = "$(cd "$S" && pwd -P)/memory/advisor" ] && check ok "migrate links memory to repo copy" || check no "migrate links memory to repo copy"
B4="$(ls -d "$T4"/backups/rsi-workshop-* 2>/dev/null | head -1)"
[ -n "$B4" ] && [ "$(cat "$B4/agent-memory/advisor/projects/p.md" 2>/dev/null)" = "REAL-ENTRY" ] && check ok "migrate keeps backup move" || check no "migrate keeps backup move"
echo "$out" | grep -q "WARNING" && echo "$out" | grep -qi "git working tree" && check ok "migrate warns memories are in git working tree" || check no "migrate warns memories are in git working tree"
after="$(cd "$ROOT/memory/advisor" && find . -type f | sort)"
[ "$before" = "$after" ] && check ok "real repo memory/advisor untouched by migrate test" || check no "real repo memory/advisor untouched by migrate test"

# (i) --migrate-memory with a conflicting file: refused, nothing overwritten or moved
rm -rf "$T4" "$S"; mkdir -p "$T4/agent-memory/advisor" "$S/memory"
cp -R "$ROOT/agents" "$ROOT/skills" "$S/"; cp -R "$ROOT/memory/advisor" "$S/memory/advisor"
echo "REAL-INDEX" > "$T4/agent-memory/advisor/MEMORY.md"
repo_idx="$(cat "$S/memory/advisor/MEMORY.md")"
out="$(bash "$INSTALL" --apply --migrate-memory --source "$S" --target "$T4" 2>&1)"
[ "$(cat "$S/memory/advisor/MEMORY.md")" = "$repo_idx" ] && [ "$(cat "$T4/agent-memory/advisor/MEMORY.md")" = "REAL-INDEX" ] && [ ! -L "$T4/agent-memory/advisor" ] && check ok "migrate conflict: no overwrite, no move" || check no "migrate conflict: no overwrite, no move"
echo "$out" | grep -qi "conflict" && echo "$out" | grep -q "MEMORY.md" && check ok "migrate conflict reported" || check no "migrate conflict reported"

[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILED"; exit 1; }
