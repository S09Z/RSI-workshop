# Architecture decision records: dashboard v2

Date: 2026-11-25. Sources are cited as R1–R5 from [research.md](research.md).

---

## D1. Build vs. reuse

**Context.** We need task-level semantics: [Tn] task IDs, WORKS / DOES_NOT_WORK, advisor rounds,
FROM MEMORY and G1–G8 hits. We also need cost and token telemetry, alerts that run with no one
watching, and everything on a laptop with no network.

**Options.**
1. *Reuse Langfuse (self-host).* It accepts OTLP at `/api/public/otel` (HTTP/JSON and HTTP/protobuf,
   not gRPC) and shows traces well. But a VM needs "at least 4 cores and 16 GiB of memory", and it
   runs ClickHouse and MinIO in Docker Compose. It knows nothing about our task IDs or reports, so
   every task metric would need custom work in it anyway (R4).
2. *Reuse Grafana + Prometheus/Loki/Tempo.* All four projects are well maintained (78k, 68k, 29k and
   5.6k stars, pushed 2026-11-24/25), and Grafana, Loki and Tempo are AGPL-3.0. That is four services,
   and task semantics would become LogQL/PromQL that cannot easily join hook events to spans (R4).
3. *Reuse Arize Phoenix.* `pip install arize-phoenix; phoenix serve`, OTLP on 6006 (HTTP) / 4317 (gRPC),
   SQLite by default (a temp folder unless configured), Elastic License 2.0. It is the lightest option,
   but it is still trace-centric and does no alerting (R4).
4. *claude-code-templates analytics* (MIT, 34k stars): a "real-time session monitoring" dashboard on
   localhost:3333. Its README does not mention OTel, subagents or task IDs (R4).
5. *Build a custom v2*, keeping v1's hook and UI.
6. *Hybrid*: custom v2 as the source of truth, with the OTel stream optionally fanned out to one of
   the tools above.

**Decision.** Option 6, built as option 5. The custom v2 owns the task semantics, the store, the
metrics, the alerts and the snapshot. Because its OTel input is plain OTLP, anyone can point the
optional collector (`otelcol.example.yaml`) at Langfuse, Phoenix or Tempo as well, for trace browsing.

**Consequences.** + Zero services and zero dependencies; it runs offline; one metric definition.
+ The v1 hook, `events.jsonl` and UI are kept. − We maintain about 2,800 lines of Python (package + hook, measured with `wc -l`), plus about 1,000 lines of tests and fixture. − No
trace-waterfall UI; use Phoenix or Langfuse through the collector if that is needed.

---

## D2. SQLite vs. DuckDB

**Context.** A single user on a laptop. Ingestion is a stream of small writes; the UI reads at the same
time. Volume is about 10³–10⁵ events per day (assumption, not measured). Queries are small aggregates.

**Options.** *SQLite*: in the standard library; WAL allows concurrent readers during writes; mature
UPSERT and UNIQUE dedup. *DuckDB*: faster columnar scans, but needs `pip install duckdb`, and allows only
one writing process.

**Decision.** SQLite, with WAL and `synchronous=NORMAL`.

**Consequences.** + No dependency; the timer, the UI and the CLI can all have it open. + Measured: a full
ingest of 100k lines takes 2.9 s, and an incremental one takes 3 ms. − Large scans are slower than
DuckDB would be. Daily aggregates stored as num/den keep trend queries small. If history ever outgrows
this, the schema is plain SQL and can be copied to DuckDB. I have not checked DuckDB's SQLite reader
for this ADR.

---

## D3. OTel ingestion path

**Context.** Claude Code exports metrics, log events and beta traces over OTLP with
`grpc | http/json | http/protobuf` (R1). We need tokens and cost per subagent dispatch.

**Options.**
1. *otelcol-contrib + file exporter.* It writes "newline-delimited OTLP JSON, one line per batch". Its
   stability is "alpha" for traces, metrics and logs. It is a second binary to install and supervise.
2. *A small custom receiver.* OTLP/HTTP with JSON encoding only. The spec allows JSON and fixes the
   mapping: hex trace/span IDs, int enums, and int64 as decimal strings. 112 lines of standard library (`otlp.py`).
3. *Skip OTel; parse transcripts.* v1 did this for subagent tokens, and its known gaps list it as
   unreliable. Transcripts also contain full prompt and code content.

**Decision.** Option 2 as the default (`orch-dashboard --otlp` on 127.0.0.1:4318). `otel-env.sh` sets
`OTEL_EXPORTER_OTLP_PROTOCOL=http/json`. Option 1 is documented as a drop-in alternative: the ingester
reads the receiver's wrapped lines and the collector's raw lines alike. Transcript parsing is dropped.

**Consequences.** + No extra binary; a ready-to-use loopback-only receiver; content is scrubbed before
it touches disk. − Protobuf and gRPC are not accepted (415); use the collector for those. − Traces are
beta, so the join records its method on every dispatch and falls back (design §3.2).

---

## D4. Alert transport and scheduler

**Context.** Alerts must work with no one watching, with no daemon we have to babysit, and with
optional network access.

**Options.** Scheduler: a long-running daemon, or the OS timer (launchd `StartInterval` / systemd timer
/ cron) running a short `--tick`. Transport: Alertmanager (another service); direct webhooks; LINE
Notify. LINE Notify is ruled out because it was discontinued on 2025-03-31, and LINE points to the
Messaging API instead (R5).

**Decision.** The OS timer runs `orch-dashboard-tick` every 5 minutes: ingest, rollup, alerts, and
retention once a day. Alerts go directly to Slack incoming webhooks, Discord execute-webhook, the LINE
Messaging API push endpoint, a generic HTTP POST, or a file. Dedup, repeat interval, grouping into a
digest and quiet hours follow Alertmanager's concepts (`group_wait`/`group_interval`/`repeat_interval`,
`time_intervals` for muting), implemented in `alerts.py` (409 lines including rules and transports).

**Consequences.** + Nothing to keep running for alerts, and a failed tick is retried 5 minutes later.
+ The file channel works offline. − Alert latency is up to 5 minutes (configurable). − LINE needs a LINE
Official Account and a channel access token; free-plan message caps vary by region (Japan: 200 per
month). − The OTLP receiver is the only long-running process (launchd `KeepAlive` / systemd
`Restart=always`). If it is down, Claude Code's export fails silently and the session is unaffected.

---

## D5. What content is logged by default (privacy)

**Context.** v1 stored up to 4,000 characters of `result_text` per dispatch: report text that can
include code, paths, test output or secrets. OTel can also export prompts and tool input when flags are
set (R1).

**Options.** (a) Keep v1 behaviour. (b) Store redacted text by default. (c) Store structured fields
only; text is opt-in and redacted.

**Decision.** (c). The hook extracts STATUS, ATTEMPTS, CONFIDENCE, FROM MEMORY (hit / none), whether a
VERIFICATION command is present, the report contract and guardrail markers, then drops the text. The
headless prompt is stored as its length only. The OTLP receiver strips content attributes, and the
`OTEL_LOG_*` content flags stay off. Opt-in: `AGENT_DASHBOARD_LOG_CONTENT=1` or
`privacy.store_result_text: true`, redacted with built-in patterns plus user regexes. Task descriptions
and todo subjects are kept (≤ 200 characters, redacted), because they are the task titles shown in the
UI.

**Consequences.** + The database and the snapshot can be shared without leaking code
(`test_no_report_or_prompt_text_stored_by_default` checks that the DB holds neither report text nor
the OTel prompt). − A new report field needs a parser change before it can be measured. − Task titles
could still contain sensitive words. Add a redaction regex if that matters.
