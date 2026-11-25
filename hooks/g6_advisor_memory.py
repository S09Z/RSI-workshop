"""G6: the Advisor may write only inside its memory folder. PreToolUse hook; blocking (exit 2).

Allowed root: realpath of $AGENT_ADVISOR_MEMORY_DIR, default ~/.claude/agent-memory/advisor.
Bash is analysed lexically (lib/shellscan.py); a write whose target cannot be known is denied.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib import common, shellscan  # noqa: E402
except BaseException as _exc:  # fail closed when lib/ is missing (a copied script)
    if os.environ.get("AGENT_WORKFLOW") != "1":
        sys.exit(0)
    print("%s: cannot load hooks/lib (%s); denying" % (__doc__.split(":")[0], _exc), file=sys.stderr)
    sys.exit(2)

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}


def memory_root():
    return os.path.realpath(os.environ.get("AGENT_ADVISOR_MEMORY_DIR")
                            or os.path.expanduser("~/.claude/agent-memory/advisor"))


def main(event):
    if common.role(event) != "advisor":
        return None
    tool = event.get("tool_name")
    cwd = event.get("cwd") or ""
    ti = event.get("tool_input") or {}
    root = memory_root()
    if tool in WRITE_TOOLS:
        p = ti.get("file_path") or ti.get("notebook_path")
        if not isinstance(p, str) or not p:
            raise ValueError("%s without a file path" % tool)
        rp = common.real(p, cwd)
        if shellscan.inside(rp, root):
            return None
        return common.Decision(False, "G6", "G6: Advisor may write only inside %s; blocked %s" % (root, rp),
                               {"tool_name": tool, "path": rp})
    if tool == "Bash":
        cmd = ti.get("command")
        if not isinstance(cmd, str):
            raise ValueError("Bash without a command string")
        s = shellscan.scan(cmd, cwd)
        if s.unsafe:
            return common.Decision(False, "G6", "G6: Bash write target cannot be verified (%s)" % s.why,
                                   {"tool_name": tool, "path": None})
        for t in s.targets:
            if not shellscan.inside(t, root):
                return common.Decision(False, "G6", "G6: Advisor may write only inside %s; blocked %s" % (root, t),
                                       {"tool_name": tool, "path": t})
    return None


common.run_hook(main, guardrail="G6", rule_version="g6-v1")
