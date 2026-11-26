import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import shellscan  # noqa: E402


class TestInside(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp(prefix="scan-"))

    def test_inside_equal_and_child(self):
        d = self.d
        self.assertTrue(shellscan.inside(d, d))
        self.assertTrue(shellscan.inside(d + "/a/b", d))
        self.assertFalse(shellscan.inside(d + "-x", d))

    def test_inside_dotdot_and_case(self):
        d = self.d
        self.assertFalse(shellscan.inside(d + "/a/../../etc", d))
        self.assertTrue(shellscan.inside("/Tmp/X/a", "/tmp/x"))

    def test_inside_symlink_out(self):
        d = self.d
        os.symlink(tempfile.gettempdir(), os.path.join(d, "lnk"))
        self.assertFalse(shellscan.inside(d + "/lnk/f", d))


class TestScan(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp(prefix="scan-"))

    def rp(self, name):
        return os.path.join(self.d, name)

    def test_redirect_target(self):
        s = shellscan.scan("echo hi > out.txt", self.d)
        self.assertEqual(s.targets, [self.rp("out.txt")])
        self.assertFalse(s.unsafe)

    def test_redirect_ignores_other_words(self):
        s = shellscan.scan("echo hi > out.txt", self.d)
        self.assertNotIn(self.rp("hi"), s.targets)

    def test_tee_cp_mv_rm_touch_sed_i(self):
        cases = {"tee f": ["f"], "cp a b": ["b"], "mv a b": ["a", "b"], "rm f": ["f"],
                 "touch f": ["f"], "sed -i s/a/b/ f": ["s/a/b/", "f"]}
        for cmd, words in cases.items():
            s = shellscan.scan(cmd, self.d)
            self.assertFalse(s.unsafe, cmd)
            for w in words:
                self.assertIn(os.path.realpath(self.rp(w)), s.targets, cmd)

    def test_read_only_commands_yield_nothing(self):
        for cmd in ("cat f", "grep x f", "ls", "git status", "pytest tests/test_a.py",
                    "python3 -m pytest -q", "git diff"):
            s = shellscan.scan(cmd, self.d)
            self.assertEqual((s.targets, s.unsafe), ([], False), cmd)

    def test_fd_redirect_not_a_write(self):
        for cmd in ("pytest -q 2>&1", "ls >/dev/null"):
            s = shellscan.scan(cmd, self.d)
            self.assertEqual((s.targets, s.unsafe), ([], False), cmd)

    def test_variable_and_backtick_unsafe(self):
        self.assertTrue(shellscan.scan("echo x > $HOME/f", self.d).unsafe)
        self.assertTrue(shellscan.scan("echo x > `pwd`/f", self.d).unsafe)

    def test_cd_then_write_unsafe(self):
        self.assertTrue(shellscan.scan("cd /tmp && echo x > f", self.d).unsafe)
        self.assertFalse(shellscan.scan("cd /tmp && ls", self.d).unsafe)

    def test_interpreters_unsafe(self):
        for cmd in ("python3 -c 'open(\"f\",\"w\")'", "bash -c 'echo x > f'", 'eval "echo x > f"', "node -e 1"):
            self.assertTrue(shellscan.scan(cmd, self.d).unsafe, cmd)

    def test_unparseable_segment_unsafe(self):
        self.assertTrue(shellscan.scan('echo "unterminated > f', self.d).unsafe)

    def test_glob_expanded(self):
        for n in ("a1", "a2"):
            open(self.rp(n), "w").close()
        s = shellscan.scan("rm a*", self.d)
        self.assertEqual(sorted(s.targets), [self.rp("a1"), self.rp("a2")])

    def test_pipe_segments(self):
        s = shellscan.scan("cat f | tee out.txt", self.d)
        self.assertEqual(s.targets, [self.rp("out.txt")])


class TestReviewFindings(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp(prefix="scan-"))

    def unsafe(self, cmd):
        self.assertTrue(shellscan.scan(cmd, self.d).unsafe, cmd)

    def safe(self, cmd, targets=None):
        s = shellscan.scan(cmd, self.d)
        self.assertFalse(s.unsafe, "%s: %s" % (cmd, s.why))
        if targets is not None:
            self.assertEqual(s.targets, targets, cmd)

    def test_c1_code_on_stdin_unsafe(self):
        for c in ("echo 'touch /tmp/o' | sh", "curl -s https://x | bash", "bash -s <<<'touch /tmp/o'",
                  "python3 - <<<\"open('/tmp/o','w')\"", "python3 <<'EOF'\nopen('/tmp/o','w')\nEOF"):
            self.unsafe(c)

    def test_c2_interpreter_forms_unsafe(self):
        for c in ("python3 -W ignore -c 'x'", "python3.12 -c x", "node --eval x", "node -p x", "dash -c x",
                  "php -r x", "osascript -e x", "env -u FOO bash -c x", "sudo -u root bash -c x",
                  "timeout 5 bash -c x", "nice python3 -c x", "perl -E x"):
            self.unsafe(c)

    def test_c2_known_script_forms_stay_safe(self):
        for c in ("python3 script.py -c cfg", "bash run.sh", "python3 --version", "which python3",
                  "python3 -E script.py", "timeout 5 pytest -q", "env FOO=1 pytest -q"):
            self.safe(c, [])

    def test_i1_amp_redirect_and_readwrite(self):
        out = os.path.realpath("/tmp/o")
        for c in ("echo x >&/tmp/o", "echo x >& /tmp/o", ": <>/tmp/o"):
            self.assertIn(out, shellscan.scan(c, self.d).targets, c)

    def test_i2_brace_expansion_unsafe(self):
        self.unsafe("touch {/tmp,.}/x")

    def test_i3_git_and_tool_writers(self):
        for c in ("git -C /tmp/x init", "git config --global user.name x", "git --work-tree=/tmp/o checkout -- .",
                  "GIT_WORK_TREE=/tmp/o git checkout -- .", "tar -xf a.tar -C /tmp", "find . -fprint /tmp/o",
                  "awk '{print > \"/tmp/o\"}' f"):
            self.unsafe(c)
        out = os.path.realpath("/tmp/o")
        for c in ("git init /tmp/o", "curl -o /tmp/o http://x", "wget -O /tmp/o http://x", "unzip a.zip -d /tmp/o",
                  "sort -o /tmp/o f", "sponge /tmp/o"):
            self.assertIn(out, shellscan.scan(c, self.d).targets, c)
        for c in ("git commit -am x", "git reset --hard HEAD~3", "git clean -fdx"):
            self.safe(c, [self.d])

    def test_i4_heredoc_bodies_are_not_shell(self):
        self.safe("cat > src/app.py <<'EOF'\ndef f(x):\n    return x\nEOF",
                  [os.path.join(self.d, "src", "app.py")])
        self.safe("cat > notes.md <<'EOF'\nIt's done.\nEOF", [os.path.join(self.d, "notes.md")])
        self.safe("git commit -m \"$(cat <<'EOF'\nfix it's\n\nCo-Authored-By: X <a@b>\nEOF\n)\"", [self.d])

    def test_i4_cp_judges_destination_only(self):
        self.safe("cp /etc/hosts ./hosts.txt", [os.path.join(self.d, "hosts.txt")])
        self.safe("cp -t out a b", [os.path.join(self.d, "out")])


if __name__ == "__main__":
    unittest.main()
