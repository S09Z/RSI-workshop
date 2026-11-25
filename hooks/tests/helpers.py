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
