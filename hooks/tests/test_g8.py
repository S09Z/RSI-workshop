import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import Env  # noqa: E402

CAP, GUARD = "g8_capture.py", "g8_worker_tests.py"


def dispatch(cwd, prompt, sub="worker"):
    return {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": cwd, "agent_type": "orchestrator",
            "tool_name": "Agent", "tool_input": {"subagent_type": sub, "prompt": prompt, "description": "d"}}


def wev(tool, cwd, **ti):
    return {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": cwd, "agent_id": "a1",
            "agent_type": "worker", "tool_name": tool, "tool_input": ti}


class Base(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp(prefix="g8-"))
        os.makedirs(os.path.join(self.d, "tests")); os.makedirs(os.path.join(self.d, "src"))
        for f in ("tests/test_x.py", "src/app.py"):
            with open(os.path.join(self.d, f), "w") as fh:
                fh.write("x")
        self.e = Env()
        self.test = os.path.join(self.d, "tests", "test_x.py")

    def known(self, files="tests/test_x.py"):
        r = self.e.run(CAP, dispatch(self.d, "[T1] do it\nDONE_WHEN: `pytest tests/test_x.py` passes.\nDONE_WHEN_FILES: %s\n" % files))
        self.assertEqual(r.returncode, 0, r.stderr)

    def denied(self, r):
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("G8", r.stderr)
        ev = self.e.events()[-1]
        self.assertEqual((ev["guardrail"], ev["blocked"], ev["case_id"]), ("G8", True, "case-1"))

    def entries(self):
        p = os.path.join(self.e.state, "done_when")
        out = []
        for f in sorted(os.listdir(p)) if os.path.isdir(p) else []:
            with open(os.path.join(p, f)) as fh:
                out.append(json.load(fh))
        return out


class TestCapture(Base):
    def test_capture_stores_done_when_files_resolved(self):
        self.known()
        en = self.entries()
        self.assertEqual(en[0]["files"], [self.test]); self.assertFalse(en[0]["unknown"])

    def test_capture_no_paths_stores_unknown(self):
        self.e.run(CAP, dispatch(self.d, "[T1] do it\nDONE_WHEN: it works\n"))
        self.assertTrue(self.entries()[0]["unknown"])

    def test_capture_ignores_non_worker_dispatch(self):
        self.e.run(CAP, dispatch(self.d, "DONE_WHEN_FILES: a.py", sub="advisor"))
        self.assertEqual(self.entries(), [])

    def test_capture_never_exits_2_on_garbage_stdin(self):
        self.assertEqual(self.e.run(CAP, "{garbage").returncode, 0)

    def test_capture_extracts_path_tokens_from_done_when_line(self):
        self.e.run(CAP, dispatch(self.d, "DONE_WHEN: `python3 -m pytest tests/test_x.py::test_a -q`\n"))
        en = self.entries()[0]
        self.assertEqual(en["files"], [self.test]); self.assertFalse(en["unknown"])

    def test_stale_state_pruned(self):
        self.known()
        p = os.path.join(self.e.state, "done_when"); old = os.path.join(p, "old-1.json")
        with open(old, "w") as fh:
            fh.write("{}")
        t = time.time() - 25 * 3600; os.utime(old, (t, t))
        self.known()
        self.assertFalse(os.path.exists(old))


