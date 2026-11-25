"""The one metrics module. CLI, JSON API, live UI, static snapshot, reports and alerts all call
compute() / trends() from here, so every number has exactly one definition.

Window rules (see docs/design.md §4):
  * task-outcome metrics count tasks whose TERMINAL time (DONE or STUCK) is in [since, until)
  * dispatch metrics count dispatches whose end_ts is in [since, until)
  * guardrail / cost / tool metrics count records whose ts is in [since, until)
A task is (project, session_id, task_id). Its full dispatch history is loaded even when it
started before `since`, so its state is never judged from a partial history.
"""
import datetime as _dt
import time
from collections import defaultdict

FAKE_WORKS_GUARDRAILS = ("G3", "G4", "G8")
ALL_GUARDRAILS = tuple(f"G{i}" for i in range(1, 9))
DAY = 86400.0


# ----------------------------------------------------------------------------- loading
def _project_sessions(conn, project):
    rows = conn.execute("SELECT DISTINCT session_id FROM raw_events WHERE project=? AND session_id IS NOT NULL "
                        "UNION SELECT DISTINCT session_id FROM dispatches WHERE project=? AND session_id IS NOT NULL "
                        "UNION SELECT DISTINCT session_id FROM runs WHERE project=? AND session_id IS NOT NULL",
                        (project, project, project)).fetchall()
    return {r[0] for r in rows}


def _in(col, values):
    values = list(values)
    if not values:
        return "0", []
    return f"{col} IN ({','.join('?' * len(values))})", values


def load_dispatches(conn, project, since, until):
    where, args = ["start_ts < ?"], [until]
    if project:
        where.append("project = ?")
        args.append(project)
    # tasks touched in the window, then their complete history
    touched = conn.execute(
        f"SELECT DISTINCT project, session_id, task_id FROM dispatches WHERE {' AND '.join(where)} "
        f"AND (end_ts IS NULL OR end_ts >= ?)", args + [since]).fetchall()
    if not touched:
        return []
    keys = {(r[0], r[1], r[2]) for r in touched}
    sessions = {k[1] for k in keys}
    cond, sargs = _in("session_id", sessions)
    rows = conn.execute(f"SELECT * FROM dispatches WHERE {cond} AND start_ts < ? ORDER BY start_ts", sargs + [until])
    out = []
    for r in rows:
        d = dict(r)
        if (d["project"], d["session_id"], d["task_id"]) in keys:
            if d["end_ts"] is not None and d["end_ts"] >= until:  # evaluate the window as of `until`
                d["end_ts"], d["status"] = None, "RUNNING"
            out.append(d)
    return out


# ----------------------------------------------------------------------------- tasks
def derive_tasks(dispatches, ended_sessions, now, max_rounds=2):
    tasks = {}
    for d in dispatches:
        key = (d["project"], d["session_id"], d["task_id"])
        t = tasks.get(key)
        if t is None:
            t = tasks[key] = {
                "key": f'{d["project"]}/{d["task_id"]}', "task": d["task_id"], "project": d["project"],
                "session_id": d["session_id"], "title": d["description"] or "", "worker_runs": 0,
                "advisor_rounds": 0, "first_try": None, "state": "queued", "start": d["start_ts"], "end": None,
                "last_ts": d["start_ts"], "history": [], "memory_hit": False, "dispatch_ids": [],
                "stuck_reason": None,
            }
        t["dispatch_ids"].append(d["tool_use_id"])
        t["history"].append({"agent": d["agent"], "status": d["status"], "from_memory": d.get("from_memory")})
        t["last_ts"] = max(t["last_ts"], d["end_ts"] or d["start_ts"])
        if d["agent"] == "worker":
            t["worker_runs"] += 1
            t["title"] = d["description"] or t["title"]
            if t["first_try"] is None and d["status"] != "RUNNING":
                t["first_try"] = d["status"] == "WORKS"
            if d["status"] == "RUNNING":
                t["state"] = "in_progress"
            elif d["status"] == "WORKS":
                t["state"], t["end"] = "done", d["end_ts"]
            elif t["advisor_rounds"] >= max_rounds:
                t["state"], t["end"], t["stuck_reason"] = "stuck", d["end_ts"], "max_advisor_rounds"
            else:
                t["state"] = "failing"
        elif d["agent"] == "advisor":
            t["advisor_rounds"] += 1
            if d.get("from_memory") == "hit":
                t["memory_hit"] = True
            t["state"] = "consulting" if d["status"] == "RUNNING" else "retry_pending"
    for t in tasks.values():
        # a headless run that finished with the task unresolved also ends it as STUCK
        ended = ended_sessions.get(t["session_id"])
        if t["state"] in ("failing", "retry_pending") and ended and ended >= t["last_ts"]:
            t["state"], t["end"], t["stuck_reason"] = "stuck", ended, "run_ended_unresolved"
        t["fixed_after_advice"] = t["state"] == "done" and t["advisor_rounds"] > 0
        t["duration_sec"] = round((t["end"] or now) - t["start"], 1)
    return sorted(tasks.values(), key=lambda t: t["start"])


