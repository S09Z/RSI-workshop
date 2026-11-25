"""Alert rules (YAML), evaluation, dedup, quiet hours and webhook transports.

Run by a timer (`orch-dashboard --tick`, see deploy/). Every rule reads numbers from
agentdash.metrics, so alerts and dashboards can never disagree.

State machine per dedup_key (table alert_state):
  new condition          -> send (or hold during quiet hours) -> firing
  still true             -> nothing, unless repeat_interval elapsed -> send again
  gone (stateful rules)  -> resolved (+ optional "resolved" notification)
Event rules (task_stuck, guardrail_hit, daily budget) fire once per key and never repeat.
"""
import datetime as _dt
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from . import metrics, yaml_lite

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

SEVERITIES = ["info", "warning", "high", "critical"]
DEFAULT_RULES = {
    "version": 1,
    "defaults": {"dashboard_url": "http://127.0.0.1:8765", "max_per_channel_per_run": 5,
                 "quiet_hours": None},
    "channels": {"log": {"type": "file", "path": "~/.claude/agent-dashboard/alerts.log"}},
    "rules": [
        {"id": "task_stuck", "kind": "task_stuck", "severity": "high", "lookback": "7d", "channels": ["log"]},
        {"id": "guardrail_g3_g8", "kind": "guardrail_hit", "guardrails": ["G3", "G8"], "severity": "critical",
         "lookback": "1d", "channels": ["log"]},
        {"id": "daily_budget", "kind": "cost_over_budget", "budget_usd": 20, "severity": "high", "channels": ["log"]},
        {"id": "advisor_fix_rate_low", "kind": "advisor_fix_rate", "last_n": 20, "below_pct": 50,
         "severity": "warning", "repeat_interval": "24h", "notify_resolved": True, "channels": ["log"]},
        {"id": "headless_silent", "kind": "no_events", "minutes": 15, "severity": "high",
         "repeat_interval": "1h", "notify_resolved": True, "channels": ["log"]},
    ],
}
STATEFUL = {"advisor_fix_rate", "no_events", "metric_threshold"}


def parse_duration(s, default=None):
    if s is None:
        return default
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().lower()
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
    if s[-1] in mult:
        return float(s[:-1]) * mult[s[-1]]
    return float(s)


def load_rules(path):
    if path and os.path.exists(path):
        doc = yaml_lite.load_file(path) or {}
    else:
        doc = DEFAULT_RULES
    doc.setdefault("defaults", {})
    doc.setdefault("channels", {})
    doc.setdefault("rules", [])
    for r in doc["rules"]:
        if "id" not in r or "kind" not in r:
            raise ValueError(f"alert rule needs id and kind: {r}")
        if r.get("severity", "warning") not in SEVERITIES:
            raise ValueError(f"rule {r['id']}: severity must be one of {SEVERITIES}")
    return doc


# --------------------------------------------------------------------------- quiet hours
def in_quiet_hours(qh, now):
    """qh = {start: '22:00', end: '07:00', tz: 'Asia/Bangkok', days: [mon, ...]}; window may wrap midnight."""
    if not qh:
        return False
    tz = _dt.timezone.utc
    if qh.get("tz") and ZoneInfo:
        try:
            tz = ZoneInfo(qh["tz"])
        except Exception:
            tz = _dt.timezone.utc
    t = _dt.datetime.fromtimestamp(now, tz)
    days = [d.lower()[:3] for d in (qh.get("days") or [])]
    s_h, s_m = map(int, str(qh.get("start", "22:00")).split(":"))
    e_h, e_m = map(int, str(qh.get("end", "07:00")).split(":"))
    cur, start, end = t.hour * 60 + t.minute, s_h * 60 + s_m, e_h * 60 + e_m
    if start <= end:
        inside = start <= cur < end
        day = t
    else:
        inside = cur >= start or cur < end
        day = t if cur >= start else t - _dt.timedelta(days=1)  # the window began yesterday
    if inside and days:
        inside = day.strftime("%a").lower()[:3] in days
    return inside


