"""G7: the Worker may write only inside the git root. PreToolUse hook; blocking (exit 2).

Git root: the first ancestor of the event cwd (inclusive) holding a .git file or directory (worktrees use a file).
No git root found: every write is denied. Bash is analysed lexically (lib/shellscan.py).
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


def git_root(cwd):
    if not cwd:
        return None
    p = os.path.realpath(cwd)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def _deny(reason, tool, path):
    return common.Decision(False, "G7", reason, {"tool_name": tool, "path": path})


def main(event):
    if common.role(event) != "worker":
        return None
    tool = event.get("tool_name")
    cwd = event.get("cwd") or ""
    ti = event.get("tool_input") or {}
    root = git_root(cwd)
    if tool in WRITE_TOOLS:
        p = ti.get("file_path") or ti.get("notebook_path")
        if not isinstance(p, str) or not p:
            raise ValueError("%s without a file path" % tool)
        rp = common.real(p, cwd)
        if root is None:
            return _deny("G7: no git root found from %s; denying writes" % cwd, tool, rp)
        if shellscan.inside(rp, root):
            return None
        return _deny("G7: Worker may write only inside the git root %s; blocked %s" % (root, rp), tool, rp)
    if tool == "Bash":
        cmd = ti.get("command")
        if not isinstance(cmd, str):
            raise ValueError("Bash without a command string")
        s = shellscan.scan(cmd, cwd)
        if s.unsafe:
            return _deny("G7: Bash write target cannot be verified (%s)" % s.why, tool, None)
        for t in s.targets:
            if root is None:
                return _deny("G7: no git root found from %s; denying writes" % cwd, tool, t)
            if not shellscan.inside(t, root):
                return _deny("G7: Worker may write only inside the git root %s; blocked %s" % (root, t), tool, t)
    return None


common.run_hook(main, guardrail="G7", rule_version="g7-v1")
