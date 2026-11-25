"""G8 (part 2): the Worker may not edit the test files named in DONE_WHEN. PreToolUse; blocking."""
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import common  # noqa: E402

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
FALLBACK_RE = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*\.py$|_test\.(py|go)$|\.(test|spec)\.[a-z]+$|(^|/)conftest\.py$")
READONLY = {"cat", "grep", "head", "tail", "ls", "diff", "wc", "pytest"}
GIT_READ = {"diff", "status", "log", "show"}
DANGEROUS = re.compile(r">|(^|\s)(tee|truncate|mv|cp|rm|dd)(\s|$)|sed\s+(-\w*i|--in-place)|perl\s+-\w*i|"
                       r"git\s+(checkout|restore|stash|apply)|(python3?|node)\s+-[ce]\b")


def load_state(session_id):
    sid = re.sub(r"[^A-Za-z0-9_-]", "_", str(session_id or "nosession"))
    d = os.path.join(common.state_dir(), "done_when")
    files, unknown, found = set(), False, False
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.startswith(sid + "-"):
                with open(os.path.join(d, f)) as fh:
                    e = json.load(fh)
                found = True
                files |= set(e.get("files", []))
                unknown = unknown or bool(e.get("unknown"))
    return files, (unknown or not found)


def covered(path, files):
    for f in files:
        if path == f or (os.path.isdir(f) and path.startswith(f.rstrip("/") + "/")):
            return True
    return False


def allowlisted(seg):
    try:
        w = shlex.split(seg)
    except ValueError:
        return False
    if not w:
        return True
    if w[0] in READONLY:
        return True
    if w[0] in ("python", "python3") and w[1:3] in (["-m", "pytest"], ["-m", "unittest"]):
        return True
    return w[0] == "git" and len(w) > 1 and w[1] in GIT_READ


def mentions(seg, files, cwd):
    for f in files:
        rel = os.path.relpath(f, cwd) if cwd else f
        if f in seg or rel in seg or os.path.basename(f.rstrip("/")) in seg:
            return True
    return False


def bash_denied(cmd, files, unknown, cwd):
    for seg in re.split(r";|&&|\|\||\||\n", cmd):
        if mentions(seg, files, cwd) and (DANGEROUS.search(seg) or not allowlisted(seg)):
            return "G8: Bash command would change a DONE_WHEN test file"
        if unknown and DANGEROUS.search(seg) and FALLBACK_RE.search(seg.replace("\\", "/")):
            return "G8 fallback_no_done_when: Bash command would change a test-like path"
    return None


def main(event):
    if common.role(event) != "worker":
        return None
    tool, ti, cwd = event.get("tool_name"), event.get("tool_input") or {}, event.get("cwd") or ""
    files, unknown = load_state(event.get("session_id"))
    known = {f for f in files}
    if tool in WRITE_TOOLS:
        p = ti.get("file_path") or ti.get("notebook_path")
        if not p:
            raise ValueError("write tool without a path")
        rp = common.real(p, cwd)
        if covered(rp, known):
            return common.Decision(False, "G8", "G8: Worker may not edit the DONE_WHEN test " + rp, {"tool_name": tool, "path": rp})
        if unknown and FALLBACK_RE.search(rp):
            return common.Decision(False, "G8", "G8 fallback_no_done_when: no DONE_WHEN files known; test-like path " + rp,
                                   {"tool_name": tool, "path": rp})
    elif tool == "Bash":
        cmd = ti.get("command")
        if not isinstance(cmd, str):
            raise ValueError("Bash without command")
        why = bash_denied(cmd, known, unknown, cwd)
        if why:
            return common.Decision(False, "G8", why, {"tool_name": "Bash"})
    return None


common.run_hook(main, guardrail="G8", rule_version="g8-v1")
