"""
exptrack/capture/notebook_hooks.py — IPython post_run_cell hook and snapshot saving
"""
from __future__ import annotations
import json
import hashlib
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .variables import (
    _HP_RE, _SCALAR, _SKIP_NAMES, is_observational,
    var_summary, var_fingerprint, extract_assignments,
)
from .cell_lineage import (
    cell_hash, find_parent_hash, store_cell_lineage,
    get_cell_source, get_cell_baseline, update_cell_baseline,
    simple_diff,
)

if TYPE_CHECKING:
    from ..core import Experiment

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
}


def attach_notebook(exp: "Experiment", nb_name: str = "notebook", ip=None):
    """
    Install the post_run_cell hook into the running IPython kernel.
    Safe to call outside notebooks — does nothing if IPython isn't active.
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
    for hook_fn in (_post_run_cell, _post_execute):
        try:
            ip.events.unregister("post_run_cell", hook_fn)
        except (ValueError, Exception):
            pass
        try:
            ip.events.unregister("post_execute", hook_fn)
        except (ValueError, Exception):
            pass


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

        # ── 0. Get the cell source and output early ─────────────────────────
        source = None
        output = None
        if result is not None:
            try:
                source = result.info.raw_cell
            except AttributeError:
                pass
            try:
                if hasattr(result, 'result') and result.result is not None:
                    output = repr(result.result)
                elif hasattr(result, 'info') and hasattr(result.info, 'result'):
                    output = repr(result.info.result) if result.info.result is not None else None
            except Exception:
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
        if output is None:
            try:
                exec_count = ip.execution_count
                out_dict = ip.user_ns.get("Out", {})
                if exec_count in out_dict:
                    output = repr(out_dict[exec_count])
                elif exec_count - 1 in out_dict:
                    output = repr(out_dict[exec_count - 1])
            except Exception:
                pass

        # ── 0b. Handle deferred start ────────────────────────────────────────
        if _nb_state.get("deferred"):
            if _is_magic_only(source):
                return
            start_fn = _nb_state.get("deferred_start_fn")
            nb_file = _nb_state.get("deferred_nb_file", "")
            _nb_state["deferred"] = False
            _nb_state["deferred_start_fn"] = None
            if start_fn:
                start_fn(nb_file, ip=ip)

        exp = _nb_state["exp"]
        if exp is None:
            return

        _nb_state["exec_count"] += 1
        exec_num = _nb_state["exec_count"]
        ch = cell_hash(source)
        notebook = _nb_state["nb_name"]

        # ── 1. Content-addressed cell lineage ────────────────────────────────
        parent_hash = find_parent_hash(notebook, source, ch)
        store_cell_lineage(notebook, source, parent_hash)

        # ── 2. Compute diff against parent cell (if any) ────────────────────
        code_is_new = parent_hash is None
        code_changed = False
        source_diff = None
        parent_source = None

        already_seen = ch in _nb_state["cell_history"]

        if already_seen:
            pass
        elif code_is_new:
            source_diff = [{"op": "+", "line": line}
                           for line in source.splitlines() if line.strip()]
        else:
            parent_source = get_cell_source(parent_hash)
            if parent_source and parent_source != source:
                code_changed = True
                source_diff = simple_diff(parent_source, source)

        _nb_state["cell_history"][ch] = source
        _nb_state["last_cell_hash"] = ch

        # ── 2b. Also update legacy position-based baselines ──────────────────
        baseline_source = get_cell_baseline(notebook, exec_num)
        if baseline_source is None:
            update_cell_baseline(notebook, exec_num, source)
        elif source != baseline_source:
            update_cell_baseline(notebook, exec_num, source)

        # ── 3. Detect observational cells ────────────────────────────────────
        is_obs = is_observational(source)

        # ── 4. Extract assignment expressions from cell source ───────────────
        cell_assignments = extract_assignments(source)

        # ── 5. Capture new/changed variables (scalars + arrays + more) ───────
        ns = ip.user_ns
        prev_snap = _nb_state["var_snapshot"]
        new_vars, changed_vars = {}, {}

        for name, val in list(ns.items()):
            if name.startswith("_") or name in _SKIP_NAMES:
                continue
            summary = var_summary(val)
            tname = type(val).__name__

            if summary is None:
                if name not in cell_assignments:
                    continue
                expr = cell_assignments[name]
                summary = f"{tname}()"
                if len(expr) <= 500:
                    display = f"{name} = {expr}  # {tname}"
                else:
                    display = f"{tname}()"
                fp = f"{tname}:{name}:{cell_hash(expr)}"
            else:
                fp = var_fingerprint(val)
                display = summary
                if not isinstance(val, _SCALAR) and name in cell_assignments:
                    expr = cell_assignments[name]
                    if len(expr) <= 500:
                        display = f"{name} = {expr}  # {summary}"

            if name not in prev_snap:
                new_vars[name] = display
            else:
                prev_entry = prev_snap[name]
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

        new_snap = {}
        for name, val in list(ns.items()):
            if name.startswith("_") or name in _SKIP_NAMES:
                continue
            summary = var_summary(val)
            if summary is not None:
                new_snap[name] = {
                    "fp": var_fingerprint(val),
                    "display": summary,
                }
            elif name in cell_assignments:
                tname = type(val).__name__
                expr = cell_assignments[name]
                new_snap[name] = {
                    "fp": f"{tname}:{name}:{cell_hash(expr)}",
                    "display": f"{name} = {expr}  # {tname}"
                        if len(expr) <= 500 else f"{tname}()",
                }
        _nb_state["var_snapshot"] = new_snap

        is_first = _nb_state["first_run"]
        _nb_state["first_run"] = False

        # ── 6. Emit timeline events ──────────────────────────────────────────
        diff_str = None
        if source_diff:
            diff_str = json.dumps(source_diff)

        event_type = "observational" if is_obs else "cell_exec"
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
                "has_output": output is not None,
                "output_preview": str(output)[:200] if output else None,
            },
            source_diff=diff_str,
        )

        for name, display in new_vars.items():
            exp.log_event(
                event_type="var_set",
                cell_hash=ch,
                cell_pos=exec_num,
                key=name,
                value=display,
                prev_value=None,
            )

        for name, change in changed_vars.items():
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

        all_new_var = {f"_var/{k}": v for k, v in new_vars.items()}
        all_changed_var = {f"_var/{k}": d["to"] for k, d in changed_vars.items()}
        if all_new_var or all_changed_var:
            exp.log_params({**all_new_var, **all_changed_var})

        if source_diff and (code_is_new or code_changed):
            diff_summary = "; ".join(
                f"{'+'if e['op']=='+'else '-'} {e['line'].strip()}"
                for e in source_diff if e["op"] != "="
            )[:500]
            if diff_summary:
                exp.log_param(f"_code_change/cell_{exec_num}", diff_summary)

        if already_seen and not code_changed and not new_vars and not changed_vars:
            _nb_state["cells_ran"].append(exec_num)
            exp.log_param("_cells_ran", json.dumps(_nb_state["cells_ran"]))

        # ── 8. Save snapshot to .exptrack/notebook_history/ ───────────────────
        _save_cell_snapshot(exp, exec_num, ch, source,
                            parent_source or "",
                            source_diff, new_vars, changed_vars, output,
                            is_rerun=(already_seen and not code_changed
                                      and not new_vars and not changed_vars),
                            is_observational=is_obs)

    except Exception as _e:
        print(f"[exptrack] cell capture error: {_e}", file=sys.stderr)


# Backward-compat alias — old code registered _post_execute
_post_execute = _post_run_cell


def _save_cell_snapshot(exp, exec_num, cell_id, source, prev_source,
                        source_diff, new_vars, changed_vars, output,
                        is_rerun=False, is_observational=False):
    from .. import config as cfg
    root = cfg.project_root()
    nb_name = _nb_state["nb_name"]
    hist_dir = root / cfg.load().get("notebook_history_dir",
                                      ".exptrack/notebook_history") / nb_name
    hist_dir.mkdir(parents=True, exist_ok=True)

    snap = {
        "exp_id":       exp.id,
        "exp_name":     exp.name,
        "ts":           datetime.now(timezone.utc).isoformat(),
        "exec_num":     exec_num,
        "cell_id":      cell_id,
        "source_hash":  hashlib.md5(source.encode()).hexdigest()[:12],
        "source_diff":  source_diff,
        "new_vars":     new_vars,
        "changed_vars": changed_vars,
        "output":       str(output)[:2000] if output else None,
        "is_rerun":     is_rerun,
        "is_observational": is_observational,
        "source":       source if (not prev_source and source_diff) else None,
    }

    fname = f"exec{exec_num:04d}_{cell_id}.json"
    (hist_dir / fname).write_text(json.dumps(snap, indent=2, default=str))
