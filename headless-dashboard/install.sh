#!/usr/bin/env bash
# Install the orchestrator / worker / advisor setup and dashboard v2 for the current user.
# Nothing is written inside any project. Safe to run more than once (idempotent).
#
#   ./install.sh                    install / upgrade
#   ./install.sh --with-services    also install the alert timer + OTLP receiver (launchd or systemd --user)
#   ./install.sh --dry-run          print what would change, change nothing
#   ./install.sh --uninstall        remove agents, hook entries, commands, package and services (data is kept)
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
DASH="$CLAUDE_HOME/agent-dashboard"
SETTINGS="$CLAUDE_HOME/settings.json"
MARK="log_event.py"   # recognises our hook entries when merging/removing
SERVICE_HOME="${SERVICE_HOME:-$HOME}"

uninstall=false; services=false; dry=false
for a in "$@"; do
  case "$a" in
    --uninstall) uninstall=true ;;
    --with-services) services=true ;;
    --dry-run) dry=true ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done
run() { if $dry; then echo "[dry-run] $*"; else "$@"; fi; }

command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "python3 >= 3.10 is required"; exit 1; }

OS="$(uname -s)"
install_services() {
  if [ "$OS" = "Darwin" ]; then
    local la="$SERVICE_HOME/Library/LaunchAgents"
    run mkdir -p "$la"
    for n in tick otlp; do
      local dst="$la/com.agentdash.$n.plist"
      if $dry; then echo "[dry-run] write $dst"; else
        sed "s#__HOME__#$HOME#g" "$SRC/deploy/com.agentdash.$n.plist" > "$dst"
        launchctl bootout "gui/$(id -u)" "$dst" 2>/dev/null || true
        launchctl bootstrap "gui/$(id -u)" "$dst" 2>/dev/null || echo "note: launchctl bootstrap failed for $n (load it manually)"
      fi
    done
  elif command -v systemctl >/dev/null; then
    local ud="$SERVICE_HOME/.config/systemd/user"
    run mkdir -p "$ud"
    run cp "$SRC/deploy/agentdash-tick.service" "$SRC/deploy/agentdash-tick.timer" "$SRC/deploy/agentdash-otlp.service" "$ud/"
    run systemctl --user daemon-reload || true
    run systemctl --user enable --now agentdash-tick.timer agentdash-otlp.service || echo "note: enable the units manually"
  else
    echo "No launchd/systemd found. Add the line in deploy/crontab.example with crontab -e."
  fi
}
remove_services() {
  if [ "$OS" = "Darwin" ]; then
    for n in tick otlp; do
      local dst="$SERVICE_HOME/Library/LaunchAgents/com.agentdash.$n.plist"
      [ -f "$dst" ] || continue
      $dry || launchctl bootout "gui/$(id -u)" "$dst" 2>/dev/null || true
      run rm -f "$dst"
    done
  elif command -v systemctl >/dev/null; then
    run systemctl --user disable --now agentdash-tick.timer agentdash-otlp.service 2>/dev/null || true
    run rm -f "$SERVICE_HOME/.config/systemd/user/agentdash-tick.service" "$SERVICE_HOME/.config/systemd/user/agentdash-tick.timer" \
      "$SERVICE_HOME/.config/systemd/user/agentdash-otlp.service"
  fi
}

run mkdir -p "$CLAUDE_HOME/agents" "$CLAUDE_HOME/hooks" "$DASH" "$BIN_DIR"

if $uninstall; then
  run rm -f "$CLAUDE_HOME/agents/orchestrator.md" "$CLAUDE_HOME/agents/worker.md" "$CLAUDE_HOME/agents/advisor.md"
  run rm -f "$CLAUDE_HOME/hooks/log_event.py"
  run rm -f "$BIN_DIR/orch" "$BIN_DIR/orch-headless" "$BIN_DIR/orch-dashboard" "$BIN_DIR/orch-dashboard-tick"
  run rm -rf "$DASH/agentdash"
  run rm -f "$DASH/server.py" "$DASH/index.html" "$DASH/demo.py" "$DASH/otel-env.sh" "$DASH/alerts.example.yaml" "$DASH/otelcol.example.yaml"
  remove_services
  echo "Removed agents, hook script, commands, package and services."
  echo "Data kept in $DASH (events.jsonl, otel.jsonl, dashboard.sqlite3, alerts.yaml). Delete it yourself if you want."
