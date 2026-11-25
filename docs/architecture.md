# Architecture (baseline)

The system as described by its owner; not yet present on this machine.
It is a three-agent coding workflow on Claude Code, installed globally in `~/.claude`.

## Agents

- Orchestrator (Opus): main session, `claude --agent orchestrator`. Plans, splits work into tasks
  tagged [T1], [T2]..., dispatches them. Never edits files. May spawn only `Agent(worker, advisor)`.
- Worker (Sonnet): codes and fixes bugs. Returns WORKER REPORT: STATUS (WORKS / DOES_NOT_WORK /
  BLOCKED), FINDINGS, CHANGES, VERIFICATION (command, result, ran_at), ATTEMPTS (max 3).
- Advisor (Opus): reads the codebase, cannot edit it. Persistent memory in
  `~/.claude/agent-memory/advisor/`: `MEMORY.md` (index, auto-loaded, first 200 lines),
  `projects/<project>.md` (symptom, cause, advised fix, outcome, hit count), `topics/<topic>.md`
  (cross-project lessons). Returns ADVISOR GUIDANCE: DIAGNOSIS, CONFIDENCE, EVIDENCE (file:line),
  PLAN, HOW_TO_VERIFY, FROM_MEMORY.

## Loop

A task ends only DONE or STUCK. Test-first gate: the DONE_WHEN test must fail first. The Worker runs
and reports. If not WORKS, the Orchestrator consults the Advisor (max 2 rounds) and the Worker
retries. The Orchestrator then sends the outcome back to the Advisor to update memory.

## Guardrails (Claude Code hooks)

| ID | Name |
|---|---|
| G1 | report contract check |
| G2 | Orchestrator may not write files |
| G3 | silent-failure detection |
| G4 | fresh evidence required |
| G5 | test-first acceptance gate |
| G6 | Advisor may write only to its memory folder |
| G7 | Worker may write only inside the git root |
| G8 | Worker may not edit the test files named in DONE_WHEN |

Spec: `hooks/guardrails.yaml`. No hook code exists in this repo.

## Observability

Hooks log events to `~/.claude/agent-dashboard/events.jsonl`, feeding a local dashboard (progress,
workload, first-try success, escalation rate, advisor fix rate, cost). Planned: Claude Code built-in
OpenTelemetry export to Langfuse, Honeycomb or Grafana.

## Eval plan

10-20 real tasks comparing: single agent, Orchestrator + Worker, full system. Tools: promptfoo or
Inspect SWE.

## RSI-modifiable surfaces

1 prompts/agent definitions; 2 advisor memory (content, structure, consolidation/deletion rules);
3 skills and checklists; 4 guardrail rules and thresholds; 5 routing (model, escalation, retry
limits). Human approval plus an eval gate. Model weights are out of scope.

## Roadmap

Harden, then Measure (gate: +15 points over single agent), then Scale (parallel worktrees), then
Memory (semantic-search MCP).
