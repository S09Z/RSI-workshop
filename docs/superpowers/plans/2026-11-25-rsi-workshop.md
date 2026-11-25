# RSI Workshop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make this folder the git-versioned home of the three-agent system (placeholders only) and write the sourced 11-section RSI research report whose recommendations point at paths in this layout.

**Architecture:** A plain git repo of Markdown/YAML/JSON plus two shell scripts and two Python check scripts. The checks are the "tests": `scripts/check_scaffold.py` pins the layout and protections; `scripts/check_report.py` pins the report's structure and that every citation resolves to an evidence-log entry. Research facts flow evidence log → report → derived artifacts (ADRs, schemas, guardrails YAML, architecture doc).

**Tech Stack:** git 2.54, bash, Python 3.12 (stdlib + PyYAML, run with `python3 -I`), Mermaid in Markdown, WebSearch + web-fetch agent + `gh api` for research.

**Spec:** `docs/superpowers/specs/2026-11-25-rsi-workshop-design.md`

## Global Constraints

- "As of" date for every repo/tool stat: 2026-11-25.
- Evidence types, exactly: `peer-reviewed`, `preprint`, `vendor claim`, `community anecdote`.
- No number in the report that is not in an evidence-log entry read from an opened source; unopened → "not verified".
- Every report section separates **Evidence** and **Inference** subsections.
- No executable hook scripts under `hooks/`; guardrails exist only as `hooks/guardrails.yaml`.
- `PROTECTED.paths` lists: `hooks/`, `evals/graders/`, `evals/tasks/heldout/`, `PROTECTED.paths`, `scripts/install.sh`.
- `install.sh` is never run against the real `~/.claude` in this plan; it never touches `settings.json`.
- Proposed G9+ guardrails carry `status: proposed`; G1–G8 are never removed or weakened.
- No eval tasks are invented; task folders hold only a README with the format.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No remote.

## Review Focus

- `install.sh` run when `~/.claude/agents/` already holds a real (non-symlink) file of the same name → must back it up, not overwrite; test in Task 2.
- `install.sh` run twice → second run is a no-op, no nested backups; test in Task 2.
- A citation in the report like `[E12]` with no `E12` in the log, or a log entry missing date/type → check fails; test in Task 3.
- A G9+ entry in `guardrails.yaml` without `status: proposed`, or G1–G8 missing → check fails; test in Task 1 (re-run in Task 5).
- A path in `PROTECTED.paths` that doesn't exist (typo makes protection void) → check fails; test in Task 1.

---

### Task 1: Repo and scaffold

**Files:**
- Create: `scripts/check_scaffold.py`, `.gitignore`, `README.md`, `PROTECTED.paths`
- Create: `agents/{orchestrator,worker,advisor}.md`, `skills/README.md`, `hooks/README.md`, `hooks/guardrails.yaml`, `routing/routing.yaml`
- Create: `memory/advisor/{MEMORY.md,SCHEMA.md,projects/.gitkeep,topics/.gitkeep}`
- Create: `evals/README.md`, `evals/tasks/train/README.md`, `evals/tasks/heldout/README.md`, `evals/configs/{single-agent,orch-worker,full-system}.yaml`, `evals/graders/README.md`, `evals/results/.gitkeep`
- Create: `proposals/TEMPLATE.md`, `proposals/{inbox,accepted,rejected}/.gitkeep`
- Create: `telemetry/events.schema.json`, `docs/architecture.md`, `docs/adr/.gitkeep`, `docs/research/evidence-log.md`

**Interfaces:**
- Produces: `check_scaffold.py` exit 0 = pass, nonzero + one line per failure. `guardrails.yaml` shape: `guardrails: [{id: G1, name: str, enforces: str, status: active|proposed, protected: bool}]`. `evidence-log.md` entry format (used by Task 3):
  `| E<n> | <claim> | <title> | <url> | <YYYY-MM-DD> | <evidence type> | <opened 2026-11-25> |`

- [ ] **Step 1: `git init`** in the folder; branch `main`.
- [ ] **Step 2: Write `scripts/check_scaffold.py`** asserting: every file in the Files list exists; each `PROTECTED.paths` line exists on disk and the five required lines are present; `hooks/` has no files with exec bit or `.sh/.py/.js` suffix; `guardrails.yaml` has G1–G8 with `status: active` and every id ≥ G9 has `status: proposed`; `.gitignore` contains `evals/results/raw/`; each `agents/*.md` has frontmatter `name`, `model` and body containing `placeholder`.
- [ ] **Step 3: Run** `python3 -I scripts/check_scaffold.py` → FAIL listing missing files.
- [ ] **Step 4: Create the files.** Agent frontmatter from the brief: orchestrator `model: opus`, `tools` limited to `Agent(worker, advisor)` + read tools; worker `model: sonnet`; advisor `model: opus`, memory path. `routing.yaml`: worker attempts max 3, advisor rounds max 2. `guardrails.yaml`: G1–G8 with names from the brief. `docs/architecture.md`: baseline system as the brief describes it, guardrails table, roadmap (Harden → Measure gate +15 pts → Scale → Memory). `SCHEMA.md`, `events.schema.json`, `TEMPLATE.md` hold a v0 per the brief's current formats, marked "v2 pending report §4/§5/§7".
- [ ] **Step 5: Run** the check → PASS.
- [ ] **Step 6: Commit** `chore: scaffold RSI workshop layout` (include `docs/superpowers/` spec and plan).

### Task 2: install.sh