else
  run cp "$SRC/claude-home/agents/"*.md "$CLAUDE_HOME/agents/"
  run cp "$SRC/claude-home/hooks/log_event.py" "$CLAUDE_HOME/hooks/log_event.py"
  run rm -rf "$DASH/agentdash"
  run cp -R "$SRC/claude-home/agent-dashboard/agentdash" "$DASH/agentdash"
  run find "$DASH/agentdash" -name '__pycache__' -prune -exec rm -rf {} +
  for f in server.py index.html demo.py otel-env.sh alerts.example.yaml otelcol.example.yaml; do
    run cp "$SRC/claude-home/agent-dashboard/$f" "$DASH/$f"
  done
  # user-owned config: created once, never overwritten
  [ -f "$DASH/alerts.yaml" ] || run cp "$SRC/claude-home/agent-dashboard/alerts.example.yaml" "$DASH/alerts.yaml"
  if [ ! -f "$DASH/alerts.env" ]; then
    if $dry; then echo "[dry-run] create $DASH/alerts.env (600)"; else
      ( umask 077; printf '# Webhook secrets for alerts (read by orch-dashboard-tick)\n# AGENTDASH_SLACK_WEBHOOK=\n# AGENTDASH_DISCORD_WEBHOOK=\n# AGENTDASH_LINE_TOKEN=\n# AGENTDASH_LINE_TO=\n# AGENTDASH_WEBHOOK_URL=\n' > "$DASH/alerts.env" )
    fi
  fi
  run cp "$SRC/bin/orch" "$SRC/bin/orch-headless" "$SRC/bin/orch-dashboard" "$SRC/bin/orch-dashboard-tick" "$BIN_DIR/"
  run chmod +x "$CLAUDE_HOME/hooks/log_event.py" "$BIN_DIR/orch" "$BIN_DIR/orch-headless" "$BIN_DIR/orch-dashboard" "$BIN_DIR/orch-dashboard-tick"
  # migrate the store now (fails open: a broken store never blocks the install)
  $dry || PYTHONPATH="$DASH" python3 -c "from agentdash import store, config; store.connect(config.paths('$DASH')['db'])" \
    || echo "note: could not initialise the dashboard store"
  $services && install_services
fi

# Merge hook entries into settings.json without touching other settings.
if $dry; then
  echo "[dry-run] merge hook entries from claude-home/settings.hooks.json into $SETTINGS"
else
python3 - "$SETTINGS" "$SRC/claude-home/settings.hooks.json" "$uninstall" "$MARK" <<'PY'
import json, os, sys, shutil, time
settings_path, hooks_path, uninstall, mark = sys.argv[1], sys.argv[2], sys.argv[3] == "true", sys.argv[4]
data = {}
if os.path.exists(settings_path):
    with open(settings_path, encoding="utf-8") as f:
        raw = f.read().strip()
        data = json.loads(raw) if raw else {}
    shutil.copy(settings_path, settings_path + f".bak-{int(time.time())}")
ours = json.load(open(hooks_path, encoding="utf-8"))["hooks"]
hooks = data.setdefault("hooks", {})

def is_ours(group):
    return any(mark in (h.get("command") or "") for h in group.get("hooks", []))

for event in list(hooks.keys()):
    hooks[event] = [g for g in hooks[event] if not is_ours(g)]
    if not hooks[event]:
        del hooks[event]
if not uninstall:
    for event, groups in ours.items():
        hooks.setdefault(event, []).extend(groups)
if not hooks:
    data.pop("hooks", None)
os.makedirs(os.path.dirname(settings_path), exist_ok=True)
with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
print(("Removed" if uninstall else "Merged") + " hook entries in", settings_path)
PY
fi

case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "Note: add $BIN_DIR to your PATH";; esac
if ! $uninstall; then
  echo "Installed. Next: cd <project> && orch   |   orch-headless \"task\"   |   orch-dashboard"
  $services || echo "Headless alerts/OTel: ./install.sh --with-services   (or see deploy/ for cron / launchd / systemd)"
fi
