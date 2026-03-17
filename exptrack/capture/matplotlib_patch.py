"""
exptrack/capture/matplotlib_patch.py — Monkey-patch plt.savefig for auto artifact capture
"""
from __future__ import annotations

import shutil
import sys
from typing import TYPE_CHECKING

from .notebook_hooks import _nb_state

if TYPE_CHECKING:
    from ..core import Experiment

_plt_patched = False
# Buffer for savefig calls that happen before an experiment is created
_pending_artifacts: list[dict] = []

def patch_savefig(exp: Experiment | None = None):
    """
    Monkey-patch matplotlib.pyplot.savefig and Figure.savefig so that every
    saved plot is automatically registered as an artifact on the active
    experiment.  Also emits a timeline 'artifact' event linking the saved
    plot to the current variable context.

    Can be called with exp=None to eagerly install the patch (e.g. during
    deferred notebook start).  Artifacts saved before an experiment exists
    are buffered and flushed when the experiment is created.
    """
    global _plt_patched
    if exp is not None:
        _nb_state["exp"] = exp
        _flush_pending(exp)
    if _plt_patched:
        return
    _plt_patched = True

    try:
        import matplotlib.figure as mfig
        import matplotlib.pyplot as plt
    except ImportError:
        return

    _orig_plt_savefig = plt.savefig
    _orig_fig_savefig = mfig.Figure.savefig
    _savefig_in_progress = [False]

    def _namespace_and_save(fname, save_fn, *args, **kwargs):
        """Save the file, copy to experiment output dir, and register as artifact."""
        from pathlib import Path as _P
        if _savefig_in_progress[0]:
            return save_fn(fname, *args, **kwargs)
        _savefig_in_progress[0] = True
        try:
            result = save_fn(fname, *args, **kwargs)
            cur_exp = _nb_state.get("exp")

            orig_path = _P(str(fname)).resolve()

            if not orig_path.exists():
                fmt = kwargs.get("format")
                if not fmt:
                    try:
                        import matplotlib as _mpl
                        fmt = _mpl.rcParams.get("savefig.format", "png")
                    except Exception as e:
                        print(f"[exptrack] warning: could not detect savefig format: {e}", file=sys.stderr)
                        fmt = "png"
                candidate = orig_path.with_suffix("." + fmt)
                if candidate.exists():
                    orig_path = candidate
                else:
                    for ext in ('.png', '.pdf', '.svg', '.jpg', '.eps'):
                        candidate = orig_path.with_suffix(ext)
                        if candidate.exists():
                            orig_path = candidate
                            break

            fig_title = _nb_state.pop("_last_fig_title", "")

            # No experiment yet — buffer the artifact for later
            if cur_exp is None:
                if orig_path.exists():
                    _pending_artifacts.append({
                        "orig_path": str(orig_path),
                        "fig_title": fig_title,
                        "cell_hash": _nb_state.get("last_cell_hash"),
                    })
                return result

            _register_and_protect(cur_exp, orig_path, fig_title)
            return result
        finally:
            _savefig_in_progress[0] = False

    def _hooked_plt_savefig(fname, *args, **kwargs):
        return _namespace_and_save(fname, _orig_plt_savefig, *args, **kwargs)

    def _hooked_fig_savefig(self_fig, fname, *args, **kwargs):
        try:
            fig_title = self_fig._suptitle.get_text() if self_fig._suptitle else ""
            if not fig_title:
                for ax in self_fig.axes:
                    t = ax.get_title()
                    if t:
                        fig_title = t
                        break
            if fig_title:
                _nb_state["_last_fig_title"] = fig_title
        except Exception as e:
            print(f"[exptrack] warning: could not extract figure title: {e}", file=sys.stderr)
        return _namespace_and_save(fname, lambda f, *a, **kw: _orig_fig_savefig(self_fig, f, *a, **kw), *args, **kwargs)

    plt.savefig = _hooked_plt_savefig
    mfig.Figure.savefig = _hooked_fig_savefig


def _register_and_protect(exp, orig_path, fig_title=""):
    """Copy the saved file to the experiment's output dir and register as artifact."""

    art_seq = None
    try:
        art_seq = exp.log_event(
            event_type="artifact",
            cell_hash=_nb_state.get("last_cell_hash"),
            key=orig_path.name,
            value=str(orig_path),
        )
    except Exception as e:
        print(f"[exptrack] warning: could not log artifact event: {e}", file=sys.stderr)

    # Copy the file to the experiment's output directory so it's protected
    # from being overwritten by subsequent saves to the same path.
    protected_path = orig_path
    try:
        from ..core.naming import output_path as _output_path
        dest = _output_path(orig_path.name, exp.name)
        if dest.resolve() != orig_path.resolve():
            shutil.copy2(str(orig_path), str(dest))
            protected_path = dest
    except Exception as _e:
        print(f"[exptrack] savefig copy warning: {_e}", file=sys.stderr)

    try:
        if fig_title:
            label = f"{fig_title} ({orig_path.name})"
        elif exp.name:
            label = f"{exp.name}/{orig_path.name}"
        else:
            label = orig_path.name
        exp.log_artifact(str(protected_path), label=label, timeline_seq=art_seq)
    except Exception as _e:
        print(f"[exptrack] savefig artifact error: {_e}", file=sys.stderr)


def _flush_pending(exp):
    """Register any buffered savefig calls that happened before the experiment existed."""
    from pathlib import Path as _P
    while _pending_artifacts:
        info = _pending_artifacts.pop(0)
        orig_path = _P(info["orig_path"])
        if orig_path.exists():
            _nb_state["last_cell_hash"] = info.get("cell_hash")
            _register_and_protect(exp, orig_path, info.get("fig_title", ""))