# ----------------------------------------------------------------------------- cost & tokens
def cost_breakdown(conn, sessions, project, since, until):
    """Cost per session from the best source available for that session:
    1. OTel api_request log events (cost_usd per API call)
    2. OTel claude_code.cost.usage metric points (delta temporality)
    3. orch-headless run_result.cost_usd
    Sources are never added together for one session, so nothing is double counted."""
    by_source = defaultdict(float)
    total = 0.0
    per_session = {}
    covered = set()
    if sessions:
        cond, args = _in("session_id", sessions)
        for sid, c in conn.execute(f"SELECT session_id, SUM(cost_usd) FROM otel_logs WHERE name='api_request' AND {cond} "
                                   f"AND ts>=? AND ts<? GROUP BY session_id", args + [since, until]):
            per_session[sid] = (c or 0.0, "otel_logs")
        have_logs = {r[0] for r in conn.execute(f"SELECT DISTINCT session_id FROM otel_logs WHERE name='api_request' AND {cond}", args)}
        covered |= have_logs
        for sid, c in conn.execute(f"SELECT session_id, SUM(value) FROM otel_metric_points WHERE name='claude_code.cost.usage' "
                                   f"AND {cond} AND ts>=? AND ts<? GROUP BY session_id", args + [since, until]):
            if sid not in covered:
                per_session[sid] = (c or 0.0, "otel_metrics")
        covered |= {r[0] for r in conn.execute(f"SELECT DISTINCT session_id FROM otel_metric_points WHERE "
                                               f"name='claude_code.cost.usage' AND {cond}", args)}
    q = "SELECT session_id, cost_usd FROM runs WHERE kind='result' AND ts>=? AND ts<? AND cost_usd IS NOT NULL"
    a = [since, until]
    if project:
        q += " AND project=?"
        a.append(project)
    for sid, c in conn.execute(q, a):
        if sid and sid in covered:
            continue
        k = sid or f"run-{len(per_session)}"
        prev = per_session.get(k, (0.0, "run_result"))[0]
        per_session[k] = (prev + c, "run_result")
    for sid, (c, src) in per_session.items():
        total += c
        by_source[src] += c
    return round(total, 4), {k: round(v, 4) for k, v in by_source.items()}


def dispatch_tokens(conn, d):
    """Tokens for one dispatch, best source first. Returns (tokens, source)."""
    if d.get("agent_id"):
        r = conn.execute("SELECT SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)), COUNT(*) FROM otel_logs "
                         "WHERE name='api_request' AND agent_id=?", (d["agent_id"],)).fetchone()
        if r and r[1]:
            return int(r[0] or 0), "otel_logs"
    r = conn.execute(
        "SELECT SUM(COALESCE(c.input_tokens,0)+COALESCE(c.output_tokens,0)), COUNT(c.span_id) FROM otel_spans t "
        "JOIN otel_spans c ON c.trace_id=t.trace_id AND c.parent_span_id=t.span_id AND c.name='claude_code.llm_request' "
        "WHERE t.tool_use_id=? AND t.name='claude_code.tool'", (d["tool_use_id"],)).fetchone()
    if r and r[1]:
        return int(r[0] or 0), "otel_spans"
    if d.get("tokens_hook"):
        return int(d["tokens_hook"]), "hook"
    return 0, "none"


