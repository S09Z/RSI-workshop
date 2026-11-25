#!/usr/bin/env python3
"""Generate a deterministic recorded-events fixture plus independently computed expectations.

    python3 tests/fixtures/make_fixture.py [out_dir]

Writes events.jsonl (hook + run events, v1 and v2 shapes), otel.jsonl (OTLP JSON lines as
written by agentdash.otlp) and expected.json. Covers 3 projects, 23 tasks, stuck tasks,
guardrail hits G1-G8, advisor memory hits, a headless run, a running task and v1 events.

The expectations are computed here by straightforward counting, NOT by agentdash.metrics,
so the tests compare two independent implementations.
"""
import json
import os
import random
import sys

BASE = 1793577600.0          # 2026-11-02 00:00:00 UTC (a Monday)
NOW = BASE + 22 * 86400      # 2026-11-24 00:00 UTC: "now" used by the tests
DAY = 86400.0

# Outcome scripts. Worker steps: WORKS / DOES_NOT_WORK / BLOCKED / RUNNING, optional *Gn guardrail
# attached to that worker dispatch. Advisor steps: adv:hit (FROM MEMORY used) / adv:none / adv:missing.
P = {
    "A": ["WORKS"],
    "B": ["DOES_NOT_WORK", "adv:none", "WORKS"],
    "C": ["DOES_NOT_WORK", "adv:hit", "WORKS"],
    "D": ["DOES_NOT_WORK", "adv:none", "DOES_NOT_WORK", "adv:hit", "DOES_NOT_WORK"],
    "E": ["BLOCKED", "adv:hit", "DOES_NOT_WORK", "adv:none", "BLOCKED"],
    "F": ["WORKS*G3"],
    "G": ["WORKS*G4"],
    "H": ["DOES_NOT_WORK", "adv:hit", "WORKS*G8"],
    "M": ["DOES_NOT_WORK", "adv:missing", "WORKS"],
    "R": ["DOES_NOT_WORK", "adv:none", "RUNNING"],
    "U": ["DOES_NOT_WORK"],   # unresolved when its headless run ends -> stuck
}

# (session_id, project, day offset, mode, otel, task patterns)
SESSIONS = [
    ("s-shop-1", "shop-api", 0, "interactive", "trace", ["A", "B", "C", "F"]),
    ("s-shop-2", "shop-api", 7, "interactive", "trace", ["A", "D", "H", "A"]),
    ("s-shop-3", "shop-api", 14, "headless", "trace", ["C", "A", "U"]),
    ("s-mob-1", "mobile-app", 1, "v1", None, ["A", "E", "B"]),
    ("s-mob-2", "mobile-app", 9, "interactive", "metrics", ["G", "M", "A"]),
    ("s-data-1", "data-pipeline", 3, "headless", None, ["A", "D", "C"]),
    ("s-data-2", "data-pipeline", 21, "interactive", "trace", ["B", "A", "R"]),
]
EXTRA_GUARDRAILS = [  # (session, task index, guardrail, reason)
    ("s-shop-1", 1, "G1", "WORKER REPORT missing VERIFICATION"),
    ("s-shop-2", 1, "G5", "DONE_WHEN test passed before work started"),
    ("s-mob-2", 1, "G7", "write outside git root: /etc/hosts"),
    ("s-data-1", 1, "G6", "advisor Edit outside memory folder"),
    ("s-data-2", 0, "G2", "orchestrator attempted Edit"),
]