# --------------------------------------------------------------------------- rule evaluation
def _alert(rule, key_parts, project, summary, details, task_id=None, session_id=None, inspect=None):
    key = ":".join([rule["id"]] + [str(p) for p in key_parts if p is not None])
    return {"dedup_key": key, "rule": rule["id"], "kind": rule["kind"], "severity": rule.get("severity", "warning"),
            "project": project, "task_id": task_id, "session_id": session_id, "summary": summary,
            "details": details, "inspect_command": inspect or (
                f"orch-dashboard --json --project {project}" + (f" --task {task_id}" if task_id else "")
                if project else "orch-dashboard --json")}


def evaluate(conn, doc, now=None, cfg=None):
    now = now or time.time()
    out = []
    for rule in doc["rules"]:
        if rule.get("enabled", True) is False:
            continue
        fn = KINDS.get(rule["kind"])
        if fn is None:
            raise ValueError(f"unknown alert kind {rule['kind']!r} in rule {rule['id']}")
        out.extend(fn(conn, rule, now, cfg or {}))
    return out


def _projects(conn, rule):
    if rule.get("project"):
        return [rule["project"]]
    return [r[0] for r in conn.execute("SELECT DISTINCT project FROM raw_events WHERE project IS NOT NULL")]


def k_task_stuck(conn, rule, now, cfg):
    lb = parse_duration(rule.get("lookback"), 7 * 86400)
    res = metrics.compute(conn, project=rule.get("project"), since=now - lb, until=now + 1, now=now)
    out = []
    for t in res["tasks"]:
        if t["state"] == "stuck" and t["end"] and t["end"] >= now - lb:
            out.append(_alert(rule, [t["project"], t["session_id"], t["task"]], t["project"],
                              f"Task {t['task']} is STUCK in {t['project']} after {t['advisor_rounds']} advisor round(s)",
                              {"reason": t["stuck_reason"], "worker_runs": t["worker_runs"],
                               "advisor_rounds": t["advisor_rounds"], "title": t["title"],
                               "guardrails": t.get("guardrails", [])},
                              task_id=t["task"], session_id=t["session_id"]))
    return out


def k_guardrail_hit(conn, rule, now, cfg):
    lb = parse_duration(rule.get("lookback"), 86400)
    wanted = [g.upper() for g in rule.get("guardrails") or metrics.ALL_GUARDRAILS]
    q = f"SELECT * FROM guardrail_hits WHERE ts>=? AND guardrail IN ({','.join('?' * len(wanted))})"
    args = [now - lb] + wanted
    if rule.get("project"):
        q += " AND project=?"
        args.append(rule["project"])
    out = []
    for h in conn.execute(q, args):
        out.append(_alert(rule, [h["id"]], h["project"],
                          f"Guardrail {h['guardrail']} hit on {h['task_id'] or 'unattributed task'} in {h['project']}",
                          {"guardrail": h["guardrail"], "reason": h["reason"], "dispatch": h["dispatch_id"],
                           "at": h["ts"]}, task_id=h["task_id"], session_id=h["session_id"]))
    return out


def k_cost_over_budget(conn, rule, now, cfg):
    budget = float(rule.get("budget_usd") or (cfg.get("budget") or {}).get("daily_usd") or 20)
    day = _dt.datetime.fromtimestamp(now, _dt.timezone.utc).date()
    start = _dt.datetime(day.year, day.month, day.day, tzinfo=_dt.timezone.utc).timestamp()
    out = []
    for p in ([rule.get("project")] if rule.get("project") else [None]):
        res = metrics.compute(conn, project=p, since=start, until=now + 1, now=now, include_detail=False)
        cost = res["metrics"]["cost_usd"]["value"] or 0
        if cost > budget:
            out.append(_alert(rule, [p or "*", day.isoformat()], p,
                              f"Cost today ${cost:,.2f} is over the ${budget:,.2f} budget" + (f" ({p})" if p else ""),
                              {"cost_usd": cost, "budget_usd": budget, "sources": res["cost_sources"], "day": day.isoformat()}))
    return out


