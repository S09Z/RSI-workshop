import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import Env  # noqa: E402

HOOK = "g1_report_contract.py"

WORKER = """Done, wrote the file.

=== WORKER REPORT ===
TASK: create hello.txt
STATUS: {status}
FINDINGS:
- none
CHANGES:
- hello.txt: created
VERIFICATION:
- command: {command}
- result: pass
ATTEMPTS: {attempts}
{notworking}=== END REPORT ==="""
NOTWORKING = "IF NOT WORKING:\n- hypotheses tried: a\n- current error: e\n- what I think is needed: unknown\n"


def worker(status="WORKS", command="test -f hello.txt", attempts="1/3", notworking="", end=True):
    t = WORKER.format(status=status, command=command, attempts=attempts, notworking=notworking)
    return t if end else t.replace("=== END REPORT ===", "")


ADVISOR = """=== ADVISOR GUIDANCE ===
DIAGNOSIS: {diag}
CONFIDENCE: {conf}
EVIDENCE:
- a.py:1
WHY PREVIOUS ATTEMPTS FAILED:
- x
PLAN FOR WORKER:
1. do
{verify}RISKS / WATCH OUT:
- none
FROM MEMORY: none
=== END GUIDANCE ==="""


def advisor(diag="root cause", conf="high", verify="HOW TO VERIFY:\n- pytest\n"):
    return ADVISOR.format(diag=diag, conf=conf, verify=verify)


def stop(msg, agent_type="worker", active=False, **extra):
    ev = {"hook_event_name": "SubagentStop", "session_id": "s1", "cwd": "/tmp", "agent_id": "a1",
          "agent_type": agent_type, "stop_hook_active": active, "last_assistant_message": msg}
    ev.update(extra)
    return ev


class TestG1(unittest.TestCase):
    def run_hook(self, ev, **kw):
        self.e = Env(**kw)
        return self.e.run(HOOK, ev)

    def denied(self, r, field=None):
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("G1", r.stderr)
        if field:
            self.assertIn(field, r.stderr)
        ev = self.e.events()[-1]
        self.assertEqual((ev["guardrail"], ev["blocked"], ev["case_id"]), ("G1", True, "case-1"))

    def test_valid_worker_report_allowed(self):
        self.assertEqual(self.run_hook(stop(worker())).returncode, 0)

    def test_valid_advisor_guidance_allowed(self):
        self.assertEqual(self.run_hook(stop(advisor(), "advisor")).returncode, 0)

    def test_worker_missing_end_marker_denied(self):
        self.denied(self.run_hook(stop(worker(end=False))), "END REPORT")

    def test_worker_bad_status_denied(self):
        self.denied(self.run_hook(stop(worker(status="MAYBE"))), "STATUS")

    def test_worker_empty_verification_command_denied(self):
        self.denied(self.run_hook(stop(worker(command=""))), "command")

    def test_worker_attempts_4_of_3_denied(self):
        self.denied(self.run_hook(stop(worker(attempts="4/3"))), "ATTEMPTS")

    def test_worker_attempts_0_denied(self):
        self.denied(self.run_hook(stop(worker(attempts="0/3"))), "ATTEMPTS")

    def test_worker_blocked_without_if_not_working_denied(self):
        self.denied(self.run_hook(stop(worker(status="BLOCKED"))), "IF NOT WORKING")

    def test_worker_blocked_full_contract_allowed(self):
        self.assertEqual(self.run_hook(stop(worker(status="BLOCKED", notworking=NOTWORKING))).returncode, 0)

    def test_advisor_missing_how_to_verify_denied(self):
        self.denied(self.run_hook(stop(advisor(verify=""), "advisor")), "HOW TO VERIFY")

    def test_advisor_bad_confidence_denied(self):
        self.denied(self.run_hook(stop(advisor(conf="sure"), "advisor")), "CONFIDENCE")

    def test_empty_final_message_denied(self):
        self.denied(self.run_hook(stop("")))

    def test_missing_message_and_unreadable_transcript_denied(self):
        ev = stop("x"); del ev["last_assistant_message"]; ev["agent_transcript_path"] = "/nonexistent/t.jsonl"
        self.denied(self.run_hook(ev))

    def test_message_from_transcript_fallback_allowed(self):
        import json
        p = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": worker()}]}}) + "\n")
        ev = stop("x"); del ev["last_assistant_message"]; ev["agent_transcript_path"] = p
        self.assertEqual(self.run_hook(ev).returncode, 0)

    def test_stop_hook_active_allows_and_logs_retry_cap(self):
        r = self.run_hook(stop(worker(status="MAYBE"), active=True))
        self.assertEqual(r.returncode, 0)
        ev = self.e.events()[-1]
        self.assertEqual((ev["guardrail"], ev["blocked"], ev["reason"]), ("G1", False, "retry_cap"))

    def test_other_agent_type_not_governed(self):
        self.assertEqual(self.run_hook(stop("anything", "Explore")).returncode, 0)

    def test_inactive_without_agent_workflow_allowed_and_no_log(self):
        r = self.run_hook(stop("garbage"), workflow=None)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.e.events(), [])

    def test_malformed_stdin_denied(self):
        self.e = Env(); self.assertEqual(self.e.run(HOOK, "{oops").returncode, 2)

    def test_real_probe_payload_without_report_denied(self):
        import json
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "real", "subagentstop_worker.json")
        with open(base) as f:
            ev = json.load(f)
        ev["last_assistant_message"] = "I created hello.txt, all good."
        self.denied(self.run_hook(ev), "WORKER REPORT")


if __name__ == "__main__":
    unittest.main()