rng = random.Random(42)


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    events, otel = [], []
    exp = {"tasks": 0, "done": 0, "stuck": 0, "active": 0, "first_try": 0, "with_report": 0, "escalated_terminal": 0,
           "fixed": 0, "works_reports": 0, "worker_reports": 0, "fake_works": 0, "advisor_with_field": 0,
           "memory_hits": 0, "memory_tasks_terminal": 0, "memory_tasks_done": 0, "guardrail_hits": {},
           "rounds": {"0": 0, "1": 0, "2": 0, "3+": 0}, "cost_usd": 0.0, "projects": {}, "stuck_keys": [],
           "cost_by_source": {}}
    n = 0
    for sid, proj, day, mode, otel_mode, patterns in SESSIONS:
        t = BASE + day * DAY + 9 * 3600
        trace_id = (sid.encode().hex() + "0" * 32)[:32]
        pe = exp["projects"].setdefault(proj, {"done": 0, "stuck": 0, "tasks": 0})
        run_id = f"run-{sid}"
        v1 = mode == "v1"

        def ev(**kw):
            e = {"ts": kw.pop("ts"), "project": proj, "cwd": f"/home/dev/{proj}", "session_id": sid}
            e.update(kw)
            events.append(e)
            return e

        if mode == "headless":
            ev(ts=t - 5, event="run_start", run_id=run_id, prompt_len=42)
        todos = [{"content": f"[T{i + 1}] task {i + 1} of {proj}", "status": "pending"} for i in range(len(patterns) + 1)]
        ev(ts=t, event="PostToolUse", tool="TodoWrite", todos=todos)
        t += 10
        session_cost = 0.0
        for ti, pat in enumerate(patterns):
            tid = f"T{ti + 1}"
            steps = P[pat]
            rounds = 0
            first = None
            mem_hit = False
            last_status = None
            for step in steps:
                n += 1
                uid = f"toolu_{n:05d}"
                is_adv = step.startswith("adv:")
                agent = "advisor" if is_adv else "worker"
                desc = f"[{tid}] Diagnose task {tid}" if is_adv else f"[{tid}] Implement task {tid}"
                dur = rng.uniform(60, 200) if is_adv else rng.uniform(120, 600)
                ev(ts=t, event="PreToolUse", tool="Agent", tool_use_id=uid, subagent_type=agent, description=desc)
                agent_id = f"ag-{uid}"
                ev(ts=t + 1, event="SubagentStart", agent_id=agent_id, agent_type=agent)
                for k in range(3):
                    failed = (n + k) % 7 == 0
                    ev(ts=t + 5 + k * 10, event="PostToolUseFailure" if failed else "PostToolUse",
                       tool=["Read", "Edit", "Bash"][k], tool_use_id=f"{uid}-c{k}", agent_id=agent_id, agent_type=agent)
                if step == "RUNNING":
                    last_status = "RUNNING"
                    t += 40
                    break
                status, g = (step.split("*") + [None])[:2]
                rep = {}
                text = ""
                if is_adv:
                    rounds += 1
                    fm = {"adv:hit": "hit", "adv:none": "none", "adv:missing": None}[step]
                    if fm is not None:
                        exp_key = "advisor_with_field"
                        exp[exp_key] += 1
                    if fm == "hit":
                        exp["memory_hits"] += 1
                        mem_hit = True
                    rep = {"confidence": "medium", "from_memory": fm, "contract_ok": True}
                    text = "=== ADVISOR GUIDANCE ===\nDIAGNOSIS: x\nCONFIDENCE: medium\n" + (
                        "" if fm is None else f"FROM MEMORY: {'projects/' + proj + '.md: flaky fixture' if fm == 'hit' else 'none'}\n") + "=== END GUIDANCE ==="
                else:
                    exp["worker_reports"] += 1
                    rep = {"status": status, "attempts": 2, "has_verification": True, "contract_ok": True}
                    text = f"=== WORKER REPORT ===\nTASK: {tid}\nSTATUS: {status}\nVERIFICATION:\n- command: pytest -q\n- result: ok\nATTEMPTS: 2/3\n=== END REPORT ==="
                    if first is None:
                        first = status
                    if status == "WORKS":
                        exp["works_reports"] += 1
                        if g in ("G3", "G4", "G8"):
                            exp["fake_works"] += 1
                    last_status = status
                post = dict(ts=t + dur, event="PostToolUse", tool="Agent", tool_use_id=uid, subagent_type=agent,
                            description=desc, duration_ms=int(dur * 1000), tokens=int(dur * 50))
                if v1:
                    post["result_text"] = text           # v1 hook shape: raw report text, no 'report'
                else:
                    post["report"] = rep
                    post["v"] = 2
                ev(**post)
                ev(ts=t + dur + 0.5, event="SubagentStop", agent_id=agent_id, agent_type=agent)
                if g:
                    ev(ts=t + dur + 2, event="guardrail_hit", guardrail=g, reason=f"{g} flagged report of {tid}",
                       tool_use_id=uid)
                    exp["guardrail_hits"][g] = exp["guardrail_hits"].get(g, 0) + 1
                # OTel for this dispatch
                cost = round(dur * 0.0004, 6)
                in_tok, out_tok = int(dur * 40), int(dur * 10)
                if otel_mode == "trace":
                    tool_span = f"{n:016x}"
                    otel.append(_spans(trace_id, tool_span, uid, agent, agent_id, sid, t, t + dur, in_tok, out_tok))
                    otel.append(_log(sid, agent_id, t + dur / 2, cost, in_tok, out_tok))
                    session_cost += cost
                elif otel_mode == "metrics":
                    otel.append(_metric(sid, t + dur, cost))
                    session_cost += cost
                t += dur + 15
            # extra guardrails on this task
            for (gs, gi, g, reason) in EXTRA_GUARDRAILS:
                if gs == sid and gi == ti:
                    ev(ts=t - 10, event="guardrail_hit", guardrail=g, reason=reason, task_id=tid)
                    exp["guardrail_hits"][g] = exp["guardrail_hits"].get(g, 0) + 1
            # expected task outcome
            exp["tasks"] += 1
            pe["tasks"] += 1
            terminal = None
            if last_status == "WORKS":
                terminal = "done"
            elif last_status == "RUNNING":
                exp["active"] += 1
            elif rounds >= 2:
                terminal = "stuck"
            elif mode == "headless":
                terminal = "stuck"     # run_result arrives with the task unresolved
            else:
                exp["active"] += 1
            if terminal:
                exp[terminal] += 1
                pe[terminal] += 1
                exp["with_report"] += 1
                exp["first_try"] += int(first == "WORKS")
                exp["rounds"]["3+" if rounds >= 3 else str(rounds)] += 1
                if rounds:
                    exp["escalated_terminal"] += 1
                    exp["fixed"] += int(terminal == "done")
                if mem_hit:
                    exp["memory_tasks_terminal"] += 1
                    exp["memory_tasks_done"] += int(terminal == "done")
                if terminal == "stuck":
                    exp["stuck_keys"].append(f"{proj}/{tid}")
            todos[ti]["status"] = "completed" if terminal == "done" else "in_progress"
            ev(ts=t, event="PostToolUse", tool="TodoWrite", todos=[dict(x) for x in todos])
        # main-session (orchestrator) API calls
        if otel_mode == "trace":
            otel.append(_log(sid, None, t, 0.05, 2000, 500))
            session_cost += 0.05
        if otel_mode:
            exp["cost_by_source"]["otel_logs" if otel_mode == "trace" else "otel_metrics"] = round(
                exp["cost_by_source"].get("otel_logs" if otel_mode == "trace" else "otel_metrics", 0) + session_cost, 6)
        if mode == "headless":
            run_cost = round(session_cost if otel_mode else 1.25, 6)
            ev(ts=t + 5, event="run_result", run_id=run_id, cost_usd=run_cost, duration_ms=int((t - BASE) * 10),
               num_turns=30, is_error=False, exit_code=0, prompt_len=42)
            if not otel_mode:
                session_cost = run_cost
                exp["cost_by_source"]["run_result"] = round(exp["cost_by_source"].get("run_result", 0) + run_cost, 6)
        ev(ts=t + 6, event="Stop")
        exp["cost_usd"] = round(exp["cost_usd"] + session_cost, 6)

    events.sort(key=lambda e: e["ts"])
    with open(os.path.join(out_dir, "events.jsonl"), "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    with open(os.path.join(out_dir, "otel.jsonl"), "w", encoding="utf-8") as f:
        for o in otel:
            f.write(json.dumps(o) + "\n")
    exp["guardrail_total"] = sum(exp["guardrail_hits"].values())
    exp["now"] = NOW
    exp["base"] = BASE
    exp["events"] = len(events)
    with open(os.path.join(out_dir, "expected.json"), "w", encoding="utf-8") as f:
        json.dump(exp, f, indent=2, sort_keys=True)
    return exp


def _kv(d):
    out = []
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out.append({"key": k, "value": {"boolValue": v}})
        elif isinstance(v, int):
            out.append({"key": k, "value": {"intValue": str(v)}})
        elif isinstance(v, float):
            out.append({"key": k, "value": {"doubleValue": v}})
        else:
            out.append({"key": k, "value": {"stringValue": str(v)}})
    return out


def _ns(t):
    return str(int(t * 1e9))


def _res():
    return {"attributes": _kv({"service.name": "claude-code"})}


def _spans(trace_id, tool_span, uid, agent, agent_id, sid, start, end, in_tok, out_tok):
    spans = [
        {"traceId": trace_id, "spanId": tool_span, "parentSpanId": "", "name": "claude_code.tool", "kind": 1,
         "startTimeUnixNano": _ns(start), "endTimeUnixNano": _ns(end),
         "attributes": _kv({"session.id": sid, "tool_name": "Agent", "tool_use_id": uid, "subagent_type": agent,
                            "span.type": "claude_code.tool"})},
        {"traceId": trace_id, "spanId": "c" + tool_span[1:], "parentSpanId": tool_span, "name": "claude_code.llm_request",
         "kind": 1, "startTimeUnixNano": _ns(start + 2), "endTimeUnixNano": _ns(start + 9),
         "attributes": _kv({"session.id": sid, "agent_id": agent_id, "model": "claude-sonnet-5-5",
                            "input_tokens": in_tok, "output_tokens": out_tok, "success": True})},
    ]
    return {"signal": "traces", "received": end, "body": {"resourceSpans": [
        {"resource": _res(), "scopeSpans": [{"scope": {"name": "com.anthropic.claude_code"}, "spans": spans}]}]}}


def _log(sid, agent_id, ts, cost, in_tok, out_tok):
    a = {"event.name": "api_request", "session.id": sid, "agent_id": agent_id, "model": "claude-opus-5-5",
         "cost_usd": cost, "input_tokens": in_tok, "output_tokens": out_tok, "duration_ms": 1234.0,
         "prompt": "SECRET PROMPT TEXT SHOULD NEVER BE STORED"}
    return {"signal": "logs", "received": ts, "body": {"resourceLogs": [{"resource": _res(), "scopeLogs": [
        {"scope": {"name": "com.anthropic.claude_code.events"}, "logRecords": [
            {"timeUnixNano": _ns(ts), "body": {"stringValue": "claude_code.api_request"}, "attributes": _kv(a)}]}]}]}}


def _metric(sid, ts, cost):
    # raw collector-file-exporter shape (no {"signal","body"} wrapper), to test both formats
    return {"resourceMetrics": [{"resource": _res(), "scopeMetrics": [{"scope": {"name": "com.anthropic.claude_code"},
            "metrics": [{"name": "claude_code.cost.usage", "unit": "USD", "sum": {"aggregationTemporality": 1, "dataPoints": [
                {"timeUnixNano": _ns(ts), "startTimeUnixNano": _ns(ts - 60), "asDouble": cost,
                 "attributes": _kv({"session.id": sid, "model": "claude-sonnet-5-5"})}]}}]}]}]}


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "recorded")
    e = main(out)
    print(json.dumps({k: e[k] for k in ("tasks", "done", "stuck", "active", "guardrail_total", "cost_usd", "events")}))
