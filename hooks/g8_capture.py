"""G8 (part 1): record the DONE_WHEN test files of each Worker dispatch. PreToolUse on Agent.

Fails closed: if a Worker dispatch cannot be recorded the dispatch is denied (exit 2), because an unrecorded
dispatch would leave its test files unprotected. Non-worker dispatches never touch the state dir."""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib import common  # noqa: E402
except BaseException as _exc:  # fail closed when lib/ is missing (a copied script)
    if os.environ.get("AGENT_WORKFLOW") != "1":
        sys.exit(0)
    print("%s: cannot load hooks/lib (%s); denying" % (__doc__.split(":")[0], _exc), file=sys.stderr)
    sys.exit(2)

EXT = (".py", ".js", ".ts", ".go", ".rs", ".sh")
TTL = 24 * 3600


def _clean(tok):
    tok = tok.strip().strip("`'\"").rstrip(".,;:)")
    return tok.split("::")[0].strip("`'\"")


def parse_paths(prompt):
    explicit, tokens = [], []
    for line in prompt.splitlines():
        m = re.match(r"\s*DONE_WHEN_FILES:\s*(.*)", line)
        if m:
            explicit += [_clean(p) for p in m.group(1).split(",") if _clean(p)]
            continue
        m = re.match(r"\s*DONE_WHEN:\s*(.*)", line)
        if m:
            for t in m.group(1).split():
                t = _clean(t)
                if t and not t.startswith("-") and ("/" in t or t.endswith(EXT)):
                    tokens.append(t)
    return explicit + tokens


def main(event):
    ti = event.get("tool_input") or {}
    if event.get("tool_name") != "Agent" or ti.get("subagent_type") != "worker":
        return None
    cwd = event.get("cwd") or ""
    files = sorted({common.real(p, cwd) for p in parse_paths(ti.get("prompt") or "")})
    d = os.path.join(common.state_dir(), "done_when")
    os.makedirs(d, exist_ok=True)
    now = time.time()
    for f in os.listdir(d):
        fp = os.path.join(d, f)
        try:
            if now - os.lstat(fp).st_mtime > TTL:
                os.remove(fp)
        except FileNotFoundError:
            pass  # another capture pruned it first
    sid = re.sub(r"[^A-Za-z0-9_-]", "_", str(event.get("session_id") or "nosession"))
    with open(os.path.join(d, "%s-%d.json" % (sid, int(now * 1000))), "w") as f:
        json.dump({"files": files, "unknown": not files, "cwd": cwd}, f)
    return None


common.run_hook(main, guardrail="G8", rule_version="g8-capture-v1")
