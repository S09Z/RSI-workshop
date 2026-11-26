# hooks/ (PROTECTED)

RSI surface 4: guardrails. `guardrails.yaml` is the spec; this folder also holds the blocking hooks built in
the Harden phase (ADR-0001) for **G1-G8**. Agents may not write here
(see `../PROTECTED.paths`). G1-G8 are never removed or weakened; new guardrails (G9+) start as `status: proposed`.

## Layout

| Path | Hook event | Guardrail |
|---|---|---|
| `g1_report_contract.py` | SubagentStop | G1: Worker/Advisor report matches the contract |
| `g2_orchestrator_nowrite.py` | PreToolUse Write/Edit/NotebookEdit/MultiEdit | G2: Orchestrator may not write files |
| `g3_rerun_done_when.py` | SubagentStop | G3: a Worker `WORKS` is accepted only if the recorded DONE_WHEN test passes when re-run |
| `g4_fresh_evidence.py` | SubagentStop | G4: a `WORKS` report carries a UTC `ran_at` between this run's dispatch and now |
| `g5_test_first.py` | PreToolUse Agent | G5: the DONE_WHEN test must run and fail before the first Worker dispatch; records and locks the command |
| `g6_advisor_memory.py` | PreToolUse Write/Edit/NotebookEdit/MultiEdit/Bash | G6: Advisor writes only inside its memory folder (`$AGENT_ADVISOR_MEMORY_DIR`, default `~/.claude/agent-memory/advisor`) |
| `g7_worker_gitroot.py` | PreToolUse Write/Edit/NotebookEdit/MultiEdit/Bash | G7: Worker writes only inside the git root (first ancestor of `cwd` with a `.git` file or directory; none found = deny every write) |
| `g8_capture.py` | PreToolUse Agent (never blocks) | G8: records DONE_WHEN files from the dispatch prompt |
| `g8_worker_tests.py` | PreToolUse Write/Edit/NotebookEdit/MultiEdit/Bash | G8: Worker may not edit DONE_WHEN tests |
| `lib/donewhen.py` | - | G3/G4/G5: parse the dispatch, allowlist the test command, run it without a shell, classify, keep per-task records |
| `lib/shellscan.py` | - | lexical Bash scan for G6/G7: paths a command would write, and `unsafe` when the target cannot be known |
| `lib/common.py` | - | fail-closed wrapper, role detection, realpath, event log |
| `settings.snippet.json` | - | example registration, **not applied** |
| `tests/` | - | unit tests, X1 runner `run_x1.py`, fixtures (`fixtures/PROBE.md` = observed hook input) |

## Behaviour

