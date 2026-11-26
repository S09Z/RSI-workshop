import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import PASSING, Env, Project  # noqa: E402

HOOK = "g4_fresh_evidence.py"


def at(seconds=0, suffix="Z"):
    t = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%S") + suffix


class G4(unittest.TestCase):
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
        self.assertEqual((e["guardrail"], e["blocked"], e["rule_version"]), ("G4", True, "g4-v1"))

    def test_fresh_allowed(self):
        self.dispatched()
        for value in (at(), at(suffix="+00:00"), at(suffix=".123456Z"), "`%s`" % at()):
            with self.subTest(value=value):
                self.allow(self.p.stop(ran_at=value))
        self.assertFalse(self.env.events()[-1]["blocked"])

    def test_missing(self):
        self.dispatched()
        self.deny(self.p.stop(), "no ran_at")

    def test_ran_at_outside_verification_ignored(self):
        self.dispatched()
        ev = self.p.stop()
        ev["last_assistant_message"] = ev["last_assistant_message"].replace("FINDINGS:\n", "FINDINGS:\n- ran_at: %s\n" % at())
        self.deny(ev, "no ran_at")

    def test_before_dispatch_and_future(self):
        self.dispatched()
        self.deny(self.p.stop(ran_at="2020-01-01T00:00:00Z"), "before this task was dispatched")
        self.deny(self.p.stop(ran_at=at(3600)), "in the future")

    def test_bad_format(self):
        self.dispatched()
        for value in (at(suffix=""), at(suffix="+07:00"), "yesterday", "<UTC time of that run>"):
            with self.subTest(value=value):
                self.deny(self.p.stop(ran_at=value), "ISO-8601", "timezone")

    def test_every_ran_at_must_be_fresh(self):
        self.dispatched()
        self.deny(self.p.stop(ran_at="%s\n- ran_at: 2020-01-01T00:00:00Z" % at()), "before")

    def test_other_status_and_agents_ignored(self):
        self.dispatched()
        self.allow(self.p.stop(status="BLOCKED"))
        self.allow(self.p.stop(agent="advisor"))
        self.allow(self.p.stop(active=True))

    def test_no_record(self):
        self.deny(self.p.stop(ran_at=at()), "no dispatch record")

    def test_write_test_needs_ran_at_too(self):
        self.dispatched(cmd=None, kind="write-test")
        self.deny(self.p.stop(), "no ran_at")
        self.allow(self.p.stop(ran_at=at()))

    def test_no_task_id_after_g3_marked_stopped(self):
        # G3 and G4 run in parallel on SubagentStop: G3 verifying first must not make G4 block
        self.dispatched()
        self.p.test(PASSING)
        self.assertEqual(self.env.run("g3_rerun_done_when.py", self.p.stop(task="")).returncode, 0)
        self.allow(self.p.stop(task="", ran_at=at()))

    def test_redispatch_needs_new_evidence(self):
        self.dispatched()
        stale = "2020-01-01T00:00:00Z"
        self.dispatched()
        self.deny(self.p.stop(ran_at=stale), "before")

    def test_fail_closed_and_inert(self):
        self.assertEqual(self.env.run(HOOK, "{bad").returncode, 2)
        self.assertEqual(Env(workflow=None).run(HOOK, self.p.stop()).returncode, 0)


if __name__ == "__main__":
    unittest.main()
