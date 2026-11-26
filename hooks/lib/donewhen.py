"""The DONE_WHEN contract shared by G3, G4 and G5: parse a dispatch, allowlist its test command, run it
without a shell, classify the run, and keep one record per task.

Nothing here runs a command that validate() did not accept.
"""
import os
import re
import shlex
from dataclasses import dataclass
from typing import List, Optional

TASK_ID = re.compile(r"\s*\[(T\d+)\]")
META = ";&|<>$`()\n"
FLAGS = {"pytest": {"-q", "-v", "-x"}, "unittest": {"-v", "-f"}}
VALUE_FLAGS = {"pytest": {"-k", "-m", "--maxfail"}, "unittest": {"-k"}}
EQ_FLAGS = {"pytest": re.compile(r"--tb=(short|line|no|long)|--maxfail=\d+"), "unittest": re.compile(r"(?!)")}


@dataclass
class Dispatch:
    task: str
    kind: str          # "test" or "write-test"
    argv: List[str]
    files: List[str]   # real paths


def _lines(prompt, key):
    return re.findall(r"^[ \t]*%s:[ \t]*(.*?)[ \t]*$" % key, prompt, re.M)


def parse(prompt: str, cwd: str, description: str = "") -> Dispatch:
    m = TASK_ID.match(description or "") or TASK_ID.match(prompt.split("\n", 1)[0])
    if not m:
        raise ValueError("no task id [Tn] at the start of the Agent description")
    cmds = _lines(prompt, "DONE_WHEN_CMD")
    write = "write-test" in _lines(prompt, "TASK_KIND")
    if len(cmds) + write != 1:
        raise ValueError("need exactly one DONE_WHEN_CMD line, or TASK_KIND: write-test instead")
    files = []
    for line in _lines(prompt, "DONE_WHEN_FILES"):
        for tok in line.split(","):
            tok = tok.strip().strip("`'\"")
            if tok:
                files.append(os.path.realpath(os.path.join(cwd, tok)))
    argv = []
    if cmds:
        bad = sorted(set(cmds[0]) & set(META))
        if bad:
            raise ValueError("shell metacharacter %r in DONE_WHEN_CMD" % "".join(bad))
        argv = shlex.split(cmds[0])
        if not argv:
            raise ValueError("DONE_WHEN_CMD is empty")
    return Dispatch(m.group(1), "write-test" if write else "test", argv, sorted(set(files)))


def _runner(argv):
    """(runner, remaining args) for the three allowed shapes, else (None, [])."""
    if argv[:1] == ["pytest"]:
        return "pytest", argv[1:]
    if argv[:2] == ["python3", "-m"] and argv[2:3] and argv[2] in ("pytest", "unittest"):
        return argv[2], argv[3:]
    return None, []


def _inside(path, root):
    return os.path.commonpath([path, root]) == root


def validate(d: Dispatch, root: str) -> Optional[str]:
    """None when the command is allowed, else the reason."""
    if d.kind == "write-test":
        return None
    if any(set(a) & set(META) for a in d.argv):
        return "shell metacharacter in DONE_WHEN_CMD"
    runner, rest = _runner(d.argv)
    if runner is None:
        return "only pytest, python3 -m pytest and python3 -m unittest are allowed"
    root = os.path.realpath(root)
    positionals = 0
    it = iter(rest)
    for tok in it:
        if tok in FLAGS[runner] or EQ_FLAGS[runner].fullmatch(tok):
            continue
        if tok in VALUE_FLAGS[runner]:
            if next(it, None) is None:
                return "option %s needs a value" % tok
            continue
        if tok.startswith(("-", "@")):
            return "option %s is not allowed" % tok
        path = tok.split("::", 1)[0] if runner == "pytest" else tok
        real = os.path.realpath(os.path.join(root, path))
        if not real.endswith(".py") or not os.path.isfile(real):
            return "%s is not an existing .py test file" % tok
        if real not in d.files:
            return "%s is not listed in DONE_WHEN_FILES" % tok
        if not _inside(real, root):
            return "%s resolves outside the git root %s" % (tok, root)
        positionals += 1
    if not positionals:
        return "name at least one test file (no discovery runs)"
    return None


def git_root(cwd: str) -> Optional[str]:
    """First ancestor of cwd (inclusive) holding a .git entry (a file in worktrees)."""
    if not cwd or not os.path.isabs(cwd):
        return None
    p = os.path.realpath(cwd)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
