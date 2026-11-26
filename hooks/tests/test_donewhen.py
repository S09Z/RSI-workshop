"""Unit tests for hooks/lib/donewhen.py (G3/G4/G5 shared contract)."""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from lib import donewhen as dw  # noqa: E402

try:
    import pytest  # noqa: F401
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False


def put(root, rel, text=""):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)
    return p


def project():
    root = os.path.realpath(tempfile.mkdtemp(prefix="dw-"))
    os.mkdir(os.path.join(root, ".git"))
    put(root, "tests/test_a.py")
    put(root, "tests/other_test.py")
    return root


def prompt(cmd, files="tests/test_a.py", head="fix it"):
    return "%s\nDONE_WHEN_FILES: %s\nDONE_WHEN_CMD: %s" % (head, files, cmd)


class ParseValidate(unittest.TestCase):
    def setUp(self):
        self.root = project()
        self.a = os.path.join(self.root, "tests", "test_a.py")

    def check(self, cmd, files="tests/test_a.py"):
        try:
            d = dw.parse(prompt(cmd, files), self.root, "[T1] x")
        except ValueError as e:
            return str(e)  # rejected while parsing the raw line
        return dw.validate(d, self.root)

    def test_parse_dispatch(self):
        d = dw.parse(prompt("pytest -q tests/test_a.py", head="[T1] fix"), self.root)
        self.assertEqual((d.task, d.kind, d.argv), ("T1", "test", ["pytest", "-q", "tests/test_a.py"]))
        self.assertEqual(d.files, [self.a])

    def test_id_from_description_wins(self):
        d = dw.parse(prompt("pytest tests/test_a.py", head="[T9] x"), self.root, "[T2] y")
        self.assertEqual(d.task, "T2")

    def test_write_test(self):
        d = dw.parse("[T1] write\nDONE_WHEN_FILES: tests/test_a.py\nTASK_KIND: write-test", self.root)
        self.assertEqual((d.kind, d.argv), ("write-test", []))
        self.assertIsNone(dw.validate(d, self.root))

    def test_parse_errors(self):
        ok = "DONE_WHEN_CMD: pytest tests/test_a.py"
        for text in ("fix\n" + ok, "[T1] x\nDONE_WHEN_FILES: tests/test_a.py", "",
                     "[T1] x\n%s\n%s" % (ok, ok), "[T1] x\n%s\nTASK_KIND: write-test" % ok,
                     '[T1] x\nDONE_WHEN_CMD: pytest "unclosed', "[T1] x\nDONE_WHEN_CMD:   "):
            with self.subTest(text=text), self.assertRaises(ValueError):
                dw.parse(text, self.root)

    def test_allowed(self):
        for cmd in ("pytest tests/test_a.py", "pytest -q -v -x --tb=short --maxfail=2 -k name -m slow tests/test_a.py",
                    "pytest tests/test_a.py::test_one", "python3 -m pytest -q tests/test_a.py",
                    "python3 -m unittest -v -f -k name tests/test_a.py"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.check(cmd))

    def test_rejected(self):
        for cmd in ("pytest -q tests/test_a.py; rm -rf x", "pytest -p evil tests/test_a.py",
                    "pytest -o addopts=--cov tests/test_a.py", "pytest tests/", "pytest tests/other_test.py",
                    'bash -c "pytest"', 'python3 -c "print(1)"', "pytest $(echo x)",
                    "pytest tests/test_a.py --junitxml=out.xml", "pytest -c x.ini tests/test_a.py",
                    "pytest --rootdir=/ tests/test_a.py", "pytest `echo` tests/test_a.py", "pytest > out",
                    "pytest", "pytest -q", "python3 -m unittest", "python3 -m unittest discover",
                    "python3 -m unittest tests.test_a", "python3 -m unittest -q tests/test_a.py::x",
                    "pytest -k tests/test_a.py", "pytest --tb=auto tests/test_a.py", "python tests/test_a.py",
                    "/tmp/pytest tests/test_a.py", "FOO=1 pytest tests/test_a.py", "python3 -m pip install x"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.check(cmd))

    def test_argsfile_and_non_py_rejected(self):
        put(self.root, "@args", "-p\nevil\n")
        put(self.root, "tests/data.txt")
        self.assertIsNotNone(self.check("pytest @args", "@args"))
        self.assertIsNotNone(self.check("pytest tests/data.txt", "tests/data.txt"))

    def test_symlink_out_of_root(self):
        out = put(os.path.realpath(tempfile.mkdtemp(prefix="dw-out-")), "test_x.py")
        os.symlink(out, os.path.join(self.root, "tests", "test_link.py"))
        self.assertIsNotNone(self.check("pytest tests/test_link.py", "tests/test_link.py"))

    def test_git_root(self):
        sub = os.path.join(self.root, "tests")
        self.assertEqual(dw.git_root(sub), self.root)
        wt = os.path.realpath(tempfile.mkdtemp(prefix="dw-wt-"))
        put(wt, ".git", "gitdir: /elsewhere\n")
        self.assertEqual(dw.git_root(wt), wt)
        bare = os.path.realpath(tempfile.mkdtemp(prefix="dw-none-"))
        self.assertIsNone(dw.git_root(bare))
        self.assertIsNone(dw.git_root(""))


