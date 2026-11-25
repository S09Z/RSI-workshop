# RSI Workshop — Design

Date: 2026-11-25 · Status: draft, awaiting approval

## 1. Intent and why

A personal lab for adding recursive self-improvement (RSI) to a three-agent Claude Code
workflow (Orchestrator / Worker / Advisor). "RSI" here means: the system mines its own run
history (worker reports, advisor guidance, outcomes, guardrail hits, eval results) to
propose changes to its prompts, advisor memory, skills/checklists, guardrails and routing;
each change is tested against an eval gate and adopted only with human approval. Model
weights are out of scope.

Two outputs:

1. **A research report** answering Q1–Q8 of the brief, in the 11-section structure the
   brief specifies, with every claim sourced and every recommendation mapped to a concrete
   file, contract, guardrail, metric or roadmap phase *in this folder's layout*.
2. **A scaffold** that makes this folder the versioned home of the agent system, so every
   self-modification is a git diff with a rationale and can be rolled back.

## 2. Goals, non-goals, anti-goals

**Goals**
- Report meets the brief's quality bar (sourced numbers, evidence type per claim,
  evidence vs. inference separated, immature tools and preprint-only results flagged,
  cost per recommendation, held-out + non-target regression in the eval plan).
- Folder layout gives each RSI-modifiable surface (brief items 1–5) one home under git.
- Protected surfaces (graders, held-out tasks, guardrail hooks, the protected-paths list
  itself) are named in one machine-readable file, ready for a future guardrail to enforce.

**Non-goals (this round)**
- Writing working agent definitions or G1–G8 hook code. They are not on this machine
  (`~/.claude/agents/`, `~/.claude/hooks/`, `~/.claude/agent-memory/`,
  `~/.claude/agent-dashboard/` are absent or empty as of 2026-11-25). Building them is a
  later step that follows the report.
- Running any eval or experiment. The report designs them; it does not execute them.
- Changing `~/.claude`. `install.sh` is written, not run.

**Anti-goals (would be failure even if "done")**
- Numbers or tool stats in the report that were not read in an opened source.
- A scaffold whose layout lets an agent edit its own graders, held-out tasks or guardrails.
- Stub hooks installed into `~/.claude` that silently pass everything (a false sense of
  protection).

## 3. Constraints

- No real run history exists here: the report designs against the system as described in
  the brief, and says so wherever data would be needed.
- Web research only through tools available in this session (WebSearch, the web-fetch
  agent, `gh` if authenticated). Anything that cannot be opened is marked unverified, not
  stated.
- "As of" date for all repo/tool stats: 2026-11-25.

## 4. Approaches considered

| | Approach | Trade-off | Outcome |
|---|---|---|---|
| A | This folder is the system's home (agents, hooks, memory, evals, proposals, docs) under git; `install.sh` links into `~/.claude` | One source of truth and rollback; `~/.claude` depends on this folder | **Chosen by user** |
| B | Folder holds research + evals only; agents stay in `~/.claude` | Simpler; proposals and rollback split across two places | Rejected |
| C | A plus writing working agents and hooks now | Runnable sooner; behaviour invented before research shapes it; double the work | Deferred to a later step |

## 5. Folder layout (decided: approach A)

