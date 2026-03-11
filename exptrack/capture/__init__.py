"""
exptrack/capture — Zero-friction parameter capture

Two capture modes:
  1. argparse   — patches ArgumentParser.parse_args() AND parse_known_args()
                  so params are logged the moment the user's script calls it.
  2. notebook   — IPython post_execute hook that after EVERY cell:
                    - diffs the cell source against previous version (by content hash)
                    - captures new/changed scalar variables
                    - captures stdout/stderr output
                    - logs timeline events for ordering and context reconstruction
                  Stores snapshots in .exptrack/notebook_history/<nb_name>/
"""
from __future__ import annotations
import re
import sys
import json
import hashlib
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import Experiment

# ── Argparse patch ────────────────────────────────────────────────────────────

_patched = False

def patch_argparse(exp: "Experiment"):
    """
    Monkey-patch ArgumentParser.parse_args AND parse_known_args once.
    When the user's script calls either, params flow into exp automatically.
    After capture, the run name is refreshed to include real param values.
    """
    global _patched
    if _patched:
        return
    _patched = True

    import argparse
    _orig_parse = argparse.ArgumentParser.parse_args
    _orig_known = argparse.ArgumentParser.parse_known_args

    def _hooked_parse(self_ap, args=None, namespace=None):
        ns = _orig_parse(self_ap, args, namespace)
        _capture_namespace(exp, ns)
        return ns

    def _hooked_known(self_ap, args=None, namespace=None):
        ns, remaining = _orig_known(self_ap, args, namespace)
        _capture_namespace(exp, ns)
        # Also capture unknown args as raw params
        _capture_raw_args(exp, remaining)
        return ns, remaining

    argparse.ArgumentParser.parse_args = _hooked_parse
    argparse.ArgumentParser.parse_known_args = _hooked_known


def _capture_namespace(exp: "Experiment", ns):
    try:
        params = {k: v for k, v in vars(ns).items()
                  if not k.startswith("_") and v is not None}
        exp.log_params(params)
        from ..core import make_run_name
        exp._rename(make_run_name(exp.script, exp._params))
    except Exception:
        pass


def _capture_raw_args(exp: "Experiment", args: list):
    """Capture --key value pairs from a list of unknown args."""
    params = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                params[k] = _coerce(v)
            elif i + 1 < len(args) and not args[i + 1].startswith("-"):
                params[key] = _coerce(args[i + 1])
                i += 1
            else:
                params[key] = True
        elif a.startswith("-") and len(a) == 2:
            # Single-dash flag: -l value
            key = a[1:]
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                params[key] = _coerce(args[i + 1])
                i += 1
            else:
                params[key] = True
        i += 1
    if params:
        exp.log_params(params)


# ── Raw argv fallback ─────────────────────────────────────────────────────────

def capture_argv(exp: "Experiment"):
    """
    Parse --key value / --key=value / -k value / --flag from sys.argv directly.
    Used when the script doesn't use argparse at all (click, manual, etc.).
    """
    params = {}
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                params[k] = _coerce(v)
            elif i + 1 < len(args) and not args[i + 1].startswith("-"):
                params[key] = _coerce(args[i + 1])
                i += 1
            else:
                params[key] = True
        elif a.startswith("-") and len(a) == 2:
            key = a[1:]
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                params[key] = _coerce(args[i + 1])
                i += 1
            else:
                params[key] = True
        i += 1
    if params:
        exp.log_params(params)


def _coerce(v: str):
    if v.lower() == "true":  return True
    if v.lower() == "false": return False
    try:    return int(v)
    except Exception: pass
    try:    return float(v)
    except Exception: pass
    return v


# ── Notebook capture ──────────────────────────────────────────────────────────

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


def _is_observational(source: str) -> bool:
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
        # Skip comments
        if line.startswith('#'):
            continue
        # If any line contains assignment, it's not observational
        if '=' in line:
            eq_pos = line.find('=')
            if eq_pos > 0 and line[eq_pos - 1] not in '!<>+*-/^%&|~' and \
               (eq_pos + 1 >= len(line) or line[eq_pos + 1] != '='):
                return False
        # Method calls on objects that are read-only are observational
        # e.g., df.head(), x.shape, model.summary()
        # But df.drop(...), model.fit(...) are NOT
        # Heuristic: if the line is a bare expression (no assignment) it's observational
    # If we get here, no assignments — likely observational
    return True


