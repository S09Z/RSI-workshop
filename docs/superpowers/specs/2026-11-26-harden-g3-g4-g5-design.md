# Harden G3, G4, G5: hooks that re-run the DONE_WHEN test (design)

Date: 2026-11-26 · Status: draft, awaiting approval · Parent: ADR-0001, report §8 X1 and §9
Continues `2026-11-25-harden-g1-g2-g8-design.md` and `2026-11-25-harden-g6-g7-design.md`.
Same rules: stdlib Python 3 run as `python3 -I`, fail closed, inert unless `AGENT_WORKFLOW=1`, exit 2 blocks,
nothing registered in `~/.claude/settings.json` (a snippet is an example only).
Size: a project (new executing hooks, new shared module, prompt changes in live surfaces), so full design.

## 1. Intent and why

A Worker's `STATUS: WORKS` is a self-report. Today nothing checks it (R4 fake evidence, R5 early exit,
R6 quiet scope narrowing in the report). G3, G4 and G5 close that gap with hooks that run the acceptance test
themselves:

- **G5** test-first gate: before the first Worker dispatch of a task, the DONE_WHEN test must run and fail.
- **G3** silent-failure detection: when a Worker reports `WORKS`, the hook re-runs the DONE_WHEN test; a
  failing run, a run that executes zero tests, or a timeout blocks the stop.
- **G4** fresh evidence: a `WORKS` report must carry `ran_at` inside this task's run window.

Why now: G1, G2, G6, G7, G8 are done; these three are the rest of the X1 set (G1–G8). They are different in kind:
the hook executes a command, so the command source is a security question (see §4).

## 2. Goals, non-goals, anti-goals

**Goals**
- Three blocking hooks (`g5_test_first.py`, `g3_rerun_done_when.py`, `g4_fresh_evidence.py`) and one shared
  module `hooks/lib/donewhen.py` (parse, validate, run, classify).
- Prompt changes so the hooks have something to check: `DONE_WHEN_CMD:` and a fail-first step in
  `agents/orchestrator.md`; `ran_at` and a task-id-first `TASK:` line in `agents/worker.md`.
- X1 hook-level fixtures: at least 5 violations per guardrail (G3, G4, G5) plus new controls; the runner's
  minimum check extends to G1–G8.
- Every block is a `guardrail_hit` event with `guardrail`, `blocked: true`, `case_id`, `rule_version`.

**Non-goals**
- Registering hooks; X1 live layer; G9+; a sandbox; touching `g8_*.py` (G8 stays as is, its parser is
  re-implemented in the shared module rather than refactored).
- Runners other than pytest and `python3 -m unittest`. Directory or discovery runs.
- Making the verified result the only source of `outcome: worked` (report G11, a later round).

**Anti-goals**
- A hook that executes any command an LLM wrote. A hook whose error lets a false `WORKS` through
  (except the documented retry cap). A false block on a real passing run (counts against X1).

## 3. Approaches

1. **A. `DONE_WHEN_CMD:` in the dispatch prompt, validated against an allowlist, run by the hook (chosen).**
   Per-task precision; the allowlist removes arbitrary command execution. Costs a prompt change and a strict format.
2. B. Command read from a project config file. No LLM-written command at all, but it can only run the whole
   suite, so G5 cannot tell whether this task's test fails first, and it is slow.
3. C. Orchestrator runs the test and the hook only checks the evidence. Simplest, but the hook never re-runs,
   so fake-WORKS (R4) stays open; that is not G3.

The owner chose A on 2026-11-26 (runners in use: `pytest`, `python3 -m unittest`).

## 4. Design

### 4.1 Dispatch contract (live-surface prompt change)

Every Worker dispatch prompt carries, one per line:

```
DONE_WHEN_FILES: tests/test_x.py[, ...]      # already required (G8)
DONE_WHEN_CMD: pytest -q tests/test_x.py     # new
```