class TestGuardFiles(Base):
    def test_worker_edit_done_when_file_denied(self):
        self.known(); self.denied(self.e.run(GUARD, wev("Edit", self.d, file_path=self.test)))

    def test_worker_write_done_when_relative_path_denied(self):
        self.known(); self.denied(self.e.run(GUARD, wev("Write", self.d, file_path="tests/test_x.py")))

    def test_worker_write_new_test_file_allowed_when_state_known(self):
        self.known()
        self.assertEqual(self.e.run(GUARD, wev("Write", self.d, file_path=os.path.join(self.d, "tests", "test_new.py"))).returncode, 0)

    def test_worker_write_src_allowed(self):
        self.known(); self.assertEqual(self.e.run(GUARD, wev("Write", self.d, file_path=os.path.join(self.d, "src", "app.py"))).returncode, 0)

    def test_worker_edit_via_symlink_alias_denied(self):
        self.known(); os.symlink(os.path.join(self.d, "tests"), os.path.join(self.d, "alias"))
        self.denied(self.e.run(GUARD, wev("Edit", self.d, file_path=os.path.join(self.d, "alias", "test_x.py"))))

    def test_relative_done_when_other_cwd_denied(self):
        self.known(); other = tempfile.mkdtemp()
        self.denied(self.e.run(GUARD, wev("Edit", other, file_path=self.test)))

    def test_done_when_directory_covers_files_inside(self):
        self.known(files="tests/")
        self.denied(self.e.run(GUARD, wev("Write", self.d, file_path=os.path.join(self.d, "tests", "other.py"))))

    def test_non_worker_not_governed(self):
        self.known(); ev = wev("Edit", self.d, file_path=self.test); ev.update(agent_type="advisor")
        self.assertEqual(self.e.run(GUARD, ev).returncode, 0)

    def test_inactive_without_agent_workflow_allowed_and_no_log(self):
        e = Env(workflow=None)
        self.assertEqual(e.run(GUARD, wev("Edit", self.d, file_path=self.test)).returncode, 0)
        self.assertEqual(e.events(), [])

    def test_malformed_stdin_denied(self):
        self.assertEqual(self.e.run(GUARD, "{oops").returncode, 2)


class TestGuardBash(Base):
    def run_bash(self, cmd):
        return self.e.run(GUARD, wev("Bash", self.d, command=cmd))

    def test_bash_sed_i_on_test_denied(self):
        self.known(); self.denied(self.run_bash("sed -i 's/a/b/' tests/test_x.py"))

    def test_bash_redirect_into_test_denied(self):
        self.known(); self.denied(self.run_bash("echo pass > tests/test_x.py"))

    def test_bash_mv_test_denied(self):
        self.known(); self.denied(self.run_bash("mv tests/test_x.py /tmp/gone.py"))

    def test_bash_python_c_open_write_denied(self):
        self.known(); self.denied(self.run_bash("python3 -c \"open('tests/test_x.py','w').write('')\""))

    def test_bash_git_checkout_test_denied(self):
        self.known(); self.denied(self.run_bash("git checkout HEAD -- tests/test_x.py"))

    def test_bash_pipeline_cat_then_tee_test_denied(self):
        self.known(); self.denied(self.run_bash("cat src/app.py | tee tests/test_x.py"))

    def test_bash_pytest_naming_test_allowed(self):
        self.known(); self.assertEqual(self.run_bash("python3 -m pytest tests/test_x.py::test_a -q").returncode, 0)

    def test_bash_cat_test_allowed(self):
        self.known(); self.assertEqual(self.run_bash("cat tests/test_x.py").returncode, 0)

    def test_bash_not_mentioning_test_allowed(self):
        self.known(); self.assertEqual(self.run_bash("sed -i 's/a/b/' src/app.py").returncode, 0)

    def test_bash_unparseable_quote_mentioning_test_denied(self):
        self.known(); self.denied(self.run_bash("echo 'unterminated > tests/test_x.py"))


class TestFallbackC(Base):
    def test_fallback_c_denies_tests_dir_when_no_state(self):
        self.denied(self.e.run(GUARD, wev("Write", self.d, file_path=os.path.join(self.d, "tests", "test_y.py"))))
        self.assertIn("fallback_no_done_when", self.e.events()[-1]["reason"])

    def test_fallback_c_denies_when_state_unknown(self):
        self.e.run(CAP, dispatch(self.d, "DONE_WHEN: it works"))
        self.denied(self.e.run(GUARD, wev("Edit", self.d, file_path=os.path.join(self.d, "conftest.py"))))

    def test_fallback_c_allows_src_file(self):
        self.assertEqual(self.e.run(GUARD, wev("Write", self.d, file_path=os.path.join(self.d, "src", "app.py"))).returncode, 0)

    def test_fallback_c_bash_sed_i_on_tests_denied(self):
        self.denied(self.e.run(GUARD, wev("Bash", self.d, command="sed -i 's/a/b/' tests/test_x.py")))


if __name__ == "__main__":
    unittest.main()
