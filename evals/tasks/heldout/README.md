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
- After RSI starts, Measure re-runs use only heldout and rotating tasks. `train/` is excluded because the
  proposer has seen it (report §5, Pooling).
- Read isolation (proposed G10, report §5): managed-settings deny rules for Read, Grep and Glob on
  `evals/tasks/heldout/**` and `evals/graders/**` in every agent session, plus a sandbox read-deny for
  Bash. Not in place today: `PROTECTED.paths` blocks writes only, not reads.

PROTECTED: never shown to proposal generation.