def _var_summary(val) -> str | None:
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
    # numpy array
    if tname == "ndarray":
        try:
            shape = val.shape
            dtype = val.dtype
            return f"ndarray(shape={shape}, dtype={dtype})"
        except Exception:
            return f"ndarray(?)"
    # pandas DataFrame / Series
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
    # torch Tensor
    if tname == "Tensor":
        try:
            return f"Tensor(shape={list(val.shape)}, dtype={val.dtype})"
        except Exception:
            return f"Tensor(?)"
    # list / tuple / dict / set — show type + length
    if isinstance(val, (list, tuple, set, frozenset)):
        return f"{tname}(len={len(val)})"
    if isinstance(val, dict):
        return f"dict(len={len(val)}, keys={list(val.keys())[:8]})"
    # matplotlib Figure
    if tname == "Figure":
        return None  # skip figures, captured via savefig
    # Generic: show type name
    try:
        s = repr(val)
        if len(s) > 200:
            return f"{tname}(...)"
        return s
    except Exception:
        return f"{tname}(?)"


def _var_fingerprint(val) -> str:
    """
    Return a fingerprint string used for change detection.
    For large objects we use id+type, for scalars the repr.
    """
    if isinstance(val, _SCALAR):
        return repr(val)
    tname = type(val).__name__
    if tname == "ndarray":
        try:
            import hashlib as _hl
            return f"ndarray:{val.shape}:{val.dtype}:{_hl.md5(val.tobytes()).hexdigest()[:8]}"
        except Exception:
            return f"ndarray:{id(val)}"
    if tname in ("DataFrame", "Series"):
        try:
            import hashlib as _hl
            return f"{tname}:{val.shape}:{_hl.md5(val.values.tobytes()).hexdigest()[:8]}"
        except Exception:
            return f"{tname}:{id(val)}"
    if tname == "Tensor":
        try:
            import hashlib as _hl
            return f"Tensor:{list(val.shape)}:{_hl.md5(val.cpu().numpy().tobytes()).hexdigest()[:8]}"
        except Exception:
            return f"Tensor:{id(val)}"
    if isinstance(val, (list, tuple, set, frozenset, dict)):
        try:
            j = json.dumps(val, default=str, sort_keys=True)
            if len(j) < 10000:
                return j
        except Exception:
            pass
        return f"{tname}:{len(val)}:{id(val)}"
    try:
        r = repr(val)
        if len(r) < 1000:
            return r
    except Exception:
        pass
    return f"{tname}:{id(val)}"


# ── Cell lineage helpers (content-addressed) ─────────────────────────────────

def _cell_hash(source: str) -> str:
    """Content hash for a cell — this IS the cell's identity."""
    return hashlib.md5(source.encode()).hexdigest()[:12]


def _find_parent_hash(notebook: str, source: str, current_hash: str) -> str | None:
    """
    Find the most similar existing cell in this notebook's lineage.
    Used when a cell is edited: the new hash points back to the old hash.
    Also handles cell splits — if a new cell's source is a subset of an
    existing cell, that existing cell is the parent.
    """
    try:
        from ..core import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT cell_hash, source FROM cell_lineage WHERE notebook=?",
            (notebook,)
        ).fetchall()
    except Exception:
        return None

    if not rows:
        return None

    best_hash = None
    best_ratio = 0.0

    for row in rows:
        if row["cell_hash"] == current_hash:
            continue  # skip self
        ratio = SequenceMatcher(None, row["source"], source).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_hash = row["cell_hash"]

    # Require at least 30% similarity to consider it a parent.
    # This catches edits, splits (subset of original), and merges.
    if best_ratio >= 0.3:
        return best_hash
    return None


