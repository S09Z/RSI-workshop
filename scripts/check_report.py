#!/usr/bin/env python3
"""Evidence-log and report checker. Exit 0 = pass; nonzero = one line per failure on stdout."""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TYPES = {"peer-reviewed", "preprint", "vendor claim", "community anecdote"}
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}|n\.d\.)$")
ID_RE = re.compile(r"^E\d+$")


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def check_log(path):
    errs = []
    if not path.exists():
        return [f"log: {path} not found"], set()
    ids, seen = set(), set()
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue
        cells = split_row(line)
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c) or cells[0] == "id":
            continue
        if len(cells) != 7:
            errs.append(f"log line {n}: expected 7 columns, got {len(cells)}")
            continue
        for i, c in enumerate(cells):
            if not c:
                errs.append(f"log line {n}: column {i + 1} is empty")
        if cells[0] and not ID_RE.match(cells[0]):
            errs.append(f"log line {n}: bad id '{cells[0]}'")
        if cells[0] in seen:
            errs.append(f"log line {n}: duplicate id {cells[0]}")
        seen.add(cells[0])
        ids.add(cells[0])
        if cells[4] and not DATE_RE.match(cells[4]):
            errs.append(f"log line {n}: bad date '{cells[4]}'")
        if cells[5] and cells[5] not in TYPES:
            errs.append(f"log line {n}: bad evidence type '{cells[5]}'")
    return errs, ids


def sections(text):
    parts = list(re.finditer(r"^## (\d+)\.\s.*$", text, re.M))
    out = {}
    for i, m in enumerate(parts):
        end = parts[i + 1].start() if i + 1 < len(parts) else len(text)
        out[int(m.group(1))] = text[m.end():end]
    return [int(m.group(1)) for m in parts], out


def check_report(path, ids):
    errs = []
    if not path.exists():
        return [f"report: {path} not found"]
    text = path.read_text()
    order, secs = sections(text)
    if order != list(range(1, 12)):
        errs.append(f"report: headings '## N.' must be 1..11 in order, got {order}")
    if 1 in secs and len(secs[1].split()) > 200:
        errs.append(f"report: section 1 has {len(secs[1].split())} words (max 200)")
    for cited in sorted(set(re.findall(r"\[(E\d+)\]", text))):
        if cited not in ids:
            errs.append(f"report: citation [{cited}] not in evidence log")
    for n in range(2, 9):
        if n in secs:
            for word in ("Evidence", "Inference"):
                if not re.search(rf"^#{{3,6}}\s+\**{word}\b", secs[n], re.M):
                    errs.append(f"report: section {n} lacks '{word}' subheading")
    if 3 in secs and "```mermaid" not in secs[3]:
        errs.append("report: section 3 lacks a ```mermaid block")
    m = re.search(r"quality bar", text, re.I)
    if not m:
        errs.append("report: no 'Quality bar' checklist")
    else:
        tail = text[m.start():]
        boxes = re.findall(r"^\s*[-*]\s+\[( |x|X)\]\s*(.*)$", tail, re.M)
        if not boxes:
            errs.append("report: Quality bar has no checklist items")
        for state, rest in boxes:
            if state == " " and not re.search(r"\S{3,}.*(because|reason|—|--|:)", rest):
                errs.append(f"report: unticked quality-bar item lacks explanation: {rest[:50]}")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(ROOT / "docs/research/evidence-log.md"))
    ap.add_argument("--report", default=str(ROOT / "docs/report/rsi-research-report.md"))
    ap.add_argument("--log-only", action="store_true")
    a = ap.parse_args()
    errs, ids = check_log(Path(a.log))
    if not a.log_only:
        errs += check_report(Path(a.report), ids)
    for e in errs:
        print("FAIL", e)
    if errs:
        return 1
    print(f"PASS ({len(ids)} log rows{'' if a.log_only else ', report ok'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
