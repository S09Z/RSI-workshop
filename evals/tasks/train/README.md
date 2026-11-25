# Task format

Each task is a folder with: repo, base commit, DONE_WHEN test, category tag, source (synthetic or replayed PR).
No tasks exist yet.

## Fields and rules (proposed — report §5, §8)

- `category`: one of bug, feature, refactor, test, config. Also tag `surface_under_test`.
- `source`: synthetic or replayed merged PR (dated).
- A human reads each task's tests once before entry (audit; broken tests are common).
- Do not use SWE-bench Verified as a gate (contaminated).
- `train/` (dev): visible to the proposer; target >= 20 tasks.
- Tasks from `rotating/` move here after one use in heldout.
