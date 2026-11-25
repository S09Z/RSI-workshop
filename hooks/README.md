# hooks/ (PROTECTED)

RSI surface 4: guardrails. They exist here only as a spec, `guardrails.yaml`.

No hook scripts and no stubs are created. A stub that passes everything would give a false sense of
protection. Real hook code arrives in a later step, after the report. Agents may not write here
(see `../PROTECTED.paths`). G1-G8 are never removed or weakened; new guardrails (G9+) start as
`status: proposed`.

## Notes for the Harden change (ADR-0001)

- `scripts/check_scaffold.py` fails on any `.py`, `.sh` or `.js` file and any executable file in `hooks/`.
  Harden creates `hooks/g*.py`, so that change must relax the rule: allow only scripts that
  `guardrails.yaml` references and that have tests. Do not relax it before then.
- Any future G1-G8 byte-identity check (G12) must baseline against commit `826985b` or later. G1-G8
  gained the `proposed_mechanism` and `enforced` fields in that commit, so an older baseline would
  flag them. G6's `proposed_mechanism` was extended again (resolved real paths) in the final-review
  fix commit; baseline against the newest commit that changed a G1-G8 block
  (`git log -- hooks/guardrails.yaml`).
- After `scripts/install.sh`, the repo's files are the live `~/.claude` config through symlinks. Hook
  path checks must compare resolved real paths (see `docs/architecture.md`, "Live surfaces").
- Hooks are registered in `settings.json` by a proposed separate `scripts/install-hooks.sh` (human-run,
  backs up `settings.json`); `scripts/install.sh` never touches `settings.json`.