**Files:**
- Create: `scripts/install.sh`, `scripts/test_install.sh`

**Interfaces:**
- Produces: `install.sh [--apply] [--target DIR]`; default dry-run prints planned links; `--target` defaults to `$HOME/.claude`. Links `agents/*.md` → `TARGET/agents/`, `memory/advisor` → `TARGET/agent-memory/advisor`, `skills/*` (excluding README) → `TARGET/skills/`. Existing non-symlink → moved to `TARGET/backups/rsi-workshop-<timestamp>/`. Already-correct symlink → skipped. Never touches `hooks/` or `settings.json`.

- [ ] **Step 1: Write `scripts/test_install.sh`** using `mktemp -d` as target: (a) dry-run creates nothing; (b) `--apply` creates the three agent symlinks pointing into the repo; (c) pre-existing real `agents/worker.md` ends up in `backups/` with original content; (d) second `--apply` changes nothing and creates no new backup dir; (e) no `settings.json` and no `hooks/` in target.
- [ ] **Step 2: Run** `bash scripts/test_install.sh` → FAIL (script missing).
- [ ] **Step 3: Write `scripts/install.sh`** (`set -euo pipefail`, resolves repo root from script location).
- [ ] **Step 4: Run** the test → PASS; re-run `check_scaffold.py` → PASS.
- [ ] **Step 5: Commit** `feat: add dry-run-first install script`.

### Task 3: Research → evidence log

**Files:**
- Create: `scripts/check_report.py`
- Modify: `docs/research/evidence-log.md`

**Interfaces:**
- Produces: `check_report.py [--log-only]`; checks every log row has 7 non-empty columns, date `YYYY-MM-DD` or `n.d.`, type in the four allowed values, unique ids; without `--log-only` also checks the report (Task 4).

- [ ] **Step 1: Write `check_report.py`** with the log checks, plus report checks: 11 `## N.` headings in the brief's order; §1 ≤ 200 words; every `[E<n>]` in the report exists in the log; each of §2–§8 contains `Evidence` and `Inference` subheadings; a ```mermaid block in §3; a "Quality bar" checklist at the end with all boxes ticked or each unticked one explained.
- [ ] **Step 2: Run** `python3 -I scripts/check_report.py --log-only` on a log with one malformed test row → FAIL; remove the row.
- [ ] **Step 3: Research Q1** — open each named lead (Reflexion, ExpeL, Voyager, ADAS, SICA, Darwin Gödel Machine, AlphaEvolve, DSPy, GEPA, Anthropic engineering posts on harnesses/evals) plus 2025–2026 work found by search; log mechanism, what's modified, verification, results, failure modes.
- [ ] **Step 4: Research Q2** — memory practice and tools (Mem0, Graphiti/Zep, Letta, MCP memory servers, Claude Code memory/subagent memory docs); stars, last commit, license via `gh api repos/<o>/<r>` on 2026-11-25.
- [ ] **Step 5: Research Q3–Q4** — outcome-to-change methods with costs; eval design, run counts/significance under non-determinism, LLM-judge calibration, promptfoo and Inspect (repo stats), SWE-bench-style replay.
- [ ] **Step 6: Research Q5–Q8** — reward hacking in coding agents, controls, governance tooling (OpenTelemetry GenAI conventions, Claude Code OTel docs, AGENTS.md), metrics, limits; current Anthropic model pricing for cost estimates.
- [ ] **Step 7: Run** `check_report.py --log-only` → PASS.
- [ ] **Step 8: Commit** `docs: research evidence log`.

### Task 4: Write the report

**Files:**
- Create: `docs/report/rsi-research-report.md`

**Interfaces:**
- Consumes: evidence-log ids `E<n>`; repo paths from Task 1.

- [ ] **Step 1: Write §2, §4–§8, §10, §11** from the log; each recommendation names a path in this repo (e.g. `memory/advisor/SCHEMA.md`, `hooks/guardrails.yaml#G9`, `evals/tasks/heldout/`) or a roadmap phase, and a cost estimate with its basis.
- [ ] **Step 2: Write §3** (Mermaid loop; table of step · input · output · owner · trigger) and §9 (ADRs inline + guardrails table and roadmap diffs).
- [ ] **Step 3: Write §1 last** (≤ 200 words, 5 findings, first action).
- [ ] **Step 4: Fill the quality-bar checklist** honestly at the end.
- [ ] **Step 5: Run** `python3 -I scripts/check_report.py` → PASS.
- [ ] **Step 6: Commit** `docs: RSI research report`.

### Task 5: Apply report outputs to the scaffold

**Files:**
- Create: `docs/adr/ADR-000N-<slug>.md` (one per ADR in §9)
- Modify: `hooks/guardrails.yaml` (add G9+ as proposed), `docs/architecture.md` (guardrails table, roadmap — marked "proposed"), `memory/advisor/SCHEMA.md` (v2 from §4), `telemetry/events.schema.json` (fields §7 metrics need), `proposals/TEMPLATE.md` (from §5), `evals/tasks/*/README.md` (task format + rotation rules from §5/§8)

- [ ] **Step 1: Write ADR files** matching §9 (context, options, decision, consequences).
- [ ] **Step 2: Update the five artifacts** to match the report; each change cites its report section.
- [ ] **Step 3: Validate** `python3 -I -c "import json;json.load(open('telemetry/events.schema.json'))"` → no error; `check_scaffold.py` → PASS; `check_report.py` → PASS.
- [ ] **Step 4: Commit** `docs: apply report recommendations as proposed artifacts`.
