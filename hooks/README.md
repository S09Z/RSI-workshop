# hooks/ (PROTECTED)

RSI surface 4: guardrails. `guardrails.yaml` is the spec; this folder also holds the blocking hooks built in
the Harden phase (ADR-0001) for **G1, G2 and G8**. G3-G7 have no code yet. Agents may not write here
(see `../PROTECTED.paths`). G1-G8 are never removed or weakened; new guardrails (G9+) start as `status: proposed`.

## Layout

| Path | Hook event | Guardrail |
|---|---|---|
| `g1_report_contract.py` | SubagentStop | G1: Worker/Advisor report matches the contract |
| `g2_orchestrator_nowrite.py` | PreToolUse Write/Edit/NotebookEdit/MultiEdit | G2: Orchestrator may not write files |
| `g8_capture.py` | PreToolUse Agent (never blocks) | G8: records DONE_WHEN files from the dispatch prompt |
| `g8_worker_tests.py` | PreToolUse Write/Edit/NotebookEdit/MultiEdit/Bash | G8: Worker may not edit DONE_WHEN tests |
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
  `${AGENT_DASHBOARD_DIR:-~/.claude/agent-dashboard}/events.jsonl`; G8 state lives in
  `${AGENT_HOOK_STATE_DIR:-~/.claude/agent-hook-state}`.
- The Orchestrator must put `DONE_WHEN_FILES: <paths>` in every Worker dispatch (`agents/orchestrator.md`);
  without it G8 falls back to blocking test-like paths.
- Residual risk (all need the sandbox; none is closed by these hooks):
  - G2: Bash writes by the Orchestrator; write-capable MCP tools.
  - G8: Bash analysis is lexical, so a path built at run time inside a script, base64, or another interpreter is not seen;
    the hook state and event log are agent-writable except for the names the hook denies; a Worker can add
    `conftest.py`/`pytest.ini` that patch the test (G14); path comparison is case-folded and uses `samefile`.
  - Over-blocking is accepted: a Bash write through an unresolved `$VAR` is denied when DONE_WHEN files are known.

## Run the checks

```bash
python3 -I -W error -m unittest discover -s hooks/tests -p 'test_*.py'
python3 -I hooks/tests/run_x1.py        # blocked 32/32, false_blocks 0/12
python3 -I scripts/check_scaffold.py
```

## Not done

- Registration in `settings.json` (no `install-hooks.sh` yet; the user chose not to register this round).
- X1 live layer (real agent sessions); G3-G7; the Bash sandbox. `run_x1.py` refuses to pass with fewer than 5 violations per guardrail or 10 controls.
- `ran_at` freshness is G4, not G1.

## Notes for later work

- `scripts/check_scaffold.py` allows `hooks/*.py` only when `guardrails.yaml` lists it under `hook:` and a test
  mentions it.
- Any future G1-G8 byte-identity check (G12) must baseline against the newest commit that changed a G1-G8 block
  (`git log -- hooks/guardrails.yaml`); this round added `hook:`, `implemented:` and `residual:` fields.
- After `scripts/install.sh`, the repo's files are the live `~/.claude` config through symlinks. Hook path checks
  compare resolved real paths.
