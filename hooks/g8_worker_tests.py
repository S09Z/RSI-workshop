"""G8 (part 2): the Worker may not edit the test files named in DONE_WHEN. PreToolUse; blocking.

Write/Edit checks compare file identity (case-folded path, samefile). Bash is analysed on shell tokens (quotes
removed, globs expanded, option values read), not on raw text. It is still lexical: scripts that build a path at
run time are a documented residual (needs the sandbox). The hook state and event log are protected too.
"""
import fnmatch
import glob
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib import common  # noqa: E402
except BaseException as _exc:  # fail closed when lib/ is missing (a copied script)
    if os.environ.get("AGENT_WORKFLOW") != "1":
        sys.exit(0)
    print("G8: cannot load hooks/lib (%s); denying" % _exc, file=sys.stderr)
    sys.exit(2)

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
FALLBACK_RE = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*\.py$|_test\.(py|go)$|\.(test|spec)\.[a-z]+$|(^|/)conftest\.py$", re.I)
TEXT_RE = re.compile(r"(^|[/\s'\"=(])(tests?|__tests__)/|test_[^/\s'\"]*\.py|_test\.(py|go)|\.(test|spec)\.[a-z]+|conftest\.py", re.I)
READONLY = {"cat", "grep", "head", "tail", "ls", "diff", "wc", "pytest"}
GIT_READ = {"diff", "status", "log", "show"}
WRITE_FLAGS = {"-o", "--output", "--junitxml", "--junit-xml", "--resultlog", "--result-log", "--log-file", "--html", "--report-log"}
DANGEROUS = re.compile(r">|(^|\s)(tee|truncate|mv|cp|rm|dd|ln|install|touch|chmod|chown|patch)(\s|$)|sed\s+(-\w*i|--in-place)|perl\s+-\w*i|"
                       r"git\s+(checkout|restore|stash|apply)|(python[\d.]*|node)\s+(-\S+\s+)*-[ce]\b")
FD_REDIRECT = re.compile(r"\d*>&\d+|\d*>&-|&?\d*>>?\s*/dev/null")
STATE_WORDS = ("AGENT_HOOK_STATE_DIR", "AGENT_DASHBOARD_DIR", "agent-hook-state", "agent-dashboard")


def norm(p):
    return p.lower()


def same(a, b):
    if norm(a) == norm(b):
        return True
    try:
        return os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b)
    except OSError:
        return False


def under(path, d):
    return norm(path).startswith(norm(d.rstrip("/")) + "/")


def covered(path, files):
    return any(same(path, f) or (os.path.isdir(f) and under(path, f)) for f in files)


def holds(path, files):
    """path (a file or directory named on a command line) is, or contains, a DONE_WHEN file."""
    return covered(path, files) or any(under(f, path) for f in files)


def guarded_dirs():
    return [os.path.realpath(common.state_dir()), os.path.realpath(os.path.dirname(common.events_path()))]


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


def allowlisted(words):
    if not words:
        return True
    w = list(words)
    while w and re.match(r"^[A-Za-z_]\w*=", w[0]):
        w.pop(0)
    if not w or w[0] in READONLY:
        return True
    if w[0] in ("python", "python3") and w[1:3] in (["-m", "pytest"], ["-m", "unittest"]):
        return True
    return w[0] == "git" and len(w) > 1 and w[1] in GIT_READ


def tokens_of(seg):
    seg = re.sub(r"(\d*>>?)", r" \1 ", FD_REDIRECT.sub(" ", seg))
    return shlex.split(seg)


