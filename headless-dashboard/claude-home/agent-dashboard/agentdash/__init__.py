"""agentdash: headless-first monitoring for the orchestrator / worker / advisor workflow.

Standard library only (Python 3.10+). Modules:
  config    paths, privacy and retention settings
  yaml_lite small YAML subset loader (PyYAML is used instead when installed)
  parse     report parsing (WORKER REPORT / ADVISOR GUIDANCE), guardrail markers, redaction
  store     SQLite schema and migrations
  ingest    incremental ingestion of events.jsonl and otel.jsonl (byte offsets, rotation safe)
  metrics   the ONLY metric definitions; used by CLI, API, UI, snapshot and alerts
  alerts    YAML rules, dedup, quiet hours, webhook transports
  otlp      minimal OTLP/HTTP JSON receiver (127.0.0.1 only)
  report    markdown reports and the self-contained HTML snapshot
  server    JSON API (/api/v1/...) and live UI
  cli       `orch-dashboard` entry point
"""
__version__ = "2.0.0"
