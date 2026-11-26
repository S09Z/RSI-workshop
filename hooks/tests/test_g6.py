import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import HOOKS, Env  # noqa: E402

HOOK = "g6_advisor_memory.py"


class Base(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="g6-"))
        self.mem = os.path.join(self.root, "mem")
        self.proj = os.path.join(self.root, "proj")
        os.makedirs(self.mem)
        os.makedirs(self.proj)
        self.e = Env(AGENT_ADVISOR_MEMORY_DIR=self.mem)

    def ev(self, tool, agent="advisor", **ti):
        return {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": self.proj,
                "agent_id": "a1", "agent_type": agent, "tool_name": tool, "tool_input": ti}

    def run_hook(self, tool, **ti):
        return self.e.run(HOOK, self.ev(tool, **ti))

    def assertDenied(self, r):
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("G6", r.stderr)
        ev = self.e.events()[-1]
        self.assertEqual((ev["guardrail"], ev["blocked"], ev["case_id"]), ("G6", True, "case-1"))

    def assertAllowed(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.e.events(), [])


class TestG6Denied(Base):
    def test_write_outside_memory_denied(self):
        self.assertDenied(self.run_hook("Write", file_path=os.path.join(self.proj, "a.py"), content="x"))

    def test_edit_project_file_denied(self):
        self.assertDenied(self.run_hook("Edit", file_path="a.py", old_string="a", new_string="b"))

    def test_notebookedit_and_multiedit_outside_denied(self):
        self.assertDenied(self.run_hook("NotebookEdit", notebook_path=os.path.join(self.proj, "n.ipynb")))
        self.assertDenied(self.run_hook("MultiEdit", file_path=os.path.join(self.proj, "a.py")))

    def test_dotdot_out_of_memory_denied(self):
        self.assertDenied(self.run_hook("Write", file_path=os.path.join(self.mem, "..", "x.md")))

    def test_symlink_inside_memory_pointing_out_denied(self):
        os.symlink(self.proj, os.path.join(self.mem, "lnk"))
        self.assertDenied(self.run_hook("Write", file_path=os.path.join(self.mem, "lnk", "x.md")))

    def test_case_variant_outside_not_confused(self):
        self.assertDenied(self.run_hook("Write", file_path=self.mem + "-evil/x.md"))

    def test_bash_redirect_outside_denied(self):
        self.assertDenied(self.run_hook("Bash", command="echo x > %s/f" % self.proj))

    def test_bash_tee_outside_denied(self):
        self.assertDenied(self.run_hook("Bash", command="echo x | tee %s/f" % self.proj))

    def test_bash_variable_target_denied(self):
        self.assertDenied(self.run_hook("Bash", command="echo x > $HOME/f"))

    def test_bash_cd_then_write_denied(self):
        self.assertDenied(self.run_hook("Bash", command="cd /tmp && echo x > f"))

    def test_bash_git_commit_in_project_denied(self):
        self.assertDenied(self.run_hook("Bash", command="git commit -am x"))

    def test_bash_python_c_denied(self):
        self.assertDenied(self.run_hook("Bash", command="python3 -c 'open(\"f\",\"w\")'"))


class TestG6Allowed(Base):
    def test_write_inside_memory_allowed(self):
        self.assertAllowed(self.run_hook("Write", file_path=os.path.join(self.mem, "MEMORY.md")))

    def test_write_new_file_inside_memory_allowed(self):
        self.assertAllowed(self.run_hook("Write", file_path=os.path.join(self.mem, "topics", "new", "t.md")))

    def test_symlinked_memory_dir_allowed(self):
        link = os.path.join(self.root, "memlink")
        os.symlink(self.mem, link)
        self.e = Env(AGENT_ADVISOR_MEMORY_DIR=link)
        self.assertAllowed(self.run_hook("Write", file_path=os.path.join(link, "a.md")))
        self.assertAllowed(self.run_hook("Write", file_path=os.path.join(self.mem, "b.md")))

    def test_bash_cat_and_git_log_allowed(self):
        self.assertAllowed(self.run_hook("Bash", command="cat MEMORY.md && git log -n 3"))

    def test_bash_redirect_inside_memory_allowed(self):
        self.assertAllowed(self.run_hook("Bash", command="echo x > %s/note.md" % self.mem))

    def test_worker_write_outside_not_governed(self):
        self.assertAllowed(self.e.run(HOOK, self.ev("Write", agent="worker", file_path="/etc/x")))

    def test_orchestrator_not_governed(self):
        ev = self.ev("Write", file_path="/etc/x")
        del ev["agent_id"]
        ev["agent_type"] = "orchestrator"
        self.assertAllowed(self.e.run(HOOK, ev))

    def test_inert_without_agent_workflow(self):
        self.e = Env(workflow=None, AGENT_ADVISOR_MEMORY_DIR=self.mem)
        self.assertAllowed(self.run_hook("Write", file_path="/etc/x"))


class TestG6FailClosed(Base):
    def test_missing_file_path_denies(self):
        r = self.run_hook("Write", content="x")
        self.assertEqual(r.returncode, 2)

    def test_malformed_stdin_denies(self):
        self.assertEqual(self.e.run(HOOK, "{oops").returncode, 2)

    def test_bash_without_command_denies(self):
        self.assertEqual(self.run_hook("Bash").returncode, 2)

    def test_missing_lib_denies(self):
        d = tempfile.mkdtemp(prefix="g6-nolib-")
        shutil.copy(os.path.join(HOOKS, HOOK), d)
        r = self.e.run(os.path.join(d, HOOK), self.ev("Write", file_path=os.path.join(self.mem, "a.md")))
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_unwritable_event_log_still_denies(self):
        open(self.e.dash, "w").close()  # a file where the log directory should be
        r = self.run_hook("Write", file_path=os.path.join(self.proj, "a.py"))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("G6", r.stderr)


if __name__ == "__main__":
    unittest.main()
