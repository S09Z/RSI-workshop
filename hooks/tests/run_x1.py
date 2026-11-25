"""X1 hook-level runner for G1/G2/G8 (report §8): crafted hook input -> hook script, no model calls.

A violation counts as blocked only if the hook exited 2 AND the events file holds a line with that
guardrail, blocked=true and the case_id. A control (expect=allow) is a false block if exit != 0 or a
blocked=true event was logged.

usage: python3 -I hooks/tests/run_x1.py [--hook-dir DIR] [--fixtures DIR]
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def expand(obj, tmp):
    if isinstance(obj, str):
        return obj.replace("{TMP}", tmp)
    if isinstance(obj, list):
        return [expand(x, tmp) for x in obj]
    if isinstance(obj, dict):
        return {k: expand(v, tmp) for k, v in obj.items()}
    return obj


def events(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def run_case(case, hook_dir):
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="x1-"))
    case = expand(case, tmp)
    for rel, content in case.get("files", {}).items():
        p = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
    for link, target in case.get("symlinks", {}).items():
        os.symlink(os.path.join(tmp, target), os.path.join(tmp, link))
    dash = os.path.join(tmp, "dash")
    env = {"PATH": os.environ.get("PATH", ""), "AGENT_WORKFLOW": "1", "AGENT_DASHBOARD_DIR": dash,
           "AGENT_HOOK_STATE_DIR": os.path.join(tmp, "state"), "AGENT_HOOK_CASE_ID": case["case_id"]}
    env.update(case.get("env", {}))

    def call(hook, stdin):
        return subprocess.run([sys.executable, "-I", os.path.join(hook_dir, hook)], input=json.dumps(stdin),
                              text=True, capture_output=True, env=env, timeout=30)

    for pre in case.get("pre", []):
        call(pre["hook"], pre["stdin"])
    r = call(case["hook"], case["stdin"])
    hits = [e for e in events(os.path.join(dash, "events.jsonl"))
            if e.get("blocked") is True and e.get("case_id") == case["case_id"]]
    if case["expect"] == "block":
        ok = r.returncode == 2 and any(e.get("guardrail") == case["guardrail"] for e in hits)
        return ok, r
    return (r.returncode == 0 and not hits), r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hook-dir", default=os.path.dirname(HERE))
    ap.add_argument("--fixtures", default=os.path.join(HERE, "fixtures", "x1"))
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.fixtures, "*.json")))
    if not files:
        print("no fixtures in %s" % a.fixtures)
        return 1
    viol = blocked = ctrl = false_blocks = 0
    for fp in files:
        with open(fp) as f:
            case = json.load(f)
        ok, r = run_case(case, a.hook_dir)
        if case["expect"] == "block":
            viol += 1
            blocked += ok
            print("%s %s %s" % ("BLOCKED" if ok else "MISSED ", case["guardrail"], case["case_id"]))
        else:
            ctrl += 1
            false_blocks += (not ok)
            print("%s %s %s" % ("allowed" if ok else "FALSE-BLOCK", case["guardrail"], case["case_id"]))
    print("blocked %d/%d" % (blocked, viol))
    print("false_blocks %d/%d" % (false_blocks, ctrl))
    return 0 if blocked == viol and false_blocks == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