def orchestrator_tokens(conn, sessions, since, until):
    if not sessions:
        return 0
    cond, args = _in("session_id", sessions)
    r = conn.execute(f"SELECT SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)) FROM otel_logs WHERE name='api_request' "
                     f"AND agent_id IS NULL AND {cond} AND ts>=? AND ts<?", args + [since, until]).fetchone()
    return int(r[0] or 0)


# ----------------------------------------------------------------------------- registry
def _ratio(num, den):
    return num, den


METRICS = [
    # name, title, unit, scale, min_sample, source, formula, alert, fn(ctx)->(num, den)
    ("tasks_done", "Tasks done", "tasks", None, 0, "hook dispatches",
     "count(tasks with state=done and end in window)", "—",
     lambda c: (len([t for t in c.terminal if t["state"] == "done"]), None)),
    ("tasks_stuck", "Tasks stuck", "tasks", None, 0, "hook dispatches (+ run_result)",
     "count(tasks with state=stuck and end in window)", "any new → alert task_stuck",
     lambda c: (len([t for t in c.terminal if t["state"] == "stuck"]), None)),
    ("first_try_success_pct", "First-try success", "%", 100, 5, "hook dispatches",
     "terminal tasks whose first worker report is WORKS ÷ terminal tasks", "< 40% weekly (info)",
     lambda c: (sum(1 for t in c.terminal if t["first_try"]), len([t for t in c.terminal if t["first_try"] is not None]))),
    ("escalation_pct", "Escalation rate", "%", 100, 5, "hook dispatches",
     "terminal tasks with ≥1 advisor round ÷ terminal tasks", "> 60% weekly (info)",
     lambda c: (sum(1 for t in c.terminal if t["advisor_rounds"] > 0), len(c.terminal))),
    ("advisor_fix_pct", "Advisor fix rate", "%", 100, 5, "hook dispatches",
     "escalated terminal tasks that ended done ÷ escalated terminal tasks", "< 50% over last 20 escalations",
     lambda c: (sum(1 for t in c.terminal if t["advisor_rounds"] > 0 and t["state"] == "done"),
                sum(1 for t in c.terminal if t["advisor_rounds"] > 0))),
    ("worker_success_pct", "Worker success", "%", 100, 10, "hook dispatches",
     "worker reports with STATUS=WORKS ÷ finished worker dispatches (incl. NO_REPORT, ERROR)", "—",
     lambda c: (sum(1 for d in c.ended if d["agent"] == "worker" and d["status"] == "WORKS"),
                sum(1 for d in c.ended if d["agent"] == "worker"))),
    ("avg_task_sec", "Avg time per solved task", "s", None, 3, "hook dispatches",
     "mean(end − start of first dispatch) over done tasks", "—",
     lambda c: (sum(t["end"] - t["start"] for t in c.terminal if t["state"] == "done"),
                len([t for t in c.terminal if t["state"] == "done"]))),
    ("throughput_per_day", "Throughput", "tasks/day", None, 0, "hook dispatches",
     "tasks done ÷ window length in days", "—",
     lambda c: (len([t for t in c.terminal if t["state"] == "done"]), c.window_days)),
    ("cost_usd", "Cost", "USD", None, 0, "otel api_request > otel cost.usage > run_result",
     "Σ cost in window, one source per session", "> budget.daily_usd per day",
     lambda c: (c.cost, None)),
    ("cost_per_solved_task_usd", "Cost per solved task", "USD", None, 1, "cost ÷ hook dispatches",
     "Σ cost in window ÷ tasks done in window", "—",
     lambda c: (c.cost, len([t for t in c.terminal if t["state"] == "done"]))),
    ("guardrail_hits_per_task", "Guardrail hits per task", "hits/task", None, 5, "guardrail_hits",
     "guardrail hits in window ÷ tasks touched in window", "any G3/G8 hit → alert",
     lambda c: (len(c.hits), len(c.touched))),
    ("fake_works_pct", "Fake-WORKS rate", "%", 100, 5, "guardrail_hits + hook dispatches",
     "WORKS reports with ≥1 G3/G4/G8 hit attributed to that dispatch ÷ WORKS reports", "> 10% weekly (warn)",
     lambda c: (len({h["dispatch_id"] for h in c.hits if h["guardrail"] in FAKE_WORKS_GUARDRAILS}
                    & {d["tool_use_id"] for d in c.ended if d["agent"] == "worker" and d["status"] == "WORKS"}),
                sum(1 for d in c.ended if d["agent"] == "worker" and d["status"] == "WORKS"))),
    ("memory_hit_pct", "Advisor memory hit rate", "%", 100, 5, "hook dispatches (FROM MEMORY field)",
     "advisor guidances with FROM_MEMORY ≠ none ÷ advisor guidances that have the field", "—",
     lambda c: (sum(1 for d in c.ended if d["agent"] == "advisor" and d.get("from_memory") == "hit"),
                sum(1 for d in c.ended if d["agent"] == "advisor" and d.get("from_memory") in ("hit", "none")))),
    ("memory_assisted_success_pct", "Memory-assisted success", "%", 100, 3, "hook dispatches",
     "terminal tasks with a memory-hit guidance that ended done ÷ terminal tasks with a memory-hit guidance", "—",
     lambda c: (sum(1 for t in c.terminal if t["memory_hit"] and t["state"] == "done"),
                sum(1 for t in c.terminal if t["memory_hit"]))),
    ("tool_failure_pct", "Tool failure rate", "%", 100, 20, "hook PostToolUse / PostToolUseFailure",
     "PostToolUseFailure ÷ all tool results (non-Agent tools)", "—",
     lambda c: (c.tool_fail, c.tool_total)),
]
METRIC_INDEX = {m[0]: m for m in METRICS}


