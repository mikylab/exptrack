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

from .capture import attach_notebook, detach_notebook, patch_savefig, patch_tensorboard
from .core import Experiment

_active: Experiment | None = None


# ── Explicit API ──────────────────────────────────────────────────────────────

def start(name: str = "", nb_file: str = "", new: bool = False, **params) -> Experiment:
    """Start a new experiment. Pass hyperparams as kwargs.

    ``new=True`` is a readability alias — every ``start()`` already closes the
    prior run and opens a fresh one, so ``start(new=True)`` documents the intent
    ("this is a new attempt") at the call site for the run/try/compare loop.
    """
    global _active
    if _active is not None:
        # Close the prior run at this boundary; auto=True so a run whose last
        # cell raised is recorded 'failed' rather than 'done'.
        _finish_active(auto=True)

    # Try to detect notebook filename
    if not nb_file:
        nb_file = _detect_nb_name()

    # Try to get the IPython shell instance for reliable hook registration
    ip = None
    try:
        ip = get_ipython()
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
    patch_tensorboard(_active)
    return _active


def metric(key: str, value: float, step: int | None = None) -> None:
    _require().log_metric(key, value, step=step)


def metrics(step: int | None = None, **kwargs: float) -> None:
    _require().log_metrics(kwargs, step=step)


def param(key: str, value: Any) -> None:
    _require().log_param(key, value)


def tag(*tags: str) -> None:
    # Route through the real mutator so tags land in the experiments.tags column
    # (the dashboard/CLI read that, not a param). add_tag dedups; batch so N tags
    # collapse to one commit instead of one fsync each.
    exp = _require()
    with exp.batched_writes():
        for t in tags:
            exp.add_tag(t)


def note(text: str) -> None:
    # add_note appends (newline-joined, stripped) and writes the notes column.
    _require().add_note(text)


def artifact(path: str | Path, label: str = "") -> None:
    _require().log_artifact(path, label)


def out(filename: str) -> Path:
    """Get experiment-namespaced output path and register as artifact."""
    return _require().save_output(filename)


def done() -> None:
    """Explicitly finish the active run as successful.

    An explicit done() declares success and always finishes 'done', even if the
    last cell happened to raise — only the automatic finish paths (kernel
    shutdown, a new-run boundary) mark a broken run 'failed'.
    """
    _finish_active(auto=False)


def _finish_active(auto: bool = False) -> None:
    """Finish the active run. When *auto* is True (kernel shutdown / new-run
    boundary) and the most recent cell raised, mark the run 'failed' with its
    traceback so broken runs are self-identifying and never need manual
    deletion."""
    global _active
    if _active is None:
        if not auto:
            print("[exptrack] No active experiment.")
        return
    err_tb = None
    if auto:
        try:
            from .capture.notebook_hooks import consume_cell_error
            err_tb = consume_cell_error()
        except Exception:
            err_tb = None
    try:
        if err_tb and not _active._finished:
            msg = err_tb.strip().splitlines()[-1] if err_tb.strip() else "cell raised an exception"
            _active.fail(msg, traceback=err_tb)
        else:
            _active.finish()
    except Exception as e:
        print(f"[exptrack] warning: could not finish experiment: {e}", file=sys.stderr)
    detach_notebook()
    _active = None


