"""
exptrack/capture/notebook_hooks.py — IPython post_run_cell hook and snapshot saving
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .. import config as cfg
from .cell_lineage import (
    cell_hash,
    find_parent_hash,
    get_cell_baseline,
    get_cell_source,
    is_magic_only,
    simple_diff,
    store_cell_lineage,
    update_cell_baseline,
)
from .variables import (
    _HP_RE,
    _SCALAR,
    _SKIP_NAMES,
    extract_assignments,
    is_observational,
    var_fingerprint,
    var_summary,
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
    "_stdout_buf":   None,    # StringIO capturing the running cell's stdout
}

# Cap on captured cell output (stdout + trailing-expression repr) stored per
# cell — keeps a chatty training loop from bloating the DB / dashboard.
_MAX_CELL_OUTPUT = 4000
# The live tee stops buffering past this so a cell printing megabytes can't
# balloon memory; the headroom over _MAX_CELL_OUTPUT lets _combine_cell_output
# still detect the overflow and add its "… (output truncated)" marker.
_STDOUT_BUFFER_CAP = _MAX_CELL_OUTPUT * 2


class _StdoutTee:
    """Wraps a stream so writes go to BOTH the original (the notebook still
    shows the output) and a capture buffer (so exptrack can record print()
    output). Buffering is bounded at _STDOUT_BUFFER_CAP — writes past that still
    reach the real stream but aren't captured. Everything else delegates to the
    original stream."""

    def __init__(self, original, buffer):
        self._original = original
        self._buffer = buffer
        self._captured = 0

    def write(self, s):
        try:
            remaining = _STDOUT_BUFFER_CAP - self._captured
            if remaining > 0:
                chunk = s if len(s) <= remaining else s[:remaining]
                self._buffer.write(chunk)
                self._captured += len(chunk)
        except Exception:
            pass
        return self._original.write(s)

    def flush(self):
        return self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)


def _start_stdout_capture():
    """Install a tee on sys.stdout so the running cell's printed output is
    captured. Idempotent and defensive — never breaks the user's cell."""
    try:
        if isinstance(sys.stdout, _StdoutTee):
            return  # already capturing (re-entrant pre_run_cell)
        buf = io.StringIO()
        _nb_state["_stdout_buf"] = buf
        sys.stdout = _StdoutTee(sys.stdout, buf)
    except Exception as e:
        print(f"[exptrack] warning: could not start stdout capture: {e}",
              file=sys.stderr)


def _collect_stdout_capture() -> str:
    """Read the captured stdout for the cell that just ran and restore the
    original stream. Returns the captured text ('' if none). Always restores,
    so an early return in the post-hook can't leave the tee installed."""
    text = ""
    buf = _nb_state.get("_stdout_buf")
    try:
        if buf is not None:
            text = buf.getvalue()
    except Exception:
        pass
    # Restore only if our tee is still the active stream — the user's cell may
    # have swapped sys.stdout itself, in which case we leave their choice alone.
    try:
        if isinstance(sys.stdout, _StdoutTee):
            sys.stdout = sys.stdout._original
    except Exception:
        pass
    _nb_state["_stdout_buf"] = None
    return text


def _combine_cell_output(stdout_text: str, result_repr):
    """Merge captured stdout (print output) with the trailing-expression repr
    into one output blob, mirroring what the notebook shows (prints first, then
    the cell's returned value). Caps the total so a chatty cell can't bloat the
    DB. Returns None when the cell produced nothing."""
    parts = []
    if stdout_text:
        parts.append(stdout_text.rstrip("\n"))
    if result_repr:
        parts.append(str(result_repr))
    combined = "\n".join(p for p in parts if p)
    if not combined:
        return None
    if len(combined) > _MAX_CELL_OUTPUT:
        combined = combined[:_MAX_CELL_OUTPUT] + "\n… (output truncated)"
    return combined


