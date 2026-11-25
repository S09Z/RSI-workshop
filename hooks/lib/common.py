"""Shared, fail-closed plumbing for the Harden hooks (G1, G2, G8).

Blocking hooks exit 2 to block (exit 1 does NOT block: hooks/tests/fixtures/PROBE.md, answer e).
Any error inside a blocking hook becomes a deny.
"""
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional


@dataclass
class Decision:
    allow: bool
    guardrail: str
    reason: str = ""
    fields: dict = field(default_factory=dict)


def events_path() -> str:
    base = os.environ.get("AGENT_DASHBOARD_DIR") or os.path.expanduser("~/.claude/agent-dashboard")
    return os.path.join(base, "events.jsonl")


def state_dir() -> str:
    return os.environ.get("AGENT_HOOK_STATE_DIR") or os.path.expanduser("~/.claude/agent-hook-state")


def log_event(guardrail, blocked, reason, rule_version, tool_name=None, path=None) -> None:
    rec = {
        "event": "guardrail_hit", "guardrail": guardrail, "blocked": bool(blocked),
        "case_id": os.environ.get("AGENT_HOOK_CASE_ID") or None,
        "rule_version": rule_version, "tool_name": tool_name, "path": path, "reason": reason,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    p = events_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(rec) + "\n")


def real(path: str, cwd: str) -> str:
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(cwd or "", path))


def role(event: dict) -> str:
    """worker / advisor / orchestrator / other. Main thread has no agent_id (PROBE.md a)."""
    at = event.get("agent_type")
    if event.get("agent_id") and at in ("worker", "advisor"):
        return at
    if at == "orchestrator" or not event.get("agent_id"):
        return "orchestrator"
    return "other"


def run_hook(main: Callable[[dict], Optional[Decision]], *, guardrail: str, rule_version: str,
             blocking: bool = True):
    if os.environ.get("AGENT_WORKFLOW") != "1":
        sys.exit(0)
    event = {}
    try:
        event = json.loads(sys.stdin.read())
        if not isinstance(event, dict):
            raise ValueError("stdin JSON is not an object")
        d = main(event)
    except SystemExit:
        raise
    except BaseException as exc:  # fail closed, including KeyboardInterrupt
        _best_effort_log(guardrail, blocking, "hook_error", rule_version,
                         event.get("tool_name") if isinstance(event, dict) else None)
        if blocking:
            print("%s: hook error (%s: %s); denying" % (guardrail, type(exc).__name__, exc), file=sys.stderr)
            sys.exit(2)
        sys.exit(0)
    if d is None:
        sys.exit(0)
    if d.allow:
        if d.fields.get("log"):
            _best_effort_log(d.guardrail, False, d.reason, rule_version, d.fields.get("tool_name"), d.fields.get("path"))
        sys.exit(0)
    # A deny must never depend on the log: an unwritable log would otherwise exit 1, which does not block.
    _best_effort_log(d.guardrail, True, d.reason, rule_version, d.fields.get("tool_name"), d.fields.get("path"))
    print(d.reason, file=sys.stderr)
    sys.exit(2)


def _best_effort_log(*args):
    try:
        log_event(*args)
    except BaseException:
        pass
