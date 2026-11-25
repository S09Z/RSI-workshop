"""Incremental ingestion: events.jsonl (hooks, v1 and v2) and otel.jsonl (OTLP JSON) -> SQLite.

Reading is by byte offset per source. Rotation (rename + new file) and truncation are
detected with (dev, inode), file size and a hash of the file head. Every line is hashed and
stored with a UNIQUE constraint, so re-reading a line is a no-op: ingestion is idempotent.
A partial last line (writer still appending) is left for the next run.
"""
import datetime as _dt
import glob
import gzip
import hashlib
import json
import os
import time

from . import parse

HEAD_BYTES = 256
CHUNK = 8 * 1024 * 1024
POST_HOC_WINDOW_S = 300      # a hit up to 5 min after a dispatch ends is attributed to it
AGENT_TOOLS = ("Task", "Agent")


# --------------------------------------------------------------------------- file reading
def _head_sig(path, size):
    n = min(HEAD_BYTES, size)
    with open(path, "rb") as f:
        return f"{n}:{hashlib.sha1(f.read(n)).hexdigest()}"


def _sig_matches(path, sig, size):
    if not sig:
        return True
    n, _, h = sig.partition(":")
    n = int(n)
    if size < n:
        return False
    with open(path, "rb") as f:
        return hashlib.sha1(f.read(n)).hexdigest() == h


def _read_from(path, offset):
    """Yield (complete_line_bytes) from offset; return the offset after the last full line."""
    lines, pos = [], offset
    with open(path, "rb") as f:
        f.seek(offset)
        buf = b""
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            buf += chunk
            cut = buf.rfind(b"\n")
            if cut < 0:
                continue
            complete, buf = buf[:cut + 1], buf[cut + 1:]
            for ln in complete.split(b"\n")[:-1]:
                lines.append(ln)
            pos += len(complete)
    return lines, pos


def _find_rotated(path, inode):
    d, base = os.path.dirname(path) or ".", os.path.basename(path)
    for cand in glob.glob(os.path.join(d, base + "*")):
        try:
            if os.stat(cand).st_ino == inode and not cand.endswith(".gz"):
                return cand
        except OSError:
            continue
    return None


def read_new(conn, source, path):
    """Return new complete lines of `path` since the stored offset, handling rotation/truncation.
    The new offset is committed by the caller via commit_offset(), after the lines are stored."""
    notes = []
    if not os.path.exists(path):
        return [], None, notes
    st = os.stat(path)
    row = conn.execute("SELECT * FROM ingest_state WHERE source=?", (source,)).fetchone()
    lines, start = [], 0
    if row and row["path"] == path:
        if (row["dev"], row["inode"]) != (st.st_dev, st.st_ino):
            old = _find_rotated(path, row["inode"])
            if old:
                more, _ = _read_from(old, row["offset"])
                lines.extend(more)
                notes.append(f"rotated: drained {len(more)} lines from {os.path.basename(old)}")
            else:
                notes.append("rotated: previous file not found, starting new file at 0")
            start = 0
        elif st.st_size < row["offset"] or not _sig_matches(path, row["head_hash"], st.st_size):
            notes.append("truncated or replaced: re-reading from 0 (duplicates are skipped)")
            start = 0
        else:
            start = row["offset"]
    more, new_off = _read_from(path, start)
    lines.extend(more)
    state = {"source": source, "path": path, "dev": st.st_dev, "inode": st.st_ino,
             "offset": new_off, "head_hash": _head_sig(path, st.st_size) if st.st_size else None}
    return lines, state, notes


def commit_offset(conn, state):
    if not state:
        return
    conn.execute(
        "INSERT INTO ingest_state(source,path,dev,inode,offset,head_hash,updated_at) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(source) DO UPDATE SET path=excluded.path, dev=excluded.dev, inode=excluded.inode, "
        "offset=excluded.offset, head_hash=excluded.head_hash, updated_at=excluded.updated_at",
        (state["source"], state["path"], state["dev"], state["inode"], state["offset"],
         state["head_hash"], time.time()))


# --------------------------------------------------------------------------- helpers
def _ts(v):
    if isinstance(v, (int, float)):
        return float(v) / 1000.0 if v > 1e12 else float(v)
    if isinstance(v, str) and v:
        try:
            return float(v)
        except ValueError:
            pass
        try:
            return _dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _agent_of(e):
    return (e.get("subagent_type") or "unknown").lower()