```
RSI-workshop/
├── README.md                     what this is, layout, how to install (later)
├── PROTECTED.paths               paths agents may never write (input for proposed G9)
├── .gitignore                    evals/results/raw/, *.log, .env
├── agents/                       RSI surface 1 — placeholders until the baseline is written
│   ├── orchestrator.md
│   ├── worker.md
│   └── advisor.md
├── skills/                       RSI surface 3 — skills and checklists agents load
│   └── README.md
├── hooks/                        RSI surface 4 — guardrails (PROTECTED)
│   ├── guardrails.yaml           G1–G8 as described + proposed G9+ (status: proposed)
│   └── README.md                 one stub per guardrail is NOT created (anti-goal)
├── routing/                      RSI surface 5
│   └── routing.yaml              models, escalation rules, retry limits (values from brief)
├── memory/advisor/               RSI surface 2 — Memory v2 layout from the report
│   ├── MEMORY.md
│   ├── SCHEMA.md                 entry schema, consolidation and pruning rules
│   ├── projects/
│   └── topics/
├── evals/
│   ├── tasks/train/              tasks the loop may optimise against
│   ├── tasks/heldout/            PROTECTED; never shown to proposal generation
│   ├── configs/                  single-agent, orch+worker, full-system
│   ├── graders/                  PROTECTED
│   └── results/                  summaries committed; raw/ ignored
├── proposals/                    change proposals as diff + rationale
│   ├── TEMPLATE.md
│   ├── inbox/  accepted/  rejected/
├── telemetry/
│   └── events.schema.json        schema for events.jsonl, incl. fields the metrics need
├── docs/
│   ├── architecture.md           baseline system as described in the brief + guardrails
│   │                             table + roadmap (the "architecture doc" the report updates)
│   ├── adr/                      ADR-0001… from report section 9
│   ├── report/rsi-research-report.md   the 11-section deliverable
│   ├── research/evidence-log.md  claim · source · date · evidence type (working log)
│   └── superpowers/specs/        this document
└── scripts/
    └── install.sh                dry-run by default; backs up before linking; refuses to
                                  link hooks/ while guardrails are stubs
```

Agent placeholder files contain frontmatter (name, model, allowed tools as described in
the brief) and a body that says "placeholder — baseline not yet written"; nothing that
pretends to be the real prompt.

## 6. Report: how it gets made

- Structure: exactly the brief's sections 1–11.
- Research: search widely, then open each lead (Reflexion, ExpeL, Voyager, ADAS, SICA,
  Darwin Gödel Machine, AlphaEvolve, DSPy/GEPA, Anthropic engineering posts on harnesses
  and evals, plus 2025–2026 additions found in search). Memory tools: Mem0, Graphiti/Zep,
  Letta, MCP memory servers. Eval tools: promptfoo, Inspect, SWE-bench-style harnesses.
- Every claim goes into `docs/research/evidence-log.md` first (source, URL, date, type:
  peer-reviewed / preprint / vendor claim / community anecdote). The report cites only
  logged entries.
- Repo stats (stars, last commit, license, maintenance) read from the repo page or
  `gh api` on 2026-11-25; anything not read is marked "not verified".
- Each section separates **Evidence** from **Inference** explicitly.
- Cost estimates: computed from current published model pricing (read at report time) ×
  estimated tokens per task run; the token estimate is labelled inference.
- Mermaid diagram for the RSI loop in section 3.
- Section 9's ADRs are also written as separate files in `docs/adr/`, and the guardrails
  table / roadmap changes are applied to `docs/architecture.md` (marked "proposed").
- Final pass checks the brief's quality-bar checklist and records the result at the end
  of the report.

## 7. Calls made by Claude (correct any)

- Agent and hook placeholders only; no working code (approach C deferred).
- No stub hook scripts at all — guardrails exist as a YAML spec until real code is written.
- `PROTECTED.paths` covers `hooks/`, `evals/graders/`, `evals/tasks/heldout/`,
  `PROTECTED.paths`, `scripts/install.sh`.
- `git init` with one initial commit for the scaffold, one for the report; no remote.
- Report is Markdown in the repo (the brief's deliverable lives with the system it changes).

- `install.sh` targets: `agents/*.md` → `~/.claude/agents/`, `memory/advisor/` →
  `~/.claude/agent-memory/advisor/`, `skills/*` → `~/.claude/skills/`. It never edits
  `settings.json`; hook registration comes with the real hook code.
- `evals/tasks/*` start empty with a README defining the task format (repo, base commit,
  DONE_WHEN test, category tag, source: synthetic / replayed PR); no tasks are invented.
- Assumption: the described agent files don't exist elsewhere either; if they turn up, they
  replace the placeholders as the baseline commit.

## 8. Left to the builder

- Exact wording inside README, templates and schemas.
- How many sources per question beyond the named leads.
- Order of research work.
