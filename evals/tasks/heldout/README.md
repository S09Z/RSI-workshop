# Task format

Each task is a folder with: repo, base commit, DONE_WHEN test, category tag, source (synthetic or replayed PR).
No tasks exist yet.

## Fields and rules (proposed — report §5, §8)

- `category`: one of bug, feature, refactor, test, config. Also tag `surface_under_test`.
- `source`: synthetic or replayed merged PR (dated).
- A human reads each task's tests once before entry (audit; broken tests are common).
- Do not use SWE-bench Verified as a gate (contaminated).
- `heldout/`: target >= 30 tasks. Each has a visible DONE_WHEN test plus a hidden test in `evals/graders/`.
- `rotating/` (proposed, not yet created): 5-10 tasks per month replayed from merged real PRs, dated, used once in heldout then moved to `train/`.
- Not part of any pooled Measure re-run after RSI starts except heldout + rotating (the proposer has seen `train/`).

PROTECTED: never shown to proposal generation.
