"""SQLite store: schema, ordered migrations, connection helper.

Migrations are append-only. Each runs once inside a transaction and is recorded in
schema_migrations. Never edit an applied migration; add a new one.
"""
import os
import sqlite3
import time

MIGRATIONS = [
    (1, "initial schema", """
CREATE TABLE IF NOT EXISTS ingest_state (
  source      TEXT PRIMARY KEY,          -- 'events' | 'otel'
  path        TEXT NOT NULL,
  dev         INTEGER, inode INTEGER,
  offset      INTEGER NOT NULL DEFAULT 0, -- byte offset of the next unread line
  head_hash   TEXT,                       -- sha1 of the first 256 bytes: detects replace/truncate
  updated_at  REAL
);

-- Every hook / run line, content-free (see privacy). Retention: raw_days.
CREATE TABLE IF NOT EXISTS raw_events (
  id          INTEGER PRIMARY KEY,
  line_hash   TEXT NOT NULL UNIQUE,       -- sha1 of the raw line: makes re-ingestion idempotent
  ts          REAL NOT NULL,
  event       TEXT NOT NULL,
  project     TEXT, session_id TEXT, agent_id TEXT, agent_type TEXT,
  tool        TEXT, tool_use_id TEXT,
  payload     TEXT                        -- JSON of whitelisted, redacted fields
);
CREATE INDEX IF NOT EXISTS ix_raw_ts ON raw_events(ts);
CREATE INDEX IF NOT EXISTS ix_raw_session ON raw_events(session_id, ts);
CREATE INDEX IF NOT EXISTS ix_raw_project_ts ON raw_events(project, ts);

-- One row per Agent/Task tool call (worker or advisor dispatch). Retention: structured_days.
CREATE TABLE IF NOT EXISTS dispatches (
  tool_use_id   TEXT PRIMARY KEY,
  session_id    TEXT, project TEXT,
  task_id       TEXT,                     -- [T3] -> 'T3'; v1 fallback: description prefix
  agent         TEXT,                     -- worker | advisor | other subagent type
  description   TEXT,                     -- redacted, <= 200 chars
  start_ts      REAL, end_ts REAL,
  status        TEXT,                     -- RUNNING | WORKS | DOES_NOT_WORK | BLOCKED | NO_REPORT | GUIDANCE | ERROR | DONE
  attempts      INTEGER,
  confidence    TEXT,
  from_memory   TEXT,                     -- 'hit' | 'none' | NULL (field missing)
  has_verification INTEGER,
  contract_ok   INTEGER,
  duration_ms   REAL,
  tokens_hook   INTEGER,                  -- totalTokens from the Agent tool response (may be absent)
  tool_uses     INTEGER,
  agent_id      TEXT,                     -- subagent id, from OTel join or SubagentStart
  join_method   TEXT,                     -- trace | single_running | none
  result_text   TEXT                      -- NULL unless privacy.store_result_text
);
CREATE INDEX IF NOT EXISTS ix_disp_task ON dispatches(project, session_id, task_id);
CREATE INDEX IF NOT EXISTS ix_disp_start ON dispatches(start_ts);
CREATE INDEX IF NOT EXISTS ix_disp_agent_id ON dispatches(agent_id);

CREATE TABLE IF NOT EXISTS tool_events (
  id INTEGER PRIMARY KEY, ts REAL, project TEXT, session_id TEXT,
  agent TEXT, agent_id TEXT, tool TEXT, tool_use_id TEXT, failed INTEGER
);
CREATE INDEX IF NOT EXISTS ix_tool_ts ON tool_events(ts);
CREATE INDEX IF NOT EXISTS ix_tool_session ON tool_events(session_id, ts);

CREATE TABLE IF NOT EXISTS guardrail_hits (
  id INTEGER PRIMARY KEY,
  line_hash TEXT,                         -- with guardrail: unique per source line
  ts REAL, project TEXT, session_id TEXT,
  task_id TEXT, dispatch_id TEXT, tool_use_id TEXT,
  guardrail TEXT NOT NULL,                -- G1..G8 (G9+ allowed)
  source TEXT,                            -- event | marker
  reason TEXT,                            -- redacted, <= 300 chars
  UNIQUE(line_hash, guardrail)
);
CREATE INDEX IF NOT EXISTS ix_gr_ts ON guardrail_hits(ts);
CREATE INDEX IF NOT EXISTS ix_gr_task ON guardrail_hits(project, session_id, task_id);

CREATE TABLE IF NOT EXISTS plan_items (
  project TEXT, session_id TEXT, item_key TEXT, task_id TEXT, subject TEXT, status TEXT, updated_ts REAL,
  PRIMARY KEY (project, session_id, item_key)
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, line_hash TEXT UNIQUE,
  kind TEXT,                              -- start | result
  run_id TEXT, ts REAL, project TEXT, session_id TEXT,
  cost_usd REAL, duration_ms REAL, num_turns INTEGER, is_error INTEGER, exit_code INTEGER,
  prompt_len INTEGER, prompt TEXT          -- prompt NULL unless privacy.store_prompts
);
CREATE INDEX IF NOT EXISTS ix_runs_ts ON runs(ts);

-- OpenTelemetry (Claude Code export). Retention: raw_days.
CREATE TABLE IF NOT EXISTS otel_spans (
  trace_id TEXT, span_id TEXT, parent_span_id TEXT,
  name TEXT, start_ts REAL, end_ts REAL,
  session_id TEXT, tool_use_id TEXT, tool_name TEXT, subagent_type TEXT,
  agent_id TEXT, parent_agent_id TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_creation_tokens INTEGER,
  success INTEGER,
  PRIMARY KEY (trace_id, span_id)
);
CREATE INDEX IF NOT EXISTS ix_span_tool_use ON otel_spans(tool_use_id);
CREATE INDEX IF NOT EXISTS ix_span_parent ON otel_spans(trace_id, parent_span_id);
CREATE INDEX IF NOT EXISTS ix_span_session ON otel_spans(session_id, start_ts);

CREATE TABLE IF NOT EXISTS otel_logs (
  id INTEGER PRIMARY KEY, rec_hash TEXT UNIQUE,
  ts REAL, name TEXT, session_id TEXT, prompt_id TEXT, agent_id TEXT, parent_agent_id TEXT,
  tool_use_id TEXT, tool_name TEXT, model TEXT, query_source TEXT,
  cost_usd REAL, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_creation_tokens INTEGER,
  duration_ms REAL, success INTEGER
);
CREATE INDEX IF NOT EXISTS ix_olog_ts ON otel_logs(ts);
CREATE INDEX IF NOT EXISTS ix_olog_session ON otel_logs(session_id, name);
CREATE INDEX IF NOT EXISTS ix_olog_agent ON otel_logs(agent_id);

CREATE TABLE IF NOT EXISTS otel_metric_points (
  id INTEGER PRIMARY KEY, rec_hash TEXT UNIQUE,
  ts REAL, name TEXT, session_id TEXT, type TEXT, model TEXT, query_source TEXT, value REAL
);
CREATE INDEX IF NOT EXISTS ix_omp_ts ON otel_metric_points(ts, name);

-- Kept forever. Ratios are stored as num/den so weeks can be re-aggregated exactly.
CREATE TABLE IF NOT EXISTS daily_aggregates (
  day TEXT NOT NULL,                      -- YYYY-MM-DD (UTC)
  project TEXT NOT NULL,                  -- '*' = all projects
  metric TEXT NOT NULL,
  num REAL, den REAL, value REAL,
  computed_at REAL,
  PRIMARY KEY (day, project, metric)
);

CREATE TABLE IF NOT EXISTS alert_state (
  dedup_key TEXT PRIMARY KEY,
  rule_id TEXT, severity TEXT, project TEXT, task_id TEXT,
  status TEXT,                            -- firing | resolved
  first_seen REAL, last_seen REAL, last_sent REAL, send_count INTEGER DEFAULT 0,
  held INTEGER DEFAULT 0,                 -- 1 = waiting for quiet hours to end
  last_error TEXT, payload TEXT
);
"""),
    (2, "alert log", """
CREATE TABLE IF NOT EXISTS alert_log (
  id INTEGER PRIMARY KEY, ts REAL, dedup_key TEXT, channel TEXT, status TEXT, ok INTEGER, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_alert_log_ts ON alert_log(ts);
"""),
    (3, "rollup dirty days", """
-- UTC days that received new data since their daily_aggregates were written
CREATE TABLE IF NOT EXISTS rollup_dirty (day TEXT PRIMARY KEY, marked_at REAL);
-- last value of each cumulative OTLP sum series, so points can be stored as deltas
CREATE TABLE IF NOT EXISTS otel_cumulative (series TEXT PRIMARY KEY, last_ts REAL, last_value REAL);
"""),
]

SCHEMA_VERSION = MIGRATIONS[-1][0]


def connect(path):
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def migrate(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at REAL)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    for version, name, sql in MIGRATIONS:
        if version in done:
            continue
        with conn:
            for stmt in _split(sql):
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (version, name, time.time()))
    return current_version(conn)


def current_version(conn):
    r = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return r[0] or 0


def _split(sql):
    out, buf = [], []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        code = line.split(" --")[0] if " --" in line else line
        buf.append(code)
        if code.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";")
            if stmt:
                out.append(stmt)
            buf = []
    rest = "\n".join(buf).strip()
    if rest:
        out.append(rest)
    return out