- Hooks are inert unless `AGENT_WORKFLOW=1` (set by the owner's `bin/orch`). If someone exports it globally,
  plain sessions are governed too.
- Blocking = exit code 2 (exit 1 does not block; observed in `fixtures/PROBE.md`). Any error inside a blocking
  hook denies, including an unwritable event log and a missing `lib/` (a copied script); tests cover both.
  `g8_capture.py` also denies the Worker dispatch when it cannot record the DONE_WHEN files.
- Every block logs a `guardrail_hit` event (`guardrail`, `blocked`, `case_id`, `rule_version`) to
  `${AGENT_DASHBOARD_DIR:-~/.claude/agent-dashboard}/events.jsonl`; G8 and G3-G5 state lives in
  `${AGENT_HOOK_STATE_DIR:-~/.claude/agent-hook-state}`.
- The Orchestrator must put `DONE_WHEN_FILES: <paths>` in every Worker dispatch (`agents/orchestrator.md`);
  without it G8 falls back to blocking test-like paths.
- G5 also needs, in every Worker dispatch, an Agent `description` starting with a task id `[Tn]` and one line
  `DONE_WHEN_CMD:` (or `TASK_KIND: write-test`). Allowed commands: `pytest`, `python3 -m pytest`,
  `python3 -m unittest`, with a few options, naming `.py` files listed in `DONE_WHEN_FILES` inside the git root.
  The run uses no shell, `cwd` = git root, a short environment allowlist, and `AGENT_DONEWHEN_TIMEOUT`
  seconds (default 120). Keep the hook `timeout` in settings above it: a hook the harness kills does not block.
  pytest runs with `-p no:cacheprovider -o addopts=`, and cached bytecode of the test files is removed first.
  - `DONE_WHEN_FILES` paths resolve against the session cwd (as G8 does), the command runs in the git root:
    from a subdirectory use absolute paths.
  - `unittest` imports a path as a module, so every part of it must be a Python identifier and nothing else may
    answer to that module name (a same-named package or extension, a standard library module such as `test/`
    without `__init__.py`). A test that cannot be imported counts as "did not run".
  - A `write-test` dispatch still needs a `DONE_WHEN_FILES` line that does not list the file to be written
    (`.no-done-when-files` when nothing needs protecting).
- Residual risk (all need the sandbox; none is closed by these hooks):
  - G2: Bash writes by the Orchestrator; write-capable MCP tools.
  - G8: Bash analysis is lexical, so a path built at run time inside a script, base64, or another interpreter is not seen;
    the hook state and event log are agent-writable except for the names the hook denies; a Worker can add
    `conftest.py`/`pytest.ini` that patch the test (G14); path comparison is case-folded and uses `samefile`.
  - G6, G7: same lexical Bash limit (shared `lib/shellscan.py`); write-capable MCP tools; a Worker symlink created
    inside the repo after the check. Not seen: a script file that writes (`bash run.sh`, `python3 x.py`, `make`),
    `sed 'w FILE'`, `npm install -g`. Denied as unverifiable: `$VAR`/backticks, brace expansion, `cd`/`-C`/`--work-tree`/`GIT_*`,
    grouping or a write; any interpreter with inline code or code on stdin (`| sh`, `python3 -`, `bash -c`, also
    behind `env`/`sudo`/`timeout`/`nice`); `xargs`, `eval`, `find -exec/-delete`, `git config --global`.
    Any git subcommand except diff/status/log/show and similar counts as a write to the working tree at `cwd`
    (so the Advisor cannot `git commit` the project)
  - G3, G4, G5: after any SubagentStop block (G1, G3 or G4) the Worker's retry is not re-checked (retry cap);
    the report's `TASK:` id picks the record G3 verifies; code under test runs inside the hook and can forge the
    runner's summary; `ran_at` is self-reported; `TASK_KIND: write-test` skips G5 and G3 for that dispatch
    (logged); records expire after 24 hours; a `unittest.py` or `pytest.py` in the git root replaces the runner for
    the `python3 -m` forms; a `write-test` Worker can edit any test that no earlier dispatch listed.
  - Over-blocking is accepted: a Bash write through an unresolved `$VAR` is denied when DONE_WHEN files are known.

## Run the checks

```bash
python3 -I -W error -m unittest discover -s hooks/tests -p 'test_*.py'
python3 -I hooks/tests/run_x1.py        # blocked 65/65, false_blocks 0/26
python3 -I scripts/check_scaffold.py
```

## Not done

- Registration in `settings.json` (no `install-hooks.sh` yet; the user chose not to register this round).
- X1 live layer (real agent sessions); the Bash sandbox. `run_x1.py` refuses to pass with fewer than 5 violations per guardrail or 16 controls.

## Notes for later work

- `scripts/check_scaffold.py` allows `hooks/*.py` only when `guardrails.yaml` lists it under `hook:` and a test
  mentions it.
- Any future G1-G8 byte-identity check (G12) must baseline against the newest commit that changed a G1-G8 block
  (`git log -- hooks/guardrails.yaml`); this round added `hook:`, `implemented:` and `residual:` fields.
- After `scripts/install.sh`, the repo's files are the live `~/.claude` config through symlinks. Hook path checks
  compare resolved real paths.