and the Agent `description` starts with the task id `[Tn]` (already required by `orchestrator.md`).
Exception: `TASK_KIND: write-test` replaces `DONE_WHEN_CMD:` for a dispatch whose job is to write the failing
test (the Orchestrator cannot write files, G2). G5 and G3 skip such a dispatch and log it; G8 protects the test
from the next dispatch on, because that dispatch lists it in `DONE_WHEN_FILES`.

### 4.2 Shared module `hooks/lib/donewhen.py`

- `parse(prompt) -> Dispatch(cmd_argv, files, kind)`; `cmd` from the `DONE_WHEN_CMD:` line via `shlex`.
- `validate(argv, files, root) -> (ok, why)`. Allowed shapes only:
  `pytest …`, `python3 -m pytest …`, `python3 -m unittest …`.
  Allowed options: `-q -v -x --tb=<short|line|no|long> --maxfail=N -k EXPR -m EXPR` (unittest: `-v -f -k EXPR`).
  Every positional must be a test file (pytest may add `::node`) whose real path is in `files` and inside the
  git root. No directories, no module names, no `-p`, `-c`, `--rootdir`, `--junitxml`, no shell metacharacters.
  Anything else is denied with the reason.
- `run(argv, root) -> Result`: `subprocess.run` with `shell=False`, `cwd=root`, stdin closed, own process group
  (killed on timeout), timeout `AGENT_DONEWHEN_TIMEOUT` (default 120 s), output capped, and a scrubbed
  environment (PATH, HOME, LANG, LC_ALL, TMPDIR, VIRTUAL_ENV only, plus `PYTHONDONTWRITEBYTECODE=1`).
  pytest gets `-p no:cacheprovider -o addopts=` added so repo ini files cannot inject options or plugins.
- `classify(result) -> passed | failed | error`: `passed` = exit 0 and at least one test ran; `failed` = tests ran
  and at least one failed or errored; `error` = timeout, usage error, zero tests collected (pytest exit 5, unittest
  "Ran 0"), collection error (pytest exit 2), or an unparseable summary. Count from the summary line and exit code.
- Git root: first ancestor of the event `cwd` with a `.git` entry (as G7); none found means deny.

### 4.3 G5 `g5_test_first.py` (PreToolUse `Agent`, rule_version `g5-v1`)
Acts only for `subagent_type == "worker"` and not `write-test`.
1. No task id, or no `DONE_WHEN_CMD:`, or `validate` fails: deny with the reason.
2. State file `<state>/done_when_cmd/<session>-<task>.json` exists (a re-dispatch after Advisor guidance): the
   command and the file set must equal the recorded ones, else deny (R6 lock). No re-run. Allow.
3. First dispatch: run the command. Only `failed` allows. `passed` (the test already passes) and `error` deny
   with the classification and the output tail. On allow, write the record (cmd, files, root, `dispatched_at`).

### 4.4 G3 `g3_rerun_done_when.py` (SubagentStop, rule_version `g3-v1`)
Acts only for `agent_type == "worker"` and report `STATUS: WORKS` (parsed as G1 does). `stop_hook_active`
allows and logs `retry_cap`, as G1 does.
1. Find the record by the task id at the start of the report's `TASK:` line; if the id is missing, the newest
   record of the session with no stop yet. No record: deny (cannot verify a WORKS).
2. Re-run the recorded command. `passed` allows and logs the exit code and test count (non-blocking event).
   `failed` or `error` denies, naming the classification and the output tail.
`DOES_NOT_WORK` and `BLOCKED` are not G3's business.

### 4.5 G4 `g4_fresh_evidence.py` (SubagentStop, rule_version `g4-v1`)
For a `WORKS` report: `VERIFICATION` must hold `ran_at:` as ISO-8601 with `Z` or `+00:00`. It must be at or after
the record's `dispatched_at` and not more than 5 seconds after now. Missing, unparseable, earlier, or future: deny.
G4 checks format and window; G3 is the authority on truth. Record lookup as in G3.

### 4.6 Prompt changes
- `agents/orchestrator.md`: add `DONE_WHEN_CMD:`, `TASK_KIND: write-test`, and a step "run DONE_WHEN_CMD yourself
  and confirm it fails before dispatch; the hook enforces it".
