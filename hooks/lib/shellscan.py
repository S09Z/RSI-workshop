"""Lexical scan of a Bash command: which paths would it write, and is that knowable?

Used by G6 and G7. Not a shell parser: a path built at run time by a script, base64 or another
interpreter is not seen (documented residual; the sandbox closes it). When in doubt it says `unsafe`.
"""
import glob
import os
import re
import shlex
from dataclasses import dataclass, field

try:
    from lib import common
except ImportError:  # imported as a top-level module
    import common  # type: ignore

WRITERS = {"tee", "truncate", "mv", "cp", "rm", "dd", "ln", "install", "touch", "chmod", "chown", "patch",
           "mkdir", "rmdir", "unlink", "rsync"}
GIT_WRITERS = {"checkout", "restore", "stash", "apply"}
READ_ONLY = {"cat", "grep", "head", "tail", "ls", "diff", "wc", "pytest"}
GIT_READ_ONLY = {"diff", "status", "log", "show"}
INTERPRETERS = {"python", "python3", "node", "perl", "ruby", "sh", "bash", "zsh"}
WRAPPERS = {"env", "nohup", "time", "command", "exec", "sudo", "builtin"}
FD_REDIRECT = re.compile(r"\d*>&\d+|\d*>&-|&?\d*>>?\s*/dev/null")
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
EXEC_FLAG = re.compile(r"^-[A-Za-z]*[ce]$")
INPLACE = re.compile(r"^(-[A-Za-z]*i[A-Za-z.]*|--in-place.*)$")


@dataclass
class Scan:
    targets: list = field(default_factory=list)
    unsafe: bool = False
    why: str = ""


def inside(path: str, root: str) -> bool:
    p = os.path.realpath(path).casefold()
    r = os.path.realpath(root).casefold()
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _split(cmd: str):
    """Quote-aware split on ; | & newline and parentheses. Returns (segments, saw_grouping)."""
    segs, cur, quote, group, i = [], [], None, False, 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            cur.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(cmd):
                i += 1
                cur.append(cmd[i])
            elif c == quote:
                quote = None
        elif c == "\\" and i + 1 < len(cmd):
            cur.append(c)
            i += 1
            cur.append(cmd[i])
        elif c in "'\"":
            quote = c
            cur.append(c)
        elif c in ";|\n":
            segs.append("".join(cur)); cur = []
        elif c in "()":
            group = True
            segs.append("".join(cur)); cur = []
        elif c == "&":
            nxt = cmd[i + 1] if i + 1 < len(cmd) else ""
            prev = cmd[i - 1] if i else ""
            if nxt == ">" or prev == ">":
                cur.append(c)
            else:
                segs.append("".join(cur)); cur = []
        else:
            cur.append(c)
        i += 1
    segs.append("".join(cur))
    return [s for s in segs if s.strip()], group


def _expand(word: str, cwd: str) -> list:
    word = os.path.expanduser(word)
    if word.startswith("of="):
        word = word[3:]
    full = word if os.path.isabs(word) else os.path.join(cwd or "", word)
    if any(ch in word for ch in "*?["):
        hits = sorted(glob.glob(full))
        if hits:
            return [common.real(h, cwd) for h in hits]
    return [common.real(word, cwd)]


def scan(cmd: str, cwd: str) -> Scan:
    segs, group = _split(cmd)
    targets, whys = [], []
    writing_any = cdlike = False

    def flag(why):
        if why not in whys:
            whys.append(why)

    for seg in segs:
        seg = FD_REDIRECT.sub(" ", seg).replace("&>", ">")
        try:
            toks = shlex.split(re.sub(r"\d*>>?", " > ", seg))
        except ValueError:
            flag("unparseable segment")
            continue
        words, redirs, i = [], [], 0
        while i < len(toks):
            t = toks[i]
            if t == ">":
                if i + 1 < len(toks):
                    redirs.append(toks[i + 1])
                else:
                    flag("redirect without a target")
                i += 2
            elif t == "<":
                i += 2
            else:
                words.append(t)
                i += 1
        while words and (ASSIGN.match(words[0]) or words[0] in WRAPPERS):
            w = words.pop(0)
            while w in WRAPPERS and words and words[0].startswith("-"):
                words.pop(0)
        if any(w == "-C" or w.startswith("--directory") for w in words) or (
                words and words[0] in ("cd", "pushd", "popd")):
            cdlike = True
        if not words and not redirs:
            continue
        head = os.path.basename(words[0]) if words else ""
        # commands whose target cannot be known lexically
        unknowable = head in ("eval", "xargs") or (
            head in INTERPRETERS and _has_exec_flag(words[1:])) or (
            head == "find" and any(w in ("-exec", "-execdir", "-ok", "-delete") for w in words))
        if unknowable:
            flag("%s runs code whose target cannot be seen" % head)
            continue
        read_only = bool(words) and (
            words[0] in READ_ONLY
            or (words[0] in ("python", "python3") and words[1:3] in (["-m", "pytest"], ["-m", "unittest"]))
            or (words[0] == "git" and _git_sub(words) in GIT_READ_ONLY))
        seg_targets, writing = [], bool(redirs)
        seg_targets += list(redirs)
        if words and not read_only:
            idx = _writer_index(words)
            if idx is not None:
                writing = True
                rest = [w for w in words[idx + 1:] if not w.startswith("-") and not w.startswith("if=")]
                if os.path.basename(words[idx]) == "git":
                    rest = rest[1:]
                    if not rest:
                        rest = [cwd or "."]
                seg_targets += rest
        if not writing:
            continue
        writing_any = True
        if "$" in seg or "`" in seg:
            flag("writing command uses a variable or command substitution")
        for w in seg_targets:
            for p in _expand(w, cwd):
                if p not in targets:
                    targets.append(p)
    if writing_any and (cdlike or group):
        flag("directory change or grouping together with a write")
    return Scan(targets, bool(whys), "; ".join(whys))


def _has_exec_flag(args) -> bool:
    for a in args:
        if a == "-m":
            return False
        if EXEC_FLAG.match(a):
            return True
        if not a.startswith("-"):
            return False
    return False


def _git_sub(words):
    for w in words[1:]:
        if not w.startswith("-"):
            return w
    return None


def _writer_index(words):
    for idx, w in enumerate(words):
        b = os.path.basename(w)
        if b in WRITERS:
            return idx
        if b in ("sed", "perl") and any(INPLACE.match(a) for a in words[idx + 1:]):
            return idx
        if b == "git" and _git_sub(words[idx:]) in GIT_WRITERS:
            return idx
    return None