def spec():
    return [{"name": m[0], "title": m[1], "unit": m[2], "min_sample": m[4], "source": m[5], "formula": m[6],
             "alert": m[7]} for m in METRICS]


def _value(m, num, den):
    _, _, unit, scale, min_sample = m[:5]
    if den is None:
        v = num
        n = None
    else:
        v = (num / den * (scale or 1)) if den else None
        n = den
    if v is not None:
        v = round(v, 4 if unit == "USD" else 2)
    ok = True if den is None else (den >= (min_sample or 0) and den > 0)
    return {"value": v, "num": num, "den": den, "n": n, "unit": unit, "min_sample": min_sample,
            "sufficient": ok}


class _Ctx:
    pass


# ----------------------------------------------------------------------------- compute
def compute(conn, project=None, since=None, until=None, now=None, max_rounds=2, include_detail=True):
    now = now or time.time()
    until = until or now + 1
    if since is None:
        r = conn.execute("SELECT MIN(ts) FROM raw_events" + (" WHERE project=?" if project else ""),
                         (project,) if project else ()).fetchone()
        since = (r[0] if r and r[0] else now) - 1
    sessions = _project_sessions(conn, project) if project else None

    ds = load_dispatches(conn, project, since, until)
    ended_sessions = {}
    q = "SELECT session_id, MAX(ts) FROM runs WHERE kind='result' AND session_id IS NOT NULL AND ts<?"
    for sid, ts in conn.execute(q + " GROUP BY session_id", (until,)):
        ended_sessions[sid] = ts
    tasks = derive_tasks(ds, ended_sessions, min(now, until), max_rounds)

    c = _Ctx()
    c.terminal = [t for t in tasks if t["state"] in ("done", "stuck") and t["end"] is not None and since <= t["end"] < until]
    c.touched = tasks
    c.ended = [d for d in ds if d["end_ts"] is not None and since <= d["end_ts"] < until]
    hq = "SELECT * FROM guardrail_hits WHERE ts>=? AND ts<?"
    ha = [since, until]
    if project:
        hq += " AND project=?"
        ha.append(project)
    c.hits = [dict(r) for r in conn.execute(hq, ha)]
    tq = "SELECT agent, SUM(failed), COUNT(*) FROM tool_events WHERE ts>=? AND ts<?"
    ta = [since, until]
    if project:
        tq += " AND project=?"
        ta.append(project)
    tool_rows = conn.execute(tq + " GROUP BY agent", ta).fetchall()
    c.tool_fail = sum(r[1] or 0 for r in tool_rows)
    c.tool_total = sum(r[2] for r in tool_rows)
    all_sessions = sessions if sessions is not None else {r[0] for r in conn.execute(
        "SELECT DISTINCT session_id FROM raw_events WHERE session_id IS NOT NULL")}
    c.cost, cost_sources = cost_breakdown(conn, all_sessions, project, since, until)
    first_ts = conn.execute("SELECT MIN(ts) FROM raw_events WHERE ts>=?" + (" AND project=?" if project else ""),
                            ([since, project] if project else [since])).fetchone()[0]
    span_start = max(since, first_ts or since)
    c.window_days = max((min(until, now) - span_start) / DAY, 1 / 24)

    metrics = {}
    for m in METRICS:
        num, den = m[8](c)
        metrics[m[0]] = _value(m, num, den)

    out = {
        "schema": "agentdash.metrics/v1",
        "generated_at": now, "since": since, "until": until, "project": project,
        "metrics": metrics,
        "guardrails": guardrail_breakdown(c.hits, c.touched),
        "advisor_rounds_distribution": rounds_distribution(c.terminal),
        "cost_sources": cost_sources,
    }
    if include_detail:
        by_state = defaultdict(int)
        for t in tasks:
            by_state[t["state"]] += 1
        plan = plan_items(conn, project)
        dispatched = {(t["project"], t["session_id"], t["task"]) for t in tasks}
        not_started = [p for p in plan if (p["project"], p["session_id"], p["task_id"]) not in dispatched
                       and (p["status"] or "").lower() not in ("completed", "done")]
        out["progress"] = {
            "tasks_total": len(tasks), "by_state": dict(by_state), "done": by_state.get("done", 0),
            "active": sum(by_state.get(s, 0) for s in ("in_progress", "failing", "consulting", "retry_pending", "queued")),
            "stuck": by_state.get("stuck", 0), "not_started": len(not_started),
            "planned_total": len(plan),
            "planned_done": sum(1 for p in plan if (p["status"] or "").lower() in ("completed", "done")),
        }
        tot = out["progress"]["planned_total"] or len(tasks)
        done_n = out["progress"]["planned_done"] if out["progress"]["planned_total"] else by_state.get("done", 0)
        out["progress"]["pct"] = round(100 * done_n / tot, 1) if tot else None
        out["agents"] = agent_stats(conn, ds, c, all_sessions, since, until, now, project)
        out["tasks"] = [{k: v for k, v in t.items() if k != "dispatch_ids"} for t in tasks]
        for t in out["tasks"]:
            t["guardrails"] = sorted({h["guardrail"] for h in c.hits if h["task_id"] == t["task"]
                                      and h["session_id"] == t["session_id"]})
        out["plan"] = plan
        out["timeline"] = [{"agent": d["agent"], "task": d["task_id"], "project": d["project"], "status": d["status"],
                            "start": d["start_ts"], "end": d["end_ts"], "description": d["description"]} for d in ds]
        out["runs"] = runs(conn, project, since, until)
        out["sessions"] = len({d["session_id"] for d in ds} | {r["session_id"] for r in out["runs"] if r["session_id"]})
        out["join"] = join_quality(ds)
        out["active_runs"] = active_runs(conn, project, now)
    return out


