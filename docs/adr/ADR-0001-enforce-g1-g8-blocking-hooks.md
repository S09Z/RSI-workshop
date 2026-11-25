# ADR-0001: Enforce G1–G8 as blocking hooks before any self-modification

Status: Proposed
Date: 2026-11-25
Source: docs/report/rsi-research-report.md §9

- **Context.** All registered hooks are async loggers that always exit 0 (repo: `docs/baseline.md`); async hooks cannot gate [E414]. Only PreToolUse exit 2/deny and Stop/SubagentStop can block [E413]. Read/Edit deny misses subprocesses; the sandbox covers Bash but is off by default and fails open [E415][E416]. Test modification is the dominant Claude cheat [E405]. Prompts alone (`agents/*.md`) carry G2/G6/G7 today, and prompts are context, not enforcement [E201].
- **Options.** (a) Keep async logging, rely on prompts. (b) Synchronous PreToolUse command hooks for G2, G6, G7, G8 plus SubagentStop hooks for G1, G3, G4 and a G5 check; enable sandbox with `failIfUnavailable` for the Worker and Advisor. (c) Managed-settings deny rules only.
- **Decision.** (b), with (c) for static path denies where possible (managed settings cannot be overridden [E415]). Keep the owner's async logger for telemetry; add `blocked: true` events. Change `hooks/guardrails.yaml` to carry `enforced: false|true` per guardrail (human-approved; additive, does not weaken).
- **Consequences.** RSI may start only when X1 passes 40/40. Some latency per tool call (not measured). G3/G4/G5 need prompt changes (`ran_at`, fail-first step) in `agents/worker.md`/`agents/orchestrator.md`. Cost: 12–20 human hours + X1 ($13.50).
