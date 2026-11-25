# Q3 and Q4 notes: turning outcomes into changes, and evaluating self-improvement

Evidence tags [E1xx], [E2xx], [E3xx] refer to `docs/research/evidence-log.md`. Numbers appear only as read; anything computed by me is under an **Inference** heading and labelled. Surfaces: agents/*.md, memory/advisor/, skills/, hooks/guardrails.yaml, routing/routing.yaml, evals/.

# Q3. Turning logged outcomes into proposed prompt, skill and rule changes

## Comparison table

| Method | Cost (as reported) | Reliability | Risk | Sources |
|---|---|---|---|---|
| Human blameless postmortem / retrospective | No cost figures in the source; effort is human review time. | Source says a draft is reviewed by senior engineers and that an unreviewed postmortem might as well never have existed. Triggers are qualitative only. | Source gives no measured failure modes; its stated risk is blame suppressing honest reports, addressed by the blameless norm. | [E300] |
| LLM reflection on own trajectories (Reflexion, ExpeL) | ExpeL about 4310 tokens per HotpotQA trajectory vs about 1320 for ReAct. Reflexion keeps 1-3 reflections. | Reflexion HumanEval 91.0 pass@1 (GPT-4 80.1); ExpeL ALFWorld 40.0% to 59.0%; no significant gain on WebShop for Reflexion. | Self-written tests false-positive 16.3% on MBPP; local minima; depends on the model's self-evaluation. | [E100][E102][E105] |
| LLM reflector + curator maintaining a playbook (ACE) | Reports -75.1% rollouts and -82.3% offline latency vs GEPA; no dollar figure read. | AppWorld ReAct+ACE 59.4% average vs IBM CUGA 60.3%; ICLR 2026 poster. | Needs a strong Reflector; degrades without reliable feedback; context collapse example 18,282 to 122 tokens, accuracy 66.7 to 57.1. | [E131][E132][E133] |
| Claude Code `/insights` (LLM report over session logs) | Up to 200 unseen sessions per run; tokens count against plan or API usage; no per-run figure given. Org average about 13 USD per developer per active day (context, not /insights cost). | Docs state no accuracy, no check of suggestions, and no automatic edit of any file; report is an HTML file for a human to read. | Suggestions unverified by any eval; reports deleted after 30 days by default. | [E305][E306] |
| LLM root-cause analysis of incidents (nearest evidence to LLM-written postmortems) | Not reported in the abstract. | ReAct agent competitive with strong baselines, higher factual accuracy; incident discussions gave no significant gain. | Search snippets mention hallucinated remediation steps (not opened; see Not verified). | [E307] |
| Automated prompt optimization against an eval set: MIPROv2 / DSPy | 20-50 full-evaluation trials; typically 500 train, 500 dev; 5 runs per method; no dollar, token or call counts reported. | Best on 5 of 7 tasks, gains up to 13%; ScoNe 79.4 vs 75.4 but HotPotQA 46.4 vs 45.8. DSPy docs advise 200+ examples to avoid overfitting. | Paper does not discuss overfitting; some tasks have no dev split; needs handwritten seed prompt for complex rules. | [E122][E123][E124][E303] |
| Automated prompt optimization: GEPA | 1,839 to 7,051 rollouts per benchmark vs 24,000 for GRPO; validation takes most of the budget; no dollar figure in the part read. | Beats MIPROv2 on all six benchmarks reported (e.g. AIME-2025 32.00 vs 20.00 on Qwen3 8B); Pareto selection +12.44 vs +6.05 for best-candidate. | Kernel and adversarial results labelled preliminary by the authors; self-reported README figures. | [E126][E127][E304] |
| Automated prompt optimization: OPRO, TextGrad | No cost figures read (abstracts only). | OPRO up to +8% GSM8K, up to +50% BBH vs human prompts; TextGrad GPQA 51% to 55%, LeetCode-Hard +20% relative. | Abstract-level only; mechanism details not read. | [E301][E302][E336] |
| Evolutionary search over agent code/config: ADAS | 25-30 iterations per domain; no dollar figure read. | DROP F1 79.4 vs 69.1, MGSM 53.4 vs 39.0, MMLU 69.6 vs 67.6, GPQA 34.6 vs 32.9. | Only single-step QA tasks evaluated; single objective; generated code needs containers. | [E110][E111] |
| Evolutionary: SICA, Darwin Godel Machine | SICA about 7,000 USD for 15 iterations; DGM about 22,000 USD per SWE-bench run vs about 10,000 USD baseline, about 2 weeks. | SICA SWE-B 0.17 to 0.51; DGM SWE-bench 20.0% to 50.0%. | DGM hallucinated tool use including a faked passing-test log; SICA reported no reward-hacking evaluation. | [E113][E114][E116][E117][E118] |
| Evolutionary with automated evaluators: AlphaEvolve, OpenEvolve | Not given in the post read. | Works only where solutions are automatically checkable; Borg heuristic recovers 0.7% of worldwide compute (vendor claim). | README figures lack stated methodology; no limitations section in OpenEvolve README. | [E120][E121] |

## Evidence

- Human practice: the SRE chapter defines a postmortem as a written record of impact, mitigation, root cause and follow-up actions, reviewed by senior engineers before wider sharing [E300]. It sets no numeric triggers [E300].
- LLM-written reflection is the oldest automated route and is bounded by the quality of the feedback signal: Reflexion's evaluator was self-written tests with a 16.3% false-positive rate on MBPP [E102]; ACE reports it degrades without reliable feedback [E133].
- Claude Code's own `/insights` is a read-only analysis step. The docs describe a report of friction points and suggestions generated from up to 200 sessions per run, and say its tokens count against usage [E305][E306]. The docs do not say it edits CLAUDE.md or checks its suggestions [E306].
- Optimizer budgets read: MIPRO 20-50 full-evaluation trials with 500 training and 500 dev examples [E303]; GEPA 1,839-7,051 rollouts depending on benchmark [E304]; GRPO 24,000 [E304]. DSPy docs recommend 40+ trials and 200+ examples for MIPROv2 to avoid overfitting [E124].
- Evolutionary methods are the most expensive reported: about 7,000 USD for 15 SICA iterations [E114], about 22,000 USD per DGM SWE-bench run [E117]. The DGM post reports a faked test log and removed hallucination-detection markers [E118].

## Inference

- The user's system has 10-20 eval tasks (system-context). Optimizers reported above use hundreds of training examples and thousands of rollouts [E303][E304]. Inference: a MIPROv2 or GEPA run on this eval set would be fitting 10-20 tasks, which is the overfitting situation the DSPy docs warn about [E124]. The cheap, safe pattern is LLM-proposed diffs (reflector style [E133] or `/insights`-style reading of events.jsonl) that a human approves and an eval gate checks, not an optimizer in the loop.
- Inference: `/insights` is a candidate generator for CLAUDE.md-level rules only; the docs claim no verification, so every suggestion needs the same eval gate as a hand-written change.
- Inference: reward hacking risk rises with automation and with the evaluator being editable by the optimized agent [E118]; guardrail G8 (Worker cannot edit DONE_WHEN tests) is the matching control.

# Q4. Evaluation design for self-improvement

## 4.1 Eval set design (overfitting resistance)

### Evidence
- OpenAI stopped reporting SWE-bench Verified on 2026-02-23: it says all frontier models tested had seen some problems or solutions, and of 138 audited problems 59.4% had material test or description issues (35.5% narrow tests, 18.8% wide tests) [E317].
- OpenAI then audited SWE-Bench Pro (public split of 731) and estimated about 30% broken tasks, and retracted its recommendation [E318]. The SWE-Bench Pro paper describes a public set, a held-out set and a commercial set not publicly accessible [E321].
- Rolling fresh tasks: SWE-bench-Live (1,319 tasks, issues created since 2024, 93 repos) [E319]; SWE-rebench (over 21,000 tasks, automated continuous collection; comparison suggests inflated scores from contamination) [E320]; LiveCodeBench adds new competitive-programming problems over time [E322].
- Anthropic: 20-50 simple tasks from real failures is a good start; early in development large effect sizes mean small samples suffice; an eval at 100% gives no signal; test both cases where a behavior should and should not occur; clean environment per trial (one trial read earlier trials' git history) [E130][E311].
- DSPy guidance: 200+ examples for MIPROv2 to avoid overfitting [E124].

### Inference
- For a private repository, contamination from public training data is less likely than leakage inside the system: advisor memory written during eval task A can reach task B, and the Worker may see git history of earlier trials [E130]. Reset memory and worktree per trial, or measure with memory frozen at a dated snapshot.
- Split tasks into an optimization/dev set (used to propose changes), a held-out set (touched only at the gate) and a rotating set refilled from newly merged real work (the SWE-bench-Live pattern [E319]). Tag each task with a category (bug fix, feature, refactor, test) and a creation date so changes can be tested only on tasks created after the change was designed.
- Public benchmark scores (SWE-bench Verified in particular) should not be used as the gate; inspect_evals defaults its swe_bench task to the Verified dataset [E330] while OpenAI says it is contaminated [E317].

## 4.2 Sample size and statistics

### Evidence (exact formulas, Miller 2024 [E308][E309])
- CI95 = mean +/- 1.96 x SE.
- Clustered: SE_clustered = ( SE_CLT^2 + (1/n^2) sum_c sum_i sum_{j != i} (s_ic - mean)(s_jc - mean) )^(1/2).
- Paired: SE_(A-B) = sqrt( Var(s_(A-B)) / n ); Var_paired = ( Var(s_A) + Var(s_B) - 2 Cov(s_A, s_B) ) / n.
- Resampling K times: Var(mu_hat given K) = Var(mu_hat given K=1) x (1 + 2/K)/3 in the uniform-difficulty binary example; do not pool all K x N answers into one SE; do not lower temperature to reduce variance.
- Sample size: n = (z_(alpha/2) + z_beta)^2 ( omega^2 + sigma_A^2/K_A + sigma_B^2/K_B ) / delta^2, with omega^2 = Var(x_A) + Var(x_B) - 2 Cov(x_A, x_B), where x is a question's mean score and sigma^2 is expected within-question variance.
- MDE: delta = (z_(alpha/2) + z_beta) sqrt( (omega^2 + sigma_A^2/K_A + sigma_B^2/K_B) / n ). Paper's examples: about 969 questions for delta = 0.03; with n = 198, K from 1 to 10 cuts MDE from 13.2% to 7.5%.
- Anthropic's post summarizes the same five recommendations and reports question-score correlations of 0.3 to 0.7 between frontier models [E310].
- Agent runs: 10 runs per configuration on SWE-Bench-Verified moved single-run pass@1 by 2.2 to 6.0 points; temperature 0 did not remove variance [E313][E314]. Their power table (80% power, p < 0.05): 2-point gain at sigma 1.5% needs about 9 runs; 1-point needs about 36; 10-point needs 1 run [E314].
- Anthropic: infrastructure configuration moved Terminal-Bench 2.0 scores by 6 points (p < 0.01); differences below 3 points deserve skepticism [E312].
- pass^k = E_task[ C(c,k) / C(n,k) ] and pass@k = 1 - E_task[ C(n-c,k) / C(n,k) ] with n trials, c successes [E316]. Anthropic's illustration: 0.75 per-trial over 3 trials gives about 42% pass^3 [E130][E311]. Pass^k and pass@k diverge widely for agents (Devstral-2 pass@1 63.5, pass@5 76.2, pass^5 49.1) [E314].
- Inspect implements clustered stderr via `stderr(cluster=...)`, `--epochs` and reducers pass_at_k / pass_k_k [E329]; promptfoo has `--repeat` but docs mention no significance testing [E327].

### Inference: minimum detectable difference for the +15-point gate (computed by me)
Setup: paired comparison of two configurations on the same N tasks, K independent runs per task per configuration, two-sided alpha = 0.05, power 80%, so z_(alpha/2) + z_beta = 1.960 + 0.842 = 2.802. I apply Miller's Equation 10 with sigma_A^2 = sigma_B^2 = sigma^2:

MDE = 2.802 x sqrt( (omega^2 + 2 sigma^2 / K) / N )

Sanity check: this reproduces Miller's 969 questions (omega^2 = 1/9, delta = 0.03) and his 13.2% to 7.5% example (I get 13.3% and 7.6%).

Assumptions (mine, not measured on this system): omega^2 is the variance across tasks of the true per-task success-rate difference; scenario A omega^2 = 0.09 (SD 0.30), sigma^2 = 0.08; scenario B omega^2 = 1/9, sigma^2 = 1/6 (Miller's example values). Normal approximation (z, not t), so small-N values are optimistic. Tasks independent, runs independent, no clustering by repository.

MDE in percentage points, scenario A:

| N tasks | K=1 | K=3 | K=5 | K=10 |
|---|---|---|---|---|
| 10 | 44.3 | 33.5 | 30.9 | 28.8 |
| 15 | 36.2 | 27.4 | 25.3 | 23.6 |
| 20 | 31.3 | 23.7 | 21.9 | 20.4 |
| 30 | 25.6 | 19.4 | 17.9 | 16.7 |
| 50 | 19.8 | 15.0 | 13.8 | 12.9 |

Scenario B at N = 20: 41.8 (K=1), 29.5 (K=3), 26.4 (K=5), 23.8 (K=10); at N = 50: 26.4, 18.7, 16.7, 15.1.

Tasks needed to detect exactly +15 points: scenario A 87 (K=1), 50 (K=3), 43 (K=5), 37 (K=10); scenario B 155, 78, 62, about 50. Even with deterministic tasks (sigma^2 = 0, K irrelevant) scenario A needs N = 2.802^2 x 0.09 / 0.15^2 = about 31 tasks.

Consequences (inference): (1) With 10-20 tasks the MDE is roughly 20-40 points, so a measured +15 cannot be told from noise; the gate would be a descriptive threshold, not a significance test. (2) Raising K helps only until omega^2 dominates; adding tasks is the stronger lever. (3) Two comparisons (single vs orchestrator+worker, and vs full system) at Bonferroni alpha = 0.025 raise the z sum to about 3.08, scaling every MDE by about 1.10. (4) A defensible gate with 15-20 tasks is "paired 95% CI lower bound above 0 on a much larger effect, or a pre-registered descriptive threshold with the CI reported", otherwise grow the set to 40-90 tasks.

## 4.3 Graders and calibration

### Evidence
- Code-based graders: fast, cheap, objective, reproducible but brittle to valid variations; model graders flexible but non-deterministic and need calibration with human graders; humans calibrate model graders [E311]. Grade the outcome, not the path; give partial credit on multi-component tasks [E311].
- Deterministic tests are fallible: 59.4% of audited SWE-bench Verified problems had flawed tests [E317]; about 30% of SWE-Bench Pro public tasks estimated broken, with low-coverage tests letting incomplete fixes pass [E318]; Reflexion's self-written tests false-positive 16.3% on MBPP [E102]; Opus 4.5 scored 42% on CORE-Bench until grading bugs were fixed, then 95% [E130].
- Judge calibration: GPT-4 agreed with humans 85% on non-tie votes vs 81% human-human; 66% vs 63% when ties counted [E324]. Position bias: swap-consistency GPT-4 65.0%, GPT-3.5 46.2%, Claude-v1 23.8%; verbosity attack failure Claude-v1 91.3%, GPT-4 8.7%; math grading failures 14/20 default, 3/20 with a reference answer [E324]. G-Eval Spearman 0.514 with humans on summarization, with possible bias toward LLM-generated text [E325]. Mitigations: swap positions, chain-of-thought, reference-guided judging, few-shot (about 4x cost) [E324]. Peer-reviewed venue for the MT-Bench paper: NeurIPS 2023 D&B [E323].
- promptfoo `llm-rubric` returns score 0-1 and pass; without threshold, `pass` decides; docs do not discuss calibration [E327].

### Inference
- Primary grader for this system: the DONE_WHEN test (deterministic) plus a held-out hidden test the Worker cannot see, since visible tests can be gamed or flawed [E102][E318]. Audit each eval task's test once by hand (the OpenAI audits used five to six engineers per case [E317][E318]; for 10-20 tasks one engineer reading each is feasible).
- Use an LLM judge only for what tests cannot see (report quality, diff minimality), always with a reference answer, order swapping and a human-labelled calibration slice. Agreement numbers above come from chat preference and summarization, not code review, so the user must measure agreement on their own labelled sample.

## 4.4 Non-target regression detection

### Evidence
- Anthropic separates capability evals (start low) from regression evals (nearly 100% pass) and says capability evals can graduate into regression suites; also test cases where behavior should not occur [E311].
- Inspect `grouped()` computes a metric per metadata group plus an overall metric [E329].
- Infra and run noise can mask or mimic changes: 6-point swing from resource limits [E312].

### Inference
- Tag every eval task with category and surface-under-test; report per-category paired deltas next to the aggregate, with the caveat that each slice has a much larger MDE than the aggregate (MDE scales with 1/sqrt(slice size)).
- Because slices are tiny, regression is better caught by a canary suite of deterministic checks (guardrails G1-G8 still fire; report contract still validates; advisor memory under 200 lines) than by score deltas. This canary-suite idea is my design suggestion; no source read defines it for agent systems.
- Freeze resources and model versions per eval run [E312] so a changed prompt is the only variable.

## 4.5 Tools

| Tool | Stars | Last push | License | Role for this system | Maturity flags | Sources |
|---|---|---|---|---|---|---|
| promptfoo | 27643 | 2026-11-25 | MIT | Prompt/model comparison, CI gate, llm-rubric judge, `--repeat` | README says now part of OpenAI (governance risk, stays MIT); no significance testing in docs; built for prompt/app evals, not multi-agent repo runs (my reading) | [E326][E327] |
| Inspect AI | 3332 | 2026-11-25 | MIT | Eval framework with epochs, reducers incl. pass_k, clustered stderr, grouped metrics | Version 0.3.292 (0.x); fewer stars; whether it can drive a user-configured `claude --agent orchestrator` session not verified | [E328][E329] |
| inspect_evals | 758 | 2026-11-25 | MIT | swe_bench, swe_bench_verified_mini tasks | Default dataset is SWE-bench Verified (contaminated per OpenAI); heavy Docker and token use; arm64 images expose reference fixes | [E330][E317] |
| Harbor | 7427 | 2026-11-25 | Apache-2.0 | Official Terminal-Bench 2.0 harness; runs Claude Code and other agents; custom benchmarks | v0.27.0 (0.x); needs Docker or cloud sandboxes | [E331] |
| terminal-bench-2 / -1 | 453 / 2626 | 2026-04-30 / 2026-07-11 | Apache-2.0 | Terminal task benchmark | Moved under harbor-framework; terminal tasks, not repo PR work | [E332][E312] |
| SWE-bench / SWE-bench-Live | 6241 / 265 | 2026-09-18 / 2026-11-24 | MIT | Original harness / rolling fresh tasks | Verified contaminated [E317]; Live is a small repo with preprint-only paper | [E334][E319] |
| LiveCodeBench | 980 | 2025-07-16 | MIT | Contamination-limited code problems | No push since 2025-07; competitive programming, not agentic | [E335][E322] |
| tau-bench | 1517 | 2026-03-18 | MIT | Defines pass^k | Customer-service domains, not coding | [E335][E316] |
| openai/evals | 19799 | 2026-04-14 | NOASSERTION (as reported) | Eval registry | Not accepting custom-code evals; license unclear; last push 2026-04 | [E333] |

Inference: for this system the practical choice is a thin custom harness (a script that runs each task K times in a fresh worktree and writes paired per-task results) plus analysis code implementing the E309 formulas, optionally wrapped in Harbor (documents Claude Code as a supported agent [E331]) or Inspect (for epochs/stderr [E329]). Verify first that either can load the user's global ~/.claude agent definitions; that was not checked.

## Disagreements between sources

- SWE-Bench Pro: OpenAI first recommended it as the replacement for Verified [E317], then retracted the recommendation after estimating about 30% broken tasks [E318]. The Pro authors position it as contamination-resistant [E321].
- Sample size: Anthropic says 20-50 tasks is a good start and large effects need small samples [E130][E311]; Miller's worked example says new evals should have at least 1,000 questions for a 3-point difference [E309]. They are consistent only if the effect is large; the +15 gate is mid-sized.
- Variance size: Anthropic's infrastructure post says differences under 3 points deserve skepticism [E312]; the randomness paper finds single-run swings of 2.2 to 6.0 points from run choice alone [E313]. The latter implies the threshold is larger for single runs.
- Internal mismatches: randomness paper abstract says temperature-0 SDs exceed 1.5 while its Table 1 shows about 1.0 to 1.8 [E314]. GEPA's text cites aggregate gains (+13.33 and +5.64 for GPT-4.1 Mini) different from the Qwen3 8B table (+9.62 and +2.61), which is explained by different models, not an error [E304]. In Miller's Section 4.2 example the stated variance reduction from 1/6 to 1/9 does not follow from the stated Cov = 1/24 under his own formula (1/6 - 2/24 = 1/12); I used only Equations 9-10 and checked them against his 969 and 13.2%/7.5% examples [E309].
- Reliability of pass^k: Anthropic's 0.75^3 = about 42% assumes independent trials [E311]; tau-bench's estimator uses observed per-task counts, which differs when tasks vary in difficulty [E316].

## Not verified

- OPRO and TextGrad mechanism and cost details (abstract pages only) [E301][E302]; AlphaEvolve and OpenEvolve cost figures.
- GEPA Appendix H (generalization gap) and Section E.3 (costs): the page was truncated at 100k of 181k characters [E304]. MIPRO last 29k characters unread [E303]. Miller Appendix C (cluster-adjusted power formulas) not read.
- Claims from search snippets only, pages not opened: DeepSWE (2607.07946), AgentLens, SWE-NFI, SWEPatchTest, OpenRCA / CloudIR-Bench / ORCA-bench hallucination findings, a secondary review of the OpenAI retraction (arXiv 2608.13867).
- Whether Anthropic's own docs say anything about `/insights` accuracy beyond the two pages read; third-party blog claims (30-day window, 50-session cap) conflict with the docs' 200-session figure and are not used.
- Venues: OPRO (ICLR 2024), SWE-rebench (NeurIPS 2025), GEPA (ICLR 2026 oral) are stated in arXiv comments only, so logged as preprint.
- Inspect pass_at_k / pass_k_k computation details; whether Inspect or Harbor can run the user's ~/.claude agents; promptfoo behavior with repeats and caching.
- No source read defines "canary suite" for agent systems, and no source reports a measured cost of an LLM-written postmortem.
- Judge-agreement numbers are from chat and summarization tasks; none read for code or agent transcripts.
