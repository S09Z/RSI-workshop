"""Load a small, safe subset of YAML with the standard library.

Supported: nested block mappings, block sequences ("- item" and "- key: value" maps),
inline lists/maps ([a, b], {k: v}), quoted and plain scalars, ints, floats, true/false/null,
and "#" comments. Anchors, multi-line strings and tags are not supported.

If PyYAML is installed it is used instead (yaml.safe_load), so full YAML works there.
"""
import json
import re

try:  # optional, never required
    import yaml as _pyyaml  # type: ignore
except Exception:  # pragma: no cover - depends on environment
    _pyyaml = None


class YAMLError(ValueError):
    pass


def load(text, force_lite=False):
    if _pyyaml is not None and not force_lite:
        return _pyyaml.safe_load(text)
    lines = []
    for raw in text.splitlines():
        s = _strip_comment(raw).rstrip()
        if s.strip() == "" or s.strip() in ("---", "..."):
            continue
        indent = len(s) - len(s.lstrip(" "))
        if "\t" in s[:indent]:
            raise YAMLError("tabs are not allowed for indentation")
        lines.append((indent, s.strip()))
    if not lines:
        return None
    value, pos = _block(lines, 0, lines[0][0])
    if pos != len(lines):
        raise YAMLError(f"unexpected content: {lines[pos][1]!r}")
    return value


def load_file(path):
    with open(path, encoding="utf-8") as f:
        return load(f.read())


def _strip_comment(s):
    out, q = [], None
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = None
        elif ch in ("'", '"'):
            q = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out)


def _block(lines, pos, indent):
    if lines[pos][1].startswith("- ") or lines[pos][1] == "-":
        return _seq(lines, pos, indent)
    return _map(lines, pos, indent)


def _split_key(s):
    m = re.match(r'^("[^"]*"|\'[^\']*\'|[^:{}\[\]]+?)\s*:(\s+|$)(.*)$', s)
    if not m:
        return None
    return _scalar(m.group(1)), m.group(3)


def _map(lines, pos, indent):
    out = {}
    while pos < len(lines) and lines[pos][0] == indent:
        kv = _split_key(lines[pos][1])
        if kv is None:
            raise YAMLError(f"expected 'key: value', got {lines[pos][1]!r}")
        key, rest = kv
        pos += 1
        if rest == "":
            if pos < len(lines) and lines[pos][0] > indent:
                out[key], pos = _block(lines, pos, lines[pos][0])
            elif pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
                out[key], pos = _seq(lines, pos, indent)
            else:
                out[key] = None
        else:
            out[key] = _inline(rest)
    if pos < len(lines) and lines[pos][0] > indent:
        raise YAMLError(f"bad indentation near {lines[pos][1]!r}")
    return out, pos


def _seq(lines, pos, indent):
    out = []
    while pos < len(lines) and lines[pos][0] == indent and (lines[pos][1].startswith("- ") or lines[pos][1] == "-"):
        body = lines[pos][1][1:].strip()
        if body == "":
            pos += 1
            if pos < len(lines) and lines[pos][0] > indent:
                v, pos = _block(lines, pos, lines[pos][0])
            else:
                v = None
            out.append(v)
            continue
        if _split_key(body) is not None and not body.startswith(("[", "{", '"', "'")):
            # "- key: value" starts a mapping whose other keys are indented to the key column
            child_indent = indent + 2 + (len(lines[pos][1][1:]) - len(lines[pos][1][1:].lstrip()) - 1)
            sub = [(child_indent, body)]
            j = pos + 1
            while j < len(lines) and lines[j][0] > indent:
                sub.append(lines[j])
                j += 1
            v, k = _map(sub, 0, child_indent)
            if k != len(sub):
                raise YAMLError(f"bad indentation near {sub[k][1]!r}")
            out.append(v)
            pos = j
        else:
            out.append(_inline(body))
            pos += 1
    return out, pos


def _inline(s):
    s = s.strip()
    if s.startswith("[") or s.startswith("{"):
        return _flow(s)
    return _scalar(s)


def _flow(s):
    # Convert simple flow collections to JSON, quoting bare words.
    tokens = re.findall(r'"[^"]*"|\'[^\']*\'|[\[\]{},:]|[^\[\]{},:]+', s)
    out = []
    for t in tokens:
        ts = t.strip()
        if ts == "":
            continue
        if ts in "[]{},:":
            out.append(ts)
        else:
            out.append(json.dumps(_scalar(ts)))
    try:
        return json.loads("".join(out))
    except json.JSONDecodeError as e:
        raise YAMLError(f"cannot parse flow value {s!r}: {e}")


def _scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", ""):
        return None
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", s):
        return float(s)
    return s