def _gkey(g):
    """Sort key that never raises: G1..G99 in number order, anything else after them."""
    d = str(g)[1:]
    return (0, int(d), "") if d.isdigit() else (1, 0, str(g))


def guardrail_breakdown(hits, touched):
    by_g = {g: 0 for g in ALL_GUARDRAILS}
    for h in hits:
        by_g[h["guardrail"]] = by_g.get(h["guardrail"], 0) + 1
    n = len(touched)
    return {"total": len(hits), "tasks": n,
            "by_guardrail": {g: {"hits": v, "per_task": round(v / n, 3) if n else None} for g, v in sorted(by_g.items(), key=lambda kv: _gkey(kv[0]))},
            "unattributed": sum(1 for h in hits if not h["dispatch_id"] and not h["task_id"])}


def rounds_distribution(terminal):
    dist = {"0": 0, "1": 0, "2": 0, "3+": 0}
    for t in terminal:
        r = t["advisor_rounds"]
        dist["3+" if r >= 3 else str(r)] += 1
    return dist


def _p(vals, q):
    if not vals:
        return None
    vals = sorted(vals)
    return round(vals[int(q * (len(vals) - 1))], 1)


def agent_stats(conn, ds, c, sessions, since, until, now, project=None):
    names = ["orchestrator", "worker", "advisor"] + sorted({d["agent"] for d in ds} - {"worker", "advisor", "orchestrator"})
    tool_by = defaultdict(lambda: [0, 0])
    q = "SELECT agent, SUM(failed), COUNT(*) FROM tool_events WHERE ts>=? AND ts<?"
    a = [since, until]
    if project:
        q += " AND project=?"
        a.append(project)
    for ag, f, n in conn.execute(q + " GROUP BY agent", a):
        tool_by[ag] = [n, f or 0]
    # observed wall time: per session from first to last raw event, clipped to the window
    observed = 0.0
    if sessions:
        cond, args = _in("session_id", sessions)
        for lo, hi in conn.execute(f"SELECT MIN(ts), MAX(ts) FROM raw_events WHERE {cond} AND ts>=? AND ts<? "
                                   f"GROUP BY session_id", args + [since, until]):
            observed += max(0.0, (hi or 0) - (lo or 0))
    token_sources = defaultdict(int)
    out = {}
    for name in names:
        mine = [d for d in ds if d["agent"] == name and (d["end_ts"] is None or d["end_ts"] >= since)]
        done = [d for d in mine if d["status"] != "RUNNING"]
        durs = [((d["end_ts"] or now) - d["start_ts"]) for d in done]
        busy = sum(min(d["end_ts"] or now, until) - max(d["start_ts"], since) for d in mine)
        toks = 0
        for d in mine:
            n, src = dispatch_tokens(conn, d)
            toks += n
            token_sources[src] += 1
        if name == "orchestrator":
            toks = orchestrator_tokens(conn, sessions, since, until)
        out[name] = {
            "running": sum(1 for d in mine if d["status"] == "RUNNING"),
            "dispatches": len(mine), "completed": len(done),
            "busy_sec": round(busy, 1),
            "utilization_pct": round(100 * busy / observed, 1) if observed and name != "orchestrator" else None,
            "avg_sec": round(sum(durs) / len(durs), 1) if durs else None,
            "p90_sec": _p(durs, 0.9),
            "tool_calls": tool_by[name][0], "tool_failures": tool_by[name][1],
            "tokens": toks,
        }
    w = [d for d in c.ended if d["agent"] == "worker"]
    out["worker"]["works"] = sum(1 for d in w if d["status"] == "WORKS")
    out["worker"]["fails"] = len(w) - out["worker"]["works"]
    out["_token_sources"] = dict(token_sources)
    return out


