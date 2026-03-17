"""
exptrack/capture/variables.py — Variable capture, classification, and fingerprinting
"""
from __future__ import annotations
import hashlib
import json
import re
import sys

# Heuristic: variable names that look like hyperparameters
_HP_RE = re.compile(
    r"^(lr|learning.rate|batch.size|bs|n?_?epochs?|dropout|weight.decay|"
    r"wd|hidden|d.model|n.heads?|n.layers?|num.layers?|kernel|stride|"
    r"padding|momentum|beta|gamma|temperature|threshold|seed|arch|"
    r"architecture|model|backbone|optimizer|loss|scheduler|aug|"
    r"num.classes|in.channels?|out.channels?|latent|z.dim|embed|"
    r"lambda|alpha|scale|gamma|delta|lr.schedule|warmup|clip).*$",
    re.IGNORECASE,
)
_SCALAR = (int, float, bool, str)

# Types we skip entirely (modules, functions, classes, etc.)
_SKIP_TYPES_NAMES = frozenset({
    "module", "function", "builtin_function_or_method", "type",
    "method", "classmethod", "staticmethod", "property",
    "getset_descriptor", "member_descriptor", "wrapper_descriptor",
    "method_descriptor", "method-wrapper",
})
# Internal IPython names to never capture
_SKIP_NAMES = frozenset({
    "In", "Out", "get_ipython", "exit", "quit", "open",
})

# Patterns for "observational" cells — print/display/inspect/debug statements
# that don't change state and shouldn't clutter the timeline
_OBSERVATIONAL_RE = re.compile(
    r"^\s*(?:print|display|type|len|shape|head|tail|describe|info|summary|"
    r"help|dir|vars|id|repr|str|list|dict|set|tuple|sorted|enumerate|"
    r"isinstance|hasattr|getattr)\s*\(", re.MULTILINE
)


def is_observational(source: str) -> bool:
    """
    Detect "dumb" cells that just inspect/print values without assigning.
    e.g., print(x), df.head(), x.shape, type(y)

    These still get logged in the timeline as 'observational' events
    but are visually de-emphasized and don't trigger full snapshots.
    """
    lines = [l.strip() for l in source.splitlines()
             if l.strip() and not l.strip().startswith('#')]
    if not lines:
        return False
    for line in lines:
        if line.startswith('#'):
            continue
        if '=' in line:
            eq_pos = line.find('=')
            if eq_pos > 0 and line[eq_pos - 1] not in '!<>+*-/^%&|~' and \
               (eq_pos + 1 >= len(line) or line[eq_pos + 1] != '='):
                return False
    return True


def var_summary(val) -> str | None:
    """
    Return a short summary string for any variable value.
    Returns None if the variable should be skipped.
    """
    if isinstance(val, _SCALAR):
        if isinstance(val, str) and len(val) > 200:
            return None
        return repr(val)
    tname = type(val).__name__
    if tname in _SKIP_TYPES_NAMES:
        return None
    if tname == "ndarray":
        try:
            return f"ndarray(shape={val.shape}, dtype={val.dtype})"
        except Exception:
            return f"ndarray(?)"
    if tname == "DataFrame":
        try:
            return f"DataFrame(shape={val.shape}, cols={list(val.columns)[:8]})"
        except Exception:
            return f"DataFrame(?)"
    if tname == "Series":
        try:
            return f"Series(len={len(val)}, dtype={val.dtype})"
        except Exception:
            return f"Series(?)"
    if tname == "Tensor":
        try:
            return f"Tensor(shape={list(val.shape)}, dtype={val.dtype})"
        except Exception:
            return f"Tensor(?)"
    if isinstance(val, (list, tuple, set, frozenset)):
        return f"{tname}(len={len(val)})"
    if isinstance(val, dict):
        return f"dict(len={len(val)}, keys={list(val.keys())[:8]})"
    if tname == "Figure":
        return None  # skip figures, captured via savefig
    try:
        s = repr(val)
        if len(s) > 200:
            return f"{tname}(...)"
        return s
    except Exception:
        return f"{tname}(?)"


def var_fingerprint(val) -> str:
    """
    Return a fingerprint string used for change detection.
    For large objects we use id+type, for scalars the repr.
    """
    if isinstance(val, _SCALAR):
        return repr(val)
    tname = type(val).__name__
    if tname == "ndarray":
        try:
            return f"ndarray:{val.shape}:{val.dtype}:{hashlib.md5(val.tobytes()).hexdigest()[:8]}"
        except Exception:
            return f"ndarray:{id(val)}"
    if tname in ("DataFrame", "Series"):
        try:
            return f"{tname}:{val.shape}:{hashlib.md5(val.values.tobytes()).hexdigest()[:8]}"
        except Exception:
            return f"{tname}:{id(val)}"
    if tname == "Tensor":
        try:
            return f"Tensor:{list(val.shape)}:{hashlib.md5(val.cpu().numpy().tobytes()).hexdigest()[:8]}"
        except Exception:
            return f"Tensor:{id(val)}"
    if isinstance(val, (list, tuple, set, frozenset, dict)):
        try:
            j = json.dumps(val, default=str, sort_keys=True)
            if len(j) < 10000:
                return j
        except Exception as e:
            print(f"[exptrack] warning: could not fingerprint {tname}: {e}", file=sys.stderr)
        return f"{tname}:{len(val)}:{id(val)}"
    try:
        r = repr(val)
        if len(r) < 1000:
            return r
    except Exception as e:
        print(f"[exptrack] warning: repr failed for {tname}: {e}", file=sys.stderr)
    return f"{tname}:{id(val)}"


def extract_assignments(source: str) -> dict[str, str]:
    """
    Parse cell source to extract variable assignment expressions.
    Returns {var_name: rhs_expression} for simple assignments like:
        x = np.linspace(0, r, 100)  ->  {"x": "np.linspace(0, r, 100)"}
        a, b = 1, 2                 ->  {"a": "1, 2", "b": "1, 2"}
    """
    assignments = {}
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('%'):
            continue
        if '=' in stripped and not any(stripped.startswith(kw) for kw in ('if ', 'for ', 'while ', 'def ', 'class ', 'return ', 'yield ', 'import ', 'from ', 'with ', 'assert ')):
            eq_pos = stripped.find('=')
            if eq_pos > 0 and stripped[eq_pos - 1] not in '!<>+*-/^%&|~' and (eq_pos + 1 >= len(stripped) or stripped[eq_pos + 1] != '='):
                lhs = stripped[:eq_pos].strip()
                rhs = stripped[eq_pos + 1:].strip()
                comment_pos = _find_comment(rhs)
                if comment_pos >= 0:
                    rhs = rhs[:comment_pos].strip()
                if ',' in lhs and not lhs.startswith('(') and not lhs.startswith('['):
                    names = [n.strip() for n in lhs.split(',')]
                    for n in names:
                        if n.isidentifier():
                            assignments[n] = rhs
                elif lhs.isidentifier():
                    assignments[lhs] = rhs
    return assignments


def _find_comment(s: str) -> int:
    """Find the position of # comment outside quotes. Returns -1 if none."""
    in_single = in_double = False
    for i, c in enumerate(s):
        if c == "'" and not in_double:
            in_single = not in_single
        elif c == '"' and not in_single:
            in_double = not in_double
        elif c == '#' and not in_single and not in_double:
            return i
    return -1
