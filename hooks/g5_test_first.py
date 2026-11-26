"""G5: the DONE_WHEN test must run and fail before the first Worker dispatch of a task. PreToolUse on Agent.

Records the dispatch for G3 and G4. A later dispatch of the same task may not change the command or the files."""
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
    return common.Decision(False, "G5", "G5: " + reason, {"tool_name": "Agent"})


def _allow(reason):
    return common.Decision(True, "G5", reason, {"log": True, "tool_name": "Agent"})


def main(event):
    ti = event.get("tool_input") or {}
    if event.get("tool_name") != "Agent" or ti.get("subagent_type") != "worker":
        return None
    cwd = event.get("cwd") or ""
    root = dw.git_root(cwd)
    prompt = ti.get("prompt") or ""
    try:
        d = dw.parse(prompt, root or cwd, ti.get("description") or "")
    except ValueError as e:
        return _deny("dispatch needs a task id [Tn] and DONE_WHEN_CMD (or TASK_KIND: write-test): %s" % e)
    sid = event.get("session_id") or "nosession"
    prior = dw.read_record(sid, d.task)
    locked = prior if prior and prior.get("kind") == "test" else None
    if locked and (d.kind != "test" or d.argv != locked.get("argv") or d.files != locked.get("files")):
        return _deny("DONE_WHEN for %s changed after the first dispatch (locked)" % d.task)
    if d.kind == "write-test":
        dw.write_record(sid, d, "", dw.now_iso(), root or cwd)
        return _allow("%s: write-test dispatch, no test-first run" % d.task)
    if root is None:
        return _deny("no git root found from %s" % cwd)
    cmd = " ".join(d.argv)
    if locked:  # re-dispatch after guidance: same test, new run window
        dw.write_record(sid, d, cmd, dw.now_iso(), root)
        return _allow("%s: re-dispatch with the locked DONE_WHEN" % d.task)
    res = dw.run(d, root)
    if res.status == "passed":
        return _deny("%s DONE_WHEN already passes; the test does not check the new behaviour: %s" % (d.task, res.tail))
    if res.status != "failed":
        return _deny("DONE_WHEN for %s did not run as a failing test (%s): %s" % (d.task, res.status, res.tail))
    dw.write_record(sid, d, cmd, dw.now_iso(), root)
    return _allow("%s: DONE_WHEN fails before dispatch (%d failed)" % (d.task, res.failed))


common.run_hook(main, guardrail="G5", rule_version="g5-v1")