def _clip(s, n, cfg_patterns):
    if not s:
        return s
    return parse.redact(str(s), cfg_patterns)[:n]


PAYLOAD_KEEP = ("ts", "event", "project", "session_id", "agent_id", "agent_type", "tool", "tool_use_id",
                "subagent_type", "duration_ms", "tokens", "tool_uses", "report", "guardrail", "run_id",
                "is_error", "exit_code", "num_turns", "cost_usd", "error_class", "v")


# --------------------------------------------------------------------------- hook events
class EventIngester:
    def __init__(self, conn, cfg):
        self.conn = conn
        self.cfg = cfg
        self.pats = parse.compile_redactions(cfg["privacy"].get("redact"))
        self.keep_text = bool(cfg["privacy"].get("store_result_text"))
        self.keep_prompts = bool(cfg["privacy"].get("store_prompts"))
        self.stats = {"lines": 0, "new": 0, "dup": 0, "bad": 0}

    def line(self, raw):
        self.stats["lines"] += 1
        raw = raw.strip()
        if not raw:
            return
        try:
            e = json.loads(raw)
            if not isinstance(e, dict):
                raise ValueError
        except ValueError:
            self.stats["bad"] += 1
            return
        h = hashlib.sha1(raw).hexdigest()
        ts = _ts(e.get("ts"))
        if ts is None:
            self.stats["bad"] += 1
            return
        e["ts"] = ts
        payload = {k: e[k] for k in PAYLOAD_KEEP if k in e}
        if e.get("description"):
            payload["description"] = _clip(e["description"], 200, self.pats)
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO raw_events(line_hash,ts,event,project,session_id,agent_id,agent_type,tool,tool_use_id,payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (h, ts, e.get("event") or "unknown", e.get("project"), e.get("session_id"), e.get("agent_id"),
             e.get("agent_type"), e.get("tool"), e.get("tool_use_id"), json.dumps(payload, ensure_ascii=False)))
        if cur.rowcount == 0:
            self.stats["dup"] += 1
            return
        self.stats["new"] += 1
        self.apply(e, h)

    # -- event handlers
    def apply(self, e, h):
        ev, tool = e.get("event"), e.get("tool")
        if ev in ("run_result", "run_start"):
            return self._run(e, h)
        if ev == "guardrail_hit":
            g = (e.get("guardrail") or "").upper()
            if g:
                self._hit(e, h, g, "event", e.get("reason"))
            return
        if tool in AGENT_TOOLS and ev == "PreToolUse":
            return self._dispatch_start(e)
        if tool in AGENT_TOOLS and ev in ("PostToolUse", "PostToolUseFailure"):
            return self._dispatch_end(e, h)
        if ev in ("PostToolUse", "PostToolUseFailure") and tool:
            failed = ev == "PostToolUseFailure"
            self.conn.execute(
                "INSERT INTO tool_events(ts,project,session_id,agent,agent_id,tool,tool_use_id,failed) VALUES (?,?,?,?,?,?,?,?)",
                (e["ts"], e.get("project"), e.get("session_id"), (e.get("agent_type") or "orchestrator").lower(),
                 e.get("agent_id"), tool, e.get("tool_use_id"), int(failed)))
            for g in (e.get("guardrails") or parse.guardrails(e.get("error") or e.get("result_text") if failed else "")):
                self._hit(e, h, g, "marker", None)
        if ev == "SubagentStart" and e.get("agent_id"):
            self._subagent_start(e)
        if tool == "TodoWrite" and e.get("todos") is not None:
            self._todos(e)
        if tool in ("TaskCreate", "TaskUpdate") and e.get("task"):
            self._task_item(e)
        if ev in ("SubagentStop", "Stop"):
            for g in (e.get("guardrails") or []):
                self._hit(e, h, g, "marker", None)

    def _run(self, e, h):
        prompt = e.get("prompt") or ""
        self.conn.execute(
            "INSERT OR IGNORE INTO runs(line_hash,kind,run_id,ts,project,session_id,cost_usd,duration_ms,num_turns,is_error,exit_code,prompt_len,prompt) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (h, "start" if e["event"] == "run_start" else "result", e.get("run_id"), e["ts"], e.get("project"),
             e.get("session_id"), e.get("cost_usd"), e.get("duration_ms"), e.get("num_turns"),
             None if e.get("is_error") is None else int(bool(e.get("is_error"))), e.get("exit_code"),
             e.get("prompt_len", len(prompt) if prompt else None),
             _clip(prompt, 200, self.pats) if (self.keep_prompts and prompt) else None))

    def _dispatch_start(self, e):
        tid = e.get("tool_use_id") or f"anon-{e['ts']}"
        desc = e.get("description") or ""
        self.conn.execute(
            "INSERT INTO dispatches(tool_use_id,session_id,project,task_id,agent,description,start_ts,status) "
            "VALUES (?,?,?,?,?,?,?, 'RUNNING') ON CONFLICT(tool_use_id) DO UPDATE SET "
            "start_ts=MIN(COALESCE(dispatches.start_ts, excluded.start_ts), excluded.start_ts), "
            "description=COALESCE(dispatches.description, excluded.description)",
            (tid, e.get("session_id"), e.get("project") or "", parse.task_key(desc), _agent_of(e),
             _clip(desc, 200, self.pats), e["ts"]))

    def _dispatch_end(self, e, h):
        tid = e.get("tool_use_id") or f"anon-{e['ts']}"
        agent = _agent_of(e)
        rep = e.get("report")
        text = e.get("result_text") or ""
        if rep is None:  # v1 event: parse the stored text now, then drop it
            rep = parse.report(text, agent)
        failed = e.get("event") == "PostToolUseFailure"
        if failed:
            status = "ERROR"
        elif agent == "worker":
            status = rep.get("status") or "NO_REPORT"
        elif agent == "advisor":
            status = "GUIDANCE"
        else:
            status = "DONE"
        dur = e.get("duration_ms")
        start = e["ts"] - (dur / 1000.0 if dur else 0)
        desc = e.get("description") or ""
        self.conn.execute(
            "INSERT INTO dispatches(tool_use_id,session_id,project,task_id,agent,description,start_ts,end_ts,status,attempts,"
            "confidence,from_memory,has_verification,contract_ok,duration_ms,tokens_hook,tool_uses,result_text) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tool_use_id) DO UPDATE SET "
            "end_ts=excluded.end_ts, status=excluded.status, attempts=excluded.attempts, confidence=excluded.confidence, "
            "from_memory=excluded.from_memory, has_verification=excluded.has_verification, contract_ok=excluded.contract_ok, "
            "duration_ms=excluded.duration_ms, tokens_hook=excluded.tokens_hook, tool_uses=excluded.tool_uses, "
            "result_text=excluded.result_text, "
            "start_ts=CASE WHEN excluded.duration_ms IS NOT NULL THEN MIN(dispatches.start_ts, excluded.start_ts) ELSE dispatches.start_ts END",
            (tid, e.get("session_id"), e.get("project") or "", parse.task_key(desc), agent, _clip(desc, 200, self.pats),
             start, e["ts"], status, rep.get("attempts"), rep.get("confidence"), rep.get("from_memory"),
             None if rep.get("has_verification") is None else int(rep["has_verification"]),
             None if rep.get("contract_ok") is None else int(rep["contract_ok"]),
             dur, e.get("tokens"), e.get("tool_uses"),
             _clip(text, 4000, self.pats) if (self.keep_text and text) else None))
        for g in rep.get("guardrails") or []:
            self._hit(dict(e, tool_use_id=tid), h, g, "marker", None, dispatch_id=tid)

    def _subagent_start(self, e):
        rows = self.conn.execute(
            "SELECT tool_use_id FROM dispatches WHERE session_id=? AND status='RUNNING' AND agent_id IS NULL "
            "AND agent=? AND start_ts<=?", (e.get("session_id"), (e.get("agent_type") or "").lower(), e["ts"] + 1)).fetchall()
        if len(rows) == 1:
            self.conn.execute("UPDATE dispatches SET agent_id=?, join_method='single_running' WHERE tool_use_id=?",
                              (e["agent_id"], rows[0][0]))

    def _todos(self, e):
        sid, proj = e.get("session_id") or "", e.get("project") or ""
        self.conn.execute("DELETE FROM plan_items WHERE project=? AND session_id=? AND item_key LIKE 'todo-%'", (proj, sid))
        for i, t in enumerate(e["todos"]):
            subj = t.get("content") or ""
            self.conn.execute("INSERT OR REPLACE INTO plan_items VALUES (?,?,?,?,?,?,?)",
                              (proj, sid, f"todo-{i}", parse.task_id(subj), _clip(subj, 200, self.pats),
                               t.get("status"), e["ts"]))

    def _task_item(self, e):
        t = e["task"]
        key = str(t.get("taskId") or t.get("subject") or "")
        if not key:
            return
        sid, proj = e.get("session_id") or "", e.get("project") or ""
        cur = self.conn.execute("SELECT subject,status FROM plan_items WHERE project=? AND session_id=? AND item_key=?",
                                (proj, sid, key)).fetchone()
        subj = t.get("subject") or (cur["subject"] if cur else None)
        status = t.get("status") or (cur["status"] if cur else "pending")
        self.conn.execute("INSERT OR REPLACE INTO plan_items VALUES (?,?,?,?,?,?,?)",
                          (proj, sid, key, parse.task_id(subj), _clip(subj, 200, self.pats), status, e["ts"]))

    # -- guardrail attribution: explicit task > tool_use_id > agent_id > running > just ended
    def attribute(self, e):
        sid, ts = e.get("session_id"), e["ts"]
        q = self.conn.execute
        if e.get("tool_use_id"):
            r = q("SELECT tool_use_id, task_id FROM dispatches WHERE tool_use_id=?", (e["tool_use_id"],)).fetchone()
            if r:
                return r[0], r[1]
            r = q("SELECT agent_id FROM tool_events WHERE tool_use_id=? AND agent_id IS NOT NULL", (e["tool_use_id"],)).fetchone()
            if r and not e.get("agent_id"):
                e = dict(e, agent_id=r[0])
        if e.get("agent_id"):
            r = q("SELECT tool_use_id, task_id FROM dispatches WHERE agent_id=?", (e["agent_id"],)).fetchone()
            if r:
                return r[0], r[1]
        if sid:
            rows = q("SELECT tool_use_id, task_id, agent FROM dispatches WHERE session_id=? AND start_ts<=? "
                     "AND (end_ts IS NULL OR end_ts>=?) ORDER BY start_ts DESC", (sid, ts, ts)).fetchall()
            want = (e.get("agent_type") or "").lower()
            if want:
                rows = [r for r in rows if r[2] == want] or rows
            if rows:
                return rows[0][0], rows[0][1]
            r = q("SELECT tool_use_id, task_id FROM dispatches WHERE session_id=? AND end_ts<=? AND end_ts>=? "
                  "ORDER BY end_ts DESC LIMIT 1", (sid, ts, ts - POST_HOC_WINDOW_S)).fetchone()
            if r:
                return r[0], r[1]
        return None, None

    def _hit(self, e, h, g, source, reason, dispatch_id=None):
        task = parse.task_id(e.get("task_id") or "") or e.get("task_id")
        if dispatch_id:
            r = self.conn.execute("SELECT task_id FROM dispatches WHERE tool_use_id=?", (dispatch_id,)).fetchone()
            task = task or (r[0] if r else None)
        else:
            d, t = self.attribute(e)
            dispatch_id, task = d, task or t
        self.conn.execute(
            "INSERT OR IGNORE INTO guardrail_hits(line_hash,ts,project,session_id,task_id,dispatch_id,tool_use_id,guardrail,source,reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (h, e["ts"], e.get("project"), e.get("session_id"), task, dispatch_id, e.get("tool_use_id"), g.upper(),
             source, _clip(reason, 300, self.pats)))