def join_quality(ds):
    q = defaultdict(int)
    for d in ds:
        q[d.get("join_method") or ("pending" if d["end_ts"] is None else "none")] += 1
    return dict(q)


def plan_items(conn, project):
    q = "SELECT * FROM plan_items"
    a = ()
    if project:
        q += " WHERE project=?"
        a = (project,)
    return [dict(r) for r in conn.execute(q + " ORDER BY updated_ts", a)]


def runs(conn, project, since, until):
    q = "SELECT kind, run_id, ts, project, session_id, cost_usd, duration_ms, num_turns, is_error, exit_code FROM runs WHERE ts>=? AND ts<?"
    a = [since, until]
    if project:
        q += " AND project=?"
        a.append(project)
    return [dict(r) for r in conn.execute(q + " ORDER BY ts DESC LIMIT 50", a)]


def active_runs(conn, project=None, now=None, max_age_h=12):
    """Headless runs that started (run_start) and have no run_result with the same run_id."""
    now = now or time.time()
    q = ("SELECT s.run_id, s.ts, s.project FROM runs s WHERE s.kind='start' AND s.ts>=? AND NOT EXISTS "
         "(SELECT 1 FROM runs r WHERE r.kind='result' AND r.run_id=s.run_id)")
    a = [now - max_age_h * 3600]
    if project:
        q += " AND s.project=?"
        a.append(project)
    return [dict(r) for r in conn.execute(q, a)]


