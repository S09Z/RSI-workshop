"""Live UI + versioned JSON API. Loopback only. Ingestion is incremental (byte offsets), so a
request costs one small read of new lines instead of a re-read of the whole log (the v1 gap).

  GET /api/v1/health                      store version, ingest offsets, last event
  GET /api/v1/metrics?project=&since=&until=   full metrics document (agentdash.metrics/v1)
  GET /api/v1/spec                        metric definitions
  GET /api/v1/trends?project=&weeks=12    weekly series from daily_aggregates
  GET /api/v1/tasks?project=&state=       derived tasks
  GET /api/v1/guardrails?project=&since=  guardrail hits
  GET /api/v1/alerts                      alert state
  GET /api/v1/projects
  GET /api/state?project=                 v1-compatible shape (kept for the old UI / scripts)
  GET /snapshot.html?project=             self-contained static snapshot
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, config, ingest, metrics, report, store

_lock = threading.Lock()
_last = {"ingest": 0.0, "rollup": 0.0}


def parse_since(s, now=None):
    """'24h', '7d', '2w', '30m', ISO date/time, or epoch seconds -> epoch seconds."""
    import datetime as _dt
    now = now or time.time()
    if s in (None, ""):
        return None
    s = str(s).strip()
    units = {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
    if s[-1:].lower() in units and s[:-1].replace(".", "", 1).isdigit():
        return now - float(s[:-1]) * units[s[-1].lower()]
    try:
        return float(s)
    except ValueError:
        pass
    d = _dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.timestamp()


def refresh(conn, paths, cfg, force=False):
    now = time.time()
    with _lock:
        if force or now - _last["ingest"] > 2:
            ingest.run(conn, paths, cfg)
            _last["ingest"] = now
        if force or now - _last["rollup"] > 300:
            metrics.rollup(conn, now=now)
            _last["rollup"] = now


class Handler(BaseHTTPRequestHandler):
    paths = None
    cfg = None

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str))

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        project = q.get("project") or None
        try:
            if u.path in ("/", "/index.html"):
                with open(report.UI_FILE, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            conn = store.connect(self.paths["db"])
            try:
                refresh(conn, self.paths, self.cfg)
                since, until = parse_since(q.get("since")), parse_since(q.get("until"))
                if u.path == "/api/state":
                    st = metrics.legacy_state(metrics.compute(conn, project=project, since=since, until=until))
                    st["projects"] = projects(conn)
                    return self._json(st)
                if u.path == "/api/v1/health":
                    return self._json(health(conn, self.paths))
                if u.path == "/api/v1/metrics":
                    return self._json(metrics.compute(conn, project=project, since=since, until=until))
                if u.path == "/api/v1/spec":
                    return self._json({"schema": "agentdash.spec/v1", "metrics": metrics.spec()})
                if u.path == "/api/v1/trends":
                    return self._json(metrics.trends(conn, project=project, weeks=int(q.get("weeks", 12))))
                if u.path == "/api/v1/tasks":
                    res = metrics.compute(conn, project=project, since=since, until=until)
                    ts = [t for t in res["tasks"] if not q.get("state") or t["state"] == q["state"]]
                    return self._json({"schema": "agentdash.tasks/v1", "tasks": ts})
                if u.path == "/api/v1/guardrails":
                    sql, a = "SELECT * FROM guardrail_hits WHERE ts>=?", [since or 0]
                    if project:
                        sql += " AND project=?"
                        a.append(project)
                    return self._json({"schema": "agentdash.guardrails/v1",
                                       "hits": [dict(r) for r in conn.execute(sql + " ORDER BY ts DESC LIMIT 500", a)]})
                if u.path == "/api/v1/alerts":
                    return self._json({"schema": "agentdash.alerts/v1", "alerts": [dict(r) for r in conn.execute(
                        "SELECT dedup_key,rule_id,severity,project,task_id,status,first_seen,last_seen,last_sent,send_count,held,last_error "
                        "FROM alert_state ORDER BY last_seen DESC LIMIT 200")]})
                if u.path == "/api/v1/projects":
                    return self._json({"projects": projects(conn)})
                if u.path == "/snapshot.html":
                    return self._send(200, report.snapshot_html(conn, project=project), "text/html; charset=utf-8")
            finally:
                conn.close()
            self._json({"error": "not found"}, 404)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # keep the server alive
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def log_message(self, *args):
        pass


def projects(conn):
    return [r[0] for r in conn.execute("SELECT DISTINCT project FROM raw_events WHERE project IS NOT NULL ORDER BY 1")]


def health(conn, paths):
    return {"schema": "agentdash.health/v1", "version": __version__, "schema_version": store.current_version(conn),
            "ingest": [dict(r) for r in conn.execute("SELECT source,path,offset,updated_at FROM ingest_state")],
            "last_event_ts": metrics.last_event_ts(conn),
            "rows": {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
                     ("raw_events", "dispatches", "guardrail_hits", "otel_spans", "otel_logs", "daily_aggregates")},
            "db": paths["db"]}


def serve(paths, cfg, host="127.0.0.1", port=8765, ready=None):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("refusing to listen on a non-loopback address")
    Handler.paths, Handler.cfg = paths, cfg
    srv = ThreadingHTTPServer((host, port), Handler)
    if ready:
        ready(srv)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
