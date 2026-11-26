import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import FAILING, PASSING, Env, Project  # noqa: E402

HOOK = "g5_test_first.py"


class G5(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.p = Project()

    def record(self, task="T1"):
        path = os.path.join(self.env.state, "donewhen", "s1-%s.json" % task)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def allow(self, event):
        r = self.env.run(HOOK, event)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def deny(self, event, *needles):
        r = self.env.run(HOOK, event)
        self.assertEqual(r.returncode, 2, r.stderr)
        for n in needles:
            self.assertIn(n, r.stderr)
        e = self.env.events()[-1]
        self.assertEqual((e["guardrail"], e["blocked"], e["rule_version"], e["case_id"]), ("G5", True, "g5-v1", "case-1"))
        return r

    def test_failing_test_allows_and_records(self):
        self.allow(self.p.dispatch())
        self.assertEqual(self.record()["kind"], "test")
        self.assertFalse(self.env.events()[-1]["blocked"])

    def test_passing_test_denied(self):
        self.p.test(PASSING)
        self.deny(self.p.dispatch(), "already passes")
        self.assertIsNone(self.record())

    def test_subdirectory_cwd_never_leaves_g8_guarding_another_file(self):
        """G8 resolves DONE_WHEN_FILES against the session cwd, so G5 must resolve them the same way."""
        pkg = os.path.join(self.p.root, "pkg")
        os.makedirs(os.path.join(pkg, "tests"))
        target = os.path.join(pkg, "tests", "test_sub.py")
        with open(target, "w") as f:
            f.write(FAILING)
        cmd = "python3 -m unittest pkg/tests/test_sub.py"
        root_relative = dict(self.p.dispatch(cmd=cmd, files="pkg/tests/test_sub.py"), cwd=pkg)
        self.deny(root_relative, "absolute")
        for files in ("tests/test_sub.py", target):
            with self.subTest(files=files):
                self.env = Env()
                event = dict(self.p.dispatch(cmd=cmd, files=files), cwd=pkg)
                self.allow(event)
                self.assertEqual(self.env.run("g8_capture.py", event).returncode, 0)
                edit = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "session_id": "s1", "cwd": pkg,
                        "agent_type": "worker", "agent_id": "a1", "tool_input": {"file_path": target}}
                r = self.env.run("g8_worker_tests.py", edit)
                self.assertEqual(r.returncode, 2, r.stderr)

    def test_zero_tests_denied(self):
        self.p.test("")
        self.deny(self.p.dispatch(), "did not run")

    def test_collection_error_denied(self):
        self.p.test("def (:\n")
        self.deny(self.p.dispatch(), "did not run")

    def test_missing_id_or_command(self):
        self.deny(self.p.dispatch(description="no id"), "task id")
        self.deny(self.p.dispatch(cmd=None), "DONE_WHEN_CMD")

    def test_disallowed_commands(self):
        for cmd in ('bash -c "pytest"', "pytest tests/test_new.py; rm x", "pytest -p evil tests/test_new.py",
                    "python3 -m unittest tests/test_new.py && true", "pytest $(echo tests/test_new.py)"):
            with self.subTest(cmd=cmd):
                self.deny(self.p.dispatch(cmd=cmd), "G5")

    def test_unlisted_file_and_symlink_out(self):
        self.deny(self.p.dispatch(files="tests/other.py"), "DONE_WHEN_FILES")
        out = Project()
        os.symlink(os.path.join(out.root, "tests", "test_new.py"), os.path.join(self.p.root, "tests", "test_link.py"))
        self.deny(self.p.dispatch(cmd="python3 -m unittest tests/test_link.py", files="tests/test_link.py"), "outside")

    def test_missing_runner_denied(self):
        self.env.env["PATH"] = "/nonexistent"
        self.deny(self.p.dispatch(cmd="pytest tests/test_new.py"), "not found")

    def test_timeout_denied(self):
        self.env.env["AGENT_DONEWHEN_TIMEOUT"] = "1"
        self.p.test("import time\ntime.sleep(30)\n")
        self.deny(self.p.dispatch(), "timeout")

    def test_redispatch_same_command_no_rerun(self):
        self.allow(self.p.dispatch())
        first = self.record()
        self.p.test(PASSING)
        self.allow(self.p.dispatch())
        self.assertFalse(self.record()["stopped"])
        self.assertGreaterEqual(self.record()["written_at"], first["written_at"])

    def test_redispatch_changed_is_locked(self):
        self.allow(self.p.dispatch())
        self.deny(self.p.dispatch(cmd="python3 -m unittest -v tests/test_new.py"), "locked")
        self.deny(self.p.dispatch(files="tests/test_new.py, tests/more.py"), "locked")

    def test_lock_holds_after_stop(self):
        self.allow(self.p.dispatch())
        rec = self.record()
        rec["stopped"] = True
        with open(os.path.join(self.env.state, "donewhen", "s1-T1.json"), "w") as f:
            json.dump(rec, f)
        self.deny(self.p.dispatch(cmd="python3 -m unittest -v tests/test_new.py"), "locked")
        self.allow(self.p.dispatch())
        self.assertFalse(self.record()["stopped"])

    def test_write_test(self):
        self.allow(self.p.dispatch(cmd=None, kind="write-test"))
        self.assertEqual(self.record()["kind"], "write-test")
        self.assertIn("write-test", self.env.events()[-1]["reason"])
        # the real dispatch that follows replaces it, after seeing the test fail
        self.allow(self.p.dispatch())
        self.assertEqual(self.record()["kind"], "test")
        # and write-test cannot be used to get out of the lock
        self.deny(self.p.dispatch(cmd=None, kind="write-test"), "locked")

    def test_write_test_then_passing_test_denied(self):
        self.allow(self.p.dispatch(cmd=None, kind="write-test"))
        self.p.test(PASSING)
        self.deny(self.p.dispatch(), "already passes")

    def test_write_test_needs_a_file_list(self):
        self.deny(self.p.dispatch(cmd=None, kind="write-test", files=""), "DONE_WHEN_FILES")
        self.assertIsNone(self.record())

    def test_write_test_flow_under_g8(self):
        """The Worker can create the new test, and G8 guards it from the first test dispatch that lists it."""
        new = os.path.join(self.p.root, "tests", "test_added.py")

        def dispatch(event):
            self.allow(event)
            self.assertEqual(self.env.run("g8_capture.py", event).returncode, 0)

        def worker(tool, **tool_input):
            return self.env.run("g8_worker_tests.py", {
                "hook_event_name": "PreToolUse", "tool_name": tool, "session_id": "s1", "cwd": self.p.root,
                "agent_type": "worker", "agent_id": "a1", "tool_input": tool_input})

        dispatch(self.p.dispatch(cmd=None, kind="write-test", files=".no-done-when-files"))
        r = worker("Write", file_path=new)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = worker("Bash", command="printf 'x = None\\n' > tests/test_added.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(new, "w") as f:
            f.write(FAILING)
        dispatch(self.p.dispatch(cmd="python3 -m unittest tests/test_added.py", files="tests/test_added.py"))
        self.assertEqual(worker("Write", file_path=new).returncode, 2)

    def test_other_agent_and_tool_ignored(self):
        self.allow(self.p.dispatch(agent="advisor", cmd=None))
        ev = self.p.dispatch(cmd=None)
        ev["tool_name"] = "Bash"
        self.allow(ev)
        self.assertEqual(self.env.events(), [])

    def test_no_git_root(self):
        self.p = Project(git=False)
        self.deny(self.p.dispatch(), "no git root")

    def test_fail_closed_and_inert(self):
        self.assertEqual(self.env.run(HOOK, "{bad").returncode, 2)
        self.assertEqual(Env(workflow=None).run(HOOK, self.p.dispatch(cmd=None)).returncode, 0)

    def test_unwritable_log_still_denies(self):
        with open(self.env.dash, "w") as f:
            f.write("a file where the log dir should be")
        self.assertEqual(self.env.run(HOOK, self.p.dispatch(cmd=None)).returncode, 2)

    def test_unwritable_state_denies(self):
        with open(self.env.state, "w") as f:
            f.write("a file where the state dir should be")
        self.assertEqual(self.env.run(HOOK, self.p.dispatch()).returncode, 2)


if __name__ == "__main__":
    unittest.main()
