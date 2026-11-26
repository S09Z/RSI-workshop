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
           "mkdir", "rmdir", "unlink", "rsync", "tar", "unzip", "sponge"}
SOURCE_FIRST = {"cp", "rsync", "install"}   # only the destination is written
GIT_READ_ONLY = {"diff", "status", "log", "show", "blame", "rev-parse", "ls-files", "ls-tree", "describe",
                 "shortlog", "grep", "cat-file", "rev-list", "show-ref"}
GIT_PATH_BEARING = {"init", "clone", "worktree", "submodule", "archive", "format-patch", "bundle"}
READ_ONLY = {"cat", "grep", "head", "tail", "ls", "diff", "wc", "pytest"}
INTERP = re.compile(r"^(python[\d.]*|pypy[\d.]*|node|nodejs|deno|bun|perl|ruby|php|lua|osascript|Rscript|(?:ba|da|a|k|z|c|t)?sh|fish)$")
WRAPPERS = {"env", "nohup", "time", "command", "exec", "sudo", "builtin", "timeout", "nice", "stdbuf", "watch",
            "ionice", "setsid"}
WRAPPER_VALUE_FLAGS = {"-u", "-g", "-n", "-o", "-s", "-k"}
FD_REDIRECT = re.compile(r"\d*>&\d+|\d*>&-|&?\d*>>?\s*/dev/null")
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_]\w*)\1")
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
EXEC_FLAG = re.compile(r"^-[A-Za-z]*[ce]$")
EXTRA_EXEC = {"node": {"-p", "--print"}, "nodejs": {"-p", "--print"}, "php": {"-r"}, "perl": {"-E"}}
LONG_EXEC = ("--eval", "--command", "--exec")
SCRIPT_EXT = re.compile(r"\.(py|js|mjs|cjs|sh|pl|rb|php|lua|ts|r)$", re.I)
BRACE = re.compile(r"\{[^{}]*(,|\.\.)[^{}]*\}")
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


def _strip_heredocs(cmd: str) -> str:
    """Drop heredoc bodies: they are data, not shell. Keeps the command line that introduced them."""
    out, pos = [], 0
    while True:
        m = HEREDOC.search(cmd, pos)
        if not m:
            break
        eol = cmd.find("\n", m.end())
        if eol < 0:
            break
        out.append(cmd[pos:eol + 1])
        close = re.compile(r"^[ \t]*%s[ \t]*$" % re.escape(m.group(2)), re.M).search(cmd, eol + 1)
        pos = close.end() if close else len(cmd)
    out.append(cmd[pos:])
    return "".join(out)


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


def _git_sub(words):
    for w in words[1:]:
        if not w.startswith("-"):
            return w
    return None


def _interp_unsafe(head: str, args: list) -> bool:
    """True when an interpreter runs code we cannot see: inline code flag, or code on stdin."""
    if any(a in ("-V", "--version", "-h", "--help") for a in args):
        return False
    extra = EXTRA_EXEC.get(head, set())
    for a in args:
        if a == "-m" or SCRIPT_EXT.search(a):
            return False
        if EXEC_FLAG.match(a) or a in extra or a == "-s" or a == "-" or a.startswith(LONG_EXEC):
            return True
    return not any(not a.startswith("-") for a in args)  # no script file at all: reads code from stdin


