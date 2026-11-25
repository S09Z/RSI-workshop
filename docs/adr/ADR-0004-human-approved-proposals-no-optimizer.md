# ADR-0004: Proposals are human-approved git diffs; no automated optimizer or evolutionary search yet

Status: Proposed
Date: 2026-11-25
Source: docs/report/rsi-research-report.md §9

- **Context.** Optimizers need 200+ examples [E124]; evolutionary runs cost 7,000–22,000 USD [E114][E117] and showed objective hacking [E118].
- **Options.** (a) DSPy/GEPA over prompts. (b) SICA/DGM-style self-editing archive. (c) LLM-drafted, human-approved diffs, one surface each.
- **Decision.** (c). Revisit (a) when `evals/tasks/train/` ≥ 200 tasks.
- **Consequences.** Slow cadence (≤ 2 proposals/week); human time ~1 hour per proposal.