def k_advisor_fix_rate(conn, rule, now, cfg):
    n = int(rule.get("last_n", 20))
    below = float(rule.get("below_pct", 50))
    out = []
    for p in ([rule.get("project")] if rule.get("project") else [None]):
        r = metrics.advisor_fix_rate_last(conn, n=n, project=p, now=now)
        if r["n"] >= int(rule.get("min_sample", n)) and r["pct"] is not None and r["pct"] < below:
            out.append(_alert(rule, [p or "*"], p,
                              f"Advisor fix rate {r['pct']:.0f}% over the last {r['n']} escalations (threshold {below:.0f}%)",
                              {"pct": r["pct"], "n": r["n"], "fixed": r["done"], "tasks": r["task_keys"][-5:]}))
    return out


def k_no_events(conn, rule, now, cfg):
    mins = float(rule.get("minutes", 15))
    out = []
    for run in metrics.active_runs(conn, rule.get("project"), now):
        last = metrics.last_event_ts(conn, run["project"]) or run["ts"]
        idle = now - max(last, run["ts"])
        if idle >= mins * 60:
            out.append(_alert(rule, [run["run_id"]], run["project"],
                              f"No events for {idle / 60:.0f} min while headless run {run['run_id']} is active in {run['project']}",
                              {"run_id": run["run_id"], "started": run["ts"], "last_event": last, "idle_min": round(idle / 60, 1)}))
    return out


def k_metric_threshold(conn, rule, now, cfg):
    win = parse_duration(rule.get("window"), 7 * 86400)
    name = rule["metric"]
    op, val = rule.get("op", ">"), float(rule["value"])
    out = []
    for p in ([rule.get("project")] if rule.get("project") else [None]):
        res = metrics.compute(conn, project=p, since=now - win, until=now + 1, now=now, include_detail=False)
        m = res["metrics"][name]
        if m["value"] is None or not m["sufficient"]:
            continue
        hit = {">": m["value"] > val, ">=": m["value"] >= val, "<": m["value"] < val, "<=": m["value"] <= val}[op]
        if hit:
            out.append(_alert(rule, [p or "*"], p, f"{metrics.METRIC_INDEX[name][1]} is {m['value']}{m['unit']} ({op} {val})",
                              {"metric": name, **m}))
    return out


KINDS = {"task_stuck": k_task_stuck, "guardrail_hit": k_guardrail_hit, "cost_over_budget": k_cost_over_budget,
         "advisor_fix_rate": k_advisor_fix_rate, "no_events": k_no_events, "metric_threshold": k_metric_threshold}


# --------------------------------------------------------------------------- payloads & transports
def payload(a, status, row, doc):
    base = (doc.get("defaults") or {}).get("dashboard_url", "http://127.0.0.1:8765")
    url = base + (f"/?project={a['project']}" if a.get("project") else "/")
    return {
        "schema": "agentdash.alert/v1",
        "id": hashlib.sha1(a["dedup_key"].encode()).hexdigest()[:12],
        "dedup_key": a["dedup_key"], "rule": a["rule"], "kind": a["kind"], "severity": a["severity"],
        "status": status, "project": a.get("project"), "task_id": a.get("task_id"), "session_id": a.get("session_id"),
        "summary": a["summary"], "details": a.get("details") or {},
        "first_seen": row.get("first_seen"), "last_seen": row.get("last_seen"),
        "occurrences": (row.get("send_count") or 0) + 1,
        "inspect": {"command": a["inspect_command"], "url": url},
    }


def _text(p):
    icon = {"critical": "🚨", "high": "🔴", "warning": "🟠", "info": "🔵"}.get(p["severity"], "•")
    head = f"{'✅ RESOLVED' if p['status'] == 'resolved' else icon + ' ' + p['severity'].upper()}: {p['summary']}"
    ctx = " · ".join(x for x in [p.get("project") and f"project {p['project']}", p.get("task_id") and f"task {p['task_id']}"] if x)
    return f"{head}\n{ctx}\nInspect: {p['inspect']['command']}  ({p['inspect']['url']})".strip()


