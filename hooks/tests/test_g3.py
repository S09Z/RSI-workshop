import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import FAILING, PASSING, Env, Project  # noqa: E402

HOOK = "g3_rerun_done_when.py"


class G3(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.p = Project()

    def dispatched(self, **kw):
        r = self.env.run("g5_test_first.py", self.p.dispatch(**kw))
        self.assertEqual(r.returncode, 0, r.stderr)

    def allow(self, event):
        r = self.env.run(HOOK, event)
        self.assertEqual(r.returncode, 0, r.stderr)

    def deny(self, event, *needles):
        r = self.env.run(HOOK, event)
        self.assertEqual(r.returncode, 2, r.stderr)
        for n in needles:
            self.assertIn(n, r.stderr)
        e = self.env.events()[-1]
        self.assertEqual((e["guardrail"], e["blocked"], e["rule_version"]), ("G3", True, "g3-v1"))

    def test_real_pass_allowed(self):
        self.dispatched()
        self.p.test(PASSING)
        self.allow(self.p.stop())
        e = self.env.events()[-1]
        self.assertEqual((e["guardrail"], e["blocked"]), ("G3", False))
        self.assertIn("1 passed", e["reason"])

    def test_still_failing_blocked(self):
        self.dispatched()
        self.deny(self.p.stop(), "re-run is failed")
        self.deny(self.p.stop(), "re-run is failed")

    def test_zero_tests_blocked(self):
        self.dispatched()
        for body in ("", "import sys\nsys.exit(0)\n"):
            self.p.test(body)
            self.deny(self.p.stop(), "re-run is error")

    def test_second_works_is_rerun(self):
        self.dispatched()
        self.p.test(PASSING)
        self.allow(self.p.stop())
        self.allow(self.p.stop())
        self.p.test(FAILING)
        self.deny(self.p.stop(), "re-run is failed")

    def test_no_record_blocked(self):
        self.deny(self.p.stop(), "no DONE_WHEN record")
        self.dispatched()
        self.p.test(PASSING)
        self.deny(self.p.stop(task="[T9] "), "no DONE_WHEN record")

    def test_missing_id_uses_newest_open(self):
        self.dispatched()
        self.deny(self.p.stop(task=""), "re-run is failed")
        self.p.test(PASSING)
        self.allow(self.p.stop(task=""))
        self.deny(self.p.stop(task=""), "no DONE_WHEN record")

    def test_test_swapped_for_symlink_blocked(self):
        self.dispatched()
        other = Project(PASSING)
        path = os.path.join(self.p.root, "tests", "test_new.py")
        os.remove(path)
        os.symlink(os.path.join(other.root, "tests", "test_new.py"), path)
        self.deny(self.p.stop(), "re-run is error")

    def test_other_status_and_agents_ignored(self):
        self.dispatched()
        for status in ("DOES_NOT_WORK", "BLOCKED", "WORKS | DOES_NOT_WORK | BLOCKED"):
            self.allow(self.p.stop(status=status))
        self.allow(self.p.stop(agent="advisor"))
        self.allow(self.p.stop(message="no report"))
        self.allow(self.p.stop(message=""))

    def test_works_anywhere_counts(self):
        self.dispatched()
        quoted = ("=== WORKER REPORT ===\nSTATUS: BLOCKED\n=== END REPORT ===\n"
                  + self.p.stop()["last_assistant_message"])
        self.deny(self.p.stop(message=quoted), "re-run is failed")
        self.deny(self.p.stop(status="WORKS (mostly)"), "re-run is failed")

    def test_transcript_fallback(self):
        self.dispatched()
        ev = self.p.stop()
        path = os.path.join(self.env.tmp, "t.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": ev.pop("last_assistant_message")}]}}) + "\n")
        ev["agent_transcript_path"] = path
        self.deny(ev, "re-run is failed")
        ev["agent_transcript_path"] = path + ".missing"
        self.deny(ev, "hook error")

    def test_retry_cap(self):
        self.dispatched()
        self.allow(self.p.stop(active=True))
        self.assertEqual(self.env.events()[-1]["reason"], "retry_cap")

    def test_write_test_skipped(self):
        self.dispatched(cmd=None, kind="write-test")
        self.allow(self.p.stop())
        self.assertIn("write-test", self.env.events()[-1]["reason"])

    def test_timeout_blocked(self):
        self.dispatched()
        self.p.test("import time\ntime.sleep(30)\n")
        self.env.env["AGENT_DONEWHEN_TIMEOUT"] = "1"
        self.deny(self.p.stop(), "timeout")

    def test_fail_closed_and_inert(self):
        self.assertEqual(self.env.run(HOOK, "{bad").returncode, 2)
        self.assertEqual(Env(workflow=None).run(HOOK, self.p.stop()).returncode, 0)


if __name__ == "__main__":
    unittest.main()