FAIL = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(1, 2)\n"
PASS = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"
SKIP = ("import unittest\nclass T(unittest.TestCase):\n    @unittest.skip('no')\n"
        "    def test_x(self):\n        pass\n")


class RunClassify(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="dw-run-"))
        os.mkdir(os.path.join(self.root, ".git"))

    def go(self, body, runner=("python3", "-m", "unittest", "-v"), name="test_t.py", timeout=None):
        f = put(self.root, "tests/" + name, body)
        d = dw.Dispatch("T1", "test", list(runner) + ["tests/" + name], [os.path.realpath(f)])
        return dw.run(d, self.root, timeout)

    def test_failed(self):
        r = self.go(FAIL)
        self.assertEqual((r.status, r.failed), ("failed", 1))

    def test_passed(self):
        r = self.go(PASS)
        self.assertEqual((r.status, r.passed, r.returncode), ("passed", 1, 0))

    def test_not_run_is_error(self):
        for body in ("", SKIP, "import sys\nsys.exit(0)\n"):
            with self.subTest(body=body):
                self.assertEqual(self.go(body).status, "error")

    def test_syntax_error_is_error(self):
        self.assertEqual(self.go("def (:\n").status, "error")

    def test_timeout_kills_group(self):
        marker = os.path.join(self.root, "late")
        child = "import time; time.sleep(3); open(%r, 'w')" % marker
        body = ("import subprocess, sys, time\n"
                "subprocess.Popen([sys.executable, '-c', %r])\n"
                "time.sleep(30)\n" % child)
        t0 = time.time()
        r = self.go(body, timeout=1)
        self.assertEqual((r.status, r.tail), ("error", "timeout"))
        self.assertLess(time.time() - t0, 10)
        time.sleep(3)
        self.assertFalse(os.path.exists(marker))

    def test_child_holding_output_does_not_hang(self):
        body = ("import subprocess, sys\n"
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'], start_new_session=True)\n" + PASS)
        t0 = time.time()
        self.assertEqual(self.go(body).status, "passed")
        self.assertLess(time.time() - t0, 10)

    def test_missing_runner_and_unknown_codes_are_error(self):
        for code in (127, 2, 3, 4, 5, None):
            with self.subTest(code=code):
                self.assertEqual(dw.classify("pytest", code, "1 passed in 0.1s")[0], "error")
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = ""
        try:
            self.assertEqual(self.go(PASS, runner=("pytest",)).status, "error")
        finally:
            os.environ["PATH"] = old

    def test_disallowed_command_not_executed(self):
        marker = os.path.join(self.root, "ran")
        d = dw.Dispatch("T1", "test", ["python3", "-c", "open(%r,'w')" % marker], [])
        self.assertEqual(dw.run(d, self.root).status, "error")
        self.assertFalse(os.path.exists(marker))

    def test_env_scrubbed_and_tail_bounded(self):
        os.environ["SECRET_TOKEN_X"] = "s3cr3t-value"
        try:
            r = self.go("import os\nprint('x' * 5000)\nprint('TOKEN=', os.environ.get('SECRET_TOKEN_X'))\n" + PASS)
        finally:
            del os.environ["SECRET_TOKEN_X"]
        self.assertEqual(r.status, "passed")
        self.assertLessEqual(len(r.tail), 800)
        self.assertNotIn("s3cr3t-value", r.tail)

    @unittest.skipUnless(HAS_PYTEST, "pytest not installed")
    def test_pytest(self):
        run = ("python3", "-m", "pytest", "-q")
        self.assertEqual(self.go(FAIL, runner=run).status, "failed")
        self.assertEqual(self.go(PASS, runner=run, name="test_p.py").status, "passed")
        self.assertEqual(self.go("", runner=run, name="test_e.py").status, "error")
        self.assertEqual(self.go(SKIP, runner=run, name="test_s.py").status, "error")
        self.assertEqual(self.go("def (:\n", runner=run, name="test_bad.py").status, "error")

    def test_timeout_seconds(self):
        old = os.environ.pop("AGENT_DONEWHEN_TIMEOUT", None)
        try:
            self.assertEqual(dw.timeout_seconds(), 120.0)
            for bad in ("abc", "-1", "0", "inf", "nan"):
                os.environ["AGENT_DONEWHEN_TIMEOUT"] = bad
                self.assertEqual(dw.timeout_seconds(), 120.0, bad)
            os.environ["AGENT_DONEWHEN_TIMEOUT"] = "7"
            self.assertEqual(dw.timeout_seconds(), 7.0)
        finally:
            os.environ.pop("AGENT_DONEWHEN_TIMEOUT", None)
            if old is not None:
                os.environ["AGENT_DONEWHEN_TIMEOUT"] = old


class Records(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="dw-state-")
        self.old = os.environ.get("AGENT_HOOK_STATE_DIR")
        os.environ["AGENT_HOOK_STATE_DIR"] = self.state

    def tearDown(self):
        if self.old is None:
            os.environ.pop("AGENT_HOOK_STATE_DIR", None)
        else:
            os.environ["AGENT_HOOK_STATE_DIR"] = self.old

    def write(self, sid, task, at="2026-01-01T00:00:00Z"):
        d = dw.Dispatch(task, "test", ["pytest", "t.py"], ["/r/t.py"])
        dw.write_record(sid, d, "pytest t.py", at, "/r")

    def test_roundtrip(self):
        self.write("s1", "T1")
        r = dw.read_record("s1", "T1")
        self.assertEqual((r["task"], r["kind"], r["argv"], r["files"], r["root"], r["cmd_text"], r["dispatched_at"], r["stopped"]),
                         ("T1", "test", ["pytest", "t.py"], ["/r/t.py"], "/r", "pytest t.py", "2026-01-01T00:00:00Z", False))

    def test_missing_corrupt_and_non_dict(self):
        self.assertIsNone(dw.read_record("s1", "T9"))
        self.write("s1", "T1")
        for text in ("{not json", "[1]", "{}"):
            put(self.state, os.path.relpath(dw.record_path("s1", "T1"), self.state), text)
            self.assertIsNone(dw.read_record("s1", "T1"), text)
        self.assertIsNone(dw.newest_open("s1"))

    def test_newest_open_per_session(self):
        self.write("a", "T1")
        time.sleep(0.01)
        self.write("a", "T2")
        time.sleep(0.01)
        self.write("a-b", "T3")
        self.assertEqual(dw.newest_open("a")["task"], "T2")
        dw.mark_stopped("a", "T2")
        self.assertEqual(dw.newest_open("a")["task"], "T1")
        self.assertTrue(dw.read_record("a", "T2")["stopped"])
        dw.mark_stopped("a", "T1")
        self.assertIsNone(dw.newest_open("a"))
        self.assertIsNone(dw.newest_open("nobody"))

    def test_other_sessions_record_not_read(self):
        self.write("a/b", "T1")
        self.assertIsNone(dw.read_record("a_b", "T1"))  # same file name, different session

    def test_prune(self):
        self.write("s1", "T1")
        old = time.time() - 25 * 3600
        os.utime(dw.record_path("s1", "T1"), (old, old))
        self.write("s1", "T2")
        self.assertIsNone(dw.read_record("s1", "T1"))
        self.assertIsNotNone(dw.read_record("s1", "T2"))

    def test_sanitized_path(self):
        p = dw.record_path("../x", "../T1")
        self.assertEqual(os.path.dirname(p), os.path.join(self.state, "donewhen"))

    def test_now_iso(self):
        self.assertRegex(dw.now_iso(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


if __name__ == "__main__":
    unittest.main()
