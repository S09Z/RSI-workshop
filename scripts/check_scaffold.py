#!/usr/bin/env python3
"""Scaffold check. Exit 0 = pass; nonzero = one line per failure on stdout."""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if len(sys.argv) == 3 and sys.argv[1] == "--root":
    ROOT = Path(sys.argv[2]).resolve()

REQUIRED_FILES = [
    "scripts/check_scaffold.py", "scripts/install.sh", ".gitignore", "README.md", "PROTECTED.paths",
    "agents/orchestrator.md", "agents/worker.md", "agents/advisor.md",
    "skills/README.md", "hooks/README.md", "hooks/guardrails.yaml",
    "routing/routing.yaml",
    "memory/advisor/MEMORY.md", "memory/advisor/SCHEMA.md",
    "memory/advisor/projects/.gitkeep", "memory/advisor/topics/.gitkeep",
    "evals/README.md", "evals/tasks/train/README.md", "evals/tasks/heldout/README.md",
    "evals/configs/single-agent.yaml", "evals/configs/orch-worker.yaml",
    "evals/configs/full-system.yaml", "evals/graders/README.md",
    "evals/results/.gitkeep",
    "proposals/TEMPLATE.md", "proposals/inbox/.gitkeep",
    "proposals/accepted/.gitkeep", "proposals/rejected/.gitkeep",
    "telemetry/events.schema.json", "docs/architecture.md", "docs/adr/.gitkeep",
    "docs/research/evidence-log.md",
]

REQUIRED_PROTECTED = [
    "hooks/", "evals/graders/", "evals/tasks/heldout/", "PROTECTED.paths",
    "scripts/install.sh",
]
fails = []


def fail(msg):
    fails.append(msg)


def read(rel):
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


for rel in REQUIRED_FILES:
    if not (ROOT / rel).is_file():
        fail(f"missing file: {rel}")

# PROTECTED.paths
prot = [l.strip() for l in read("PROTECTED.paths").splitlines()
        if l.strip() and not l.strip().startswith("#")]
for req in REQUIRED_PROTECTED:
    if req not in prot:
        fail(f"PROTECTED.paths missing required line: {req}")
for line in prot:
    if not (ROOT / line).exists():
        fail(f"PROTECTED.paths line not on disk: {line}")

# hooks/: no exec bit, no .sh/.js. A .py file is allowed only if it is a test or lib file, or is listed in a
# guardrail's `hook:` in hooks/guardrails.yaml AND some file under hooks/tests/ mentions its name (ADR-0001).
# (The guardrails.yaml parse below runs first; this block is checked after it.)
# guardrails.yaml: line-based parse (no yaml dependency)
g_text = read("hooks/guardrails.yaml")
entries = {}
cur = None
for line in g_text.splitlines():
    # accepts `- id: G3`, `- id: "G3"`, `- id: 'G3'`, each with an optional trailing `# comment`
    m = re.match(r"""\s*-\s*id:\s*(["']?)(G\d+)\1\s*(#.*)?$""", line)
    if m:
        cur = m.group(2)
        if cur in entries:
            fail(f"guardrails.yaml duplicate id: {cur}")
        entries[cur] = {}
        continue
    m = re.match(r"\s+(\w+):\s*(.*?)\s*$", line)
    if m and cur:
        entries[cur][m.group(1)] = m.group(2)
for n in range(1, 9):
    gid = f"G{n}"
    if gid not in entries:
        fail(f"guardrails.yaml missing {gid}")
    elif entries[gid].get("status") != "active":
        fail(f"guardrails.yaml {gid} status is not active")
    if gid in entries:
        if entries[gid].get("protected") != "true":
            fail(f"guardrails.yaml {gid} protected is not true")
        if not entries[gid].get("name"):
            fail(f"guardrails.yaml {gid} has empty name")
for gid, e in entries.items():
    if e.get("enforced") not in ("true", "false"):
        fail(f"guardrails.yaml {gid} enforced must be true or false")
    if int(gid[1:]) >= 9 and e.get("status") != "proposed":
        fail(f"guardrails.yaml {gid} status is not proposed")

# Harden: G1/G2/G8 are implemented (blocking hook code + tests) but not yet enforced (not registered).
HARDEN = ("G1", "G2", "G8")
listed_hooks = set()
for gid, e in entries.items():
    hv = e.get("hook", "").strip()
    items = [x.strip().strip("'\"") for x in hv.strip("[]").split(",") if x.strip()] if hv else []
    if gid in HARDEN:
        if e.get("implemented") != "true":
            fail(f"guardrails.yaml {gid} implemented must be true")
        if e.get("enforced") != "false":
            fail(f"guardrails.yaml {gid} enforced must stay false until registered and X1 live layer passes")
        if not items:
            fail(f"guardrails.yaml {gid} has no hook: list")
    elif e.get("implemented") == "true":
        fail(f"guardrails.yaml {gid} implemented true without a hook in this round")
    listed_hooks.update(items)

hooks = ROOT / "hooks"
if hooks.is_dir():
    test_text = "".join(t.read_text(encoding="utf-8") for t in (hooks / "tests").rglob("*.py")) if (hooks / "tests").is_dir() else ""
    for p in hooks.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if os.access(p, os.X_OK):
            fail(f"hooks/ file has exec bit: {rel}")
        if p.suffix in {".sh", ".js"}:
            fail(f"hooks/ script suffix not allowed: {rel}")
        if p.suffix == ".py" and not rel.startswith(("hooks/lib/", "hooks/tests/")):
            if rel not in listed_hooks:
                fail(f"hooks/ script not listed in guardrails.yaml hook:: {rel}")
            elif p.name not in test_text:
                fail(f"hooks/ script has no test mentioning it: {rel}")

# .gitignore
if "evals/results/raw/" not in read(".gitignore").splitlines():
    fail(".gitignore missing evals/results/raw/")

# agents
for f in sorted((ROOT / "agents").glob("*.md")):
    t = f.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", t, re.S)
    rel = f.relative_to(ROOT)
    if not m:
        fail(f"{rel}: no frontmatter")
        continue
    fm, _body = m.groups()
    fields = {}
    for line in fm.splitlines():
        km = re.match(r"([A-Za-z_]+):\s*(.*?)\s*$", line)
        if km:
            fields[km.group(1)] = km.group(2)
    for key in ("name", "model", "description", "tools"):
        if not fields.get(key):
            fail(f"{rel}: frontmatter missing or empty {key}")
    if f.name == "orchestrator.md" and "Agent(worker, advisor)" not in fields.get("tools", ""):
        fail(f"{rel}: tools lacks Agent(worker, advisor)")
    if f.name == "advisor.md" and fields.get("memory") != "user":
        fail(f"{rel}: advisor lacks memory: user")

if fails:
    print("\n".join(fails))
    sys.exit(1)
print("scaffold OK")
