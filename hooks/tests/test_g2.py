import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import Env  # noqa: E402

HOOK = "g2_orchestrator_nowrite.py"


def orch(tool, **ti):
    return {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": "/tmp",
            "agent_type": "orchestrator", "tool_name": tool, "tool_input": ti}


class TestG2(unittest.TestCase):
    def assertDenied(self, e, r):
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("G2", r.stderr)
        ev = e.events()[-1]
        self.assertEqual((ev["guardrail"], ev["blocked"], ev["case_id"]), ("G2", True, "case-1"))

    def test_orchestrator_write_denied(self):
        e = Env(); self.assertDenied(e, e.run(HOOK, orch("Write", file_path="/p/a.py", content="x")))

    def test_orchestrator_edit_denied(self):
        e = Env(); self.assertDenied(e, e.run(HOOK, orch("Edit", file_path="/p/a.py", old_string="a", new_string="b")))

    def test_orchestrator_notebookedit_denied(self):
        e = Env(); self.assertDenied(e, e.run(HOOK, orch("NotebookEdit", notebook_path="/p/n.ipynb")))

    def test_orchestrator_multiedit_denied(self):
        e = Env(); self.assertDenied(e, e.run(HOOK, orch("MultiEdit", file_path="/p/a.py")))

    def test_orchestrator_main_thread_without_agent_type_denied(self):
        e = Env()
        ev = orch("Write", file_path="/p/a.py"); del ev["agent_type"]
        self.assertDenied(e, e.run(HOOK, ev))

    def test_orchestrator_write_via_symlink_path_denied(self):
        d = tempfile.mkdtemp(); os.symlink("/tmp", os.path.join(d, "lnk"))
        e = Env(); self.assertDenied(e, e.run(HOOK, orch("Write", file_path=os.path.join(d, "lnk", "a.py"))))

    def test_worker_write_allowed(self):
        e = Env()
        ev = orch("Write", file_path="/p/a.py"); ev.update(agent_id="a1", agent_type="worker")
        self.assertEqual(e.run(HOOK, ev).returncode, 0)

    def test_orchestrator_read_allowed(self):
        e = Env(); self.assertEqual(e.run(HOOK, orch("Read", file_path="/p/a.py")).returncode, 0)

    def test_orchestrator_bash_allowed_residual(self):
        e = Env(); self.assertEqual(e.run(HOOK, orch("Bash", command="echo hi > f")).returncode, 0)

    def test_inactive_without_agent_workflow_allowed_and_no_log(self):
        e = Env(workflow=None)
        self.assertEqual(e.run(HOOK, orch("Write", file_path="/p/a.py")).returncode, 0)
        self.assertEqual(e.events(), [])

    def test_malformed_stdin_denied(self):
        e = Env(); self.assertEqual(e.run(HOOK, "{oops").returncode, 2)


if __name__ == "__main__":
    unittest.main()
