# Baseline: owner's agent definitions

Source: `headless-dashboard/claude-home/` (owner's folder, committed in `db036c2`, read-only: this repo never modifies it), imported 2026-11-25.
`agents/{orchestrator,worker,advisor}.md` are byte-for-byte copies of `headless-dashboard/claude-home/agents/*.md`; later RSI diffs are against them.

## The owner's system (file list)

- `claude-home/agents/orchestrator.md`: main-session planner; `tools: Agent(worker, advisor), ...` (line 4), `model: opus`.
- `claude-home/agents/worker.md`: implements one task, ends with a WORKER REPORT; `model: sonnet`.
- `claude-home/agents/advisor.md`: diagnoses failures, `memory: user` (line 6), `model: opus`.
- `claude-home/hooks/log_event.py`: logging hook; appends events to `events.jsonl`.
- `claude-home/settings.hooks.json`: registers `log_event.py` on PreToolUse (Task|Agent), PostToolUse, PostToolUseFailure, SubagentStart, SubagentStop, Stop.
- `claude-home/agent-dashboard/`: `agentdash` Python package, `server.py`, `index.html`, OTLP/alerts example configs, `demo.py`.
- `bin/orch`, `bin/orch-headless`, `bin/orch-dashboard`, `bin/orch-dashboard-tick`: launch the orchestrator (interactive / headless), dashboard, and timer tick.
- `install.sh`: copies the above into `~/.claude` and `~/.local/bin`.
- `deploy/`: systemd/launchd/cron units for the OTLP receiver and tick.

## Differences from the described system (facts)

- Guardrails G1-G8: not enforced. The agent files contain no mention of "guardrail" or G1-G8 (grep over `claude-home/agents/*.md`). The only G-number handling is passive: `log_event.py:47` regex-extracts `GUARDRAIL G<n>` markers from text, and `log_event.py:139-147` records a `guardrail_hit` event when called with `--guardrail`. Guardrails are specified in `hooks/guardrails.yaml`, not enforced.
- No hook can block. Every hook in `settings.hooks.json` is `"async": true` (lines 5, 9, 13, 16, 19, 22); `log_event.py:5-6` says it never blocks or fails a session, and `log_event.py:168-173` swallows all exceptions and always `sys.exit(0)`. There is no PreToolUse hook other than the `Task|Agent` logger (line 4).
- Hooks are inert unless `AGENT_WORKFLOW=1` (`log_event.py:151-152`), which `bin/orch` exports.
- `events.jsonl` is written to `~/.claude/agent-dashboard/events.jsonl` (`log_event.py:27,84`; override with `AGENT_DASHBOARD_DIR`), not to this repo's `telemetry/`.
- Content-free by default: report text is parsed into fields and dropped unless `AGENT_DASHBOARD_LOG_CONTENT=1` (`log_event.py:7-9`).
- `install.sh` edits `~/.claude/settings.json` (merges hook entries, writes a `.bak-<ts>` copy; `install.sh:35-64`) and writes into `~/.claude` and `~/.local/bin` (`install.sh:28-32`). This repo's `scripts/install.sh` never edits `settings.json`.

## Status after Harden (G1, G2, G6, G7, G8)

The facts above describe the owner's baseline. This repo now also holds blocking hooks for G1, G2, G6, G7 and G8 (`hooks/g*.py`, tests in `hooks/tests/`, observed input shapes in `hooks/tests/fixtures/PROBE.md`). They are not registered in `~/.claude/settings.json`, so the live system is unchanged: every registered hook is still the async logger. Open question Q-p (who builds Harden): a human-directed agent session built these with human review of each diff, and nothing was registered, so no live configuration changed.

## Single source of truth and the two installers

- After this repo's `scripts/install.sh --apply`, `~/.claude/agents/*.md` are symlinks into this repo's `agents/`. This repo is the single source of truth for `agents/`, `skills/` and `memory/advisor/`; `headless-dashboard/claude-home/agents/` stays the frozen baseline that RSI diffs are measured against.
- The owner's `install.sh` runs `cp "$SRC/claude-home/agents/"*.md "$CLAUDE_HOME/agents/"` (`headless-dashboard/install.sh:83`). `cp` follows symlinks, so once ours are in place it overwrites this repo's `agents/*.md` with the baseline copies and silently reverts accepted RSI changes.
- This repo's `scripts/install.sh` prints a WARNING when `~/.claude/hooks/log_event.py` exists (the owner's installer has run). Rerunning our installer alone does not undo it, because the links stay in place and only their targets changed. Remedy: after any owner-installer run, check `git diff -- agents/` here, restore with `git checkout -- agents/`, then rerun `scripts/install.sh`; or edit the owner's installer to skip destinations that are symlinks. Open question Q-o (report §10).