def last_event_ts(conn, project=None):
    q = "SELECT MAX(ts) FROM raw_events"
    r = conn.execute(q + (" WHERE project=?" if project else ""), (project,) if project else ()).fetchone()
    return r[0]


def advisor_fix_rate_last(conn, n=20, project=None, now=None):
    """Advisor fix rate over the last n escalated tasks that reached a terminal state."""
    now = now or time.time()
    res = compute(conn, project=project, since=0, until=now + 1, now=now, include_detail=True)
    esc = [t for t in res["tasks"] if t["advisor_rounds"] > 0 and t["state"] in ("done", "stuck")]
    esc.sort(key=lambda t: t["end"] or 0)
    last = esc[-n:]
    done = sum(1 for t in last if t["state"] == "done")
    return {"n": len(last), "done": done, "pct": round(100 * done / len(last), 1) if last else None,
            "task_keys": [t["key"] for t in last]}


# ----------------------------------------------------------------------------- rollups & trends
def _day_bounds(day):
    d = _dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
    s = d.timestamp()
    return s, s + DAY


def days_with_data(conn):
    rows = conn.execute("SELECT DISTINCT date(ts, 'unixepoch') FROM raw_events UNION "
                        "SELECT DISTINCT date(end_ts, 'unixepoch') FROM dispatches WHERE end_ts IS NOT NULL").fetchall()
    return sorted(r[0] for r in rows if r[0])


def rollup(conn, days=None, now=None, recompute_recent=2):
    """Write daily_aggregates for each day x project (and '*'). A past day that is already
    computed is skipped unless it is one of the most recent `recompute_recent` days or ingest
    marked it dirty (late events for it arrived after its aggregates were written)."""
    now = now or time.time()
    days = days or days_with_data(conn)
    today = _dt.datetime.fromtimestamp(now, _dt.timezone.utc).date()
    projects = [r[0] for r in conn.execute("SELECT DISTINCT project FROM raw_events WHERE project IS NOT NULL")]
    dirty = {r[0] for r in conn.execute("SELECT day FROM rollup_dirty")}
    written = 0
    for day in days:
        age = (today - _dt.date.fromisoformat(day)).days
        if age >= recompute_recent and day not in dirty:
            if conn.execute("SELECT 1 FROM daily_aggregates WHERE day=? LIMIT 1", (day,)).fetchone():
                continue
        s, e = _day_bounds(day)
        for p in [None] + projects:
            res = compute(conn, project=p, since=s, until=e, now=min(now, e), include_detail=False)
            with conn:
                for name, m in res["metrics"].items():
                    conn.execute("INSERT OR REPLACE INTO daily_aggregates VALUES (?,?,?,?,?,?,?)",
                                 (day, p or "*", name, m["num"], m["den"], m["value"], now))
                for g, v in res["guardrails"]["by_guardrail"].items():
                    conn.execute("INSERT OR REPLACE INTO daily_aggregates VALUES (?,?,?,?,?,?,?)",
                                 (day, p or "*", f"guardrail_hits_{g}", v["hits"], res["guardrails"]["tasks"], v["hits"], now))
                for k, v in res["advisor_rounds_distribution"].items():
                    conn.execute("INSERT OR REPLACE INTO daily_aggregates VALUES (?,?,?,?,?,?,?)",
                                 (day, p or "*", f"advisor_rounds_{k}", v, None, v, now))
            written += 1
        if day in dirty:
            with conn:
                conn.execute("DELETE FROM rollup_dirty WHERE day=?", (day,))
    return written


