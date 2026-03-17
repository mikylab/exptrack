"""
exptrack/notebook.py — Jupyter integration

Two ways to use:

--- Option A: Magic extension (zero friction) ----
Load once at the top of your notebook:

    %load_ext exptrack

That's it. A new experiment starts automatically. Every cell execution is
snapshotted. Hyperparameter variables (lr, batch_size, etc.) are captured
automatically. Call %exp_done when finished.

Magic commands:
    %exp_start [name]     start/restart experiment (optional name override)
    %exp_done             finish experiment (also runs on kernel shutdown)
    %exp_status           show current experiment id + params so far
    %exp_tag foo bar      add tags
    %exp_note "text"      add a note

--- Option B: Explicit API ----
    from exptrack.notebook import start, metric, out, done, current

    run = start(lr=0.001, bs=32)      # kwargs become params
    metric("val/loss", 0.23, step=5)
    path = out("preds.csv")           # namespaced output path
    done()
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any

from .core import Experiment, output_path
from .capture import attach_notebook, detach_notebook, patch_savefig

_active: Experiment | None = None


# ── Explicit API ──────────────────────────────────────────────────────────────

def start(name: str = "", nb_file: str = "", **params) -> Experiment:
    """Start a new experiment. Pass hyperparams as kwargs."""
    global _active
    if _active is not None:
        try: _active.finish()
        except Exception as e: print(f"[exptrack] warning: could not finish previous experiment: {e}", file=sys.stderr)
        detach_notebook()
        _active = None

    # Try to detect notebook filename
    if not nb_file:
        nb_file = _detect_nb_name()

    # Try to get the IPython shell instance for reliable hook registration
    ip = None
    try:
        ip = get_ipython()  # noqa
    except NameError:
        pass

    _active = Experiment(
        name=name,
        params=params or None,
        script=nb_file or "notebook",
        _caller_depth=2,
    )
    attach_notebook(_active, nb_name=Path(nb_file).stem if nb_file else "notebook", ip=ip)
    patch_savefig(_active)
    return _active


def metric(key: str, value: float, step: int = None):
    _require().log_metric(key, value, step=step)


def metrics(step: int = None, **kwargs):
    _require().log_metrics(kwargs, step=step)


def param(key: str, value: Any):
    _require().log_param(key, value)


def tag(*tags: str):
    exp = _require()
    exp.tags.extend(tags)
    exp.log_param("_tags", exp.tags)


def note(text: str):
    exp = _require()
    exp.notes = (exp.notes + "\n" + text).strip()
    from .core import get_db
    with get_db() as conn:
        conn.execute("UPDATE experiments SET notes=? WHERE id=?", (exp.notes, exp.id))
        conn.commit()


def artifact(path: str | Path, label: str = ""):
    _require().log_artifact(path, label)


def out(filename: str) -> Path:
    """Get experiment-namespaced output path and register as artifact."""
    return _require().save_output(filename)


def done():
    global _active
    if _active is None:
        print("[exptrack] No active experiment.")
        return
    _active.finish()
    detach_notebook()
    _active = None


def reset():
    """Force-close the database connection and detach hooks.

    Use this in a notebook to clean up leaked connections from before
    the caching fix. Safe to call anytime — next operation reopens fresh.

        from exptrack.notebook import reset
        reset()
    """
    global _active
    if _active is not None:
        try:
            _active.finish()
        except Exception:
            pass
        detach_notebook()
        _active = None
    from .core import close_db
    close_db()
    print("[exptrack] Connection closed and hooks detached.")


def current() -> Experiment | None:
    return _active


def _require() -> Experiment:
    if _active is None:
        raise RuntimeError(
            "No active experiment. Call exptrack.notebook.start() "
            "or use %load_ext exptrack"
        )
    return _active


def _detect_nb_name() -> str:
    """Try to detect the running notebook's filename."""
    try:
        import ipykernel
        import json as _json
        import re as _re
        import urllib.request

        kernel_id = _re.search(
            r"kernel-(.+)\.json",
            ipykernel.connect.get_connection_file()
        ).group(1)

        for port in [8888, 8889, 8890]:
            try:
                url = f"http://localhost:{port}/api/sessions"
                # Try with token from environment if available
                import os as _os
                token = _os.environ.get("JUPYTER_TOKEN", "")
                if token:
                    url += f"?token={token}"
                with urllib.request.urlopen(url, timeout=2) as r:
                    sessions = _json.loads(r.read())
                for s in sessions:
                    if kernel_id in s.get("kernel", {}).get("id", ""):
                        return s.get("notebook", {}).get("path", "")
            except Exception:
                continue  # expected — port may not exist or may need auth
    except Exception:
        pass  # notebook name detection is best-effort
    return ""


# ── IPython magic extension ───────────────────────────────────────────────────

def load_ipython_extension(ip):
    """Called by %load_ext exptrack"""
    from .capture import attach_notebook_deferred

    # Don't create an experiment yet — defer until the first real cell runs.
    # This prevents %load_ext exptrack from being counted as its own run.
    nb_file = _detect_nb_name()
    attach_notebook_deferred(nb_file=nb_file, ip=ip, start_fn=_auto_start)

    def exp_start(line):
        """Start or restart experiment. Optional: %exp_start my_run_name"""
        nb_file = _detect_nb_name()
        _auto_start(nb_file, name=line.strip(), ip=ip)

    def exp_done(line):
        """Finish the current experiment."""
        done()

    def exp_status(line):
        """Show current experiment."""
        exp = current()
        if exp is None:
            print("[exptrack] No active experiment.")
            return
        print(f"[exptrack] Active: {exp.name}  ({exp.id[:6]})")
        if exp._params:
            print("  Params:")
            for k, v in exp._params.items():
                print(f"    {k} = {v}")

    def exp_tag(line):
        """Add tags: %exp_tag baseline resnet"""
        tag(*line.strip().split())

    def exp_note(line):
        """Add a note: %exp_note "tried higher dropout" """
        note(line.strip().strip('"\''))

    # Register magics via the ip instance (works without get_ipython() context)
    ip.register_magic_function(exp_start, magic_kind='line')
    ip.register_magic_function(exp_done, magic_kind='line')
    ip.register_magic_function(exp_status, magic_kind='line')
    ip.register_magic_function(exp_tag, magic_kind='line')
    ip.register_magic_function(exp_note, magic_kind='line')

    # Finish experiment on kernel shutdown
    import atexit
    atexit.register(lambda: done() if _active else None)

    print(f"[exptrack] Loaded. Use %exp_status, %exp_done, %exp_tag, %exp_note")


def _auto_start(nb_file: str = "", name: str = "", ip=None):
    global _active
    if _active is not None:
        try: _active.finish()
        except Exception as e: print(f"[exptrack] warning: could not finish previous experiment: {e}", file=sys.stderr)
        detach_notebook()

    _active = Experiment(
        name=name or "",
        script=nb_file or "notebook",
        _caller_depth=3,
    )
    nb_name = Path(nb_file).stem if nb_file else "notebook"
    attach_notebook(_active, nb_name=nb_name, ip=ip)
    patch_savefig(_active)
