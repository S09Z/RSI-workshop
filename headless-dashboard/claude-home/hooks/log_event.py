#!/usr/bin/env python3
"""Claude Code hook: append one compact event to ~/.claude/agent-dashboard/events.jsonl (v2).

* No-op unless AGENT_WORKFLOW=1 (set by `orch` / `orch-headless`).
* Never blocks or fails a session: every error is swallowed and the script exits 0.
  Registered with "async": true, so Claude Code does not wait for it.
* Content-free by default: report text is parsed here into structured fields
  (STATUS, ATTEMPTS, CONFIDENCE, FROM MEMORY, guardrail markers) and then dropped.
  Set AGENT_DASHBOARD_LOG_CONTENT=1 to also keep redacted result_text (max 4000 chars).
  The text that is always kept (task descriptions, todo text, guardrail reasons) is
  redacted here too, with the built-in patterns plus privacy.redact from config.yaml.
  If the agentdash package cannot be imported, result_text is dropped even with
  LOG_CONTENT=1, because only a minimal fallback redaction is available.
* Same field names as v1, so v1 consumers keep working; new fields: v, report, guardrails,
  error_class.

Guardrail hooks record a hit with:
    python3 ~/.claude/hooks/log_event.py --guardrail G3 --reason "WORKS without a passing run"
(the hook's own stdin JSON is read when present, for session_id / tool_use_id / agent_id).
"""
import json
import os
import re
import sys
import time

MAX_TEXT = 4000