# --------------------------------------------------------------------------- OTel (OTLP JSON)
CONTENT_ATTRS = {"prompt", "prompt_text", "user_prompt", "response", "tool_input", "tool_parameters", "error",
                 "full_command", "file_path", "new_context", "system_reminders", "system_prompt_preview",
                 "user_system_prompt", "response.model_output", "body", "user.email"}


def _attr_val(v):
    if not isinstance(v, dict):
        return v
    for k in ("stringValue", "boolValue", "doubleValue"):
        if k in v:
            return v[k]
    if "intValue" in v:
        try:
            return int(v["intValue"])
        except (TypeError, ValueError):
            return None
    if "arrayValue" in v:
        return [_attr_val(x) for x in (v["arrayValue"].get("values") or [])]
    if "kvlistValue" in v:
        return {kv["key"]: _attr_val(kv.get("value")) for kv in v["kvlistValue"].get("values") or []}
    return None


def _attrs(lst):
    return {kv.get("key"): _attr_val(kv.get("value")) for kv in (lst or []) if isinstance(kv, dict)}


def _ns(v):
    try:
        return int(v) / 1e9
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _bool(v):
    if v is None:
        return None
    if isinstance(v, str):
        return int(v.lower() == "true")
    return int(bool(v))


def _sid(a):
    return a.get("session.id") or a.get("session_id")


