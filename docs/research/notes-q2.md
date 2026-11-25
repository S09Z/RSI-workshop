# Q2 notes: memory as the main learning channel

Evidence tags [E2xx] and [E1xx] refer to `docs/research/evidence-log.md`. Numbers appear only as read. Target surface: `memory/advisor/` (MEMORY.md index auto-loaded first 200 lines; `projects/<project>.md` symptom, cause, advised fix, outcome, hit count; `topics/<topic>.md`). Prior art already logged and not repeated here: Reflexion [E100][E102], ExpeL [E104][E105], ACE [E131][E133], MemCoder [E140], Misevolve [E137].

## 1. Entry schema practice

**Evidence**
- Claude Code's own auto memory types each note as `user`, `feedback`, `project` or `reference` in frontmatter, one topic file per memory, one line per index entry; it skips anything derivable from code or already in CLAUDE.md [E200].
- The Anthropic memory tool leaves structure to the developer; the docs recommend keeping memory "up-to-date, coherent and organized" and give a multi-session pattern (progress log, feature checklist, mark complete only after end-to-end verification) [E203].
- ExpeL stores insights with an importance count (starts at 2, removed at 0) edited by ADD/EDIT/UPVOTE/DOWNVOTE [E105].
- A-MEM writes each memory as a note with contextual description, keywords, tags and links to related notes [E210]. MIRIX separates six memory types including procedural and episodic [E227]. The survey organizes memory by function (factual, experiential, working) [E219].
- ReasoningBank stores strategies distilled from both successes and failures rather than raw trajectories [E218]; Agent Workflow Memory stores reusable workflows [E217]. The MCP memory server prescribes atomic observations, one fact each [E234].
- Graphiti attaches validity windows to facts [E231][E212]. Mem0's Claude Code plugin tags each memory with project, user, repository and session ids [E229].
- LongMemEval found that indexing at round granularity beat whole-session indexing and that adding extracted facts to retrieval keys raised recall by 9.4% on average [E215].

**Inference**
- The advisor schema (symptom, cause, advised fix, outcome, hit count) already matches the "experience entry" shape from ExpeL and ReasoningBank. Missing fields the evidence supports: a type (so a retrieval step can filter), `verified_at` or commit reference, validity (`valid_until`/`superseded_by`, from Graphiti), whether the outcome was success or failure (ReasoningBank), and a one-line retrieval key (fact-augmented key from LongMemEval). Keep entries atomic and one line in MEMORY.md, details in topic or project files, as Claude Code's own limit enforcement implies [E200].
- Excluding derivable facts [E200] argues against storing file paths or code in the advisor's memory; store the reasoning link (why the symptom had this cause).

## 2. Consolidation (episode to lesson to rule)

**Evidence**
- Generative Agents condense raw logs into "higher-level reflections" [E209]; Reflexion keeps 1-3 reflections [E102]; ExpeL extracts insights then votes them up or down [E105]; ReasoningBank distills strategies from successes and failures and reports beating raw-trajectory memory [E218]; ACE uses a Curator with deterministic delta merges, and one rewrite step collapsed an 18,282-token context to 122 tokens and lowered accuracy below baseline [E133].
- Anthropic's Dreams job reads a store plus 1 to 100 transcripts and writes a new, separate store; the input is never modified, so output can be reviewed and discarded; research preview only, Managed Agents API [E205]. Auto dream in Claude Code is reported, unofficial [E206]. Letta Code's Dreaming runs background subagents that consolidate lessons and backs up before reorganizing [E233]. mcp-memory-service advertises autonomous consolidation [E236].
- One developer anecdote: a cleaned MEMORY.md regrew from compact to 790 lines in four weeks [E207].

