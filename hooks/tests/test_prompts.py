"""The agent prompts must give G3, G4 and G5 the fields those hooks read."""
import os
import re
import unittest

AGENTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "agents")


def read(name):
    with open(os.path.join(AGENTS, name)) as f:
        return f.read()


class Prompts(unittest.TestCase):
    def test_orchestrator_fields(self):
        text = read("orchestrator.md")
        for needle in ("DONE_WHEN_FILES:", "DONE_WHEN_CMD:", "TASK_KIND: write-test", "never reuse an ID",
                       "python3 -m unittest", "fails"):
            self.assertIn(needle, text)

    def test_worker_fields(self):
        text = read("worker.md")
        for needle in ("TASK: [T", "- ran_at:", "date -u +%Y-%m-%dT%H:%M:%SZ", "DONE_WHEN_CMD"):
            self.assertIn(needle, text)
        report = text.split("=== WORKER REPORT ===", 1)[1].split("=== END REPORT ===", 1)[0]
        self.assertLess(report.index("VERIFICATION:"), report.index("- ran_at:"))
        self.assertLess(report.index("- ran_at:"), report.index("ATTEMPTS:"))

    def test_frontmatter_kept(self):
        for name in ("orchestrator.md", "worker.md"):
            text = read(name)
            self.assertTrue(text.startswith("---\n"), name)
            self.assertRegex(text.split("---", 2)[1], re.compile(r"^model: \S+", re.M))


if __name__ == "__main__":
    unittest.main()
