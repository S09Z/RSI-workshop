# ADR-0005: Telemetry v1 — log what the guardrails and gate need

Status: Proposed
Date: 2026-11-25
Source: docs/report/rsi-research-report.md §9

- **Context.** No `tool_input`, exit codes, versions or cache-creation tokens in events.jsonl (notes-q5-q8). OTel exports cost and correlation IDs [E418][E419].
- **Options.** (a) events.jsonl only. (b) OTel only. (c) events.jsonl for workflow semantics + OTel for cost/tokens.
- **Decision.** (c); add §7 fields to `telemetry/events.schema.json`; add `config_version` to both.
- **Consequences.** Logger change in the owner's code: 6–9 hours in total (schema 1, logger 4–6, OTel 1–2; §7); tool details in OTel are opt-in for privacy [E419].
