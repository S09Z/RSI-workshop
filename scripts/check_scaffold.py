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

# hooks/ has no executable scripts.
# NOTE (Harden, ADR-0001): this rule must be relaxed in the Harden change, which creates hooks/g*.py.
# Relax it then, not now: allow only scripts that hooks/guardrails.yaml references and that have tests.
hooks = ROOT / "hooks"
if hooks.is_dir():
    for p in hooks.rglob("*"):
        if p.is_file():
            if os.access(p, os.X_OK):
                fail(f"hooks/ file has exec bit: {p.relative_to(ROOT)}")
            if p.suffix in {".sh", ".py", ".js"}:
                fail(f"hooks/ script suffix not allowed: {p.relative_to(ROOT)}")

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
