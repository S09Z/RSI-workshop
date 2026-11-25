# ADR-0003: Advisor memory v2 — verified writes, deltas, supersede, outcome-based pruning, grep retrieval

Status: Proposed
Date: 2026-11-25
Source: docs/report/rsi-research-report.md §9

- **Context.** Add-all memory hurt; history-based deletion helped; periodic deletion hurt [E221]. Rewrites can collapse [E133]. Memory drift and poisoning [E137][E224]. Semantic retrieval gains are vendor-contested [E211][E213][E214].
- **Options.** (a) Status quo (pending entries, free-form). (b) v2 schema on markdown + grep. (c) Adopt Mem0/Graphiti/claude-mem now.
- **Decision.** (b) per §4. (c) deferred until the §4 retrieval trigger fires; any adopted tool runs only as an experiment arm.
- **Consequences.** The Advisor must cite `evidence` for `worked` outcomes. Consolidation output goes to `~/.claude/agent-memory/advisor/staging/`, inside the Advisor's own memory folder, so G6 is unchanged. It is excluded from retrieval and enters the live folder only as an approved proposal. Cost: ~10 human hours + ≈ $0.70/week, plus a $14 quarterly recall check.
