#!/usr/bin/env python3
"""Write a realistic sample events.jsonl so you can try the dashboard
before running real agents.

    python3 dashboard/demo.py            # writes dashboard/demo-events.jsonl
    python3 dashboard/server.py --log dashboard/demo-events.jsonl
"""
import json
import os
import random
import time

random.seed(7)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "demo-events.jsonl")
SID = "demo-session"

TASKS = [
    ("T1", "Add input validation to /api/signup", ["WORKS"]),
    ("T2", "Fix flaky test test_order_totals", ["DOES_NOT_WORK", "advisor", "WORKS"]),
    ("T3", "Migrate config loader to pydantic v2", ["WORKS"]),
    ("T4", "Fix race condition in cache invalidation", ["DOES_NOT_WORK", "advisor", "DOES_NOT_WORK", "advisor", "WORKS"]),
    ("T5", "Add pagination to /api/orders", ["WORKS"]),
    ("T6", "Resolve memory leak in websocket handler", ["DOES_NOT_WORK", "advisor", "DOES_NOT_WORK", "advisor", "DOES_NOT_WORK"]),
    ("T7", "Write integration tests for checkout", ["DOES_NOT_WORK", "advisor", "RUNNING"]),
    ("T8", "Update README for new env vars", []),
]

events = []
t = time.time() - 3 * 3600
n = 0


def add(**kw):
    events.append({"session_id": SID, "project": "demo-app", **kw})


add(ts=t, event="SessionStart")
todos = [{"content": f"[{tid}] {title}", "status": "pending"} for tid, title, _ in TASKS]
add(ts=t + 5, event="PostToolUse", tool="TodoWrite", todos=todos)
t += 20

for i, (tid, title, steps) in enumerate(TASKS):
    for step in steps:
        n += 1
        agent = "advisor" if step == "advisor" else "worker"
        dur = random.uniform(90, 260) if agent == "advisor" else random.uniform(150, 900)
        uid = f"toolu_{n:04d}"
        desc = f"[{tid}] {title}" if agent == "worker" else f"[{tid}] Diagnose: {title}"
        add(ts=t, event="PreToolUse", tool="Agent", tool_use_id=uid, subagent_type=agent, description=desc)
        for k in range(random.randint(4, 18)):
            add(ts=t + k * dur / 20, event="PostToolUse", tool=random.choice(["Read", "Edit", "Bash", "Grep"]),
                agent_type=agent, agent_id=uid)
        if random.random() < 0.15:
            add(ts=t + dur / 2, event="PostToolUseFailure", tool="Bash", agent_type=agent, agent_id=uid)
        if step == "RUNNING":  # leave this dispatch open, started 4 minutes ago
            for e in events:
                if e.get("tool_use_id") == uid:
                    e["ts"] = time.time() - 240
            break
        if agent == "advisor":
            text = f"=== ADVISOR GUIDANCE ===\nCONFIDENCE: {random.choice(['high', 'medium', 'low'])}\n"
        else:
            text = f"=== WORKER REPORT ===\nSTATUS: {step}\nATTEMPTS: {random.randint(1, 3)}/3\n"
        tok = int(dur * random.uniform(40, 90))
        add(ts=t + dur, event="PostToolUse", tool="Agent", tool_use_id=uid, subagent_type=agent,
            description=desc, result_text=text, duration_ms=int(dur * 1000), tokens=tok)
        t += dur + random.uniform(5, 30)
    status = "completed" if steps and steps[-1] == "WORKS" else ("in_progress" if steps else "pending")
    todos[i]["status"] = status
    add(ts=t, event="PostToolUse", tool="TodoWrite", todos=[dict(x) for x in todos])
    for k in range(3):
        add(ts=t - k, event="PostToolUse", tool="Read")

add(ts=time.time() - 3600, event="run_result", prompt="Sprint 14 backlog", cost_usd=4.82,
    duration_ms=5_400_000, num_turns=61, is_error=False, session_id=SID)

events.sort(key=lambda e: e["ts"])
with open(OUT, "w", encoding="utf-8") as f:
    for e in events:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
print(f"wrote {len(events)} events -> {OUT}")
