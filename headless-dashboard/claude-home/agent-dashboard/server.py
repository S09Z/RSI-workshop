#!/usr/bin/env python3
"""v1 entry point kept for backward compatibility. Delegates to agentdash (v2).

    python3 server.py                 # live UI, http://127.0.0.1:8765
    python3 server.py --json          # v1 /api/state JSON shape (use `orch-dashboard --json` for v2)
    python3 server.py --log FILE --port 9000 --project NAME
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentdash import cli  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--json" in argv and "--legacy" not in argv:
        argv.append("--legacy")
    sys.exit(cli.main(argv))
