# RSI workshop

Git-versioned home of a three-agent Claude Code system (Orchestrator, Worker, Advisor) and, later,
a research report on making that system improve itself under human approval and an eval gate.

The system is described by its owner and is not yet present on this machine. Everything under
`agents/` and `hooks/` is a placeholder or a spec, not working code.

## Layout

| Path | RSI surface | Content |
|---|---|---|
| `agents/` | 1 prompts / agent definitions | placeholders |
| `memory/advisor/` | 2 advisor memory | layout and schema (v0) |
| `skills/` | 3 skills and checklists | empty |
| `hooks/` | 4 guardrails (PROTECTED) | `guardrails.yaml` spec only; no scripts |
| `routing/` | 5 routing | models, retry and escalation limits |
| `evals/` | eval gate | task format, configs, graders (PROTECTED), held-out tasks (PROTECTED) |
| `proposals/` | change proposals | template, inbox, accepted, rejected |
| `telemetry/` | observability | `events.schema.json` (v0) |
| `docs/` | architecture, ADRs, research log, report | |
| `scripts/` | tooling | `check_scaffold.py`; `install.sh` comes later |

`PROTECTED.paths` lists what agents may never write.

## Check

    python3 -I scripts/check_scaffold.py

## Install

Not yet. `scripts/install.sh` (dry-run by default) is a later step.
