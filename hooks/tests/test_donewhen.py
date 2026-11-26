"""Unit tests for hooks/lib/donewhen.py (G3/G4/G5 shared contract)."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from lib import donewhen as dw  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