def _pre_run_cell(info=None, *args, **kwargs):
    """IPython pre_run_cell hook — start capturing this cell's stdout and
    reserve the cell_exec event's timeline seq, so artifacts saved mid-cell
    (e.g. plt.savefig) sort *after* the code rather than before it."""
    _start_stdout_capture()
    _nb_state["_reserved_seq"] = None
    exp = _nb_state.get("exp")
    if exp is not None:
        try:
            _nb_state["_reserved_seq"] = exp.reserve_timeline_seq()
        except Exception as e:
            print(f"[exptrack] warning: could not reserve timeline seq: {e}",
                  file=sys.stderr)


def attach_notebook(exp: Experiment, nb_name: str = "notebook", ip=None):
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
            ip = get_ipython()
        except NameError:
            return
    _nb_state["ip"] = ip
    _unregister_hook(ip)
    ip.events.register("pre_run_cell", _pre_run_cell)
    ip.events.register("post_run_cell", _post_run_cell)


def attach_notebook_deferred(nb_file: str = "", ip=None, start_fn=None):
    """
    Install the post_run_cell hook but DON'T create an experiment yet.
    The experiment is created on the first real (non-magic) cell execution,
    so that `%load_ext exptrack` itself is never counted as a run.

    Eagerly patches plt.savefig so plots saved before the experiment is
    created are buffered and registered once the experiment starts.
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

    # Eagerly patch savefig so plots saved before the experiment is created
    # are buffered and flushed when the experiment starts.
    from .matplotlib_patch import patch_savefig
    patch_savefig()

    if ip is None:
        try:
            ip = get_ipython()
        except NameError:
            return
    _nb_state["ip"] = ip
    _unregister_hook(ip)
    ip.events.register("pre_run_cell", _pre_run_cell)
    ip.events.register("post_run_cell", _post_run_cell)


def _is_magic_only(source: str) -> bool:
    """Return True if source consists only of IPython magic commands, comments,
    or blank lines. Used to defer experiment start past setup-only cells.

    Distinct from ``cell_lineage.is_magic_only`` (which requires an actual magic
    line) — here an all-comment/blank cell also counts, so we don't start the
    experiment on it."""
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
            ip = get_ipython()
        except NameError:
            return
    _unregister_hook(ip)


def _unregister_hook(ip):
    # _post_execute is just an alias for _post_run_cell (same object), so
    # unregistering _post_run_cell from both events covers it.
    for hook_fn, events in (
        (_post_run_cell, ("post_run_cell", "post_execute")),
        (_pre_run_cell, ("pre_run_cell",)),
    ):
        for event in events:
            try:
                ip.events.unregister(event, hook_fn)
            except ValueError:
                pass  # hook wasn't registered for this event — expected
            except Exception as e:
                print(f"[exptrack] warning: could not unregister {event} hook: {e}",
                      file=sys.stderr)


def _get_cell_source(result, ip):
    """Extract cell source and output from the execution result.

    Returns (source, output) where source may be None if no source is found.
    """
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
        except Exception as e:
            print(f"[exptrack] warning: could not capture cell output: {e}", file=sys.stderr)
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
    if output is None and source:
        try:
            exec_count = ip.execution_count
            out_dict = ip.user_ns.get("Out", {})
            if exec_count in out_dict:
                output = repr(out_dict[exec_count])
            elif exec_count - 1 in out_dict:
                output = repr(out_dict[exec_count - 1])
        except Exception as e:
            print(f"[exptrack] warning: could not get cell output from Out dict: {e}", file=sys.stderr)
    return source, output


def _handle_deferred_start(source, ip):
    """Handle deferred experiment start. Returns True if cell should be skipped."""
    if not _nb_state.get("deferred"):
        return False
    if _is_magic_only(source):
        return True
    start_fn = _nb_state.get("deferred_start_fn")
    nb_file = _nb_state.get("deferred_nb_file", "")
    _nb_state["deferred"] = False
    _nb_state["deferred_start_fn"] = None
    # Only create an experiment if one wasn't already started by
    # an explicit start() call during this cell's execution.
    if _nb_state.get("exp") is None and start_fn:
        start_fn(nb_file, ip=ip)
    return False


def _process_cell_lineage(source, ch, notebook, exec_num):
    """Handle content-addressed lineage and diff computation.

    Returns (code_is_new, code_changed, source_diff, parent_source, parent_hash,
             already_seen).
    """
    # Magic-only cells (e.g. %exptrack checkpoint/branch) are commands, not
    # editable code — keep them out of lineage so they never get a fuzzy
    # "parent" to word-diff against, and show no new/edited badge or diff.
    # Still stored (parent_hash=None) so "view source" works.
    magic_only = is_magic_only(source)

    # ── 1. Content-addressed cell lineage ────────────────────────────────
    parent_hash = None if magic_only else find_parent_hash(notebook, source, ch)
    store_cell_lineage(notebook, source, parent_hash)

    # ── 2. Compute diff against parent cell (if any) ────────────────────
    code_is_new = (not magic_only) and parent_hash is None
    code_changed = False
    source_diff = None
    parent_source = None

    already_seen = ch in _nb_state["cell_history"]

    if magic_only or already_seen:
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
    if baseline_source is None or source != baseline_source:
        update_cell_baseline(notebook, exec_num, source)

    return code_is_new, code_changed, source_diff, parent_source, parent_hash, already_seen


def _capture_variables(ip, cell_assignments):
    """Capture new/changed variables (scalars + arrays + more).

    Per-variable errors are isolated so one bad variable doesn't crash the
    whole cell capture.

    Returns (new_vars, changed_vars) and updates _nb_state["var_snapshot"].
    """
    ns = ip.user_ns
    prev_snap = _nb_state["var_snapshot"]
    new_vars, changed_vars = {}, {}
    new_snap = {}
    # Read the content-hash size cap once per cell (config is cached). Hashing
    # every DataFrame/array in the namespace on every cell is the dominant
    # per-cell cost, so this single pass computes each fingerprint exactly once
    # (it used to run twice — detect + snapshot).
    max_bytes = int(cfg.load().get("var_fingerprint_max_mb", 100)) * 1024 * 1024

    for name, val in list(ns.items()):
        if name.startswith("_") or name in _SKIP_NAMES:
            continue
        try:
            summary = var_summary(val)
            tname = type(val).__name__

            # `display` is the rich form shown on the timeline var_set event
            # (may include the `name = expr` assignment). `param` is the stable
            # value stored as the `_var/<name>` param — always the bare summary
            # (never the assignment prefix), so re-logging an unchanged var is
            # idempotent and never trips the "param overwritten" warning.
            if summary is None:
                if name not in cell_assignments:
                    continue
                expr = cell_assignments[name]
                fp = f"{tname}:{name}:{cell_hash(expr)}"
                display = (f"{name} = {expr}  # {tname}"
                           if len(expr) <= 500 else f"{tname}()")
                param = display
            else:
                fp = var_fingerprint(val, max_bytes=max_bytes)
                display = summary
                param = summary
                if not isinstance(val, _SCALAR) and name in cell_assignments:
                    expr = cell_assignments[name]
                    if len(expr) <= 500:
                        display = f"{name} = {expr}  # {summary}"

            if name not in prev_snap:
                new_vars[name] = {"display": display, "param": param}
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
                        "param": param,
                    }
            new_snap[name] = {"fp": fp, "display": display}
        except Exception as e:
            print(f"[exptrack] warning: could not capture variable '{name}': {e}",
                  file=sys.stderr)

    _nb_state["var_snapshot"] = new_snap

    return new_vars, changed_vars


def _emit_timeline_events(exp, ch, exec_num, source, source_diff, output,
                          code_is_new, code_changed, parent_hash,
                          already_seen, is_obs, new_vars, changed_vars):
    """Emit timeline events for cell execution, variable changes, and overflow."""
    from .. import config as _cfg
    _conf = _cfg.load()

    diff_str = None
    if source_diff:
        diff_str = json.dumps(source_diff)
        # Truncate large source diffs at capture time
        max_diff_kb = _conf.get("max_source_diff_kb", 20)
        if max_diff_kb and len(diff_str) > max_diff_kb * 1024:
            n_lines = len(source_diff)
            diff_str = json.dumps([{
                "op": "summary",
                "line": f"{n_lines} lines changed (diff truncated at {max_diff_kb} KB)"
            }])

    event_type = "observational" if is_obs else "cell_exec"
    # Use the seq reserved in pre_run_cell (if any) so the code event sorts
    # before any artifacts saved mid-cell; clear it so it can't leak to a later
    # cell that doesn't reserve one.
    reserved_seq = _nb_state.pop("_reserved_seq", None)
    exp.log_event(
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
            # Already capped at _MAX_CELL_OUTPUT in _combine_cell_output; store
            # it whole so the dashboard's "Out" panel can show real print output.
            "output_preview": str(output) if output else None,
        },
        source_diff=diff_str,
        seq=reserved_seq,
    )

    max_vars = _conf.get("max_vars_per_cell", 50)
    var_count = 0
    for name, info in new_vars.items():
        var_count += 1
        if max_vars and var_count > max_vars:
            overflow = len(new_vars) + len(changed_vars) - max_vars
            exp.log_event(
                event_type="var_set",
                cell_hash=ch, cell_pos=exec_num,
                key="_var_overflow",
                value=f"{overflow} more variables changed (truncated at {max_vars})",
            )
            break
        exp.log_event(
            event_type="var_set",
            cell_hash=ch,
            cell_pos=exec_num,
            key=name,
            value=info["display"],
            prev_value=None,
        )

    for name, change in changed_vars.items():
        var_count += 1
        if max_vars and var_count > max_vars:
            overflow = len(new_vars) + len(changed_vars) - max_vars
            exp.log_event(
                event_type="var_set",
                cell_hash=ch, cell_pos=exec_num,
                key="_var_overflow",
                value=f"{overflow} more variables changed (truncated at {max_vars})",
            )
            break
        prev_display = change.get("from", "(unknown)")
        exp.log_event(
            event_type="var_set",
            cell_hash=ch,
            cell_pos=exec_num,
            key=name,
            value=change["to"],
            prev_value=prev_display,
        )


def _log_hp_params(exp, ns, new_vars, changed_vars, source_diff,
                   code_is_new, code_changed, already_seen, exec_num):
    """Log HP variables as top-level params and handle code change/rerun logging."""
    def _scalar_val(name):
        v = ns.get(name)
        return v if isinstance(v, _SCALAR) else None

    hp_new = {k: _scalar_val(k) for k in new_vars if _HP_RE.match(k) and _scalar_val(k) is not None}
    hp_changed = {k: _scalar_val(k) for k in changed_vars if _HP_RE.match(k) and _scalar_val(k) is not None}
    if hp_new or hp_changed:
        exp.log_params({**hp_new, **hp_changed})
        from ..core import make_run_name
        exp._rename(make_run_name(exp.script, exp._params))

    all_new_var = {f"_var/{k}": v["param"] for k, v in new_vars.items()}
    all_changed_var = {f"_var/{k}": d["param"] for k, d in changed_vars.items()}
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


def _post_run_cell(result=None):
    """Runs after every notebook cell. Captures diff, variables, and output.
    Now also emits timeline events for full execution order tracking."""

    try:
        ip = _nb_state.get("ip")
        if ip is None:
            try:
                ip = get_ipython()
            except NameError:
                return

        # ── 0. Get the cell source and output ────────────────────────────────
        # Always collect (and tear down) the stdout tee installed by the
        # pre_run_cell hook, even on an early return, so it never leaks.
        captured_stdout = _collect_stdout_capture()
        source, result_repr = _get_cell_source(result, ip)
        if not source:
            return
        # Full cell output = printed stdout + the trailing-expression repr,
        # mirroring what the notebook displays (prints, then the returned value).
        output = _combine_cell_output(captured_stdout, result_repr)

        # ── 0a. Skip scratch cells entirely (Session Trees) ───────────────────
        try:
            from .session_hooks import is_scratch_cell
            if is_scratch_cell(source):
                return
        except Exception as e:
            print(f"[exptrack] warning: scratch-cell check failed: {e}",
                  file=sys.stderr)

        # ── 0a'. Buffer non-scratch cells onto the active session ────────────
        try:
            from ..sessions import get_current_session
            sm = get_current_session()
            if sm is not None and sm.session_id:
                sm.record_cell(source, output)
        except Exception as e:
            print(f"[exptrack] warning: could not record cell on active session: {e}",
                  file=sys.stderr)

        # ── 0b. Handle deferred start ────────────────────────────────────────
        if _handle_deferred_start(source, ip):
            return

        exp = _nb_state["exp"]
        if exp is None:
            return

        _nb_state["exec_count"] += 1
        exec_num = _nb_state["exec_count"]
        ch = cell_hash(source)
        notebook = _nb_state["nb_name"]

        # ── 1-2b. Cell lineage and diff ──────────────────────────────────────
        (code_is_new, code_changed, source_diff, parent_source,
         parent_hash, already_seen) = _process_cell_lineage(
            source, ch, notebook, exec_num)

        # ── 3. Detect observational cells ────────────────────────────────────
        is_obs = is_observational(source)

        # ── 4. Extract assignment expressions from cell source ───────────────
        cell_assignments = extract_assignments(source)

        # ── 5. Capture new/changed variables ─────────────────────────────────
        new_vars, changed_vars = _capture_variables(ip, cell_assignments)

        _nb_state["first_run"] = False

        # ── 6-7. Emit timeline events + log params, committed as one batch ───
        # A single cell emits cell_exec + up to max_vars_per_cell var_set events
        # plus the _var/ params; batching collapses ~52 commits into one fsync.
        with exp.batched_writes():
            _emit_timeline_events(
                exp, ch, exec_num, source, source_diff, output,
                code_is_new, code_changed, parent_hash,
                already_seen, is_obs, new_vars, changed_vars)

            _log_hp_params(
                exp, ip.user_ns, new_vars, changed_vars, source_diff,
                code_is_new, code_changed, already_seen, exec_num)

        # ── 8. Save snapshot to .exptrack/notebook_history/ ───────────────────
        _save_cell_snapshot(exp, exec_num, ch, source,
                            parent_source or "",
                            source_diff, new_vars, changed_vars, output,
                            is_rerun=(already_seen and not code_changed
                                      and not new_vars and not changed_vars),
                            is_observational=is_obs)

    except Exception as _e:
        import traceback
        print(f"[exptrack] cell capture error: {_e}", file=sys.stderr)
        traceback.print_exc()


# Backward-compat alias — old code registered _post_execute
_post_execute = _post_run_cell


def _save_cell_snapshot(exp, exec_num, cell_id, source, prev_source,
                        source_diff, new_vars, changed_vars, output,
                        is_rerun=False, is_observational=False):
    from .. import config as cfg
    conf = cfg.load()

    # Skip writing snapshot files when notebook_history is disabled (default)
    if not conf.get("notebook_history", False):
        return

    root = cfg.project_root()
    nb_name = _nb_state["nb_name"]
    hist_dir = root / conf.get("notebook_history_dir",
                                ".exptrack/notebook_history") / nb_name
    hist_dir.mkdir(parents=True, exist_ok=True)

    max_output = conf.get("max_cell_output_chars", 2000)
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
        "output":       str(output)[:max_output] if output else None,
        "is_rerun":     is_rerun,
        "is_observational": is_observational,
        "source":       source if (not prev_source and source_diff) else None,
    }

    fname = f"exec{exec_num:04d}_{cell_id}.json"
    (hist_dir / fname).write_text(json.dumps(snap, indent=2, default=str))
