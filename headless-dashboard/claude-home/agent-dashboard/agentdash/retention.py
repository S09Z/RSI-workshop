"""Retention: roll up first, then delete. daily_aggregates are never deleted.

  raw_days (30):         raw_events, tool_events, otel_spans, otel_logs, otel_metric_points, alert_log
  structured_days (180): dispatches, guardrail_hits, runs, plan_items, resolved alert_state
"""
import time

from . import metrics

RAW = [("raw_events", "ts"), ("tool_events", "ts"), ("otel_spans", "start_ts"), ("otel_logs", "ts"),
       ("otel_metric_points", "ts"), ("alert_log", "ts")]
STRUCTURED = [("dispatches", "COALESCE(end_ts, start_ts)"), ("guardrail_hits", "ts"), ("runs", "ts"),
              ("plan_items", "updated_ts")]


def apply(conn, cfg, now=None):
    now = now or time.time()
    r = cfg["retention"]
    raw_cut = now - float(r.get("raw_days", 30)) * 86400
    st_cut = now - float(r.get("structured_days", 180)) * 86400
    # 1. make sure every day that is about to lose raw data has its aggregates
    days = [d for d in metrics.days_with_data(conn)]
    metrics.rollup(conn, days=days, now=now)
    deleted = {}
    with conn:
        for table, col in RAW:
            deleted[table] = conn.execute(f"DELETE FROM {table} WHERE {col} < ?", (raw_cut,)).rowcount
        for table, col in STRUCTURED:
            deleted[table] = conn.execute(f"DELETE FROM {table} WHERE {col} < ?", (st_cut,)).rowcount
        # resolved rows, plus any row (event rules never resolve) not seen since the cut and not owed a send
        deleted["alert_state"] = conn.execute("DELETE FROM alert_state WHERE last_seen < ? AND (status='resolved' OR held=0)",
                                              (st_cut,)).rowcount
        conn.execute("INSERT OR REPLACE INTO ingest_state(source,path,offset,updated_at) "
                     "SELECT 'retention', 'n/a', 0, ? ", (now,))
    conn.execute("PRAGMA optimize")
    return {"raw_before": raw_cut, "structured_before": st_cut, "deleted": deleted}


def maybe_daily(conn, cfg, now=None):
    now = now or time.time()
    r = conn.execute("SELECT updated_at FROM ingest_state WHERE source='retention'").fetchone()
    if r and r[0] and now - r[0] < 86400:
        return {"skipped": "ran within the last 24h"}
    return apply(conn, cfg, now)
