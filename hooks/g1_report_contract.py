"""G1: Worker and Advisor must end with a report that matches the contract. SubagentStop; blocking.

Contract = the baseline in agents/worker.md and agents/advisor.md. ran_at freshness is G4, not here.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib import common  # noqa: E402
except BaseException as _exc:  # fail closed when lib/ is missing (a copied script)
    if os.environ.get("AGENT_WORKFLOW") != "1":
        sys.exit(0)
    print("%s: cannot load hooks/lib (%s); denying" % (__doc__.split(":")[0], _exc), file=sys.stderr)
    sys.exit(2)


def _field(body, name, value_re=r"\S"):
    return re.search(r"^[ \t]*%s:[ \t]*(%s.*)$" % (re.escape(name), value_re), body, re.M)


def _has(body, name):
    return re.search(r"^[ \t]*%s:" % re.escape(name), body, re.M) is not None


def _block(text, start, end, label_start, label_end, fails):
    i = text.find(start)
    if i < 0:
        fails.append("missing %s marker" % label_start)
        return None
    j = text.find(end, i)
    if j < 0:
        fails.append("missing %s marker" % label_end)
        return text[i + len(start):]
    return text[i + len(start):j]


def check_worker(text):
    fails = []
    body = _block(text, "=== WORKER REPORT ===", "=== END REPORT ===", "=== WORKER REPORT ===", "=== END REPORT ===", fails)
    if body is None:
        return fails
    if not _field(body, "TASK"):
        fails.append("TASK missing or empty")
    m = re.search(r"^[ \t]*STATUS:[ \t]*(\S+)[ \t]*$", body, re.M)
    status = m.group(1) if m else None
    if status not in ("WORKS", "DOES_NOT_WORK", "BLOCKED"):
        fails.append("STATUS must be WORKS, DOES_NOT_WORK or BLOCKED (got %r)" % status)
    for name in ("FINDINGS", "CHANGES", "VERIFICATION"):
        if not _has(body, name):
            fails.append("%s section missing" % name)
    v = body.split("VERIFICATION:", 1)[1] if "VERIFICATION:" in body else ""
    for name in ("command", "result"):
        if not re.search(r"^[ \t]*-?[ \t]*%s:[ \t]*\S" % name, v, re.M):
            fails.append("VERIFICATION %s missing or empty" % name)
    m = re.search(r"^[ \t]*ATTEMPTS:[ \t]*(\d+)/3[ \t]*$", body, re.M)
    if not m or not 1 <= int(m.group(1)) <= 3:
        fails.append("ATTEMPTS must be n/3 with 1 <= n <= 3")
    if status in ("DOES_NOT_WORK", "BLOCKED") and not _has(body, "IF NOT WORKING"):
        fails.append("IF NOT WORKING section missing for STATUS %s" % status)
    return fails


def check_advisor(text):
    fails = []
    body = _block(text, "=== ADVISOR GUIDANCE ===", "=== END GUIDANCE ===", "=== ADVISOR GUIDANCE ===", "=== END GUIDANCE ===", fails)
    if body is None:
        return fails
    if not _field(body, "DIAGNOSIS"):
        fails.append("DIAGNOSIS missing or empty")
    m = re.search(r"^[ \t]*CONFIDENCE:[ \t]*(\S+)[ \t]*$", body, re.M)
    if not m or m.group(1) not in ("high", "medium", "low"):
        fails.append("CONFIDENCE must be high, medium or low")
    for name in ("EVIDENCE", "PLAN FOR WORKER", "HOW TO VERIFY", "FROM MEMORY"):
        if not _has(body, name):
            fails.append("%s section missing" % name)
    return fails


def final_message(event):
    msg = event.get("last_assistant_message")
    if isinstance(msg, str) and msg.strip():
        return msg
    path = event.get("agent_transcript_path")
    if path:
        last = None
        with open(path) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                m = rec.get("message") or {}
                if rec.get("type") == "assistant" or m.get("role") == "assistant":
                    c = m.get("content")
                    text = c if isinstance(c, str) else "".join(b.get("text", "") for b in (c or []) if isinstance(b, dict))
                    if text.strip():
                        last = text
        return last
    return None


def main(event):
    kind = event.get("agent_type")
    if kind not in ("worker", "advisor"):
        return None
    if event.get("stop_hook_active"):
        return common.Decision(True, "G1", "retry_cap", {"log": True})
    text = final_message(event)
    if not text:
        fails = ["empty final message: no %s found" % ("=== WORKER REPORT ===" if kind == "worker" else "=== ADVISOR GUIDANCE ===")]
    else:
        fails = check_worker(text) if kind == "worker" else check_advisor(text)
    if fails:
        return common.Decision(False, "G1", "G1: %s contract violated: %s" % (kind, "; ".join(fails)))
    return None


common.run_hook(main, guardrail="G1", rule_version="g1-v1")
