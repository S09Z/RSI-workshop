"""G4: a Worker's WORKS report must carry ran_at from this run of the task. SubagentStop.

Checks format and time window only; the value is self-reported. G3 re-runs the test."""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib import common, donewhen as dw  # noqa: E402
except BaseException as _exc:  # fail closed when lib/ is missing (a copied script)
    if os.environ.get("AGENT_WORKFLOW") != "1":
        sys.exit(0)
    print("%s: cannot load hooks/lib (%s); denying" % (__doc__.split(":")[0], _exc), file=sys.stderr)
    sys.exit(2)

SKEW = timedelta(seconds=5)


def _deny(reason):
    return common.Decision(False, "G4", "G4: " + reason)


def _allow(reason):
    return common.Decision(True, "G4", reason, {"log": True})


def _utc(value):
    try:
        t = datetime.fromisoformat(re.sub(r"Z$", "+00:00", value))
    except ValueError:
        return None
    return t if t.utcoffset() == timedelta(0) else None


def main(event):
    if event.get("agent_type") != "worker":
        return None
    if event.get("stop_hook_active"):
        return _allow("retry_cap")
    report = dw.works_report(dw.final_message(event))
    if report is None:
        return None
    sid = event.get("session_id") or "nosession"
    rec = dw.record_for_report(sid, report)
    if rec is None and not dw.task_id(report):
        rec = dw.newest_open(sid, include_stopped=True)  # G3 runs in parallel and may have closed it
    if rec is None:
        return _deny("no dispatch record; cannot check ran_at")
    section = report.split("VERIFICATION:", 1)[1] if "VERIFICATION:" in report else ""
    values = re.findall(r"^[ \t]*-?[ \t]*ran_at:[ \t]*(.*?)[ \t]*$", section, re.M)
    if not values:
        return _deny("VERIFICATION has no ran_at")
    start = _utc(rec["dispatched_at"])
    for value in values:
        t = _utc(value.strip("`'\""))
        if t is None:
            return _deny("ran_at %r is not an ISO-8601 time with a UTC timezone (Z or +00:00)" % value[:60])
        if t < start:
            return _deny("ran_at is before this task was dispatched (%s)" % rec["dispatched_at"])
        if t > datetime.now(timezone.utc) + SKEW:
            return _deny("ran_at is in the future")
    return _allow("%s: ran_at inside the run window" % rec["task"])


common.run_hook(main, guardrail="G4", rule_version="g4-v1")