**Inference**
- The write-to-a-new-copy, human-reviewable pattern in Dreams [E205] is the safest consolidation design for an RSI gate: consolidation output becomes a diff the human approves, matching "human approval + eval gate". Guard against the ACE collapse failure [E133] by requiring consolidation to keep a pointer to each source entry and by evaluating before and after.
- Promotion rule candidate (inference, not from a source): an entry with N hits across 2 or more projects moves from `projects/` to `topics/`, and a stable topic entry may be proposed as a CLAUDE.md or checklist rule. Claude Code docs support the direction (CLAUDE.md for rules, auto memory for learnings) [E200].

## 3. Dedup, conflicts, staleness, deletion

**Evidence**
- Docs state stores accumulate duplicates, contradictions and stale entries over sessions [E205]; Claude Code asks Claude to merge or drop stale entries near the limit [E200]; contradictory CLAUDE.md instructions may be resolved arbitrarily, so review periodically [E201].
- Policies differ. Mem0's paper has ADD/UPDATE/DELETE/NOOP chosen by an LLM [E211]; Mem0's 2026 algorithm is ADD-only, nothing overwritten [E228]; Graphiti invalidates with time stamps and keeps history [E212][E231]; ExpeL removes at count 0 [E105]; the memory tool docs say to expire files not accessed for a long time [E203].
- Empirical effect of management: indiscriminate add-all lowered performance below a fixed 100-record memory on all four tasks; strict selective addition was best; history-based deletion helped on 3 of 4 tasks; periodic deletion shrank stores 60% to 70% but lowered accuracy in all four strict cases [E221]. ACL 2026 version confirms the study is peer-reviewed [E220].
- MemoryAgentBench lists selective forgetting (conflict resolution) as one of four competencies on which evaluated agents fall short [E222][E223].
- Poisoning: AgentPoison reports at least 80% average attack success at under 0.1% poison rate [E224]; MINJA injects through ordinary queries [E225]; a later study finds pre-existing legitimate memory sharply reduces attack effectiveness, and that defenses need threshold calibration [E226]. Misevolve: memory evolution cut one agent's refusal rate 99.4% to 54.4% [E137].

**Inference**
- Do not delete on age alone; the evidence favors deleting by outcome signal (history-based) [E221]. For the advisor: decrement or flag entries whose advice led to a FAILED outcome, supersede (do not overwrite) on conflict and keep the old entry marked `superseded_by`, similar to Graphiti [E212].
- Write path is an attack surface: the advisor writes memory from worker output and task text. Only the orchestrator-reported verified outcome (G4/G5 evidence) should create or upvote an entry; G6 already confines writes to the memory folder.
- Keep a hard size budget on MEMORY.md (200 lines or 25KB are the platform limits [E200]); entries past it are silently dropped on load, so ordering matters.

## 4. Retrieval options

**Evidence**
- Markdown index plus on-demand files: Claude Code loads the first 200 lines or 25KB of MEMORY.md at start, topic files only when read [E200]; subagent memory does the same [E202]; the API memory tool is file operations on /memories [E203].
- File plus grep: Letta reports 74.0% on LoCoMo with a plain file and grep/search tools vs 68.5% reported for Mem0's graph variant, self-reported with caveats [E214].
- Semantic/hybrid: Mem0 2026 fuses semantic, BM25 and entity scores [E228]; claude-mem layers Chroma on SQLite FTS5 with a three-step index, timeline, details workflow at about 50-100 tokens per index row [E235]; basic-memory offers semantic search over markdown [E237].
- Graph: Zep/Graphiti temporal graph [E212][E231]; MCP memory server substring search over entities and observations [E234]; Cognee [E238]; mcp-memory-service typed edges [E236].
- Benchmark evidence: Zep beats full-context on LongMemEval (63.8 vs 55.4 with gpt-4o-mini) at 1.6k vs 115k context tokens [E212], but on LoCoMo full-context scored 72.90 above every memory system in Mem0's table [E211]. LongMemEval design findings (round granularity, fact-augmented keys, time-aware queries) apply to any retriever [E215].

