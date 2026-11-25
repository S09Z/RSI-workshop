import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "run_x1.py")
SCRIPTS = ["g1_report_contract.py", "g2_orchestrator_nowrite.py", "g6_advisor_memory.py", "g7_worker_gitroot.py",
           "g8_capture.py", "g8_worker_tests.py"]


def run(*args):
    return subprocess.run([sys.executable, "-I", RUNNER, *args], capture_output=True, text=True, timeout=300)


def stub_dir(body):
    d = tempfile.mkdtemp(prefix="stubhooks-")
    for s in SCRIPTS:
        with open(os.path.join(d, s), "w") as f:
            f.write(body)
    return d


class TestRunner(unittest.TestCase):
    def test_runner_passes_on_real_hooks(self):
        r = run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        import re
        m = re.search(r"blocked (\d+)/(\d+)", r.stdout)
        self.assertTrue(m and m.group(1) == m.group(2) and int(m.group(2)) >= 44, r.stdout[-300:])
        m = re.search(r"false_blocks (\d+)/(\d+)", r.stdout)
        self.assertTrue(m and m.group(1) == "0" and int(m.group(2)) >= 17, r.stdout[-300:])

    def test_runner_fails_on_always_allow_stub(self):
        r = run("--hook-dir", stub_dir("import sys\nsys.exit(0)\n"))
        self.assertNotEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"blocked 0/\d+")

    def test_runner_does_not_count_exit2_without_event(self):
        r = run("--hook-dir", stub_dir("import sys\nsys.exit(2)\n"))
        self.assertNotEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"blocked 0/\d+")

    def test_runner_fails_with_too_few_violation_fixtures(self):
        import shutil
        fx = tempfile.mkdtemp(); src = os.path.join(HERE, "fixtures", "x1")
        for n in os.listdir(src):
            if n.startswith("c-"):
                shutil.copy(os.path.join(src, n), fx)
        r = run("--fixtures", fx)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("too few", r.stdout)

    def test_runner_requires_g6_and_g7_violations(self):
        import shutil
        src = os.path.join(HERE, "fixtures", "x1")
        for g in ("g6", "g7"):
            fx = tempfile.mkdtemp()
            for n in os.listdir(src):
                if not n.startswith("v-%s-" % g):
                    shutil.copy(os.path.join(src, n), fx)
            r = run("--fixtures", fx)
            self.assertNotEqual(r.returncode, 0, r.stdout[-300:])
            self.assertIn("too few", r.stdout)
            self.assertIn(g.upper(), r.stdout.split("too few")[1])

    def test_runner_fails_when_pre_hook_fails(self):
        import json
        fx = tempfile.mkdtemp()
        with open(os.path.join(fx, "v-x.json"), "w") as f:
            json.dump({"case_id": "x", "guardrail": "G2", "hook": "g2_orchestrator_nowrite.py", "expect": "block",
                       "pre": [{"hook": "no_such_hook.py", "stdin": {}}],
                       "stdin": {"agent_type": "orchestrator", "tool_name": "Write", "cwd": "/tmp", "tool_input": {"file_path": "/tmp/a"}}}, f)
        r = run("--fixtures", fx)
        self.assertIn("pre hook failed", r.stdout)

    def test_runner_flags_over_blocking_stub_as_false_blocks(self):
        body = ("import sys, os, json\nd = os.environ['AGENT_DASHBOARD_DIR']; os.makedirs(d, exist_ok=True)\n"
                "g = os.path.basename(sys.argv[0])[:2].upper()\n"
                "open(os.path.join(d, 'events.jsonl'), 'a').write(json.dumps({'guardrail': 'G8' if g == 'G8' else g, 'blocked': True, 'case_id': os.environ['AGENT_HOOK_CASE_ID']}) + '\\n')\n"
                "sys.exit(2)\n")
        r = run("--hook-dir", stub_dir(body))
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("false_blocks 0/10", r.stdout)


if __name__ == "__main__":
    unittest.main()
