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
        cases = {"tee f": ["f"], "cp a b": ["a", "b"], "mv a b": ["a", "b"], "rm f": ["f"],
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


if __name__ == "__main__":
    unittest.main()