**Inference**
- At advisor scale (tens to low hundreds of entries per project) the markdown index plus grep is likely sufficient; the evidence that semantic or graph beats grep at that scale is thin and vendor-contested (see Disagreements). Roadmap "semantic-search MCP" is justified only if the index exceeds the 200-line budget or recall tests show misses. Reasoning: the LoCoMo conversations are about 26k tokens [E211], smaller than a large project memory folder, so those results do not transfer directly.

## 5. Measuring whether memory helps

**Evidence**
- Anthropic reports 39% (memory tool plus context editing) and 29% (context editing alone) on an internal evaluation; no methodology given [E204].
- Benchmarks: LongMemEval (500 questions, five abilities) [E215], LoCoMo [E216], MemoryAgentBench with selective forgetting [E222][E223]. DMR is called inadequate by Zep's own authors because full-context scores high [E212].
- Ablation designs: ExpeL, Reflexion and Voyager compare with and without memory on held-out tasks [E105][E102][E108]; the experience-following study compares fixed, add-all and selective memory with trajectory evaluators [E221]. MemCoder reports a self-reported 9.4% gain on SWE-bench Verified [E140]. Anthropic's eval guidance: multiple trials, clean environment per trial (one case of an agent reading earlier trials' git history), read transcripts [E130].
- Benchmark reliability: the same system scores differ by who runs it (Mem0 paper Zep 65.99 vs Zep's 75.14) [E211][E213].

**Inference**
- Minimum design for the workshop: same task set, memory ON vs memory OFF vs memory-frozen-at-baseline; multiple trials each; clean per-trial memory snapshot to avoid leakage; metrics: first-try success, advisor fix rate, tokens, and memory-specific ones (FROM_MEMORY hit rate, entry precision = hits whose advice worked, stale-entry rate). A 10-20 task set can detect only large effects; treat small differences as noise (see Q3-Q4 notes).
- Run the add-all vs selective-addition comparison [E221] on the advisor's own logs as the first memory experiment.

## 6. Tool table

Stats from `gh api` on 2026-11-25. Flags: stars below 1k, no release in 6 months, pre-1.0, single maintainer (not checked for any tool), vendor-disclaimed production use, copyleft license, hosted dependency.

| Tool | What it is | Claude Code integration path | Stars | Last push | License | Maturity flag |
|---|---|---|---|---|---|---|
| Claude Code auto memory + CLAUDE.md [E200][E201] | Built-in markdown memory | Native; `/memory`, `autoMemoryEnabled` | n/a | n/a | n/a | Not enforced, only context; machine-local |
| Subagent `memory:` frontmatter [E202] | Per-agent persistent folder (user/project/local) | Native frontmatter field | n/a | n/a | n/a | Depends on auto memory being on |
| Anthropic memory tool + context editing [E203][E204] | API client-side file memory | API only, not Claude Code CLI; build own handler | n/a | n/a | n/a | Docs say stable; you own security |
| Anthropic Dreams [E205] | Consolidation job over memory store + transcripts | Managed Agents API | n/a | n/a | n/a | Research preview; not ZDR/HIPAA |
| Mem0 [E228][E229] | LLM memory layer, ADD-only in v3 | Plugin with hooks, read-only MCP search tool | 69431 | 2026-11-24 | Apache-2.0 | Needs hosted API key; headline scores from managed platform; telemetry on by default |
| OpenMemory (mem0ai/openmemory) [E230] | Now a session import/export tool, not the old MCP memory server | Beta CLI | 108 | 2026-07-29 | MIT | Under 1k stars; beta; changed purpose |
| Graphiti [E231] | Temporal knowledge graph framework | MCP server (Docker, FalkorDB/Neo4j) | 33070 | 2026-11-24 | Apache-2.0 | MCP server labeled experimental; needs graph DB and LLM calls |
| Zep [E232] | Hosted context layer | Hosted API | 5013 | 2026-11-17 | Apache-2.0 | Hosted dependency |
| Letta / Letta Code [E233] | Stateful agents, MemFS, Dreaming | Separate harness, no documented Claude Code path | 25538 (letta), 3910 (letta-code) | 2026-10-18; 2026-11-25 | Apache-2.0 | letta-ai/letta last release 2026-05-14 (more than 6 months); source moved to letta-code |
| MCP memory server [E234] | Local JSONL knowledge graph | `npx @modelcontextprotocol/server-memory` | 92231 (whole repo) | 2026-11-24 | NOASSERTION | Repo calls servers reference implementations, not production-ready; substring search only |
| claude-mem [E235] | Hook-based capture, SQLite + Chroma, MCP search | `npx claude-mem install` / plugin | 119577 | 2026-11-25 | Apache-2.0 | Created 2025-08-31; some features hosted with trial; star count not verified beyond API |
| mcp-memory-service [E236] | Self-hosted REST + MCP memory with graph | MCP config, optional hooks | 2154 | 2026-11-24 | Apache-2.0 | 5 ms claim unverified |
| basic-memory [E237] | Markdown-file MCP memory with graph and semantic search | MCP server | 4703 | 2026-11-24 | AGPL-3.0 | Copyleft license; paid cloud tier |
| Cognee [E238] | Knowledge-graph memory platform | Not checked | 33566 | 2026-11-25 | Apache-2.0 | Claude Code path not verified |

**Inference**
- For this system, the native route (subagent `memory:` plus the existing advisor folder) has zero new dependencies and is already what the user built [E202]. Plugins that capture automatically (claude-mem, Mem0) add a write path outside the G6 guard and the advisor's outcome verification; evaluate them only as comparison arms, not replacements.

## Disagreements between sources

- **Who is state of the art on LoCoMo.** Mem0 paper: Zep 65.99, Mem0 66.88, full-context 72.90 [E211]. Zep: its correct implementation scores 75.14 and Mem0's setup was flawed [E213]. Letta: plain file plus grep 74.0 vs 68.5 for Mem0 [E214]. Mem0's 2026 README: 92.5 on its managed platform [E228]. Different harnesses, answer models and judges; not comparable.
- **Is full-context a strong baseline.** On LoCoMo full-context beat all memory systems [E211][E213]; on LongMemEval Zep beat full-context [E212]. Context length differs (about 26k vs 115k tokens).
- **Update policy.** Mem0 paper: LLM-chosen UPDATE/DELETE [E211]; Mem0 2026: ADD-only [E228]; Graphiti: invalidate and keep history [E212]; Dreams: replace stale with latest value [E205]; ExpeL: vote and drop at zero [E105].
- **Add more vs add less.** Add-all hurt in the experience-following study [E221]; Mem0 2026 accumulates without overwrite [E228] (different tasks, not directly comparable).
- **Venue of LongMemEval.** arXiv abs page text said ICLR 2025; the HTML version named no venue; logged as preprint [E215].
- **Memory poisoning severity.** Idealized attacks report high success [E224][E225]; realistic memory states reduce it [E226].

## Not verified

- Venue pages for A-MEM (NeurIPS 2025 per arXiv comment), ReasoningBank (ICLR 2026), LongMemEval (ICLR 2025), Generative Agents (ACM page returned 403), Mem0 and Zep papers (no venue seen).
- MemoryAgentBench conflict-resolution scores (only seen in a search snippet); AgentPoison numbers differ between arXiv and NeurIPS versions per search snippet, only the NeurIPS page is logged.
- Generative Agents retrieval scoring (recency, importance, relevance) was not on the pages opened.
- Mem0's open evaluation repo and any independent reproduction of Mem0 92.5 or Zep 94.7 figures; the locomo-audit repo; mem0.ai benchmark blog posts (appeared in search only).
- OpenMemory's old MCP server maintenance status; Cognee's Claude Code integration; claude-mem benchmarks and whether its star count is organic; single-maintainer status for any repo.
- Anthropic's Auto Dream beyond a third-party article [E206]; the CLAUDE.md/subagent docs' remaining 14,790 characters [E202].
- Anthropic's internal 39% and 29% results have no published method [E204].
