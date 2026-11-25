# hooks/ (PROTECTED)

RSI surface 4: guardrails. They exist here only as a spec, `guardrails.yaml`.

No hook scripts and no stubs are created. A stub that passes everything would give a false sense of
protection. Real hook code arrives in a later step, after the report. Agents may not write here
(see `../PROTECTED.paths`). G1-G8 are never removed or weakened; new guardrails (G9+) start as
`status: proposed`.
