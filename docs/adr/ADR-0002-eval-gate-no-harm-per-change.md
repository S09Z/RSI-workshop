# ADR-0002: Eval gate is no-harm per change and powered only at Measure

Status: Proposed
Date: 2026-11-25
Source: docs/report/rsi-research-report.md §9

- **Context.** At K = 3, 10–20 tasks give an MDE of about 24–42 points (scenarios A and B, inference from [E309]). The normal approximation makes small-N values optimistic. Run-to-run swings of 2.2–6.0 points come from run choice alone [E313], and deterministic tests are often flawed [E317][E318].
- **Options.** (a) Significance-test each proposal on 10–20 tasks. (b) Grow to ≥ 200 tasks for small effects. (c) A per-proposal no-harm gate plus a canary. (d) Canary plus a quarterly re-run, with no per-proposal eval. The only significance test is the Measure gate: one primary comparison at N ≥ 50 (A) to ~80 (B), K = 3, recomputed with the ω² and σ² measured in X2.
- **Decision.** (c), exact criteria in §5. Gate code in `evals/graders/` and harness in `evals/harness/` are PROTECTED.
- **Consequences.** Accepted changes mean "no measured harm", not proven wins. The per-proposal non-inferiority margin is 20 points, so it catches only large regressions. The Measure gate stays descriptive until N reaches the recomputed size. Cost ≈ $194 per proposal (heldout runs only); $832.50 per Measure run at 50 tasks, $1,332 at 80. Option (d) would save the per-proposal gate, which at 1–2 proposals a week costs about 52–104 × $194 ≈ $10,088–20,176 a year (inference: §5 cost basis, 52 weeks), plus ≈ $194 per promotion to refresh cached results. The decision stands: without the gate, a regression reaches live work and is caught only by the canary or by M1, whose alert needs 43+ tasks per window and goes to human review (§7), so a large regression could run for weeks; the gate catches a −20-point drop before install. Revisit (d) if the measured proposal rate or the measured cost per run makes the gate the dominant spend.
