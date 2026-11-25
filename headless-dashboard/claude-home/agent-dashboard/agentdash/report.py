"""Markdown reports and the self-contained static HTML snapshot. Numbers come from metrics only."""
import datetime as _dt
import json
import os
import time

from . import metrics

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_FILE = os.path.join(HERE, "index.html")

PERIODS = {"daily": 86400, "weekly": 7 * 86400}
KPI_ORDER = ["tasks_done", "tasks_stuck", "first_try_success_pct", "escalation_pct", "advisor_fix_pct",
             "worker_success_pct", "fake_works_pct", "memory_hit_pct", "memory_assisted_success_pct",
             "guardrail_hits_per_task", "cost_usd", "cost_per_solved_task_usd", "avg_task_sec", "throughput_per_day",
             "tool_failure_pct"]


def _fmt(m):
    v = m["value"]
    if v is None:
        return "—"
    u = m["unit"]
    if u == "%":
        s = f"{v:.1f}%"
    elif u == "USD":
        s = f"${v:,.2f}"
    elif u == "s":
        s = _dur(v)
    else:
        s = f"{v:g}"
    if not m["sufficient"]:
        s += " ⚠︎"
    return s


def _dur(s):
    s = int(round(s))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def _iso(ts):
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def markdown(conn, period="daily", project=None, now=None):
    now = now or time.time()
    span = PERIODS[period]
    cur = metrics.compute(conn, project=project, since=now - span, until=now, now=now)
    prev = metrics.compute(conn, project=project, since=now - 2 * span, until=now - span, now=now - span,
                           include_detail=False)
    title = f"Agent workflow — {period} report" + (f" · {project}" if project else " · all projects")
    out = [f"# {title}", "", f"Window: {_iso(now - span)} → {_iso(now)}  ", f"Generated: {_iso(now)}", ""]
    p = cur["progress"]
    out += [f"**Progress:** {p['done']} done · {p['active']} active · {p['stuck']} stuck · {p['not_started']} not started", ""]
    out += ["| Metric | This period | Previous | n | min n |", "|---|---:|---:|---:|---:|"]
    for name in KPI_ORDER:
        m, pm = cur["metrics"][name], prev["metrics"][name]
        title_ = metrics.METRIC_INDEX[name][1]
        out.append(f"| {title_} | {_fmt(m)} | {_fmt(pm)} | {m['n'] if m['n'] is not None else '—'} | {m['min_sample'] or '—'} |")
    out += ["", "⚠︎ = below the minimum sample size; treat as indicative only.", ""]
    stuck = [t for t in cur["tasks"] if t["state"] == "stuck" and t["end"] and t["end"] >= now - span]
    out += ["## Stuck tasks", ""]
    if stuck:
        out += ["| Task | Project | Rounds | Reason | Inspect |", "|---|---|---:|---|---|"]
        for t in stuck:
            out.append(f"| {t['task']} | {t['project']} | {t['advisor_rounds']} | {t['stuck_reason']} | "
                       f"`orch-dashboard --json --project {t['project']} --task {t['task']}` |")
    else:
        out.append("None.")
    g = cur["guardrails"]
    out += ["", "## Guardrail hits", "", f"Total {g['total']} over {g['tasks']} tasks ({g['unattributed']} unattributed).", "",
            "| G | Hits | Per task |", "|---|---:|---:|"]
    for k, v in g["by_guardrail"].items():
        out.append(f"| {k} | {v['hits']} | {v['per_task'] if v['per_task'] is not None else '—'} |")
    d = cur["advisor_rounds_distribution"]
    out += ["", "## Advisor rounds per finished task", "", "| 0 | 1 | 2 | 3+ |", "|---:|---:|---:|---:|",
            f"| {d['0']} | {d['1']} | {d['2']} | {d['3+']} |", ""]
    out += ["## Cost sources", ""] + [f"- {k}: ${v:,.4f}" for k, v in cur["cost_sources"].items()] + (
        ["- none recorded"] if not cur["cost_sources"] else [])
    if period == "weekly":
        tr = metrics.trends(conn, project=project, weeks=8, now=now)["series"]
        out += ["", "## Weekly trend (last 8 weeks)", "", "| Metric | " + " | ".join(
            s["week"] for s in tr["tasks_done"]) + " |", "|---|" + "---:|" * len(tr["tasks_done"])]
        for name in ("tasks_done", "first_try_success_pct", "advisor_fix_pct", "fake_works_pct", "memory_hit_pct",
                     "cost_per_solved_task_usd"):
            weeks = {s["week"]: s for s in tr[name]}
            out.append(f"| {metrics.METRIC_INDEX[name][1]} | " + " | ".join(
                _fmt(weeks[w["week"]]) if w["week"] in weeks else "—" for w in tr["tasks_done"]) + " |")
    jq = cur["join"]
    out += ["", f"_OTel join: {jq}. Token sources: {cur['agents'].get('_token_sources')}._", ""]
    return "\n".join(out)


def snapshot_html(conn, project=None, now=None):
    """One self-contained HTML file: the live UI with its data inlined. No network, no fetch."""
    now = now or time.time()
    res = metrics.compute(conn, project=project, now=now)
    state = metrics.legacy_state(res)
    state["projects"] = [r[0] for r in conn.execute("SELECT DISTINCT project FROM raw_events WHERE project IS NOT NULL ORDER BY 1")]
    data = {"state": state, "v1": res, "trends": metrics.trends(conn, project=project, now=now),
            "spec": metrics.spec(), "snapshot_at": now, "project": project,
            "alerts": [dict(r) for r in conn.execute(
                "SELECT rule_id,severity,project,task_id,status,last_seen,send_count,held FROM alert_state "
                "ORDER BY last_seen DESC LIMIT 30")]}
    blob = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    with open(UI_FILE, encoding="utf-8") as f:
        html = f.read()
    inject = f"<script>window.__SNAPSHOT__ = {blob};</script>\n"
    return html.replace("<!--SNAPSHOT-->", inject, 1)