class OtelIngester:
    def __init__(self, conn):
        self.conn = conn
        self.stats = {"lines": 0, "spans": 0, "logs": 0, "points": 0, "bad": 0}

    def line(self, raw):
        self.stats["lines"] += 1
        raw = raw.strip()
        if not raw:
            return
        try:
            doc = json.loads(raw)
        except ValueError:
            self.stats["bad"] += 1
            return
        body = doc.get("body", doc) if isinstance(doc, dict) else {}
        if not isinstance(body, dict):
            self.stats["bad"] += 1
            return
        for rs in body.get("resourceSpans") or []:
            ra = _attrs((rs.get("resource") or {}).get("attributes"))
            for ss in rs.get("scopeSpans") or []:
                for sp in ss.get("spans") or []:
                    self._span(sp, ra)
        for rl in body.get("resourceLogs") or []:
            ra = _attrs((rl.get("resource") or {}).get("attributes"))
            for sl in rl.get("scopeLogs") or []:
                for lr in sl.get("logRecords") or []:
                    self._log(lr, ra)
        for rm in body.get("resourceMetrics") or []:
            ra = _attrs((rm.get("resource") or {}).get("attributes"))
            for sm in rm.get("scopeMetrics") or []:
                for m in sm.get("metrics") or []:
                    self._metric(m, ra)

    def _span(self, sp, ra):
        a = dict(ra)
        a.update(_attrs(sp.get("attributes")))
        self.conn.execute(
            "INSERT OR REPLACE INTO otel_spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sp.get("traceId"), sp.get("spanId"), sp.get("parentSpanId") or None, sp.get("name"),
             _ns(sp.get("startTimeUnixNano")), _ns(sp.get("endTimeUnixNano")), _sid(a),
             a.get("tool_use_id") or a.get("gen_ai.tool.call.id"), a.get("tool_name"), a.get("subagent_type"),
             a.get("agent_id"), a.get("parent_agent_id"), a.get("model") or a.get("gen_ai.request.model"),
             _int(a.get("input_tokens")), _int(a.get("output_tokens")), _int(a.get("cache_read_tokens")),
             _int(a.get("cache_creation_tokens")), _bool(a.get("success"))))
        self.stats["spans"] += 1

    def _log(self, lr, ra):
        a = dict(ra)
        a.update(_attrs(lr.get("attributes")))
        name = a.get("event.name") or _attr_val(lr.get("body")) or ""
        name = str(name).replace("claude_code.", "")
        ts = _ns(lr.get("timeUnixNano")) or _ns(lr.get("observedTimeUnixNano")) or _ts(a.get("event.timestamp"))
        safe = {k: v for k, v in a.items() if k not in CONTENT_ATTRS}
        h = hashlib.sha1(json.dumps([name, ts, safe], sort_keys=True, default=str).encode()).hexdigest()
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO otel_logs(rec_hash,ts,name,session_id,prompt_id,agent_id,parent_agent_id,tool_use_id,tool_name,"
            "model,query_source,cost_usd,input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,duration_ms,success) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (h, ts, name, _sid(a), a.get("prompt.id"), a.get("agent_id"), a.get("parent_agent_id"), a.get("tool_use_id"),
             a.get("tool_name"), a.get("model"), a.get("query_source"), _float(a.get("cost_usd")),
             _int(a.get("input_tokens")), _int(a.get("output_tokens")), _int(a.get("cache_read_tokens")),
             _int(a.get("cache_creation_tokens")), _float(a.get("duration_ms")), _bool(a.get("success"))))
        self.stats["logs"] += cur.rowcount

    def _metric(self, m, ra):
        name = m.get("name")
        data = m.get("sum") or m.get("gauge") or {}
        for dp in data.get("dataPoints") or []:
            a = dict(ra)
            a.update(_attrs(dp.get("attributes")))
            val = dp.get("asDouble", dp.get("asInt"))
            ts = _ns(dp.get("timeUnixNano"))
            h = hashlib.sha1(json.dumps([name, ts, dp.get("startTimeUnixNano"), a, val], sort_keys=True,
                                        default=str).encode()).hexdigest()
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO otel_metric_points(rec_hash,ts,name,session_id,type,model,query_source,value) VALUES (?,?,?,?,?,?,?,?)",
                (h, ts, name, _sid(a), a.get("type"), a.get("model"), a.get("query_source"), _float(val)))
            self.stats["points"] += cur.rowcount