def _dash_dir():
    return os.environ.get("AGENT_DASHBOARD_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "agent-dashboard")


def _parser():
    """Use the shared parser from the installed agentdash package; tiny fallback otherwise."""
    try:
        sys.path.insert(0, _dash_dir())
        from agentdash import parse  # type: ignore

        class _Full:
            full = True
            report = staticmethod(parse.report)
            guardrails = staticmethod(parse.guardrails)
            pats = None

            @staticmethod
            def redact(text, patterns=None):
                if _Full.pats is None:
                    extra = []
                    try:
                        from agentdash import config  # type: ignore
                        extra = config.load(os.path.join(_dash_dir(), "config.yaml"))["privacy"].get("redact") or []
                    except Exception:
                        extra = []
                    _Full.pats = parse.compile_redactions(extra)
                return parse.redact(text, patterns or _Full.pats)
        return _Full
    except Exception:
        class _P:
            full = False  # minimal redaction only: callers must not keep long free text
            REDACT = [re.compile(p) for p in (
                r"sk-[A-Za-z0-9_\-]{20,}", r"gh[pousr]_[A-Za-z0-9]{20,}", r"AKIA[0-9A-Z]{16}",
                r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/\-]{8,}=*",
                r"(?i)[\w.-]*(?:passw(?:or)?d|pwd|secret|token(?!s)|api[_-]?key|access[_-]?key)[\w-]*"
                r"[\"']?\s*[:=]\s*[\"']?[^\s\"',;}]+",
                r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")]
            STATUS = re.compile(r"STATUS:\s*(WORKS|DOES_NOT_WORK|BLOCKED)", re.I)

            @staticmethod
            def report(text, agent=None):
                m = _P.STATUS.search(text or "")
                return {"status": m.group(1).upper() if m else "NO_REPORT"} if agent == "worker" else {}

            @staticmethod
            def guardrails(text):
                return sorted(set(g.upper() for g in re.findall(r"GUARDRAIL[ _:-]*(G\d{1,2})\b", text or "", re.I)))

            @staticmethod
            def redact(text, patterns=None):
                for rx in _P.REDACT:
                    text = rx.sub("[REDACTED]", text or "")
                return text
        return _P


def _text(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "\n".join(_text(x) for x in v)
    if isinstance(v, dict):
        for k in ("text", "content", "result", "output", "last_assistant_message"):
            if k in v:
                return _text(v[k])
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _num(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return v
    return None


def _append(ev):
    d = _dash_dir()
    os.makedirs(d, exist_ok=True)
    line = (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(os.path.join(d, "events.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)  # one write() per line on an O_APPEND fd
    finally:
        os.close(fd)


def build(data, keep_content, P):
    ev = data.get("hook_event_name", "unknown")
    tool = data.get("tool_name")
    cwd = data.get("cwd") or os.getcwd()
    out = {"v": 2, "ts": time.time(), "event": ev, "project": os.path.basename(cwd.rstrip("/")) or cwd, "cwd": cwd,
           "session_id": data.get("session_id"), "agent_id": data.get("agent_id"), "agent_type": data.get("agent_type")}
    if tool:
        out["tool"] = tool
        out["tool_use_id"] = data.get("tool_use_id")
    ti = data.get("tool_input") or {}
    if tool in ("Task", "Agent"):
        out["subagent_type"] = ti.get("subagent_type")
        out["description"] = P.redact((ti.get("description") or "")[:400])[:200]
        if ev in ("PostToolUse", "PostToolUseFailure"):
            resp = data.get("tool_response")
            text = _text(resp) or _text(data.get("error"))
            agent = (ti.get("subagent_type") or "").lower()
            out["report"] = P.report(text, agent)
            out["duration_ms"] = _num(resp, "totalDurationMs", "duration_ms") or data.get("duration_ms")
            out["tokens"] = _num(resp, "totalTokens", "total_tokens")
            out["tool_uses"] = _num(resp, "totalToolUseCount")
            if keep_content and getattr(P, "full", False):
                out["result_text"] = P.redact(text)[-MAX_TEXT:]
            elif keep_content:
                out["result_text_dropped"] = "parser_unavailable"
    elif tool == "TodoWrite":
        out["todos"] = [{"content": P.redact(str(t.get("content") or "")[:400])[:200], "status": t.get("status")}
                        for t in (ti.get("todos") or []) if isinstance(t, dict)]
    elif tool in ("TaskCreate", "TaskUpdate"):
        out["task"] = {k: ti.get(k) for k in ("taskId", "subject", "status") if k in ti}
        resp = data.get("tool_response")
        if isinstance(resp, dict):
            tid = resp.get("taskId") or resp.get("id") or (resp.get("task") or {}).get("id")
            if tid:
                out["task"]["taskId"] = str(tid)
    if ev == "PostToolUseFailure":
        err = _text(data.get("error") or data.get("tool_response"))
        g = P.guardrails(err)
        if g:
            out["guardrails"] = g
        out["error_class"] = "interrupt" if data.get("is_interrupt") else ("guardrail" if g else "tool_error")
    if ev in ("SubagentStop", "Stop"):
        text = _text(data.get("last_assistant_message"))
        g = P.guardrails(text)
        if g:
            out["guardrails"] = g
        if keep_content and text and getattr(P, "full", False):
            out["result_text"] = P.redact(text)[-MAX_TEXT:]
        elif keep_content and text:
            out["result_text_dropped"] = "parser_unavailable"
    return out


def guardrail_event(argv, data, P=None):
    g = argv[argv.index("--guardrail") + 1].upper()
    reason = argv[argv.index("--reason") + 1] if "--reason" in argv else ""
    reason = (P or _parser()).redact(reason[:600])
    cwd = data.get("cwd") or os.getcwd()
    return {"v": 2, "ts": time.time(), "event": "guardrail_hit", "guardrail": g, "reason": reason[:300],
            "project": os.path.basename(cwd.rstrip("/")) or cwd, "cwd": cwd, "session_id": data.get("session_id"),
            "agent_id": data.get("agent_id"), "agent_type": data.get("agent_type"),
            "tool": data.get("tool_name"), "tool_use_id": data.get("tool_use_id"),
            "task_id": os.environ.get("AGENT_TASK_ID")}


def main(argv):
    if os.environ.get("AGENT_WORKFLOW") != "1":
        return
    data = {}
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
    if "--guardrail" in argv:
        _append(guardrail_event(argv, data, _parser()))
        return
    keep = os.environ.get("AGENT_DASHBOARD_LOG_CONTENT") == "1"
    _append(build(data, keep, _parser()))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception:
        pass
    sys.exit(0)
