"""Parse report blocks, task IDs and guardrail markers; redact secrets.

Used by the hook (at capture time, so report text never needs to be stored) and by the
ingester (for v1 events that still carry result_text).
"""
import re

TASK_ID_RE = re.compile(r"\[\s*([A-Za-z]+-?\d+)\s*\]")
STATUS_RE = re.compile(r"STATUS:\s*(WORKS|DOES_NOT_WORK|BLOCKED)", re.I)
CONF_RE = re.compile(r"CONFIDENCE:\s*(high|medium|low)", re.I)
ATTEMPTS_RE = re.compile(r"ATTEMPTS:\s*(\d+)")
FROM_MEMORY_RE = re.compile(r"FROM[ _]MEMORY:[ \t]*(.*)", re.I)   # value stays on the same line
NONE_RE = re.compile(r"^[\W_]*(?:none|n/?a|nil|no lesson|-+)(?:\b|$|\W)", re.I)
VERIFICATION_RE = re.compile(r"VERIFICATION:\s*\n\s*-\s*command:\s*(\S.*)", re.I)
WORKER_BLOCK = "=== WORKER REPORT ==="
ADVISOR_BLOCK = "=== ADVISOR GUIDANCE ==="
# Guardrail hooks are expected to emit `GUARDRAIL G3: <reason>` (stderr / denial reason).
# `[G3]` and `G3 hit` are accepted too. Bare "G3" is not, to avoid false positives.
GUARDRAIL_NAME_RE = re.compile(r"^\s*G(\d{1,2})\s*$", re.I)


def guardrail_name(g):
    """Normalise 'g3' / 'G03' to 'G3'. Anything else (non-string, 'GX', 'G3a') returns None."""
    m = GUARDRAIL_NAME_RE.match(g) if isinstance(g, str) else None
    return f"G{int(m.group(1))}" if m else None


GUARDRAIL_RE = re.compile(r"(?:GUARDRAIL[ _:-]*(G\d{1,2})\b|\[(G\d{1,2})\]|\b(G\d{1,2})\s+hit\b)", re.I)

BUILTIN_REDACTIONS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/\-]{8,}=*",         # Authorization headers
    r"sk-[A-Za-z0-9_\-]{20,}",                                     # Anthropic / OpenAI (sk-ant-, sk-proj-)
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z_\-]{35}",                                     # Google API keys
    r"xox[abprs]-[A-Za-z0-9\-]{10,}",
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",  # JWTs
    # key = value, key: value, "key": "value", MY_SECRET_KEY=..., AWS_SECRET_ACCESS_KEY=...
    # ("tokens" is excluded so token counts in reports survive)
    r"(?i)[\w.-]*(?:passw(?:or)?d|pwd|secret|token(?!s)|api[_-]?key|access[_-]?key|private[_-]?key|credentials?)"
    r"[\w-]*[\"']?\s*[:=]\s*[\"']?[^\s\"',;}]+",
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",            # email addresses
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
            val = fm.group(1).strip().strip("<>\"'`*_ ")
            out["from_memory"] = "none" if (not val or NONE_RE.match(val)) else "hit"
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