def _store_cell_lineage(notebook: str, source: str, parent_hash: str = None):
    """Store a cell's source in the content-addressed lineage table."""
    try:
        from ..core import get_db
        ch = _cell_hash(source)
        with get_db() as conn:
            # Don't overwrite if already exists — content-addressed
            existing = conn.execute(
                "SELECT cell_hash FROM cell_lineage WHERE cell_hash=?", (ch,)
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO cell_lineage
                       (cell_hash, notebook, source, parent_hash, created_at)
                       VALUES (?,?,?,?,?)""",
                    (ch, notebook, source, parent_hash,
                     datetime.utcnow().isoformat())
                )
                conn.commit()
    except Exception:
        pass


def _get_cell_source(cell_hash: str) -> str | None:
    """Retrieve source from the lineage table by hash."""
    try:
        from ..core import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT source FROM cell_lineage WHERE cell_hash=?", (cell_hash,)
        ).fetchone()
        return row["source"] if row else None
    except Exception:
        return None


# ── Legacy code baseline helpers (kept for backward compat) ──────────────────

def _get_cell_baseline(notebook: str, cell_seq: int) -> str | None:
    """Get the baseline source for a cell position from the DB."""
    try:
        from ..core import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT source FROM code_baselines WHERE notebook=? AND cell_seq=?",
            (notebook, cell_seq),
        ).fetchone()
        return row["source"] if row else None
    except Exception:
        return None


def _update_cell_baseline(notebook: str, cell_seq: int, source: str):
    """Store or update the baseline source for a cell position."""
    try:
        from ..core import get_db
        source_hash = hashlib.md5(source.encode()).hexdigest()[:12]
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO code_baselines
                   (notebook, cell_seq, source, source_hash, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (notebook, cell_seq, source, source_hash,
                 datetime.utcnow().isoformat()),
            )
            conn.commit()
    except Exception:
        pass


# State per notebook session
_nb_state: dict = {
    "exp":          None,     # active Experiment
    "ip":           None,     # cached IPython shell instance
    "nb_name":      "",       # notebook filename stem
    "cell_history": {},       # cell_hash -> last source seen
    "var_snapshot": {},       # varname -> last fingerprint seen
    "exec_count":   0,
    "cells_ran":    [],       # cell numbers that ran unchanged (no code/var changes)
    "first_run":    True,     # True until first cell is processed
    "deferred":     False,    # True when waiting for first real cell
    "deferred_start_fn": None,  # function to call to create the experiment
    "deferred_nb_file":  "",    # notebook file for deferred start
    "last_cell_hash": None,  # hash of the last executed cell (for lineage)
    "hash_to_last_exec_hash": {},  # cell_lineage_key -> last exec's source hash
                                   # tracks when the "same" cell changes content
}


def attach_notebook(exp: "Experiment", nb_name: str = "notebook", ip=None):
    """
    Install the post_run_cell hook into the running IPython kernel.
    Safe to call outside notebooks — does nothing if IPython isn't active.

    Parameters
    ----------
    ip : optional IPython shell instance.  When called from
         load_ipython_extension the shell is passed directly so we don't
         rely on the get_ipython() builtin (which may not resolve inside
         every module context).
    """
    _nb_state["exp"]          = exp
    _nb_state["nb_name"]      = nb_name
    _nb_state["cell_history"] = {}
    _nb_state["var_snapshot"] = {}
    _nb_state["exec_count"]   = 0
    _nb_state["cells_ran"]    = []
    _nb_state["first_run"]    = True
    _nb_state["last_cell_hash"] = None
    _nb_state["hash_to_last_exec_hash"] = {}
    if ip is None:
        try:
            ip = get_ipython()  # noqa — only defined in IPython
        except NameError:
            return
    _nb_state["ip"] = ip
    _unregister_hook(ip)
    ip.events.register("post_run_cell", _post_run_cell)


def attach_notebook_deferred(nb_file: str = "", ip=None, start_fn=None):
    """
    Install the post_run_cell hook but DON'T create an experiment yet.
    The experiment is created on the first real (non-magic) cell execution,
    so that `%load_ext exptrack` itself is never counted as a run.
    """
    _nb_state["deferred"] = True
    _nb_state["deferred_start_fn"] = start_fn
    _nb_state["deferred_nb_file"] = nb_file
    _nb_state["cell_history"] = {}
    _nb_state["var_snapshot"] = {}
    _nb_state["exec_count"] = 0
    _nb_state["cells_ran"]  = []
    _nb_state["first_run"] = True
    _nb_state["exp"] = None
    _nb_state["last_cell_hash"] = None
    _nb_state["hash_to_last_exec_hash"] = {}

    if ip is None:
        try:
            ip = get_ipython()  # noqa
        except NameError:
            return
    _nb_state["ip"] = ip
    _unregister_hook(ip)
    ip.events.register("post_run_cell", _post_run_cell)


def _is_magic_only(source: str) -> bool:
    """Return True if source consists only of IPython magic commands or blank lines."""
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('%') or stripped.startswith('!'):
            continue
        return False
    return True


def detach_notebook():
    _nb_state["exp"] = None
    ip = _nb_state.get("ip")
    if ip is None:
        try:
            ip = get_ipython()  # noqa
        except NameError:
            return
    _unregister_hook(ip)


def _unregister_hook(ip):
    # Remove both old-style and new-style hooks for safe upgrades
    for hook_fn in (_post_run_cell, _post_execute):
        try:
            ip.events.unregister("post_run_cell", hook_fn)
        except (ValueError, Exception):
            pass
        try:
            ip.events.unregister("post_execute", hook_fn)
        except (ValueError, Exception):
            pass


def _extract_assignments(source: str) -> dict[str, str]:
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
        # Simple assignment: name = expr  (also handles a = b = expr)
        if '=' in stripped and not any(stripped.startswith(kw) for kw in ('if ', 'for ', 'while ', 'def ', 'class ', 'return ', 'yield ', 'import ', 'from ', 'with ', 'assert ')):
            # Skip augmented assignments (+=, -=, etc.) and comparisons (==, !=, <=, >=)
            eq_pos = stripped.find('=')
            if eq_pos > 0 and stripped[eq_pos - 1] not in '!<>+*-/^%&|~' and (eq_pos + 1 >= len(stripped) or stripped[eq_pos + 1] != '='):
                lhs = stripped[:eq_pos].strip()
                rhs = stripped[eq_pos + 1:].strip()
                # Remove inline comments from rhs
                # Simple heuristic: find # not inside strings
                comment_pos = _find_comment(rhs)
                if comment_pos >= 0:
                    rhs = rhs[:comment_pos].strip()
                # Handle tuple unpacking: a, b = ...
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


def _post_run_cell(result=None):
    """Runs after every notebook cell. Captures diff, variables, and output.
    Now also emits timeline events for full execution order tracking."""

    try:
        ip = _nb_state.get("ip")
        if ip is None:
            try:
                ip = get_ipython()  # noqa
            except NameError:
                return

        # ── 0. Get the cell source early (needed for deferred start check) ──
        source = None
        output = None
        if result is not None:
            try:
                source = result.info.raw_cell
            except AttributeError:
                pass
        if not source:
            try:
                source = ip.history_manager.input_hist_raw[-1]
            except (IndexError, AttributeError):
                pass
        if not source:
            try:
                source = ip.user_ns.get("In", [""])[-1]
            except (IndexError, TypeError):
                pass
        if not source:
            return

        # ── 0b. Handle deferred start ────────────────────────────────────────
        # If we're in deferred mode (from %load_ext), skip magic-only cells
        # and start the experiment on the first real cell.
        if _nb_state.get("deferred"):
            if _is_magic_only(source):
                return  # skip — don't create an experiment for magic cells
            # First real cell — start the experiment now
            start_fn = _nb_state.get("deferred_start_fn")
            nb_file = _nb_state.get("deferred_nb_file", "")
            _nb_state["deferred"] = False
            _nb_state["deferred_start_fn"] = None
            if start_fn:
                start_fn(nb_file, ip=ip)
            # Fall through to capture this cell's variables

        exp = _nb_state["exp"]
        if exp is None:
            return

        _nb_state["exec_count"] += 1
        exec_num = _nb_state["exec_count"]
        ch = _cell_hash(source)
        notebook = _nb_state["nb_name"]

        # ── 1. Content-addressed cell lineage ────────────────────────────────
        # Store in the lineage table.  Find parent by similarity (handles
        # edits, splits, and merges).
        parent_hash = _find_parent_hash(notebook, source, ch)
        _store_cell_lineage(notebook, source, parent_hash)

        # ── 2. Compute diff against parent cell (if any) ────────────────────
        # Diff against the parent in the lineage (the previous version of
        # this cell), NOT against position.  If no parent, it's a new cell.
        code_is_new = parent_hash is None
        code_changed = False
        source_diff = None
        parent_source = None

        # Also check if we've already executed a cell with this exact hash
        # in this session — if so, it's a re-run with no code changes.
        already_seen = ch in _nb_state["cell_history"]

        if already_seen:
            # Same code as before — no diff needed
            pass
        elif code_is_new:
            # Brand new cell with no similar ancestor
            source_diff = [{"op": "+", "line": line}
                           for line in source.splitlines() if line.strip()]
        else:
            # Has a parent — compute diff
            parent_source = _get_cell_source(parent_hash)
            if parent_source and parent_source != source:
                code_changed = True
                source_diff = _simple_diff(parent_source, source)

        # Update session-local history
        _nb_state["cell_history"][ch] = source
        _nb_state["last_cell_hash"] = ch

        # ── 2b. Also update legacy position-based baselines ──────────────────
        baseline_source = _get_cell_baseline(notebook, exec_num)
        if baseline_source is None:
            _update_cell_baseline(notebook, exec_num, source)
        elif source != baseline_source:
            _update_cell_baseline(notebook, exec_num, source)

        # ── 3. Detect observational cells ────────────────────────────────────
        is_observational = _is_observational(source)

        # ── 4. Extract assignment expressions from cell source ───────────────
        cell_assignments = _extract_assignments(source)

        # ── 5. Capture new/changed variables (scalars + arrays + more) ───────
        ns = ip.user_ns
        prev_snap = _nb_state["var_snapshot"]
        new_vars, changed_vars = {}, {}

        for name, val in list(ns.items()):
            if name.startswith("_") or name in _SKIP_NAMES:
                continue
            summary = _var_summary(val)
            tname = type(val).__name__

            # If _var_summary skips this type (functions, modules, etc.),
            # still capture it if the cell explicitly assigned it — we want
            # to track `f = lambda x: x**2` or `model = create_model()`.
            if summary is None:
                if name not in cell_assignments:
                    continue  # truly skip — not assigned in this cell
                # Use the creation expression as the display value
                expr = cell_assignments[name]
                summary = f"{tname}()"
                if len(expr) <= 500:
                    display = f"{name} = {expr}  # {tname}"
                else:
                    display = f"{tname}()"
                fp = f"{tname}:{name}:{_cell_hash(expr)}"
            else:
                fp = _var_fingerprint(val)
                # For non-scalar types, prefer the source expression over
                # the summary so the user can reconstruct the value
                display = summary
                if not isinstance(val, _SCALAR) and name in cell_assignments:
                    expr = cell_assignments[name]
                    if len(expr) <= 500:
                        display = f"{name} = {expr}  # {summary}"

            if name not in prev_snap:
                new_vars[name] = display
            else:
                prev_entry = prev_snap[name]
                # Backward compat: old snapshots stored bare fingerprint strings
                if isinstance(prev_entry, str):
                    prev_fp, prev_disp = prev_entry, prev_entry
                else:
                    prev_fp = prev_entry["fp"]
                    prev_disp = prev_entry["display"]
                if prev_fp != fp:
                    changed_vars[name] = {
                        "from": prev_disp,
                        "to": display,
                    }

        # Update snapshot with fingerprints AND display strings for change
        # detection and human-readable prev_value tracking
        new_snap = {}
        for name, val in list(ns.items()):
            if name.startswith("_") or name in _SKIP_NAMES:
                continue
            summary = _var_summary(val)
            if summary is not None:
                new_snap[name] = {
                    "fp": _var_fingerprint(val),
                    "display": summary,
                }
            elif name in cell_assignments:
                # Track explicitly-assigned skippable types too
                tname = type(val).__name__
                expr = cell_assignments[name]
                new_snap[name] = {
                    "fp": f"{tname}:{name}:{_cell_hash(expr)}",
                    "display": f"{name} = {expr}  # {tname}"
                        if len(expr) <= 500 else f"{tname}()",
                }
        _nb_state["var_snapshot"] = new_snap

        # On first run, capture all variables as the baseline
        is_first = _nb_state["first_run"]
        _nb_state["first_run"] = False

        # ── 6. Emit timeline events ──────────────────────────────────────────
        # cell_exec — always emitted so execution order is preserved
        diff_str = None
        if source_diff:
            diff_str = json.dumps(source_diff)

        event_type = "observational" if is_observational else "cell_exec"
        cell_seq = exp.log_event(
            event_type=event_type,
            cell_hash=ch,
            cell_pos=exec_num,
            key=f"cell_{exec_num}",
            value={
                "code_is_new": code_is_new and not already_seen,
                "code_changed": code_changed,
                "parent_hash": parent_hash,
                "is_rerun": already_seen and not code_changed and not new_vars and not changed_vars,
                "source_preview": source[:200],
            },
            source_diff=diff_str,
        )

        # var_set — one event per changed/new variable
        for name, display in new_vars.items():
            val = ns.get(name)
            exp.log_event(
                event_type="var_set",
                cell_hash=ch,
                cell_pos=exec_num,
                key=name,
                value=display,
                prev_value=None,
            )

        for name, change in changed_vars.items():
            val = ns.get(name)
            # change["from"] is now a human-readable display string
            # (stored alongside fingerprints in var_snapshot)
            prev_display = change.get("from", "(unknown)")

            exp.log_event(
                event_type="var_set",
                cell_hash=ch,
                cell_pos=exec_num,
                key=name,
                value=change["to"],
                prev_value=prev_display,
            )

        # ── 7. Log HP variables as top-level params (for run naming) ─────────
        def _scalar_val(name):
            v = ns.get(name)
            return v if isinstance(v, _SCALAR) else None

        hp_new = {k: _scalar_val(k) for k in new_vars if _HP_RE.match(k) and _scalar_val(k) is not None}
        hp_changed = {k: _scalar_val(k) for k in changed_vars if _HP_RE.match(k) and _scalar_val(k) is not None}
        if hp_new or hp_changed:
            exp.log_params({**hp_new, **hp_changed})
            from ..core import make_run_name
            exp._rename(make_run_name(exp.script, exp._params))

        # Log ALL variable changes as _var/ params so they appear in the
        # dashboard's "Variable Changes" section — including HP-named ones
        all_new_var = {f"_var/{k}": v for k, v in new_vars.items()}
        all_changed_var = {f"_var/{k}": d["to"] for k, d in changed_vars.items()}
        if all_new_var or all_changed_var:
            exp.log_params({**all_new_var, **all_changed_var})

        # Log code diffs only for new or changed cells (not unchanged ones)
        if source_diff and (code_is_new or code_changed):
            diff_summary = "; ".join(
                f"{'+'if e['op']=='+'else '-'} {e['line'].strip()}"
                for e in source_diff if e["op"] != "="
            )[:500]
            if diff_summary:
                exp.log_param(f"_code_change/cell_{exec_num}", diff_summary)

        # If cell ran unchanged with no variable changes, just note it ran
        if already_seen and not code_changed and not new_vars and not changed_vars:
            _nb_state["cells_ran"].append(exec_num)
            exp.log_param("_cells_ran", json.dumps(_nb_state["cells_ran"]))

        # ── 8. Save snapshot to .exptrack/notebook_history/ ───────────────────
        # Only save full snapshots when there are actual changes to record
        if code_is_new or code_changed or new_vars or changed_vars:
            _save_cell_snapshot(exp, exec_num, ch, source,
                                parent_source or "",
                                source_diff, new_vars, changed_vars, output)

    except Exception as _e:
        print(f"[exptrack] cell capture error: {_e}", file=sys.stderr)


# Backward-compat alias — old code registered _post_execute
_post_execute = _post_run_cell


def _save_cell_snapshot(exp, exec_num, cell_id, source, prev_source,
                        source_diff, new_vars, changed_vars, output):
    from .. import config as cfg
    root = cfg.project_root()
    nb_name = _nb_state["nb_name"]
    hist_dir = root / cfg.load().get("notebook_history_dir",
                                      ".exptrack/notebook_history") / nb_name
    hist_dir.mkdir(parents=True, exist_ok=True)

    snap = {
        "exp_id":       exp.id,
        "exp_name":     exp.name,
        "ts":           datetime.utcnow().isoformat(),
        "exec_num":     exec_num,
        "cell_id":      cell_id,
        # Only store the diff, not the full source — keeps snapshots light.
        # The first execution of a cell stores a hash; subsequent ones store
        # only what changed.
        "source_hash":  hashlib.md5(source.encode()).hexdigest()[:12],
        "source_diff":  source_diff,
        "new_vars":     new_vars,
        "changed_vars": changed_vars,
        "output":       str(output)[:2000] if output else None,
    }

    fname = f"exec{exec_num:04d}_{cell_id}.json"
    (hist_dir / fname).write_text(json.dumps(snap, indent=2, default=str))


# ── Matplotlib savefig patch ─────────────────────────────────────────────────

_plt_patched = False

def patch_savefig(exp: "Experiment"):
    """
    Monkey-patch matplotlib.pyplot.savefig and Figure.savefig so that every
    saved plot is automatically registered as an artifact on the active
    experiment.  Also emits a timeline 'artifact' event linking the saved
    plot to the current variable context.
    """
    global _plt_patched
    if _plt_patched:
        return
    _plt_patched = True

    try:
        import matplotlib.pyplot as plt
        import matplotlib.figure as mfig
    except ImportError:
        return

    _orig_plt_savefig = plt.savefig
    _orig_fig_savefig = mfig.Figure.savefig

    def _namespace_and_save(fname, save_fn, *args, **kwargs):
        """Save the file, copy to experiment output dir, and register artifact."""
        from pathlib import Path as _P
        import shutil
        # Save to the original location first
        result = save_fn(fname, *args, **kwargs)
        try:
            orig_path = _P(str(fname)).resolve()
            # Also copy into the experiment's namespaced output directory
            out_dir = exp.output_path(orig_path.name)
            if out_dir.resolve() != orig_path:
                shutil.copy2(str(orig_path), str(out_dir))
            # Emit timeline artifact event BEFORE registering
            # so the artifact row can reference the timeline seq
            art_seq = exp.log_event(
                event_type="artifact",
                cell_hash=_nb_state.get("last_cell_hash"),
                key=orig_path.name,
                value=str(orig_path),
            )
            # Register artifact with experiment name as context
            label = f"{exp.name}/{orig_path.name}" if exp.name else orig_path.name
            exp.log_artifact(str(orig_path), label=label, timeline_seq=art_seq)
        except Exception:
            pass
        return result

    def _hooked_plt_savefig(fname, *args, **kwargs):
        return _namespace_and_save(fname, _orig_plt_savefig, *args, **kwargs)

    def _hooked_fig_savefig(self_fig, fname, *args, **kwargs):
        return _namespace_and_save(fname, lambda f, *a, **kw: _orig_fig_savefig(self_fig, f, *a, **kw), *args, **kwargs)

    plt.savefig = _hooked_plt_savefig
    mfig.Figure.savefig = _hooked_fig_savefig


# ── Script source tracking ───────────────────────────────────────────────────

def capture_script_snapshot(exp: "Experiment", script_path: str):
    """
    Diff the script against the last git commit (HEAD) and log only the
    changed lines.  No full-source copies are stored — the committed file
    in git is always the reference point, keeping storage minimal.
    """
    import subprocess
    from pathlib import Path as _Path
    from .. import config as _cfg

    try:
        src = _Path(script_path).read_text()
    except Exception:
        return

    src_hash = hashlib.md5(src.encode()).hexdigest()[:12]
    exp.log_param("_script_hash", src_hash)

    # Use `git diff HEAD -- <file>` to get changes vs. last commit.
    # This is the same reference point core.py uses for git_diff but
    # scoped to just this script file.
    root = _cfg.project_root()
    try:
        rel = _Path(script_path).resolve().relative_to(root.resolve())
    except ValueError:
        rel = _Path(script_path)
    try:
        r = subprocess.run(
            ["git", "diff", "HEAD", "--", str(rel)],
            capture_output=True, text=True, timeout=10,
            cwd=str(root),
        )
        script_diff = r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        script_diff = ""

    if script_diff:
        # Summarise the changed lines (skip diff headers)
        changed = []
        for line in script_diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                changed.append(f"+ {line[1:].strip()}")
            elif line.startswith("-") and not line.startswith("---"):
                changed.append(f"- {line[1:].strip()}")
        if changed:
            exp.log_param("_code_changes", "; ".join(changed)[:1000])

    # Also emit a timeline event for the script execution
    exp.log_event(
        event_type="cell_exec",
        cell_hash=src_hash,
        key="script",
        value={"script": script_path, "hash": src_hash},
        source_diff="; ".join(changed)[:1000] if script_diff else None,
    )


def _simple_diff(old: str, new: str) -> list[dict]:
    """Line-level diff: returns list of {op, line} where op is +/-/=."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    result = []
    old_set = set(old_lines)
    new_set = set(new_lines)
    for line in old_lines:
        if line not in new_set:
            result.append({"op": "-", "line": line})
    for line in new_lines:
        if line not in old_set:
            result.append({"op": "+", "line": line})
        else:
            result.append({"op": "=", "line": line})
    return result
