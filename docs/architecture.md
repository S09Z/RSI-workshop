# Architecture (baseline)

The owner's system, imported from `headless-dashboard/claude-home/` (see `docs/baseline.md`).
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

`Status: active` = adopted in the design. `Enforced` = a blocking hook exists; none does today (`docs/baseline.md`).
The Mechanism column and G9-G14 are proposed (report §9) and need human approval.

| ID | Name | Status | Enforced | Mechanism (proposed — report §9) |
|---|---|---|---|---|
| G1 | report contract check | active | no | SubagentStop hook validates fields |
| G2 | Orchestrator may not write files | active | no | PreToolUse deny on Write/Edit for orchestrator agent_type; Bash via sandbox |
| G3 | silent-failure detection | active | no | SubagentStop re-runs DONE_WHEN; WORKS + fail blocks |
| G4 | fresh evidence required | active | no | SubagentStop checks `ran_at` within run |
| G5 | test-first acceptance gate | active | no | hook runs DONE_WHEN before first Worker dispatch; must fail |
| G6 | Advisor may write only to its memory folder | active | no | PreToolUse path check + sandbox write scope |
| G7 | Worker may write only inside the git root | active | no | PreToolUse path check + sandbox |
| G8 | Worker may not edit the test files named in DONE_WHEN | active | no | PreToolUse path check on Edit/Write/Bash |
| G9 | No agent writes `PROTECTED.paths` | proposed | no | PreToolUse path check for all agents; sandbox deny |
| G10 | Eval isolation | proposed | no | harness: fresh worktree + memory snapshot per trial; heldout and `evals/graders/` read-denied for every agent session: managed-settings Read/Grep/Glob deny + sandbox read-deny for Bash (report §5; fallback: store heldout outside the repo) |
| G11 | Memory write provenance | proposed | no | `outcome: worked` only from hook-verified `task_outcome` |
| G12 | Proposal scope | proposed | no | proposer writes only `proposals/inbox/`; one surface; no `PROTECTED.paths`; G1-G8 blocks byte-identical; `hooks/` and `PROTECTED.paths` change only by a human |
| G13 | Audit-log integrity | proposed | no | append-only, hash-chained events; logger outside agent-writable paths |
| G14 | Test-tamper heuristics | proposed | no | flag skip markers, `sys.exit`, conftest/operator patches in Worker diffs |

Spec: `hooks/guardrails.yaml`. Blocking hook code exists for G1, G2 and G8 (`implemented: true`, X1 hook layer passes); it is not registered in `settings.json`, so "Enforced" stays no for every row. G3–G7 have no code. G1-G8 are never removed or weakened.

Proposed (report §9) additions to `PROTECTED.paths`, now on disk and added: `evals/configs/`,
`proposals/accepted/`, `telemetry/events.schema.json`, and the live surfaces and gate scripts
`agents/`, `routing/`, `skills/`, `scripts/` (covers `check_scaffold.py`, `check_report.py`,
`test_install.sh` and the future `check_proposal.py` and `memory_lint.py`). To protect once created:
`evals/harness/` (and `evals/graders/stats.py`, already covered by `evals/graders/`). Any change to
`hooks/` or `PROTECTED.paths` requires human approval.

### Live surfaces (proposed — report §9)

After `scripts/install.sh --apply`, `~/.claude/agents/*.md`, `~/.claude/skills/*` and
`~/.claude/agent-memory/advisor/` are symlinks into this repo, so the repo files ARE the live config.

- `agents/`, `routing/` and `skills/` change only through a human-merged proposal branch (`rsi/<id>`).
- `memory/advisor/` is writable only by the Advisor (G6). It is deliberately not in `PROTECTED.paths`.
- Every path check (G6, G7, G9, G12) compares resolved real paths: the repo path and the `~/.claude`
  path are aliases of the same files.
- The Harden work (ADR-0001) is done by a human, or by an agent system that is not pointed at this repo.
- Held-out tasks and hidden tests are read-denied to agents by the G10 mechanism above; `PROTECTED.paths`
  blocks writes only.

## Decisions (proposed — report §9)

- [ADR-0001](adr/ADR-0001-enforce-g1-g8-blocking-hooks.md): enforce G1-G8 as blocking hooks first.
- [ADR-0002](adr/ADR-0002-eval-gate-no-harm-per-change.md): no-harm per-change eval gate; powered only at Measure.
- [ADR-0003](adr/ADR-0003-advisor-memory-v2.md): Advisor memory v2 (schema in `memory/advisor/SCHEMA.md`).
- [ADR-0004](adr/ADR-0004-human-approved-proposals-no-optimizer.md): human-approved proposals, no optimizer.
- [ADR-0005](adr/ADR-0005-telemetry-v1.md): telemetry v1 (`telemetry/events.schema.json`).

## Observability

Hooks log events to `~/.claude/agent-dashboard/events.jsonl`, feeding a local dashboard (progress,
workload, first-try success, escalation rate, advisor fix rate, cost). Planned: Claude Code built-in
OpenTelemetry export to Langfuse, Honeycomb or Grafana.

## Eval plan

10-20 real tasks comparing: single agent, Orchestrator + Worker, full system. Tools: promptfoo or
Inspect SWE.

Proposed change (report §5, ADR-0002): 10-20 tasks cannot detect +15 points. One primary comparison
(full vs single) needs N >= 50 (A) to ~80 (B) tasks at K = 3; below that the result is descriptive only.

## RSI-modifiable surfaces

1 prompts/agent definitions; 2 advisor memory (content, structure, consolidation/deletion rules);
3 skills and checklists; 4 guardrail rules and thresholds; 5 routing (model, escalation, retry
limits). Human approval plus an eval gate. Model weights are out of scope.

## Roadmap

Current (owner's): Harden, then Measure (gate: +15 points over single agent), then Scale (parallel
worktrees), then Memory (semantic-search MCP).

Proposed (report §9):

- Harden: enforce G1-G8 as blocking hooks (ADR-0001), pass X1 (both layers, report §8); telemetry v1 (ADR-0005);
  memory v2 schema (ADR-0003). No RSI proposals before X1 passes.
- Measure: build 50-80 audited tasks (train/heldout/rotating); X2. Gate: one primary comparison (full vs
  single), paired 95% CI lower bound > 0, sized for 80% power at +15: N >= 50 (A) to ~80 (B), K = 3,
  recomputed with omega^2/sigma^2 from X2; descriptive-only below that (ADR-0002).
- RSI (new): weekly proposal loop with no-harm gate and canary (report §5); X3-X5.
- Scale: parallel worktrees after Measure; per-worktree G7/G8 scope.
- Memory: semantic-search MCP only if MEMORY.md > 150 lines after pruning or recall misses > 20%.
