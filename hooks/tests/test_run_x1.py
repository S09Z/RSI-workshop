import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "run_x1.py")
SCRIPTS = ["g1_report_contract.py", "g2_orchestrator_nowrite.py", "g8_capture.py", "g8_worker_tests.py"]


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
        self.assertIn("blocked 15/15", r.stdout)
        self.assertIn("false_blocks 0/10", r.stdout)

    def test_runner_fails_on_always_allow_stub(self):
        r = run("--hook-dir", stub_dir("import sys\nsys.exit(0)\n"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("blocked 0/15", r.stdout)

    def test_runner_does_not_count_exit2_without_event(self):
        r = run("--hook-dir", stub_dir("import sys\nsys.exit(2)\n"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("blocked 0/15", r.stdout)

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