def reset() -> None:
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
        except Exception as e:
            print(f"[exptrack] warning: could not finish active experiment during reset: {e}",
                  file=sys.stderr)
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
    """Try to detect the running notebook's filename.

    Attempts multiple strategies in order of reliability:
    1. VS Code sets __vsc_ipynb_file__ in IPython globals
    2. NOTEBOOK_PATH / JPY_SESSION_NAME environment variables
    3. ipykernel connection file → Jupyter session API lookup
    """
    import os as _os

    # Strategy 1: VS Code injects the notebook path into IPython globals
    try:
        ip = get_ipython()  # type: ignore[name-defined]  # noqa: F821 (IPython builtin)
        vsc_path = ip.user_ns.get("__vsc_ipynb_file__", "")
        if vsc_path:
            return str(vsc_path)
    except Exception:
        pass

    # Strategy 2: Environment variables set by various notebook runners
    for var in ("NOTEBOOK_PATH", "JPY_SESSION_NAME"):
        val = _os.environ.get(var, "")
        if val:
            return val

    # Strategy 3: Query Jupyter session API via kernel ID
    try:
        import json as _json
        import re as _re
        import urllib.request

        import ipykernel

        kernel_id = _re.search(
            r"kernel-(.+)\.json",
            ipykernel.connect.get_connection_file()
        ).group(1)

        # Build list of (url, headers) to try — token-based and xsrf
        token = _os.environ.get("JUPYTER_TOKEN", "")
        for port in [8888, 8889, 8890]:
            try:
                url = f"http://localhost:{port}/api/sessions"
                if token:
                    url += f"?token={token}"
                with urllib.request.urlopen(url, timeout=2) as r:
                    sessions = _json.loads(r.read())
                for s in sessions:
                    if kernel_id in s.get("kernel", {}).get("id", ""):
                        nb_path = s.get("notebook", {}).get("path", "")
                        if nb_path:
                            return nb_path
            except Exception:
                continue
    except Exception:
        pass

    # Strategy 4: IPython %notebook magic / notebook_name config
    # Classic Jupyter sometimes stores the notebook name in
    # NotebookApp.notebook_name or as IPython config metadata.
    try:
        ip = get_ipython()  # type: ignore[name-defined]  # noqa: F821 (IPython builtin)
        # Some notebook servers store session info accessible via JavaScript
        # bridge or display metadata — check IPython's db/history for clues.
        # Also check traitlets config on the running kernel app.
        from ipykernel.zmqshell import ZMQInteractiveShell
        if isinstance(ip, ZMQInteractiveShell):
            # The execute-request parent header was tried here, but the only
            # name it carries is metadata.cellId ("cell-<hash>"), which is not
            # the notebook name. Use the kernel app's connection file instead.
            try:
                from ipykernel.kernelapp import IPKernelApp
                app = IPKernelApp.instance()
                # On some setups, connection_file encodes the notebook name
                conn_file = app.connection_file
                import re as _re
                m = _re.search(r"kernel-(.+?)-[0-9a-f]+\.json", conn_file)
                if m:
                    candidate = m.group(1)
                    if not _re.match(r"^[0-9a-f-]{32,}$", candidate):
                        return candidate + ".ipynb"
            except Exception:
                pass
    except Exception:
        pass

    # Strategy 5: Parse connection file path — some launchers embed the
    # notebook name in the kernel connection filename
    try:
        import ipykernel
        conn = ipykernel.connect.get_connection_file()
        # e.g. kernel-my_notebook-abc123.json
        import re as _re
        m = _re.search(r"kernel-(.+?)-[0-9a-f]+\.json", conn)
        if m:
            candidate = m.group(1)
            # Only use if it looks like a notebook name (not a UUID)
            if not _re.match(r"^[0-9a-f-]{32,}$", candidate):
                return candidate + ".ipynb"
    except Exception:
        pass

    # Strategy 6: Walk CWD for .ipynb files — if there's exactly one, use it.
    # If the user has multiple notebooks open, this won't help, but for the
    # common single-notebook workflow it's a reliable fallback.
    try:
        from pathlib import Path as _Path
        cwd = _Path.cwd()
        notebooks = [f for f in cwd.iterdir()
                     if f.suffix == ".ipynb" and not f.name.startswith(".")]
        if len(notebooks) == 1:
            return str(notebooks[0])
    except Exception:
        pass

    return ""


# ── IPython magic extension ───────────────────────────────────────────────────

def load_ipython_extension(ip: Any) -> None:
    """Called by %load_ext exptrack"""
    from . import config as _cfg
    from .capture import attach_notebook_deferred

    # Don't create an experiment yet — defer until the first real cell runs.
    # This prevents %load_ext exptrack from being counted as its own run.
    #
    # Honor `auto_capture.notebook`: when false, we still register the magics
    # and the session/cell hooks, but never auto-create an experiment from the
    # first code cell. This lets Session Trees (which require %load_ext) be used
    # on their own without an unsolicited run appearing — start runs explicitly
    # with %exp_start / start() instead.
    nb_file = _detect_nb_name()
    auto_nb = _cfg.load().get("auto_capture", {}).get("notebook", True)
    start_fn = _auto_start if auto_nb else None
    attach_notebook_deferred(nb_file=nb_file, ip=ip, start_fn=start_fn)

    def exp_start(line):
        """Start or restart experiment. Optional: %exp_start my_run_name"""
        nb_file = _detect_nb_name()
        _auto_start(nb_file, name=line.strip(), ip=ip)

    def exp_new(line):
        """Start a fresh run (new attempt) without restarting the kernel.

        Finishes the current run (marking it failed if its last cell raised)
        and begins a new one, so each "run, run, try" attempt is its own
        comparable experiment. Put %exp_new at the top of the notebook to make
        every Run-All a separate attempt with zero per-cell ceremony.
        Optional: %exp_new my_run_name

        Same effect as %exp_start (every start closes the prior run) — a
        distinct name for the "this is a new attempt" intent.
        """
        exp_start(line)

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
    ip.register_magic_function(exp_new, magic_kind='line')
    ip.register_magic_function(exp_done, magic_kind='line')
    ip.register_magic_function(exp_status, magic_kind='line')
    ip.register_magic_function(exp_tag, magic_kind='line')
    ip.register_magic_function(exp_note, magic_kind='line')

    # Session Trees magics (%exptrack ..., %%scratch)
    try:
        from .capture.session_hooks import register_session_magics
        register_session_magics(ip)
    except Exception as e:
        print(f"[exptrack] warning: could not register session magics: {e}",
              file=sys.stderr)

    # Finish experiment on kernel shutdown — auto path, so a run whose last
    # cell raised is recorded as 'failed' rather than silently 'done'.
    import atexit
    atexit.register(lambda: _finish_active(auto=True) if _active else None)

    print("[exptrack] Loaded. Use %exp_new, %exp_status, %exp_done, %exp_tag, %exp_note")


def _auto_start(nb_file: str = "", name: str = "", ip: Any = None) -> None:
    global _active
    if _active is not None:
        # New-run boundary — close the prior run (failed if its last cell raised).
        _finish_active(auto=True)

    _active = Experiment(
        name=name or "",
        script=nb_file or "notebook",
        _caller_depth=3,
    )
    nb_name = Path(nb_file).stem if nb_file else "notebook"
    attach_notebook(_active, nb_name=nb_name, ip=ip)
    patch_savefig(_active)
    patch_tensorboard(_active)
