"""The DONE_WHEN contract shared by G3, G4 and G5: parse a dispatch, allowlist its test command, run it
without a shell, classify the run, and keep one record per task.

Nothing here runs a command that validate() did not accept.
"""
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from . import common

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


ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV")
DEFAULT_TIMEOUT = 120.0
TAIL = 800


@dataclass
class RunResult:
    status: str                 # "passed" | "failed" | "error"
    returncode: Optional[int]
    passed: int
    failed: int
    tail: str


def timeout_seconds() -> float:
    try:
        v = float(os.environ.get("AGENT_DONEWHEN_TIMEOUT", ""))
    except ValueError:
        return DEFAULT_TIMEOUT
    return v if math.isfinite(v) and v > 0 else DEFAULT_TIMEOUT


def _counts(runner, out):
    """(passed, failed) from the runner's LAST summary; (0, 0) when there is none."""
    if runner == "pytest":
        lines = [x for x in out.splitlines() if re.search(r"\b\d+ (passed|failed|errors?|skipped)\b.* in [\d.]+s", x)]
        if not lines:
            return 0, 0
        n = dict((k.rstrip("s") if k.startswith("error") else k, int(v))
                 for v, k in re.findall(r"(\d+) (passed|failed|errors?)\b", lines[-1]))
        return n.get("passed", 0), n.get("failed", 0) + n.get("error", 0)
    found = list(re.finditer(r"^Ran (\d+) tests? in .*\n+^(OK|FAILED)(?: \((.*)\))?[ \t]*$", out, re.M))
    if not found:
        return 0, 0
    ran, verdict, detail = int(found[-1].group(1)), found[-1].group(2), found[-1].group(3) or ""
    n = {k.strip(): int(v) for k, v in re.findall(r"([a-z ]+)=(\d+)", detail)}
    failed = n.get("failures", 0) + n.get("errors", 0) + n.get("unexpected successes", 0)
    if verdict == "FAILED":
        failed = max(failed, 1)
    return max(ran - failed - n.get("skipped", 0) - n.get("expected failures", 0), 0), failed


def classify(runner: str, returncode: Optional[int], out: str):
    """(status, passed, failed). Anything that is not a clear pass or a clear test failure is an error."""
    passed, failed = _counts(runner, out)
    if returncode == 0 and passed >= 1 and failed == 0:
        return "passed", passed, failed
    if returncode == 1 and failed >= 1:
        return "failed", passed, failed
    return "error", passed, failed


def _kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run(d: Dispatch, root: str, timeout: Optional[float] = None) -> RunResult:
    """Run an allowlisted command in root. Never raises for a bad command; returns status "error"."""
    why = "write-test dispatch has no command" if d.kind != "test" else validate(d, root)
    if why:
        return RunResult("error", None, 0, 0, why[-TAIL:])
    runner = _runner(d.argv)[0]
    argv = list(d.argv)
    if runner == "pytest":
        at = 1 if argv[0] == "pytest" else 3
        argv[at:at] = ["-p", "no:cacheprovider", "-o", "addopts="]
    env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if os.path.isabs(p))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    exe = shutil.which(argv[0], path=env["PATH"]) if env["PATH"] else None
    if not exe:
        return RunResult("error", 127, 0, 0, "%s not found on PATH" % argv[0])
    # Output goes to a file, not a pipe: a surviving grandchild must not be able to hang the hook
    # (a hook the harness times out does not block).
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen([exe] + argv[1:], cwd=root, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout_seconds() if timeout is None else timeout)
        except subprocess.TimeoutExpired:
            code = None
        finally:
            _kill_group(proc)
        if code is None:
            proc.wait(timeout=5)
            return RunResult("error", None, 0, 0, "timeout")
        size = log.seek(0, os.SEEK_END)
        log.seek(max(size - 200000, 0))
        out = log.read().decode("utf-8", "replace")
    status, passed, failed = classify(runner, code, out)
    return RunResult(status, code, passed, failed, out[-TAIL:])


TTL = 24 * 3600


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(part):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(part))


def record_path(session_id: str, task: str) -> str:
    return os.path.join(common.state_dir(), "donewhen", "%s-%s.json" % (_safe(session_id), _safe(task)))


def _save(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(rec, f)
    os.replace(tmp, path)


def _load(path):
    try:
        with open(path) as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and "task" in rec and "session" in rec else None


def write_record(session_id: str, d: Dispatch, cmd_text: str, dispatched_at: str, root: str) -> None:
    path = record_path(session_id, d.task)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    now = time.time()
    for name in os.listdir(folder):
        try:
            old = os.path.join(folder, name)
            if now - os.lstat(old).st_mtime > TTL:
                os.remove(old)
        except FileNotFoundError:
            pass  # another hook pruned it first
    _save(path, {"session": str(session_id), "task": d.task, "kind": d.kind, "argv": d.argv, "files": d.files,
                 "cmd_text": cmd_text, "root": root, "dispatched_at": dispatched_at, "written_at": now,
                 "stopped": False})


def read_record(session_id: str, task: str) -> Optional[dict]:
    rec = _load(record_path(session_id, task))
    return rec if rec and rec["session"] == str(session_id) else None


def newest_open(session_id: str) -> Optional[dict]:
    folder = os.path.join(common.state_dir(), "donewhen")
    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return None
    recs = [_load(os.path.join(folder, n)) for n in names if n.endswith(".json")]
    recs = [r for r in recs if r and r["session"] == str(session_id) and not r.get("stopped")]
    return max(recs, key=lambda r: r.get("written_at", 0)) if recs else None


def mark_stopped(session_id: str, task: str) -> None:
    rec = read_record(session_id, task)
    if rec:
        rec["stopped"] = True
        _save(record_path(session_id, task), rec)


# --- SubagentStop side (G3, G4) ---

WORKS = re.compile(r"^[ \t]*STATUS:[ \t]*WORKS\b(?![ \t]*\|)", re.M)


def final_message(event: dict) -> str:
    """The subagent's last message (same sources as G1). Raises when the transcript cannot be read."""
    msg = event.get("last_assistant_message")
    if isinstance(msg, str) and msg.strip():
        return msg
    path = event.get("agent_transcript_path")
    last = ""
    if path:
        with open(path) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                m = rec.get("message") or {}
                if rec.get("type") == "assistant" or m.get("role") == "assistant":
                    c = m.get("content")
                    text = c if isinstance(c, str) else "".join(
                        b.get("text", "") for b in (c or []) if isinstance(b, dict))
                    if text.strip():
                        last = text
    return last


def works_report(text: str) -> Optional[str]:
    """The text from the report that claims WORKS (any STATUS: WORKS line counts), else None."""
    m = WORKS.search(text)
    if not m:
        return None
    start = max(text.rfind("=== WORKER REPORT ===", 0, m.start()), 0)
    end = text.find("=== END REPORT ===", m.start())
    return text[start:end if end >= 0 else len(text)]


def record_for_report(session_id: str, report: str) -> Optional[dict]:
    """By the [Tn] on the report's TASK: line; without one, the newest record not yet verified."""
    m = re.search(r"^[ \t]*TASK:[^\n]*?\[(T\d+)\]", report, re.M)
    return read_record(session_id, m.group(1)) if m else newest_open(session_id)
