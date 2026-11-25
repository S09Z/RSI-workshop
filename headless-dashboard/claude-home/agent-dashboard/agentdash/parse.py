"""Parse report blocks, task IDs and guardrail markers; redact secrets.

Used by the hook (at capture time, so report text never needs to be stored) and by the
ingester (for v1 events that still carry result_text).
"""
import re

TASK_ID_RE = re.compile(r"\[\s*([A-Za-z]+-?\d+)\s*\]")
STATUS_RE = re.compile(r"STATUS:\s*(WORKS|DOES_NOT_WORK|BLOCKED)", re.I)
CONF_RE = re.compile(r"CONFIDENCE:\s*(high|medium|low)", re.I)
ATTEMPTS_RE = re.compile(r"ATTEMPTS:\s*(\d+)")
FROM_MEMORY_RE = re.compile(r"FROM[ _]MEMORY:\s*(.+)", re.I)
VERIFICATION_RE = re.compile(r"VERIFICATION:\s*\n\s*-\s*command:\s*(\S.*)", re.I)
WORKER_BLOCK = "=== WORKER REPORT ==="
ADVISOR_BLOCK = "=== ADVISOR GUIDANCE ==="
# Guardrail hooks are expected to emit `GUARDRAIL G3: <reason>` (stderr / denial reason).
# `[G3]` and `G3 hit` are accepted too. Bare "G3" is not, to avoid false positives.
GUARDRAIL_RE = re.compile(r"(?:GUARDRAIL[ _:-]*(G\d{1,2})\b|\[(G\d{1,2})\]|\b(G\d{1,2})\s+hit\b)", re.I)

BUILTIN_REDACTIONS = [
    r"sk-ant-[A-Za-z0-9_\-]{10,}",
    r"sk-[A-Za-z0-9]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"xox[abprs]-[A-Za-z0-9\-]{10,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+",
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
]


def task_id(desc):
    if not desc:
        return None
    m = TASK_ID_RE.search(desc)
    return m.group(1).upper() if m else None


def task_key(desc):
    """v1-compatible key: the [Tn] ID, else the first 60 chars of the description."""
    if not desc:
        return "untagged"
    return task_id(desc) or desc.strip()[:60]


def guardrails(text):
    if not text:
        return []
    found = []
    for m in GUARDRAIL_RE.finditer(text):
        g = (m.group(1) or m.group(2) or m.group(3)).upper()
        if g not in found:
            found.append(g)
    return found


def report(text, agent=None):
    """Structured fields from a WORKER REPORT / ADVISOR GUIDANCE. Never returns the text."""
    text = text or ""
    out = {}
    is_worker = WORKER_BLOCK in text or (agent == "worker")
    is_advisor = ADVISOR_BLOCK in text or (agent == "advisor")
    if is_worker:
        m = STATUS_RE.search(text)
        out["status"] = m.group(1).upper() if m else "NO_REPORT"
        a = ATTEMPTS_RE.search(text)
        out["attempts"] = int(a.group(1)) if a else None
        out["has_verification"] = bool(VERIFICATION_RE.search(text))
        out["contract_ok"] = WORKER_BLOCK in text and bool(m)
    if is_advisor:
        c = CONF_RE.search(text)
        out["confidence"] = c.group(1).lower() if c else None
        fm = FROM_MEMORY_RE.search(text)
        if fm:
            val = fm.group(1).strip().strip("<>\"'` ").lower()
            out["from_memory"] = "none" if val in ("none", "n/a", "-", "") else "hit"
        else:
            out["from_memory"] = None  # field missing: excluded from memory metrics
        out["contract_ok"] = ADVISOR_BLOCK in text and bool(c)
    g = guardrails(text)
    if g:
        out["guardrails"] = g
    return out


def compile_redactions(extra=None):
    pats = BUILTIN_REDACTIONS + list(extra or [])
    out = []
    for p in pats:
        try:
            out.append(re.compile(p))
        except re.error:
            continue
    return out


_DEFAULT = compile_redactions()


def redact(text, patterns=None):
    if not text:
        return text
    for rx in (patterns or _DEFAULT):
        text = rx.sub("[REDACTED]", text)
    return text
