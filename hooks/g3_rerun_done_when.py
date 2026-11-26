"""G3: a Worker's WORKS report is accepted only if its DONE_WHEN test passes when re-run. SubagentStop.

G4 checks the report's ran_at; this hook is the authority on whether the test passes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib import common, donewhen as dw  # noqa: E402
except BaseException as _exc:  # fail closed when lib/ is missing (a copied script)
    if os.environ.get("AGENT_WORKFLOW") != "1":
        sys.exit(0)
    print("%s: cannot load hooks/lib (%s); denying" % (__doc__.split(":")[0], _exc), file=sys.stderr)
    sys.exit(2)


def _deny(reason):
    return common.Decision(False, "G3", "G3: " + reason)


def _allow(reason):
    return common.Decision(True, "G3", reason, {"log": True})


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
    if rec is None:
        return _deny("no DONE_WHEN record for this WORKS report; cannot verify it")
    if rec["kind"] == "write-test":
        dw.mark_stopped(sid, rec["task"])
        return _allow("%s: write-test dispatch, re-run skipped" % rec["task"])
    res = dw.run(dw.Dispatch(rec["task"], rec["kind"], rec["argv"], rec["files"]), rec["root"])
    if res.status != "passed":
        return _deny("WORKS for %s but DONE_WHEN re-run is %s: %s" % (rec["task"], res.status, res.tail))
    dw.mark_stopped(sid, rec["task"])
    return _allow("%s: verified, %d passed, exit %s" % (rec["task"], res.passed, res.returncode))


common.run_hook(main, guardrail="G3", rule_version="g3-v1")
