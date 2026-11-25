# Advisor memory schema v2 (proposed — report §4, ADR-0003)

Status: proposed. Replaces v0 only after human approval. Source: `docs/report/rsi-research-report.md` §4.

## Layout

- `MEMORY.md`: index, auto-loaded, first 200 lines. Hard budget: <= 150 lines and <= 20KB (§4 pruning policy, M12). One line per entry (its `key`), pointing to detail files.
- `projects/<project>.md`: one entry per `##` block.
- `topics/<topic>.md`: cross-project lessons, same entry shape.
- `staging/` (inside `~/.claude/agent-memory/advisor/`, so G6 is unchanged): consolidation output only. Never linked from MEMORY.md, excluded from retrieval by `scripts/memory_lint.py`; live entries change only through an approved proposal (§4 rule 2).

## Entry fields (§4 entry schema v2)

| Field | Type | Rule |
|---|---|---|
| `id` | `adv-<project>-<n>` | Stable, never reused |
| `kind` | `episode` / `lesson` / `rule-candidate` | Promotion only upward via the rules below |
| `key` | one line | Symptom + key fact; grep target and MEMORY.md line |
| `symptom`, `cause`, `advised_fix` | text | Reasoning only; no code or file dumps |
| `outcome` | `worked` / `did_not_work` / `pending` | Only `worked`/`did_not_work` count; `pending` is never retrieved as evidence |
| `evidence` | task_id, commit, verification command, `ran_at` | Required for `worked`; must come from the hook-verified `task_outcome` event (G11) |
| `helped` / `hurt` | integers | +1 helped when advice reused and task ended verified-done; +1 hurt when reused and failed |
| `created`, `last_used`, `verified_at` | dates | `verified_at` = last time the cause was re-checked against code |
| `superseded_by` / `valid_until` | id / date | Set on conflict; old entry kept, not retrieved |
| `sources` | list of ids | Required on `lesson` and `rule-candidate` |
| `advisory` | always `true` | Rendered as "past reference, verify before use" |

## Consolidation rules (weekly)

1. Write deltas only (add/modify one entry); never regenerate a whole file.
2. Consolidation output goes to `staging/`; the diff goes into a proposal; live entries change only after approval.
3. Episode -> lesson: >= 2 `worked` episodes with the same `key` cause; `sources` lists them.
4. Lesson -> `topics/`: lesson observed in >= 2 projects.
5. Lesson -> rule-candidate: `helped` >= 3 and `hurt` = 0. A rule-candidate becomes a proposal against `agents/advisor.md` or `agents/worker.md`, never applied directly.

## Dedup and conflict

Same `key` and same cause: merge counts. Same `key`, different cause: keep both; the newer one sets `superseded_by` on the older only when a verified outcome contradicts it.

## Pruning

Prune by outcome, not age. Score = 2 + helped - hurt; mark `superseded` at score <= 0. Entries unused for 90 days are re-verified against code (`verified_at`), not deleted.

## Write path

Only the hook-verified `task_outcome` event may set `outcome: worked` (G11, proposed). Advisor Bash write ability is removed via sandbox or PreToolUse check (G6 enforcement).

## Retrieval

Native markdown index + grep. Defer a semantic-search MCP until MEMORY.md would exceed 150 lines after pruning, or a recall check (20 known symptoms) shows > 20% misses.
