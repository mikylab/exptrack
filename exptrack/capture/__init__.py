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

# State per notebook session
_nb_state: dict = {
    "exp":          None,     # active Experiment
    "nb_name":      "",       # notebook filename stem
    "cell_history": {},       # cell_id -> last source seen
    "var_snapshot": {},       # varname -> last value seen
    "exec_count":   0,
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
        if source_changed and prev_source:
            source_diff = _simple_diff(prev_source, source)

        # ── 3. Capture new/changed scalar variables ───────────────────────────
        ns = ip.user_ns
        prev_snap = _nb_state["var_snapshot"]
        new_vars, changed_vars = {}, {}

        for name, val in ns.items():
            if name.startswith("_") or not isinstance(val, _SCALAR):
                continue
            if isinstance(val, str) and len(val) > 200:
                continue
            if name not in prev_snap:
                new_vars[name] = val
            elif prev_snap[name] != val:
                changed_vars[name] = {"from": prev_snap[name], "to": val}

        # Update snapshot
        _nb_state["var_snapshot"] = {
            k: v for k, v in ns.items()
            if not k.startswith("_") and isinstance(v, _SCALAR) and
               not (isinstance(v, str) and len(v) > 200)
        }

        # Log new HP variables as params
        hp_new = {k: v for k, v in new_vars.items() if _HP_RE.match(k)}
        hp_changed = {k: d["to"] for k, d in changed_vars.items() if _HP_RE.match(k)}
        if hp_new or hp_changed:
            exp.log_params({**hp_new, **hp_changed})
            from ..core import make_run_name
            exp._rename(make_run_name(exp.script, exp._params))

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
        "source":       source,
        "source_diff":  source_diff,
        "new_vars":     new_vars,
        "changed_vars": changed_vars,
        "output":       str(output)[:4000] if output else None,
    }

    fname = f"exec{exec_num:04d}_{cell_id}.json"
    (hist_dir / fname).write_text(json.dumps(snap, indent=2, default=str))


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