def _digest_text(ps):
    lines = [f"{len(ps)} agent-workflow alerts:"] + [f"• [{p['severity']}] {p['summary']}" for p in ps]
    return "\n".join(lines)


def format_for(channel_type, ps):
    """Build the request body for one channel from one or more alert payloads."""
    text = _text(ps[0]) if len(ps) == 1 else _digest_text(ps)
    if channel_type == "slack":
        return {"text": text, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}]}
    if channel_type == "discord":
        color = {"critical": 0xDC2626, "high": 0xEA580C, "warning": 0xD97706, "info": 0x2563EB}
        return {"content": text[:2000], "embeds": [
            {"title": p["summary"][:256], "color": color.get(p["severity"], 0x6B7280),
             "fields": [{"name": "project", "value": str(p.get("project") or "—"), "inline": True},
                        {"name": "task", "value": str(p.get("task_id") or "—"), "inline": True},
                        {"name": "inspect", "value": p["inspect"]["command"][:1024]}]} for p in ps[:10]]}
    if channel_type == "line":
        return {"messages": [{"type": "text", "text": text[:2000]}]}
    if channel_type in ("webhook", "file"):
        return ps[0] if len(ps) == 1 else {"schema": "agentdash.alert-digest/v1", "alerts": ps}
    raise ValueError(f"unknown channel type {channel_type}")


def http_post(url, body, headers=None, timeout=5):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - URL comes from the user's config
        return r.status