def candidates(words, cwd):
    """(paths named, option-value paths, unresolved) for one segment's words."""
    paths, optvals, unresolved = [], [], False
    prev = ""
    for t in words:
        vals = []
        if t.startswith("-") and "=" in t:
            vals.append(t.split("=", 1)[1])
            optvals.append(vals[-1])
        elif prev in WRITE_FLAGS:
            optvals.append(t)
        for v in [t] + vals + ([t.split("=", 1)[1]] if "=" in t and not t.startswith("-") else []):
            v = v.split("::")[0]
            if "$" in v or "`" in v:
                unresolved = True
            if any(c in v for c in "*?["):
                paths += [os.path.realpath(g) for g in glob.glob(os.path.join(cwd, v))] + [("GLOB", os.path.join(cwd, v))]
            elif v:
                paths.append(common.real(v, cwd))
        prev = t
    return paths, [common.real(v.split("::")[0], cwd) for v in optvals if v], unresolved


def touches(paths, files):
    for p in paths:
        if isinstance(p, tuple):
            if any(fnmatch.fnmatch(norm(f), norm(p[1])) for f in files):
                return True
        elif holds(p, files):
            return True
    return False


def bash_denied(cmd, files, unknown, cwd):
    gdirs = guarded_dirs()
    for seg in re.split(r";|&&|\|\||\||\n", cmd):
        cleaned = FD_REDIRECT.sub(" ", seg)
        dangerous = bool(DANGEROUS.search(cleaned))
        try:
            words = tokens_of(seg)
            parsed = True
        except ValueError:
            words, parsed = [], False
        paths, optvals, unresolved = candidates(words, cwd) if parsed else ([], [], False)
        safe = parsed and allowlisted(words) and not dangerous
        if (any(w in seg for w in STATE_WORDS) or touches(paths, [g + "/x" for g in gdirs]) or
                any(p for p in paths if not isinstance(p, tuple) and any(under(p, g) or same(p, g) for g in gdirs))):
            if not safe:
                return "G8: Worker may not touch the hook state or event log"
        text = norm(seg if not parsed else " ".join(words))
        if files:
            raw_hit = any(norm(f) in text or norm(os.path.relpath(f, cwd) if cwd else f) in text or
                          norm(os.path.basename(f.rstrip("/"))) in text for f in files) and (not parsed or not safe)
            if raw_hit or (touches(paths, files) and not safe):
                return "G8: Bash command would change a DONE_WHEN test file"
            if safe and touches(optvals, files):
                return "G8: option would write to a DONE_WHEN test file"
            if unresolved and dangerous:
                return "G8: Bash command writes to a path built from a variable; cannot prove it spares DONE_WHEN files"
        if unknown:
            test_like = any(FALLBACK_RE.search(p.replace("\\", "/") + ("/" if os.path.isdir(p) else ""))
                            for p in paths if not isinstance(p, tuple)) or bool(TEXT_RE.search(text))
            if test_like and not safe:
                return "G8 fallback_no_done_when: Bash command would change a test-like path"
    return None


def main(event):
    if common.role(event) != "worker":
        return None
    tool, ti, cwd = event.get("tool_name"), event.get("tool_input") or {}, event.get("cwd") or ""
    files, unknown = load_state(event.get("session_id"))
    if tool in WRITE_TOOLS:
        p = ti.get("file_path") or ti.get("notebook_path")
        if not p:
            raise ValueError("write tool without a path")
        rp = common.real(p, cwd)
        if any(under(rp, g) for g in guarded_dirs()):
            return common.Decision(False, "G8", "G8: Worker may not touch the hook state or event log " + rp, {"tool_name": tool, "path": rp})
        if covered(rp, files):
            return common.Decision(False, "G8", "G8: Worker may not edit the DONE_WHEN test " + rp, {"tool_name": tool, "path": rp})
        if unknown and FALLBACK_RE.search(rp):
            return common.Decision(False, "G8", "G8 fallback_no_done_when: no DONE_WHEN files known; test-like path " + rp,
                                   {"tool_name": tool, "path": rp})
    elif tool == "Bash":
        cmd = ti.get("command")
        if not isinstance(cmd, str):
            raise ValueError("Bash without command")
        why = bash_denied(cmd, files, unknown, cwd)
        if why:
            return common.Decision(False, "G8", why, {"tool_name": "Bash"})
    return None


common.run_hook(main, guardrail="G8", rule_version="g8-v2")
