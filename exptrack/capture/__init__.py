"""
exptrack/capture — Zero-friction parameter capture

Two capture modes:
  1. argparse   — patches ArgumentParser.parse_args() AND parse_known_args()
                  so params are logged the moment the user's script calls it.
  2. notebook   — IPython post_execute hook that after EVERY cell:
                    - diffs the cell source against previous version
                    - captures new/changed scalar variables
                    - captures stdout/stderr output
                  Stores snapshots in .exptrack/notebook_history/<nb_name>/
"""
from __future__ import annotations
import re
import sys
import json
import hashlib
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


# State per notebook session
_nb_state: dict = {
    "exp":          None,     # active Experiment
    "nb_name":      "",       # notebook filename stem
    "cell_history": {},       # cell_id -> last source seen
    "var_snapshot": {},       # varname -> last fingerprint seen
    "exec_count":   0,
    "first_run":    True,     # True until first cell is processed
}


def attach_notebook(exp: "Experiment", nb_name: str = "notebook"):
    """
    Install the post_execute hook into the running IPython kernel.
    Safe to call outside notebooks — does nothing if IPython isn't active.
    """
    _nb_state["exp"]          = exp
    _nb_state["nb_name"]      = nb_name
    _nb_state["cell_history"] = {}
    _nb_state["var_snapshot"] = {}
    _nb_state["exec_count"]   = 0
    _nb_state["first_run"]    = True
    try:
        ip = get_ipython()  # noqa — only defined in IPython
        _unregister_hook(ip)
        ip.events.register("post_execute", _post_execute)
    except NameError:
        pass


def detach_notebook():
    _nb_state["exp"] = None
    try:
        ip = get_ipython()  # noqa
        _unregister_hook(ip)
    except NameError:
        pass


def _unregister_hook(ip):
    try:
        ip.events.unregister("post_execute", _post_execute)
    except Exception:
        pass


def _post_execute():
    """Runs after every notebook cell. Captures diff, variables, and output."""
    exp = _nb_state["exp"]
    if exp is None:
        return

    try:
        ip = get_ipython()  # noqa
        _nb_state["exec_count"] += 1
        exec_num = _nb_state["exec_count"]

        # ── 1. Get the cell that just ran ─────────────────────────────────────
        hist = list(ip.history_manager.get_range(
            output=True, raw=True,
            start=-1, stop=None
        ))
        if not hist:
            return

        session, lineno, (source, output) = hist[-1]
        cell_id = hashlib.md5(source.encode()).hexdigest()[:8]

        # ── 2. Diff cell source against last seen version ─────────────────────
        prev_source = _nb_state["cell_history"].get(cell_id, "")
        source_changed = source != prev_source
        _nb_state["cell_history"][cell_id] = source

        source_diff = None
        if source_changed:
            if prev_source:
                source_diff = _simple_diff(prev_source, source)
            else:
                # First execution of this cell — log all lines as additions
                source_diff = [{"op": "+", "line": line}
                               for line in source.splitlines() if line.strip()]

        # ── 3. Capture new/changed variables (scalars + arrays + more) ────
        ns = ip.user_ns
        prev_snap = _nb_state["var_snapshot"]
        new_vars, changed_vars = {}, {}

        for name, val in ns.items():
            if name.startswith("_") or name in _SKIP_NAMES:
                continue
            summary = _var_summary(val)
            if summary is None:
                continue
            fp = _var_fingerprint(val)
            if name not in prev_snap:
                new_vars[name] = summary
            elif prev_snap[name] != fp:
                changed_vars[name] = {"from": "(previous)", "to": summary}

        # Update snapshot with fingerprints for change detection
        new_snap = {}
        for name, val in ns.items():
            if name.startswith("_") or name in _SKIP_NAMES:
                continue
            if _var_summary(val) is not None:
                new_snap[name] = _var_fingerprint(val)
        _nb_state["var_snapshot"] = new_snap

        # On first run, capture all variables as the baseline
        is_first = _nb_state["first_run"]
        _nb_state["first_run"] = False

        # Log HP variables as top-level params (used in run naming)
        # For HP detection, extract the actual value for scalars
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
        # (HP variables are ALSO logged as top-level params above for naming)
        all_new_var = {f"_var/{k}": v for k, v in new_vars.items()}
        all_changed_var = {f"_var/{k}": d["to"] for k, d in changed_vars.items()}
        if all_new_var or all_changed_var:
            exp.log_params({**all_new_var, **all_changed_var})

        # Log code diffs as a param so they appear in `exptrack show`
        if source_diff:
            diff_summary = "; ".join(
                f"{'+'if e['op']=='+'else '-'} {e['line'].strip()}"
                for e in source_diff if e["op"] != "="
            )[:500]
            if diff_summary:
                exp.log_param(f"_code_change/cell_{exec_num}", diff_summary)

        # ── 4. Save snapshot to .exptrack/notebook_history/ ───────────────────
        if source_changed or new_vars or changed_vars:
            _save_cell_snapshot(exp, exec_num, cell_id, source, prev_source,
                                source_diff, new_vars, changed_vars, output)

    except Exception:
        pass  # never break the user's notebook


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
    experiment.  Safe to call when matplotlib is not installed.
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
            # Register artifact with experiment name as context
            label = f"{exp.name}/{orig_path.name}" if exp.name else orig_path.name
            exp.log_artifact(str(orig_path), label=label)
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