def _iso_week(day):
    y, w, _ = _dt.date.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


def trends(conn, project=None, weeks=12, now=None):
    """Weekly value of every registry metric, re-aggregated from daily num/den (exact for ratios)."""
    now = now or time.time()
    start = _dt.datetime.fromtimestamp(now - weeks * 7 * DAY, _dt.timezone.utc).date().isoformat()
    rows = conn.execute("SELECT day, metric, num, den FROM daily_aggregates WHERE project=? AND day>=? ORDER BY day",
                        (project or "*", start)).fetchall()
    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, False]))
    for day, metric, num, den in rows:
        a = acc[metric][_iso_week(day)]
        a[0] += num or 0
        if den is not None:
            a[1] += den
            a[2] = True
    out = {}
    for name, m in METRIC_INDEX.items():
        series = []
        for wk in sorted(acc.get(name, {})):
            num, den, has_den = acc[name][wk]
            if name == "throughput_per_day":
                den = 7.0 if has_den else None
            v = _value(m, num, den if has_den else None)
            series.append({"week": wk, **v})
        out[name] = series
    for g in ALL_GUARDRAILS:
        series = []
        for wk in sorted(acc.get(f"guardrail_hits_{g}", {})):
            num, den, _ = acc[f"guardrail_hits_{g}"][wk]
            series.append({"week": wk, "value": num, "num": num, "den": den})
        out[f"guardrail_hits_{g}"] = series
    return {"schema": "agentdash.trends/v1", "project": project, "weeks": weeks, "series": out}


# ----------------------------------------------------------------------------- v1 compatibility
def legacy_state(res):
    """Shape of v1 /api/state so the existing UI and any scripts keep working."""
    m = res["metrics"]
    r1 = lambda v: None if v is None else round(v, 1)  # v1 rounded percentages to one decimal
    perf = {
        "first_try_success_pct": r1(m["first_try_success_pct"]["value"]),
        "escalation_pct": r1(m["escalation_pct"]["value"]),
        "advisor_fix_pct": r1(m["advisor_fix_pct"]["value"]),
        "worker_success_pct": r1(m["worker_success_pct"]["value"]),
        "avg_task_sec": m["avg_task_sec"]["value"],
        "throughput_per_hour": round((m["throughput_per_day"]["value"] or 0) / 24, 2),
        "total_tokens": sum(v.get("tokens", 0) for k, v in res["agents"].items() if not k.startswith("_")),
        "cost_usd": m["cost_usd"]["value"],
    }
    agents = {k: v for k, v in res["agents"].items() if not k.startswith("_")}
    return {
        "generated_at": res["generated_at"], "since": res["since"], "sessions": res["sessions"],
        "progress": {k: res["progress"][k] for k in ("tasks_total", "by_state", "planned_total", "planned_done", "pct")},
        "agents": agents, "performance": perf, "tasks": res["tasks"],
        "plan": [{"subject": p["subject"], "status": p["status"]} for p in res["plan"]],
        "timeline": res["timeline"], "runs": res["runs"][:20],
    }
