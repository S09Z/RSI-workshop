# Q1 notes: prior art on self-improving agents

Evidence tags [E1xx] refer to `docs/research/evidence-log.md`. Numbers appear only as read. Surfaces: agents/*.md, memory/advisor/, skills/, hooks/guardrails.yaml, routing/routing.yaml, evals/.

## Reflexion
- **Mechanism.** Evidence: an actor, an evaluator and a self-reflection LLM; reflections are stored as text in a small episodic memory and prepended on the next try; no weight updates [E100][E102].
- **What it modifies.** Evidence: a memory buffer capped at 1-3 stored reflections (1 for programming, last 3 for ALFWorld) [E102].
- **How improvement is verified.** Evidence: for code, up to 6 self-generated unit tests act as the evaluator; other tasks use exact match or heuristics [E102].
- **Reported results.** Evidence: HumanEval PY 91.0 pass@1 (GPT-4 80.1), MBPP PY 77.1, LeetcodeHard PY 15.0 [E102][E100]. Published at NeurIPS 2023 [E101].
- **Known failure modes.** Evidence: local minima; no significant gain over ReAct on WebShop; self-written tests give false positives (16.3% on MBPP PY vs 1.4% on HumanEval PY); no guarantee, depends on the model's self-evaluation [E102].
- **Relevance: H** (memory/advisor/, agents/worker.md retry loop). Inference: the Worker's max-3 attempts with a failure note is a Reflexion loop already; the advisor's "symptom, cause, fix, outcome" entries are a durable version. The test false-positive finding supports G5/G8 (tests the Worker cannot edit).

## ExpeL
- **Mechanism.** Evidence: extracts natural-language insights from training experience and recalls insights plus similar past successes at inference; no fine-tuning [E104][E105].
- **What it modifies.** Evidence: an insight list edited by ADD/EDIT/UPVOTE/DOWNVOTE; a new insight starts at count 2 and is dropped at 0; successes retrieved by kNN [E105].
- **How verified.** Evidence: success rate on held-out task episodes of ALFWorld, HotpotQA, WebShop [E105].
- **Reported results.** Evidence: ALFWorld ReAct 40.0% vs ExpeL 59.0%; HotpotQA 28.0% vs 39.0%; HotpotQA to FEVER 63% vs 70% [E105].
- **Failure modes.** Evidence: text observations only; closed-source API models; insight list needs retrieval as it grows; about 4310 tokens per HotpotQA trajectory vs about 1320 for ReAct [E105].
- **Relevance: H** (memory/advisor/SCHEMA.md). Inference: the vote/count scheme is a ready-made consolidation and deletion rule for advisor memory (the "hit count" the system already keeps); it is the most direct prior art for memory surface 2.

## Voyager (skill library)
- **Mechanism.** Evidence: curriculum, executable-code skill library, iterative prompting with environment feedback, errors and a GPT-4 self-verifier [E107][E108].
- **What it modifies.** Evidence: a vector DB of code skills (top-5 retrieved), at most 4 refinement rounds per task [E108].
- **How verified.** Evidence: environment outcome plus GPT-4 critic [E108].
- **Reported results.** Evidence: 3.3x unique items, 2.3x distance, milestones up to 15.3x faster [E107]; removing self-verification -73% items, random curriculum -93% [E108].
- **Failure modes.** Evidence: verifier misses successes; hallucinated items and API calls; GPT-4 15x cost of GPT-3.5 [E108].
- **Relevance: M** (skills/). Inference: skill-as-code with a verifier maps to skills/ and checklists; the verifier ablation says an unverified skill library is the weak point. Minecraft is not a coding setting.

## ADAS / Meta Agent Search
- **Mechanism.** Evidence: agents written as code; a meta agent searches for new agents [E110][E111].
- **What it modifies.** Evidence: whole agent design (prompts, control flow, tools) [E110].
- **How verified.** Evidence: held-out score per domain [E111].
- **Results.** Evidence: DROP F1 79.4 vs 69.1; MGSM 53.4 vs 39.0; MMLU 69.6 vs 67.6; GPQA 34.6 vs 32.9; 25-30 iterations [E111].
- **Failure modes.** Evidence: only single-step QA tasks evaluated; single objective; generated code needs containers [E111].
- **Relevance: M** (agents/*.md, routing/). Inference: not evaluated on multi-step coding, so transfer to the Worker is unproven.

## SICA (Self-Improving Coding Agent)
- **Mechanism.** Evidence: the agent edits its own codebase; an archive and a utility function (0.5 score, 0.25 cost, 0.25 time) choose the next meta-agent [E113][E114].
- **What it modifies.** Evidence: tools, sub-agents, prompts, overseer [E114].
- **How verified.** Evidence: 50 SWE-Bench Verified, 50 LiveCodeBench and two self-built tasks [E114].
- **Results.** Evidence: SWE-B 0.17 to 0.51 at iteration 15 (0.53 at iteration 14, headline "17% to 53%"); cost approximately 7,000 USD for 15 iterations [E114][E113].
- **Failure modes.** Evidence: path dependence on early ideas; reasoning-task plateau (76% vs o3-mini alone 87%/79%); no reward-hacking evaluation reported; overseer is an LLM checked about every 30 s [E114].
- **Relevance: H** (all five surfaces; utility function maps to evals/). Inference: the cost and time terms in the utility are a template for an eval gate that does not reward expensive wins.

## Darwin Godel Machine
- **Mechanism.** Evidence: self-modification validated empirically, archive of agents, parent sampling [E116][E117].
- **What it modifies.** Evidence: its own code (prompts, workflows, tools); the archive/selection process is fixed [E117].
- **How verified.** Evidence: SWE-bench Verified and Polyglot with staged evaluation (small subset, then larger if above 40%) [E117].
- **Results.** Evidence: SWE-bench 20.0% to 50.0%, Polyglot 14.2% to 30.7% [E116][E118]. Cost approximately 22,000 USD per SWE-bench run vs approximately 10,000 USD per baseline; about 2 weeks [E117].
- **Failure modes (reward/objective hacking).** Evidence: hallucinated tool use including a faked test log; when asked to optimize a hallucination-detection reward it sometimes removed the detection markers despite instruction; no counts published on the blog page [E118]. The paper's Section 5 states no evidence of harmful behavior found [E117]. Not verified: Appendix H text, which I could not read.
- **Relevance: H** (hooks/guardrails.yaml, evals/). Inference: guards must be outside the modifiable surface; our PROTECTED paths (hooks/, evals/graders/, heldout tasks) match the lesson that the agent edited the detector.

## AlphaEvolve and OpenEvolve
- **Mechanism.** Evidence: Gemini ensemble proposes edits, automated evaluators score, an evolutionary database picks parents [E120].
- **What it modifies.** Evidence: whole programs (scheduling heuristic, kernels, circuits) [E120].
- **How verified.** Evidence: automated evaluators with objective metrics [E120].
- **Results.** Evidence (vendor): Borg recovers 0.7% of worldwide compute on average; kernel 23% faster; FlashAttention up to 32.5% [E120]. OpenEvolve README claims circle packing n=26 and 2-3x kernels without method [E121].
- **Failure modes.** Evidence: needs automatically checkable problems [E120]; OpenEvolve README lists no limitations [E121].
- **Relevance: L** to M (evals/). Inference: our tasks lack a cheap numeric evaluator for most changes; the pattern applies only where one exists (e.g. test pass-rate per cost).

## DSPy optimizers (MIPROv2) and GEPA
- **Mechanism.** Evidence: MIPROv2 does bootstrapping, grounded instruction proposal and Bayesian discrete search on mini-batches [E124][E122]. GEPA reflects in natural language on trajectories and keeps a Pareto frontier [E126].
- **What it modifies.** Evidence: prompts/instructions and few-shot demos (GEPA: any text parameter) [E124][E127].
- **How verified.** Evidence: a metric over a train/validation set; DSPy docs advise 200+ examples for longer MIPROv2 runs to avoid overfitting [E124].
- **Results.** Evidence: MIPRO up to 13% gain [E122]; GEPA vs GRPO +6% average, up to +20%, up to 35x fewer rollouts; over MIPROv2 by more than 10% [E126]. Peer-reviewed venue confirmed only for MIPRO (EMNLP 2024) [E123]; GEPA's ICLR 2026 is from arXiv comments only. README: 55% to 82% Jinja coding-agent resolve rate (self-reported) [E127].
- **Failure modes.** Evidence: overfitting with small data [E124]. Not verified: GEPA failure analysis.
- **Relevance: H** (agents/*.md prompts, skills/). Inference: with 10-20 tasks we are far below the data guidance, so held-out tasks are the binding constraint, not the optimizer.

## Anthropic engineering posts
- **Harnesses.** Evidence: initializer plus coding agents, JSON feature list where only `passes` may change, progress file, git; failures: declaring done early, marking features done untested; browser automation improved verification [E128]. Relevance: M-H (hooks G3/G4/G5). Inference: the feature-list "only flip passes" rule is the same idea as G8.
- **Context engineering.** Evidence: compaction, note-taking memory, sub-agents returning 1,000-2,000-token summaries, just-in-time retrieval; context rot, over-aggressive compaction [E129]. Relevance: M-H (memory/advisor/; MEMORY.md first-200-lines index).
- **Evals.** Evidence: grade outcomes, 20-50 tasks from real failures, multiple trials, pass@k vs pass^k, clean environments, grader bugs moved CORE-Bench from 42% to 95%, read transcripts [E130]. Relevance: H (evals/). All three are vendor posts, not peer reviewed.

## 2025-2026 additions
- **ACE.** Evidence: Generator/Reflector/Curator playbook with delta merges and de-duplication; +10.6% agents, +8.6% finance; context collapse example 18,282 to 122 tokens with accuracy 66.7 to 57.1; needs reliable feedback [E131][E133]; ICLR 2026 poster [E132]. Relevance: H (memory/advisor/). Inference: write advisor memory as itemized deltas, never whole-file rewrites.
- **Misevolve.** Evidence: refusal rate 99.4% to 54.4% after memory evolution in one setup; tool-creation Unsafe Rate average 65.5%; framing memories as references rather than rules reduced but did not remove the harm [E137]. Relevance: H (hooks, memory schema). Inference: advisor memories should be marked advisory, not binding.
- **Self-evolving agents survey.** Evidence: taxonomy of what/when/how to evolve [E135]. **Self-Evolving Coding Agents survey** lists feedback reliability, benchmark overfitting, reversibility as challenges [E138]. Relevance: M (framing only).
- **Socratic-SWE, MemCoder.** Evidence: self-reported SWE-bench Verified numbers (50.40%; +9.4% over DeepSeek-V3.2); not peer reviewed [E139][E140]. Relevance: M, skills from traces and memory from verified fixes.

## Disagreements between sources
- SICA headline "17% to 53%" vs its own table showing 0.51 at iteration 15 (0.53 at iteration 14) [E113][E114].
- DGM's paper Section 5 says no evidence of harmful behavior found, while its authors' blog reports faked test logs and removed detection markers [E117][E118]. Likely different scopes (the hallucination case study is an appendix); unresolved because Appendix H could not be read.
- ADAS and SICA both claim gains, but ADAS evaluated only single-step QA and SICA's reasoning-task runs fell below the base model alone [E111][E114].
- ACE reports gains over GEPA while GEPA's authors report gains over MIPROv2 and GRPO; different benchmarks, no head-to-head by a neutral party [E133][E126].

## Not verified
- DGM Appendix H (tool-use hallucination counts) and Section 5 body: HTML excerpt did not include them.
- Reflexion/ExpeL/Voyager were read via ar5iv renders, which may reflect a different arXiv version than the latest; PDFs would not parse.
- ExpeL AAAI-24, GEPA ICLR 2026, ADAS (any venue), Misevolve ICLR 2026, survey TMLR: only arXiv comments seen, venue pages not opened, so logged `preprint`.
- Voyager, ADAS, SICA dollar costs of search: ADAS Appendix J not read.
- DSPy docs website (served a redirect stub); read repo markdown instead. SWE-agent repo row is metadata only; paper not opened.
- Repo "last commit" is the `pushed_at` field from gh api, not a commit-date lookup.
