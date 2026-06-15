"""
exptrack/capture/variables.py — Variable capture, classification, and fingerprinting
"""
from __future__ import annotations

import hashlib
import json
import re
import sys

from ..core.utils import debug_log, safe_call

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
        return safe_call(lambda: f"ndarray(shape={val.shape}, dtype={val.dtype})",
                         default="ndarray(?)", context="var_summary.ndarray")
    if tname == "DataFrame":
        return safe_call(lambda: f"DataFrame(shape={val.shape}, cols={list(val.columns)[:8]})",
                         default="DataFrame(?)", context="var_summary.DataFrame")
    if tname == "Series":
        return safe_call(lambda: f"Series(len={len(val)}, dtype={val.dtype})",
                         default="Series(?)", context="var_summary.Series")
    if tname == "Tensor":
        return safe_call(lambda: f"Tensor(shape={list(val.shape)}, dtype={val.dtype})",
                         default="Tensor(?)", context="var_summary.Tensor")
    if isinstance(val, (list, tuple, set, frozenset)):
        return f"{tname}(len={len(val)})"
    if isinstance(val, dict):
        return f"dict(len={len(val)}, keys={list(val.keys())[:8]})"
    if tname == "Figure":
        return None  # skip figures, captured via savefig

    def _trunc_repr():
        s = repr(val)
        return f"{tname}(...)" if len(s) > 200 else s
    return safe_call(_trunc_repr, default=f"{tname}(?)", context="var_summary.repr")


def _stable_sig(val) -> str:
    """A churn-free fingerprint based on shape/dtype only — never `id()`.

    Used as the fallback when content hashing is skipped (over the size cap) or
    unavailable. It won't detect a pure in-place content edit that leaves shape
    and dtype unchanged, but — unlike an `id()`-based signature — it stays
    stable across cells for an untouched object, so it never produces a false
    "changed".
    """
    tname = type(val).__name__
    if tname == "DataFrame":
        try:
            return f"DataFrame:{val.shape}:{tuple(str(d) for d in val.dtypes)}"
        except Exception:
            return f"DataFrame:{getattr(val, 'shape', '?')}"
    if tname == "Series":
        try:
            return f"Series:{len(val)}:{val.dtype}"
        except Exception:
            return "Series:?"
    # ndarray (and anything array-like with shape/dtype)
    return f"{tname}:{getattr(val, 'shape', '?')}:{getattr(val, 'dtype', '?')}"


def _hash_pandas(val) -> str | None:
    """Content-based, object-column-safe fingerprint for DataFrame/Series.

    Uses `pandas.util.hash_pandas_object`, which is vectorized and hashes the
    *values* (correctly for object/string columns) rather than buffer pointers.
    Returns None when pandas isn't importable or anything goes wrong, so the
    caller can fall back to `_stable_sig`. Pandas is resolved from
    `sys.modules` (never imported here — it's an optional user lib).
    """
    pd = sys.modules.get("pandas")
    if pd is None:
        return None
    try:
        hpo = getattr(getattr(pd, "util", None), "hash_pandas_object", None)
        if hpo is None:
            return None
        h = hpo(val, index=True)
        # `h` is a uint64 Series; .tobytes() is real content, not pointers.
        digest = hashlib.md5(h.values.tobytes()).hexdigest()[:8]
        return f"{type(val).__name__}:{val.shape}:{digest}"
    except Exception:
        return None


def var_fingerprint(val, max_bytes: int = 100 * 1024 * 1024) -> str:
    """
    Return a fingerprint string used for change detection.
    For large objects we use a stable shape/dtype signature, for scalars the repr.

    `max_bytes` caps content hashing: arrays/DataFrames/Tensors whose buffer
    exceeds it are fingerprinted by a stable shape/dtype signature (cheap, but
    won't detect in-place content edits). Lower it via the
    `var_fingerprint_max_mb` config knob when a namespace full of medium
    DataFrames makes per-cell capture slow.

    DataFrames/Series are content-hashed via `pandas.util.hash_pandas_object`
    (object/string-column safe and stable across cells); object-dtype ndarrays
    avoid `.tobytes()` (which would hash pointer addresses, not content, and
    churn every cell). Both fall back to `_stable_sig` — never `id()` — so an
    untouched object keeps the same fingerprint.
    """
    if isinstance(val, _SCALAR):
        return repr(val)
    tname = type(val).__name__
    if tname == "ndarray":
        try:
            # Object-dtype arrays hold Python pointers — .tobytes() would hash
            # addresses (unstable across cells), so content-hash a bounded repr
            # of the values instead, falling back to the stable signature.
            if getattr(val, "dtype", None) is not None and val.dtype.kind == "O":
                if getattr(val, "size", 0) <= 10000:
                    r = repr(val.tolist())
                    return f"ndarray:{val.shape}:O:{hashlib.md5(r.encode()).hexdigest()[:8]}"
                return _stable_sig(val)
            # Guard against OOM / slow hashing: skip .tobytes() for big arrays
            if hasattr(val, 'nbytes') and val.nbytes > max_bytes:
                return _stable_sig(val)
            return f"ndarray:{val.shape}:{val.dtype}:{hashlib.md5(val.tobytes()).hexdigest()[:8]}"
        except (MemoryError, TypeError, ValueError):
            return _stable_sig(val)
    if tname in ("DataFrame", "Series"):
        try:
            nbytes = val.values.nbytes if hasattr(val.values, 'nbytes') else 0
            if nbytes > max_bytes:
                return _stable_sig(val)
            hashed = _hash_pandas(val)
            if hashed is not None:
                return hashed
            return _stable_sig(val)
        except (MemoryError, TypeError, ValueError, AttributeError):
            return _stable_sig(val)
    if tname == "Tensor":
        try:
            elem = val.element_size() if hasattr(val, 'element_size') else 4
            numel = val.numel() if hasattr(val, 'numel') else 0
            if numel * elem > max_bytes:
                return f"Tensor:{list(val.shape)}:{id(val)}"
            return f"Tensor:{list(val.shape)}:{hashlib.md5(val.cpu().numpy().tobytes()).hexdigest()[:8]}"
        except (MemoryError, TypeError, RuntimeError, AttributeError):
            return f"Tensor:{id(val)}"
    if isinstance(val, (list, tuple, set, frozenset, dict)):
        # Check collection size before attempting JSON serialization to avoid OOM
        try:
            if len(val) > 10000:
                return f"{tname}:{len(val)}:{id(val)}"
            j = json.dumps(val, default=str, sort_keys=True)
            if len(j) < 10000:
                return j
        except (TypeError, ValueError, MemoryError, RecursionError) as e:
            debug_log(f"var_fingerprint: could not fingerprint {tname}: "
                      f"{type(e).__name__}: {e}")
        return f"{tname}:{len(val)}:{id(val)}"
    try:
        r = repr(val)
        if len(r) < 1000:
            return r
    except Exception as e:
        debug_log(f"var_fingerprint: repr failed for {tname}: {type(e).__name__}: {e}")
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