def deliver(ch, ps, sender=http_post):
    """Send to one channel. Returns (ok, error). Secrets are read from env vars named in config."""
    t = ch.get("type")
    body = format_for(t, ps)
    if t == "file":
        path = os.path.expanduser(ch.get("path") or "~/.claude/agent-dashboard/alerts.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **body} if isinstance(body, dict) else body) + "\n")
        return True, None
    headers = dict(ch.get("headers") or {})
    if t == "line":
        token = os.environ.get(ch.get("token_env", "AGENTDASH_LINE_TOKEN"))
        to = ch.get("to") or os.environ.get(ch.get("to_env", "AGENTDASH_LINE_TO"))
        if not token or not to:
            return False, "skipped: LINE token or recipient env var not set"
        body["to"] = to
        headers["Authorization"] = f"Bearer {token}"
        url = ch.get("url", "https://api.line.me/v2/bot/message/push")
    else:
        url = ch.get("url") or os.environ.get(ch.get("url_env", ""), "")
        if not url:
            return False, f"skipped: env var {ch.get('url_env')} not set"
    try:
        status = sender(url, body, headers)
        return (200 <= int(status) < 300), None if 200 <= int(status) < 300 else f"HTTP {status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:  # network errors never crash the timer
        return False, f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------- dedup / state
def process(conn, doc, alerts, now=None, sender=http_post, dry_run=False):
    now = now or time.time()
    d = doc.get("defaults") or {}
    rules = {r["id"]: r for r in doc["rules"]}
    quiet = in_quiet_hours(d.get("quiet_hours"), now)
    allow = set((d.get("quiet_hours") or {}).get("allow_severity") or ["critical"])
    outbox = {}          # channel -> [payload]
    actions = []
    seen = set()

    def queue(a, status, row, rule):
        p = payload(a, status, row, doc)
        for chn in rule.get("channels") or list(doc["channels"]):
            outbox.setdefault(chn, []).append((a["dedup_key"], p))
        return p

    for a in alerts:
        seen.add(a["dedup_key"])
        rule = rules[a["rule"]]
        row = conn.execute("SELECT * FROM alert_state WHERE dedup_key=?", (a["dedup_key"],)).fetchone()
        row = dict(row) if row else None
        repeat = parse_duration(rule.get("repeat_interval"))
        send = False
        if row is None:
            row = {"first_seen": now, "last_seen": now, "send_count": 0, "held": 0, "last_sent": None}
            send = True
        elif row["status"] == "resolved":
            send = True
            row["first_seen"] = now
        elif row["held"]:
            send = True
        elif repeat and row["last_sent"] and now - row["last_sent"] >= repeat:
            send = True
        row["last_seen"] = now
        held = 0
        if send and quiet and a["severity"] not in allow:
            held, send = 1, False
            actions.append({"dedup_key": a["dedup_key"], "action": "held_quiet_hours"})
        if send:
            queue(a, "firing", row, rule)
            actions.append({"dedup_key": a["dedup_key"], "action": "send"})
        if not dry_run:
            conn.execute(
                "INSERT INTO alert_state(dedup_key,rule_id,severity,project,task_id,status,first_seen,last_seen,last_sent,send_count,held,payload) "
                "VALUES (?,?,?,?,?, 'firing',?,?,?,?,?,?) ON CONFLICT(dedup_key) DO UPDATE SET status='firing', "
                "first_seen=excluded.first_seen, last_seen=excluded.last_seen, last_sent=excluded.last_sent, "
                "send_count=excluded.send_count, held=excluded.held, payload=excluded.payload",
                (a["dedup_key"], a["rule"], a["severity"], a.get("project"), a.get("task_id"), row["first_seen"], now,
                 now if send else row.get("last_sent"), (row.get("send_count") or 0) + (1 if send else 0), held,
                 json.dumps(a, default=str)))

    # resolve stateful alerts whose condition has cleared
    for row in conn.execute("SELECT * FROM alert_state WHERE status='firing'").fetchall():
        row = dict(row)
        rule = rules.get(row["rule_id"])
        if row["dedup_key"] in seen or not rule or rule["kind"] not in STATEFUL:
            continue
        if rule.get("notify_resolved") and row["send_count"] and not quiet:
            a = json.loads(row["payload"])
            a["summary"] = "Resolved: " + a["summary"]
            queue(a, "resolved", row, rule)
        actions.append({"dedup_key": row["dedup_key"], "action": "resolved"})
        if not dry_run:
            conn.execute("UPDATE alert_state SET status='resolved', held=0, last_seen=? WHERE dedup_key=?",
                         (now, row["dedup_key"]))

    # deliver: many alerts for one channel in one run become a single digest message
    maxn = int(d.get("max_per_channel_per_run", 5))
    results = []
    for chn, items in outbox.items():
        ch = doc["channels"].get(chn)
        if ch is None:
            results.append({"channel": chn, "ok": False, "error": "unknown channel"})
            continue
        ps = [p for _, p in items]
        batches = [ps] if len(ps) > maxn else [[p] for p in ps]
        for batch in batches:
            if dry_run:
                results.append({"channel": chn, "ok": True, "dry_run": True, "body": format_for(ch.get("type"), batch)})
                continue
            ok, err = deliver(ch, batch, sender)
            results.append({"channel": chn, "ok": ok, "error": err, "alerts": len(batch)})
            for p in batch:
                conn.execute("INSERT INTO alert_log(ts,dedup_key,channel,status,ok,error) VALUES (?,?,?,?,?,?)",
                             (now, p["dedup_key"], chn, p["status"], int(ok), err))
                if not ok and err and not err.startswith("skipped"):
                    # failed delivery: keep it held so the next tick retries
                    conn.execute("UPDATE alert_state SET held=1, last_error=? WHERE dedup_key=?", (err, p["dedup_key"]))
    if not dry_run:
        conn.commit()
    return {"quiet_hours": quiet, "evaluated": len(alerts), "actions": actions, "deliveries": results}


def run(conn, rules_path, cfg=None, now=None, sender=http_post, dry_run=False):
    doc = load_rules(rules_path)
    alerts = evaluate(conn, doc, now, cfg)
    return process(conn, doc, alerts, now=now, sender=sender, dry_run=dry_run)