- `agents/worker.md`: `TASK:` starts with the task id; `VERIFICATION` adds `ran_at: <UTC ISO-8601 of that run>`;
  the final run must be `DONE_WHEN_CMD` verbatim.

### 4.7 Registration example
`hooks/settings.snippet.json` gains g5 on PreToolUse `Agent` and g3, g4 on `SubagentStop`, each with
`"timeout"` above the run timeout (example 150 s). Not applied.

## 5. Tests and X1

- `test_donewhen.py`, `test_g3.py`, `test_g4.py`, `test_g5.py` (unit, RED first), plus a runner test that G3, G4
  and G5 each need 5 violations. Real runs use `python3 -m unittest` on tiny generated tests; pytest cases are
  skipped when pytest is not installed.
- Break attempts, G5: test already passes; zero tests; collection error; `bash -c`, `;`, `&&`, `$(...)` in the
  command; `pytest -p evil`; path not in `DONE_WHEN_FILES`; path through a symlink out of the root; changed command
  on re-dispatch; missing task id or command; timeout; no git root; `write-test` exempt; non-worker ignored.
- G3: WORKS with a failing test; WORKS with zero tests run (`sys.exit(0)` style); timeout; no record; retry cap;
  DOES_NOT_WORK allowed; the Worker editing the source to hide the failure is not G3's job (G8 and review).
- G4: `ran_at` missing, malformed, before dispatch, in the future, local time without offset.
- `hooks/tests/fixtures/x1/`: at least 5 `v-g3-*`, `v-g4-*`, `v-g5-*` each, plus at least 6 controls (valid G5
  first-fail, valid re-dispatch, valid G3 pass, valid G4, `write-test` dispatch, non-worker). Runner extends its
  state setup (a `state` map like `files`) so a SubagentStop case can start from a recorded dispatch. The
  always-allow stub must still fail (0 blocked).
- `check_scaffold.py`: HARDEN becomes G1–G8; `guardrails.yaml` G3–G5 gain `hook:`, `implemented: true`, `residual:`
  (`enforced` stays false). Docs: `hooks/README.md`, `README.md`, `docs/architecture.md`, `docs/baseline.md`.
  Any test or script that asserts prompt contents (`scripts/check_*`, `test_install.sh`) is updated.

## 6. Residuals (documented, not hidden)

- The hook runs repo code (`conftest.py`, `sitecustomize`, test imports). A Worker that plants code there gets it
  run by the hook outside any future Worker sandbox. Same privilege the Worker already has through Bash today;
  closing it needs the sandbox.
- `-o addopts=` can break a suite that depends on `addopts` (for example coverage flags): such a task is denied
  at G5, not silently passed.
- `ran_at` is self-reported; G4 checks the window, G3 the truth. Flaky tests can block a real WORKS.
- Two Workers in parallel are matched by task id; a missing id falls back to the newest open record.
- The retry cap lets a repeated false WORKS through after one block, as G1 does.
- `TASK_KIND: write-test` can be abused by an Orchestrator to skip G3; the event is logged for review (M9).
- A test that fails for the wrong reason (for example an unrelated assertion) still satisfies G5.

## 7. Calls I made (check these)

1. `write-test` exemption instead of letting the Orchestrator write the test (G2 forbids it).
2. G5 accepts only a run that executed and failed; collection errors and zero tests are denied.
3. The re-dispatch lock: the command and file set cannot change after the first dispatch.
4. Task id is mandatory; G5 denies a dispatch without one.
5. `-o addopts=` and `-p no:cacheprovider` are forced on pytest.
6. `g8_capture.py` is untouched; `donewhen.py` re-implements the file parser.
7. Default timeout 120 s, env override `AGENT_DONEWHEN_TIMEOUT`.

## 8. Left to the builder

Regexes and the exact summary parsers, the state record fields beyond those named, helper names beyond §4,
fixture content, and how the runner seeds `state`. Any call made while building goes in the ledger.
