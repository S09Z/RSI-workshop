"""Shared test helpers: run a hook script as a subprocess with isolated env dirs."""
import json
import os
import subprocess
import sys
import tempfile

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Env:
    def __init__(self, workflow="1", case_id="case-1", **extra):
        self.tmp = tempfile.mkdtemp(prefix="hooktest-")
        self.dash = os.path.join(self.tmp, "dash")
        self.state = os.path.join(self.tmp, "state")
        self.env = {
            "PATH": os.environ.get("PATH", ""),
            "AGENT_DASHBOARD_DIR": self.dash,
            "AGENT_HOOK_STATE_DIR": self.state,
            "AGENT_HOOK_CASE_ID": case_id,
        }
        if workflow is not None:
            self.env["AGENT_WORKFLOW"] = workflow
        self.env.update(extra)

    def run(self, script, stdin):
        """script: path or name under hooks/. stdin: dict or raw str. Returns CompletedProcess."""
        path = script if os.path.isabs(script) else os.path.join(HOOKS, script)
        data = stdin if isinstance(stdin, str) else json.dumps(stdin)
        return subprocess.run([sys.executable, "-I", path], input=data, text=True,
                              capture_output=True, env=self.env, timeout=30)

    def events(self):
        p = os.path.join(self.dash, "events.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(x) for x in f if x.strip()]


FAILING = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(False)\n"
PASSING = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"
CMD = "python3 -m unittest tests/test_new.py"


class Project:
    """A temp git repo with one acceptance test, plus G5/SubagentStop events for it (G3, G4, G5 tests)."""

    def __init__(self, body=FAILING, git=True):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="dwproj-"))
        if git:
            os.mkdir(os.path.join(self.root, ".git"))
        os.mkdir(os.path.join(self.root, "tests"))
        self.test(body)

    def test(self, body):
        with open(os.path.join(self.root, "tests", "test_new.py"), "w") as f:
            f.write(body)

    def dispatch(self, task="T1", cmd=CMD, files="tests/test_new.py", kind=None, agent="worker", description=None):
        lines = ["do the task", "DONE_WHEN_FILES: %s" % files]
        if cmd is not None:
            lines.append("DONE_WHEN_CMD: %s" % cmd)
        if kind:
            lines.append("TASK_KIND: %s" % kind)
        desc = "[%s] do it" % task if description is None else description
        return {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": "s1", "cwd": self.root,
                "tool_input": {"subagent_type": agent, "description": desc, "prompt": "\n".join(lines)}}

    def stop(self, status="WORKS", task="[T1] ", ran_at=None, message=None, active=False, agent="worker"):
        if message is None:
            message = ("done\n=== WORKER REPORT ===\nTASK: %sdo it\nSTATUS: %s\nFINDINGS:\n- x\nCHANGES:\n- y\n"
                       "VERIFICATION:\n- command: %s\n- result: ok\n%sATTEMPTS: 1/3\n=== END REPORT ===" %
                       (task, status, CMD, "- ran_at: %s\n" % ran_at if ran_at else ""))
        return {"hook_event_name": "SubagentStop", "agent_type": agent, "agent_id": "a1", "session_id": "s1",
                "cwd": self.root, "stop_hook_active": active, "last_assistant_message": message}
