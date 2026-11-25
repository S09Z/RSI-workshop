import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import Env, HOOKS  # noqa: E402
from lib import common  # noqa: E402


def make_script(body):
    d = tempfile.mkdtemp(prefix="hookscript-")
    p = os.path.join(d, "s.py")
    with open(p, "w") as f:
        f.write("import sys\nsys.path.insert(0, %r)\nfrom lib import common\n" % HOOKS + body)
    return p


DENY = """
def main(ev):
    return common.Decision(False, "G9", "nope", {"tool_name": "Write", "path": "/x"})
common.run_hook(main, guardrail="G9", rule_version="t-v1")
"""
BOOM = """
def main(ev):
    raise RuntimeError("boom")
common.run_hook(main, guardrail="G9", rule_version="t-v1", blocking=%s)
"""


class TestRunHook(unittest.TestCase):
    def test_inactive_without_agent_workflow_exits_0_and_logs_nothing(self):
        e = Env(workflow=None)
        r = e.run(make_script(DENY), {"x": 1})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(e.events(), [])

    def test_exception_in_main_exits_2_and_logs_hook_error(self):
        e = Env()
        r = e.run(make_script(BOOM % "True"), {"x": 1})
        self.assertEqual(r.returncode, 2)
        ev = e.events()
        self.assertEqual(len(ev), 1)
        self.assertTrue(ev[0]["blocked"])
        self.assertEqual(ev[0]["reason"], "hook_error")

    def test_invalid_json_exits_2(self):
        r = Env().run(make_script(DENY), "{not json")
        self.assertEqual(r.returncode, 2)

    def test_empty_stdin_exits_2(self):
        r = Env().run(make_script(DENY), "")
        self.assertEqual(r.returncode, 2)

    def test_nonblocking_swallows_exception_exit_0(self):
        e = Env()
        r = e.run(make_script(BOOM % "False"), {"x": 1})
        self.assertEqual(r.returncode, 0)

    def test_deny_exits_2_stderr_has_reason_and_event_has_case_id(self):
        e = Env(case_id="c1")
        r = e.run(make_script(DENY), {"x": 1})
        self.assertEqual(r.returncode, 2)
        self.assertIn("nope", r.stderr)
        ev = e.events()[0]
        self.assertEqual((ev["guardrail"], ev["blocked"], ev["case_id"], ev["rule_version"]),
                         ("G9", True, "c1", "t-v1"))
        self.assertEqual((ev["event"], ev["tool_name"], ev["path"]), ("guardrail_hit", "Write", "/x"))

    def test_allow_exits_0_and_logs_nothing(self):
        e = Env()
        body = "def main(ev):\n    return None\ncommon.run_hook(main, guardrail='G9', rule_version='t-v1')\n"
        r = e.run(make_script(body), {"x": 1})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(e.events(), [])


def _readonly_events(e):
    os.makedirs(e.dash, exist_ok=True)
    f = os.path.join(e.dash, "events.jsonl")
    with open(f, "w") as fh:
        fh.write("")
    os.chmod(f, 0o444)


class TestFailClosed(unittest.TestCase):
    def test_deny_with_readonly_event_log_still_exits_2(self):
        e = Env(); _readonly_events(e)
        r = e.run(make_script(DENY), {"x": 1})
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_real_hooks_deny_with_readonly_event_log(self):
        cases = [("g2_orchestrator_nowrite.py", {"agent_type": "orchestrator", "tool_name": "Write", "cwd": "/tmp", "tool_input": {"file_path": "/tmp/a"}}),
                 ("g1_report_contract.py", {"agent_id": "a", "agent_type": "worker", "last_assistant_message": "nope"})]
        for script, ev in cases:
            e = Env(); _readonly_events(e)
            self.assertEqual(e.run(script, ev).returncode, 2, script)

    def test_keyboardinterrupt_in_main_exits_2(self):
        body = "def main(ev):\n    raise KeyboardInterrupt()\ncommon.run_hook(main, guardrail='G9', rule_version='t-v1')\n"
        self.assertEqual(Env().run(make_script(body), {"x": 1}).returncode, 2)

    def test_hook_copied_without_lib_exits_2_when_workflow_on(self):
        import shutil
        for name in ("g1_report_contract.py", "g2_orchestrator_nowrite.py", "g8_capture.py", "g8_worker_tests.py"):
            d = tempfile.mkdtemp(); dst = os.path.join(d, name)
            shutil.copy(os.path.join(HOOKS, name), dst)
            self.assertEqual(Env().run(dst, {"x": 1}).returncode, 2, name)

    def test_hook_copied_without_lib_is_inert_when_workflow_off(self):
        import shutil
        d = tempfile.mkdtemp(); dst = os.path.join(d, "g2_orchestrator_nowrite.py")
        shutil.copy(os.path.join(HOOKS, "g2_orchestrator_nowrite.py"), dst)
        self.assertEqual(Env(workflow=None).run(dst, {"x": 1}).returncode, 0)


class TestHelpers(unittest.TestCase):
    def test_real_resolves_symlink_and_relative_with_cwd(self):
        d = os.path.realpath(tempfile.mkdtemp())
        os.makedirs(os.path.join(d, "sub"))
        open(os.path.join(d, "sub", "f.txt"), "w").close()
        os.symlink(os.path.join(d, "sub"), os.path.join(d, "link"))
        self.assertEqual(common.real("link/f.txt", d), os.path.join(d, "sub", "f.txt"))
        self.assertEqual(common.real(os.path.join(d, "link", "f.txt"), "/elsewhere"),
                         os.path.join(d, "sub", "f.txt"))

    def test_role_main_thread_is_orchestrator(self):
        self.assertEqual(common.role({"tool_name": "Write"}), "orchestrator")
        self.assertEqual(common.role({"agent_type": "orchestrator"}), "orchestrator")

    def test_role_worker_and_advisor(self):
        self.assertEqual(common.role({"agent_id": "a1", "agent_type": "worker"}), "worker")
        self.assertEqual(common.role({"agent_id": "a2", "agent_type": "advisor"}), "advisor")
        self.assertEqual(common.role({"agent_id": "a3", "agent_type": "Explore"}), "other")


if __name__ == "__main__":
    unittest.main()