def _unknowable(words: list) -> str:
    head = os.path.basename(words[0])
    args = words[1:]
    if head in ("eval", "xargs"):
        return head
    if INTERP.match(head) and _interp_unsafe(head, args):
        return "%s with inline code or code on stdin" % head
    if head == "find" and any(w in ("-exec", "-execdir", "-ok", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls")
                              for w in args):
        return "find with an action that writes or runs commands"
    if head in ("awk", "gawk", "mawk") and any(">" in a or "system(" in a or "|" in a for a in args):
        return "awk program that may write or run commands"
    if head == "git" and _git_sub(words) == "config" and any(
            a in ("--global", "--system", "--file", "-f") for a in args):
        return "git config outside the repository"
    return ""


def _writer_index(words):
    for idx, w in enumerate(words):
        b = os.path.basename(w)
        rest = words[idx + 1:]
        if b in WRITERS:
            return idx
        if b in ("sed", "perl") and any(INPLACE.match(a) for a in rest):
            return idx
        if b == "sort" and "-o" in rest:
            return idx
        if b == "curl" and any(a in ("-o", "--output", "-O", "--remote-name", "-J") for a in rest):
            return idx
        if b == "wget":
            return idx
        if b == "git":
            sub = _git_sub(words[idx:])
            if sub and sub not in GIT_READ_ONLY:
                return idx
    return None


def _targets(words: list, idx: int, cwd: str):
    """(words to judge as paths, git_in_tree). git_in_tree: the write is the working tree at cwd."""
    b = os.path.basename(words[idx])
    args = words[idx + 1:]
    nonopt = [w for w in args if not w.startswith("-") and not w.startswith("if=")]
    if b in SOURCE_FIRST:
        for i, a in enumerate(args):
            if a in ("-t", "--target-directory") and i + 1 < len(args):
                return [args[i + 1]], False
            if a.startswith("--target-directory="):
                return [a.split("=", 1)[1]], False
        return nonopt[-1:], False
    if b == "git":
        sub = _git_sub(words[idx:])
        if sub in GIT_PATH_BEARING:
            lst = list(nonopt)
            if sub in lst:
                lst.remove(sub)
            return lst or [cwd or "."], False
        return [cwd or "."], True
    if b == "curl":
        out = [args[i + 1] for i, a in enumerate(args) if a in ("-o", "--output") and i + 1 < len(args)]
        return out or [cwd or "."], False
    if b == "wget":
        out = [args[i + 1] for i, a in enumerate(args)
               if a in ("-O", "--output-document", "-P", "--directory-prefix") and i + 1 < len(args)]
        return out or [cwd or "."], False
    if b in ("tar", "unzip"):
        return nonopt + [cwd or "."], False
    return nonopt, False


def scan(cmd: str, cwd: str) -> Scan:
    segs, group = _split(_strip_heredocs(cmd))
    targets, whys = [], []
    writing_any = cdlike = False

    def flag(why):
        if why not in whys:
            whys.append(why)

    for seg in segs:
        seg = FD_REDIRECT.sub(" ", seg).replace("&>", ">").replace("<>", ">").replace(">&", ">")
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
            elif t.startswith("<"):  # <file, <<EOF, <<<text: input, not a word of the command
                i += 1
            else:
                words.append(t)
                i += 1
        while words:
            w = words[0]
            if ASSIGN.match(w):
                if w.startswith("GIT_"):
                    cdlike = True
                words.pop(0)
            elif os.path.basename(w) in WRAPPERS:
                wrapper = os.path.basename(words.pop(0))
                while words and words[0].startswith("-"):
                    f = words.pop(0)
                    if f in WRAPPER_VALUE_FLAGS and words:
                        words.pop(0)
                if wrapper == "timeout" and words and re.match(r"^\d+(\.\d+)?[smhd]?$", words[0]):
                    words.pop(0)
            else:
                break
        if any(w == "-C" or w.startswith(("--directory", "--work-tree", "--git-dir")) for w in words) or (
                words and words[0] in ("cd", "pushd", "popd")):
            cdlike = True
        if not words and not redirs:
            continue
        if words:
            why = _unknowable(words)
            if why:
                flag("%s runs code whose target cannot be seen" % why)
                continue
        read_only = bool(words) and (
            words[0] in READ_ONLY
            or (words[0] in ("python", "python3") and words[1:3] in (["-m", "pytest"], ["-m", "unittest"]))
            or (words[0] == "git" and _git_sub(words) in GIT_READ_ONLY))
        seg_targets, writing, in_tree = list(redirs), bool(redirs), False
        if words and not read_only:
            idx = _writer_index(words)
            if idx is not None:
                writing = True
                more, in_tree = _targets(words, idx, cwd)
                seg_targets += more
                if os.path.basename(words[idx]) in ("sed", "perl"):
                    seg_targets += [w for w in words[idx + 1:] if not w.startswith("-")]
        if not writing:
            continue
        writing_any = True
        if not (in_tree and not redirs) and ("$" in seg or "`" in seg):
            flag("writing command uses a variable or command substitution")
        if BRACE.search(seg):
            flag("brace expansion in a writing command")
        for w in seg_targets:
            for p in _expand(w, cwd):
                if p not in targets:
                    targets.append(p)
    if writing_any and (cdlike or group):
        flag("directory change or grouping together with a write")
    return Scan(targets, bool(whys), "; ".join(whys))
