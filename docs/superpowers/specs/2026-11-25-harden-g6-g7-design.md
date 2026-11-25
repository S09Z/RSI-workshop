# Harden G6 and G7: blocking write-scope hooks (design)

Status: approved by the owner in chat on 2026-11-25. Size: small change (short design, no builder check).
Continues `2026-11-25-harden-g1-g2-g8-design.md` (ADR-0001). Same rules: stdlib Python 3 run as `python3 -I`,
fail closed, inert unless `AGENT_WORKFLOW=1`, exit 2 blocks, nothing registered in `~/.claude/settings.json`.

## Intent

G6 (Advisor writes only to its memory folder) and G7 (Worker writes only inside the git root) are prompt
promises today. This makes them blocking PreToolUse hooks with tests that try to break them, so the X1
hook layer can count them. G3, G4 and G5 are out of scope: they re-run commands from a dispatch prompt and need
prompt changes in live surfaces; the owner chose to do G6+G7 first.

## Goals / non-goals / anti-goals

- Goals: deny Write/Edit/NotebookEdit/MultiEdit outside the allowed root for the role; deny Bash segments that
  can write and name a path outside the root; X1 hook-level fixtures (>= 5 violations, plus controls) for G6 and G7.
- Non-goals: registering hooks, editing `agents/*.md`, G3/G4/G5, touching `g8_*.py`, sandbox setup.
- Anti-goals: a hook that blocks the Advisor's own memory writes or the Worker's normal in-repo work (false
  blocks count against X1); a hook whose failure allows the write.

## Approaches

1. Two role-specific hooks plus one shared Bash-scan module (chosen).
2. Add both rules to `g8_worker_tests.py`: mixes three guardrails in one file and risks the 99 passing tests.
3. Managed-settings deny rules only: cannot be keyed on agent role, so it would block the wrong agent.

## Design

### Shared: `hooks/lib/shellscan.py`
`write_targets(cmd, cwd) -> (paths, unsafe)`. Splits on `;`, `&&`, `||`, `|`, newline; tokenises with `shlex`
(unparseable segment: `unsafe`); strips fd redirects like G8 (`2>&1`, `>/dev/null`). A segment is *writing* when
it has a redirect `>`/`>>`, or a word in `tee truncate mv cp rm dd ln install touch chmod chown patch`,
`sed -i`/`--in-place`, `perl -i`, `git checkout|restore|stash|apply`, or `python|node -c|-e`. A segment is
read-only when its first word (after `VAR=` assignments) is in `cat grep head tail ls diff wc pytest`,
`python|python3 -m pytest|unittest`, or `git diff|status|log|show`, and it is not writing. Output: every
path-like word in writing segments resolved with `common.real` (globs expanded), plus `unsafe=True` when a writing
segment contains `$`, a backtick, `cd`, `pushd`, `-C`/`--directory`, or an interpreter `-c/-e` (target unknowable).
Read-only segments contribute nothing. Case-insensitive compare and `samefile` via the same `norm`/`under` idea
as G8 (re-implemented here; G8 is not refactored).

### G6: `hooks/g6_advisor_memory.py` (rule_version `g6-v1`)
- Only when `common.role(event) == "advisor"`.
- Allowed root: `realpath($AGENT_ADVISOR_MEMORY_DIR or ~/.claude/agent-memory/advisor)`. Symlinks from `install.sh`
  resolve to the repo copy, so both aliases work.
- Write tools: deny unless `common.real(file_path|notebook_path)` is inside the root. Missing path: hook error (deny).
- Bash: deny when `unsafe`, or any write target is outside the root. Reason names the path.
- Reasons: `G6: Advisor may write only inside <root>; blocked <path>`.

### G7: `hooks/g7_worker_gitroot.py` (rule_version `g7-v1`)
- Only when role is `worker`.
- Git root: walk up from `cwd` to the first directory holding a `.git` entry (file or dir, so worktrees work).
  None found: deny every write (fail closed).
- Write tools and Bash: same rule as G6 with the git root as the allowed root.
- Reasons: `G7: Worker may write only inside the git root <root>; blocked <path>`.

### Events and registration
Each deny logs a `guardrail_hit` event via `run_hook` (`guardrail` G6 or G7). `settings.snippet.json` gains the two
hooks as an example only.

## Tests and X1

- `hooks/tests/test_g6.py`, `test_g7.py`, `test_shellscan.py`: unit tests (RED first) for each rule above and for
  fail-closed behaviour (malformed stdin, missing lib, missing path, unwritable log).
- Break attempts: `..` traversal, symlink out of the root (and a symlink into the memory dir), case-variant path,
  path built from `$VAR`, `cd /tmp && echo x > f`, `tee`, `sed -i`, `python -c`, glob, quote-split command, other roles
  (an Orchestrator write is not G6/G7's business: allowed here, G2 handles it), `AGENT_WORKFLOW` unset.
- `hooks/tests/fixtures/x1/`: >= 5 `v-g6-*` and >= 5 `v-g7-*` violations plus >= 4 new controls (in-root write,
  in-memory write, read-only Bash, `pytest`). `run_x1.py` minimum check extends to G1, G2, G6, G7, G8.
  The always-allow stub must still fail (0 blocked).
- `check_scaffold.py`: HARDEN becomes G1, G2, G6, G7, G8; each needs `implemented: true`, `enforced: false`, `hook:`.
- `guardrails.yaml`: G6/G7 gain `hook:`, `implemented: true`, `residual:`. Docs: `hooks/README.md`,
  `README.md`, `docs/architecture.md` status lines.

## Residuals (documented, not hidden)

Bash analysis is lexical: a path built at run time by a script, base64, or another interpreter is not seen; MCP
write tools; a Worker symlink created inside the repo after the check cannot be pre-empted (needs sandbox). G7
allows the Worker to write the hook state and event log only if they sit inside the git root; by default they do not.

## Left to the builder

Exact regexes, helper names beyond those above, and fixture content. Any call made while building goes in the ledger.