def join_otel(conn):
    """Attach subagent agent_id to dispatches.

    trace: the Agent tool span (claude_code.tool, tool_use_id == dispatch id) has child spans
           from the subagent that carry agent_id. Exact.
    single_running: an api_request log with agent_id inside the session while exactly one
           dispatch was running. Good for sequential runs; skipped when dispatches overlap.
    """
    n_trace = n_single = 0
    rows = conn.execute(
        "SELECT d.tool_use_id, s.trace_id, s.span_id FROM dispatches d JOIN otel_spans s ON s.tool_use_id=d.tool_use_id "
        "AND s.name='claude_code.tool' WHERE d.join_method IS NULL OR d.join_method!='trace'").fetchall()
    for tid, trace, span in rows:
        c = conn.execute("SELECT agent_id FROM otel_spans WHERE trace_id=? AND parent_span_id=? AND agent_id IS NOT NULL "
                         "LIMIT 1", (trace, span)).fetchone()
        if c:
            conn.execute("UPDATE dispatches SET agent_id=?, join_method='trace' WHERE tool_use_id=?", (c[0], tid))
            n_trace += 1
    logs = conn.execute(
        "SELECT agent_id, session_id, MIN(ts) FROM otel_logs WHERE agent_id IS NOT NULL AND session_id IS NOT NULL "
        "AND agent_id NOT IN (SELECT agent_id FROM dispatches WHERE agent_id IS NOT NULL) GROUP BY agent_id, session_id").fetchall()
    for agent_id, sid, ts in logs:
        cands = conn.execute("SELECT tool_use_id FROM dispatches WHERE session_id=? AND agent_id IS NULL AND start_ts<=? "
                             "AND (end_ts IS NULL OR end_ts>=?)", (sid, ts, ts)).fetchall()
        if len(cands) == 1:
            conn.execute("UPDATE dispatches SET agent_id=?, join_method='single_running' WHERE tool_use_id=?",
                         (agent_id, cands[0][0]))
            n_single += 1
    conn.execute("UPDATE dispatches SET join_method='none' WHERE join_method IS NULL AND end_ts IS NOT NULL")
    return {"trace": n_trace, "single_running": n_single}


# --------------------------------------------------------------------------- entry point
def run(conn, paths, cfg):
    """Ingest both sources once. Safe to call concurrently-ish: SQLite serialises writers."""
    report = {"events": None, "otel": None, "join": None, "notes": []}
    ei = EventIngester(conn, cfg)
    lines, state, notes = read_new(conn, "events", paths["events"])
    report["notes"] += notes
    with conn:
        for ln in lines:
            ei.line(ln)
        commit_offset(conn, state)
    report["events"] = ei.stats
    oi = OtelIngester(conn)
    lines, state, notes = read_new(conn, "otel", paths["otel"])
    report["notes"] += notes
    with conn:
        for ln in lines:
            oi.line(ln)
        commit_offset(conn, state)
        report["join"] = join_otel(conn)
    report["otel"] = oi.stats
    return report


def open_maybe_gz(path):
    return gzip.open(path, "rb") if path.endswith(".gz") else open(path, "rb")
