"""G2: the Orchestrator may not write files. PreToolUse hook; blocking (exit 2).

Bash is not parsed; Bash writes are a documented residual (sandbox closes them).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib import common  # noqa: E402
except BaseException as _exc:  # fail closed when lib/ is missing (a copied script)
    if os.environ.get("AGENT_WORKFLOW") != "1":
        sys.exit(0)
    print("%s: cannot load hooks/lib (%s); denying" % (__doc__.split(":")[0], _exc), file=sys.stderr)
    sys.exit(2)

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}


def main(event):
    tool = event.get("tool_name")
    if tool in WRITE_TOOLS and common.role(event) == "orchestrator":
        ti = event.get("tool_input") or {}
        p = ti.get("file_path") or ti.get("notebook_path")
        rp = common.real(p, event.get("cwd") or "") if p else None
        return common.Decision(False, "G2", "G2: Orchestrator may not write files; dispatch the worker",
                               {"tool_name": tool, "path": rp})
    return None


common.run_hook(main, guardrail="G2", rule_version="g2-v1")
