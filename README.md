# RSI workshop

Git-versioned home of a three-agent Claude Code system (Orchestrator, Worker, Advisor), plus a sourced
research report on making that system improve itself under human approval and an eval gate.

## Status

- **Baseline imported.** `agents/{orchestrator,worker,advisor}.md` are byte-for-byte copies of the owner's
  `headless-dashboard/claude-home/agents/*.md` (`docs/baseline.md`). `headless-dashboard/` is the owner's
  own code, committed read-only; this repo never modifies it.
- **Report done.** `docs/report/rsi-research-report.md`, sourced from `docs/research/evidence-log.md`.
- **Proposed, not adopted.** Artifacts derived from the report need human approval: memory schema v2
  (`memory/advisor/SCHEMA.md`), telemetry v1 (`telemetry/events.schema.json`), the guardrail
  `proposed_mechanism` fields and G9-G14 (`hooks/guardrails.yaml`), and ADR-0001 to ADR-0005 (`docs/adr/`).
- **Nothing is enforced.** Guardrails exist only as a spec; no hook code exists in this repo.

## Layout

| Path | RSI surface | Content |
|---|---|---|
| `agents/` | 1 prompts / agent definitions | owner's baseline agents (PROTECTED; live config after install) |
| `memory/advisor/` | 2 advisor memory | index and schema v2 (proposed); `projects/`, `topics/` contents gitignored |
| `skills/` | 3 skills and checklists | empty (PROTECTED; live config after install) |
| `hooks/` | 4 guardrails (PROTECTED) | `guardrails.yaml` spec only; no scripts |
| `routing/` | 5 routing | models, retry and escalation limits (PROTECTED) |
| `evals/` | eval gate | task format, configs, graders (PROTECTED), held-out tasks (PROTECTED) |
| `proposals/` | change proposals | template, inbox, accepted (PROTECTED), rejected |
| `telemetry/` | observability | `events.schema.json` v1 (proposed; PROTECTED) |
| `docs/` | architecture, baseline, ADRs, research log, report | |
| `scripts/` | tooling (PROTECTED) | `check_scaffold.py`, `check_report.py`, `install.sh`, `test_install.sh` |

`PROTECTED.paths` lists what agents may never write. `memory/advisor/` is not in it: only the Advisor
writes there (G6). See `docs/architecture.md`, "Live surfaces".

## Check

    python3 -I scripts/check_scaffold.py
    python3 -I scripts/check_report.py
    bash scripts/test_install.sh

## Install

`scripts/install.sh` symlinks `agents/*.md`, `memory/advisor/` and any `skills/*` into `~/.claude`. It
never touches `hooks/` or `settings.json`. Dry-run first, then apply:

    bash scripts/install.sh                 # dry-run: prints what it would do, changes nothing
    bash scripts/install.sh --apply         # make the links; real files are moved to ~/.claude/backups/

Options: `--target DIR` (default `~/.claude`), `--source DIR` (repo root to link from; env
`RSI_REPO_ROOT`), `--migrate-memory` (see below). After install, the repo files ARE the live config:
edit `agents/`, `routing/` and `skills/` only through a human-merged proposal branch.

**Advisor memory.** If `~/.claude/agent-memory/advisor/` is a real, non-empty folder, `install.sh`
refuses that item (other links are still made; exit code 3) so the Advisor does not silently start with
no memory. `--migrate-memory` copies its contents into the repo's `memory/advisor/` first, never
overwriting a repo file that differs (any conflict refuses the item and nothing is copied), then moves
the original into `backups/` and links. The memories are then in the git working tree: `projects/` and
`topics/` are gitignored, `MEMORY.md` is tracked, so review before committing.

**The owner's installer.** `headless-dashboard/install.sh` copies agents with `cp`
(`headless-dashboard/install.sh:83`). `cp` follows our symlinks and overwrites this repo's `agents/*.md`,
silently reverting accepted RSI changes. `install.sh` prints a WARNING when `~/.claude/hooks/log_event.py`
exists. This repo is the single source of truth for `agents/`, `skills/` and `memory/advisor/`. After any
owner-installer run, check `git diff -- agents/`, restore with `git checkout -- agents/`, and rerun
`install.sh`; or change the owner's installer to skip symlinks. Details: `docs/baseline.md`.
