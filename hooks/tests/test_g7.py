import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import HOOKS, Env  # noqa: E402

HOOK = "g7_worker_gitroot.py"


def has_git_above(path):
    p = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return True
        parent = os.path.dirname(p)
        if parent == p:
            return False
        p = parent


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.top = os.path.realpath(tempfile.mkdtemp(prefix="g7-"))
        self.repo = os.path.join(self.top, "repo")
        self.other = os.path.join(self.top, "other")
        os.makedirs(os.path.join(self.repo, ".git"))
        put(os.path.join(self.repo, ".git", "HEAD"), "ref: refs/heads/main\n")
        os.makedirs(os.path.join(self.repo, "src", "deep"))
        os.makedirs(self.other)
        self.e = Env()

    def ev(self, tool, agent="worker", cwd=None, **ti):
        return {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": cwd or self.repo,
                "agent_id": "a1", "agent_type": agent, "tool_name": tool, "tool_input": ti}

    def run_hook(self, tool, cwd=None, **ti):
        return self.e.run(HOOK, self.ev(tool, cwd=cwd, **ti))

    def assertDenied(self, r):
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("G7", r.stderr)
        ev = self.e.events()[-1]
        self.assertEqual((ev["guardrail"], ev["blocked"], ev["case_id"]), ("G7", True, "case-1"))

    def assertAllowed(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.e.events(), [])


class TestG7Denied(Base):
    def test_write_outside_root_denied(self):
        self.assertDenied(self.run_hook("Write", file_path=os.path.join(self.other, "a.py")))

    def test_dotdot_out_of_root_denied(self):
        self.assertDenied(self.run_hook("Write", file_path=os.path.join(self.repo, "..", "other", "a.py")))

    def test_symlink_in_repo_pointing_out_denied(self):
        os.symlink(self.other, os.path.join(self.repo, "lnk"))
        self.assertDenied(self.run_hook("Write", file_path=os.path.join(self.repo, "lnk", "a.py")))

    def test_edit_home_claude_denied(self):
        self.assertDenied(self.run_hook("Edit", file_path=os.path.expanduser("~/.claude/settings.json")))

    def test_no_git_root_denies_write(self):
        d = os.path.realpath(tempfile.mkdtemp(prefix="g7-nogit-"))
        if has_git_above(d):
            self.skipTest("a .git exists above the system temp dir")
        self.assertDenied(self.run_hook("Write", cwd=d, file_path=os.path.join(d, "a.py")))

    def test_bash_redirect_outside_denied(self):
        self.assertDenied(self.run_hook("Bash", command="echo x > %s/f" % self.other))

    def test_bash_cd_tmp_then_write_denied(self):
        self.assertDenied(self.run_hook("Bash", command="cd /tmp && echo x > f"))

    def test_bash_variable_target_denied(self):
        self.assertDenied(self.run_hook("Bash", command="echo x > $HOME/f"))

    def test_bash_code_piped_to_shell_denied(self):
        self.assertDenied(self.run_hook("Bash", command="echo 'touch %s/f' | sh" % self.other))

    def test_bash_wrapped_inline_code_denied(self):
        self.assertDenied(self.run_hook("Bash", command="timeout 5 bash -c 'touch %s/f'" % self.other))

    def test_bash_mv_to_outside_denied(self):
        self.assertDenied(self.run_hook("Bash", command="mv a.py %s/a.py" % self.other))


class TestG7Allowed(Base):
    def test_write_inside_root_allowed(self):
        self.assertAllowed(self.run_hook("Write", file_path=os.path.join(self.repo, "src", "a.py")))

    def test_write_in_subdirectory_cwd_uses_ancestor_root(self):
        self.assertAllowed(self.run_hook("Write", cwd=os.path.join(self.repo, "src", "deep"),
                                         file_path="../a.py"))

    def test_worktree_git_file_root(self):
        wt = os.path.join(self.top, "wt")
        os.makedirs(os.path.join(wt, "sub"))
        put(os.path.join(wt, ".git"), "gitdir: /somewhere/.git/worktrees/wt\n")
        self.assertAllowed(self.run_hook("Write", cwd=os.path.join(wt, "sub"), file_path="../a.py"))
        self.assertDenied(self.run_hook("Write", cwd=os.path.join(wt, "sub"),
                                        file_path=os.path.join(self.repo, "a.py")))

    def test_new_file_inside_root_allowed(self):
        self.assertAllowed(self.run_hook("Write", file_path=os.path.join(self.repo, "new", "x", "a.py")))

    def test_bash_redirect_inside_root_allowed(self):
        self.assertAllowed(self.run_hook("Bash", command="echo x > out.txt"))

    def test_bash_heredoc_file_and_git_commit_allowed(self):
        self.assertAllowed(self.run_hook("Bash", command="cat > a.py <<'EOF'\nx = \"it's\"\nEOF"))
        self.assertAllowed(self.run_hook("Bash", command="git commit -m \"$(cat <<'EOF'\nfix\nEOF\n)\""))

    def test_bash_pytest_and_cat_allowed(self):
        self.assertAllowed(self.run_hook("Bash", command="pytest -q 2>&1 | cat"))

    def test_bash_read_only_without_root_allowed(self):
        d = os.path.realpath(tempfile.mkdtemp(prefix="g7-nogit-"))
        self.assertAllowed(self.run_hook("Bash", cwd=d, command="ls && cat f"))

    def test_orchestrator_and_advisor_not_governed(self):
        ev = self.ev("Write", file_path=os.path.join(self.other, "a.py"))
        del ev["agent_id"]
        ev["agent_type"] = "orchestrator"
        self.assertAllowed(self.e.run(HOOK, ev))
        self.assertAllowed(self.e.run(HOOK, self.ev("Write", agent="advisor",
                                                    file_path=os.path.join(self.other, "a.py"))))

    def test_inert_without_agent_workflow(self):
        self.e = Env(workflow=None)
        self.assertAllowed(self.run_hook("Write", file_path=os.path.join(self.other, "a.py")))


class TestG7FailClosed(Base):
    def test_missing_path_denies(self):
        self.assertEqual(self.run_hook("Write", content="x").returncode, 2)

    def test_malformed_stdin_denies(self):
        self.assertEqual(self.e.run(HOOK, "{oops").returncode, 2)

    def test_missing_lib_denies(self):
        d = tempfile.mkdtemp(prefix="g7-nolib-")
        shutil.copy(os.path.join(HOOKS, HOOK), d)
        r = self.e.run(os.path.join(d, HOOK), self.ev("Write", file_path=os.path.join(self.repo, "a.py")))
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_unwritable_event_log_still_denies(self):
        put(self.e.dash, "")
        r = self.run_hook("Write", file_path=os.path.join(self.other, "a.py"))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("G7", r.stderr)


if __name__ == "__main__":
    unittest.main()
