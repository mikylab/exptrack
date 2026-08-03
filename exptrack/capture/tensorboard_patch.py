"""
exptrack/capture/tensorboard_patch.py — Monkey-patch SummaryWriter for auto metric capture

exptrack captures *params* with zero friction (argparse is patched), but until
now *metrics* had no auto-capture path at all: a value only reached the metrics
table via an explicit ``exp.log_metric(...)`` (or the notebook/CLI/pipeline
equivalents). Any custom loss or activation stat a training loop routes through
TensorBoard's ``SummaryWriter`` was invisible to exptrack.

This module closes that gap the same way ``matplotlib_patch`` closes it for
saved plots: it monkey-patches ``SummaryWriter.add_scalar`` / ``add_scalars``
(scalars → metrics) and ``add_histogram`` (activation/gradient distributions →
``<tag>/{mean,std,min,max}`` metrics) so every value already flowing to
TensorBoard is *mirrored* onto the active experiment — no user code change, no
new dependency (we patch the writer at the call site instead of parsing
``.tfevents`` files, which would require ``tensorboard``/``protobuf``).

Covers both ``torch.utils.tensorboard.SummaryWriter`` and the third-party
``tensorboardX.SummaryWriter``. Because those modules are usually imported by
the user's script *after* the patch is installed (patching happens before the
script runs), we both patch anything already imported and register a one-shot
``sys.meta_path`` import hook so a writer imported later gets patched too.

Best-effort throughout: a capture failure must never crash the user's run.

stdlib only.
"""
from __future__ import annotations

import importlib.abc
import sys
import threading
from typing import TYPE_CHECKING

from ..core.utils import debug_log, safe_call

if TYPE_CHECKING:
    from ..core import Experiment

# The writer packages we know how to mirror. Each exports ``SummaryWriter``.
_TARGET_MODULES = ("torch.utils.tensorboard", "tensorboardX")

# The experiment currently receiving mirrored metrics. Retargeted on every
# ``patch_tensorboard(exp)`` call (same rationale as argparse's ``_active_exp``:
# the class methods are patched once, but must not close over a single run).
_active_exp: Experiment | None = None

_hook_installed = False
_patch_lock = threading.Lock()


def patch_tensorboard(exp: Experiment | None = None) -> None:
    """Install SummaryWriter mirroring and point capture at ``exp``.

    Safe to call repeatedly: the writer classes are patched only once each, the
    import hook is installed only once, but every call retargets capture to the
    given experiment. Call with ``exp=None`` to eagerly install the hook (e.g.
    during deferred notebook start) before any experiment exists — in a notebook
    the active experiment is also picked up from ``_nb_state`` automatically.
    """
    global _active_exp, _hook_installed
    if exp is not None:
        _active_exp = exp

    with _patch_lock:
        # Patch any writer module the user already imported.
        for name in _TARGET_MODULES:
            mod = sys.modules.get(name)
            if mod is not None:
                _patch_writer_module(mod)

        # Register a one-shot import hook for writers imported later (the common
        # case: the script's ``from torch.utils.tensorboard import SummaryWriter``
        # runs after we patch, since patching happens before the script does).
        if not _hook_installed:
            _hook_installed = True
            try:
                sys.meta_path.insert(0, _WriterImportHook())
            except Exception as e:  # pragma: no cover - defensive
                debug_log(f"could not install tensorboard import hook: {e}")


def _current_exp() -> Experiment | None:
    """The experiment to mirror onto — the retargeted one, else the notebook's."""
    if _active_exp is not None:
        return _active_exp
    # Notebook (incl. deferred start) sets the active run into _nb_state["exp"];
    # read it here so a writer created in a cell mirrors without an explicit
    # retarget call on every experiment.
    try:
        from .notebook_hooks import _nb_state
        return _nb_state.get("exp")
    except Exception:
        return None


# ── Import hook (patch writers imported after us) ─────────────────────────────

class _WriterImportHook(importlib.abc.MetaPathFinder):
    """Meta-path finder that patches SummaryWriter right after its module loads.

    It never imports anything itself — it delegates to the finders *after* it in
    ``sys.meta_path`` to build the real spec, then wraps the loader so our patch
    runs immediately after the module's own ``exec_module``.
    """

    def find_spec(self, fullname, path, target=None):
        if fullname not in _TARGET_MODULES:
            return None
        try:
            idx = sys.meta_path.index(self)
        except ValueError:
            return None
        for finder in sys.meta_path[idx + 1:]:
            try:
                spec = finder.find_spec(fullname, path, target)
            except Exception:
                spec = None
            if spec is not None and spec.loader is not None:
                spec.loader = _PatchingLoader(spec.loader)
                return spec
        return None


class _PatchingLoader(importlib.abc.Loader):
    """Wraps a real loader, patching the writer module after it executes."""

    def __init__(self, real):
        self._real = real

    def create_module(self, spec):
        return self._real.create_module(spec)

    def exec_module(self, module):
        self._real.exec_module(module)
        safe_call(_patch_writer_module, module, context="tensorboard patch-on-import")


# ── Writer class patching ─────────────────────────────────────────────────────

def _patch_writer_module(module) -> None:
    cls = getattr(module, "SummaryWriter", None)
    if cls is not None:
        _patch_writer_class(cls)


def _patch_writer_class(cls) -> None:
    """Wrap __init__ / add_scalar / add_scalars / add_histogram.

    Idempotent per class via an ``_exptrack_patched`` marker. Originals are
    called unchanged, so TensorBoard still receives everything it always did.
    """
    if getattr(cls, "_exptrack_patched", False):
        return
    cls._exptrack_patched = True

    _orig_init = cls.__init__

    def __init__(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        safe_call(_record_log_dir, self, context="tensorboard log_dir")

    cls.__init__ = __init__

    _orig_add_scalar = cls.add_scalar

    def add_scalar(self, tag, scalar_value, global_step=None, *args, **kwargs):
        _mirror_scalar(tag, scalar_value, global_step)
        return _orig_add_scalar(self, tag, scalar_value, global_step, *args, **kwargs)

    cls.add_scalar = add_scalar

    if hasattr(cls, "add_scalars"):
        _orig_add_scalars = cls.add_scalars

        def add_scalars(self, main_tag, tag_scalar_dict, global_step=None, *args, **kwargs):
            _mirror_scalars(main_tag, tag_scalar_dict, global_step)
            return _orig_add_scalars(self, main_tag, tag_scalar_dict, global_step, *args, **kwargs)

        cls.add_scalars = add_scalars

    if hasattr(cls, "add_histogram"):
        _orig_add_histogram = cls.add_histogram

        def add_histogram(self, tag, values, global_step=None, *args, **kwargs):
            _mirror_histogram(tag, values, global_step)
            return _orig_add_histogram(self, tag, values, global_step, *args, **kwargs)

        cls.add_histogram = add_histogram


# ── Log directory capture (writer construction → linked dir) ──────────────────

# The label convention `exptrack link-dir --label tensorboard` already writes;
# reusing it means the dashboard, the delete preview and the cleanup path all
# treat an auto-captured writer dir exactly like a hand-linked one.
_TB_DIR_LABEL = "[dir] tensorboard"


def _writer_log_dir(writer) -> str | None:
    """The directory a SummaryWriter is writing events to, if we can find it.

    torch exposes ``log_dir``, tensorboardX has carried both ``logdir`` and
    ``log_dir`` across versions, and both provide ``get_logdir()`` — so ask in
    that order rather than binding to one library's attribute name.
    """
    for attr in ("log_dir", "logdir"):
        value = getattr(writer, attr, None)
        if isinstance(value, str) and value:
            return value
    getter = getattr(writer, "get_logdir", None)
    if callable(getter):
        value = getter()
        if isinstance(value, str) and value:
            return value
    return None


def _record_log_dir(writer) -> None:
    """Register the writer's log directory as a `[dir]` artifact on the run.

    Without this the directory `SummaryWriter()` creates — by default
    ``runs/<timestamp>_<hostname>/``, named and created entirely by PyTorch —
    is invisible to exptrack: it shows in no storage report and no delete
    touches it, so a project accumulates one orphaned event-file tree per run
    with nothing anywhere accounting for them. Mirroring the *values* without
    recording *where they were written* was only half the integration.
    """
    exp = _current_exp()
    if exp is None:
        return
    path = _writer_log_dir(writer)
    if not path:
        debug_log("tensorboard writer exposed no log dir")
        return
    # log_artifact resolves + dedupes by path, so a script that reopens the
    # same writer (or several writers on one dir) records it once.
    safe_call(exp.log_artifact, path, label=_TB_DIR_LABEL,
              context="tensorboard log_dir")


# ── Mirroring (writer call → exptrack metric) ─────────────────────────────────

def _mirror_scalar(tag, value, step) -> None:
    exp = _current_exp()
    if exp is None:
        return
    fval = _to_float(value)
    if fval is None:
        return
    safe_call(exp.log_metric, str(tag), fval, step=_to_step(step),
              context="tensorboard.add_scalar")


def _mirror_scalars(main_tag, tag_scalar_dict, step) -> None:
    exp = _current_exp()
    if exp is None or not hasattr(tag_scalar_dict, "items"):
        return
    step = _to_step(step)
    for sub_tag, value in tag_scalar_dict.items():
        fval = _to_float(value)
        if fval is None:
            continue
        key = f"{main_tag}/{sub_tag}" if main_tag else str(sub_tag)
        safe_call(exp.log_metric, key, fval, step=step,
                  context="tensorboard.add_scalars")


def _mirror_histogram(tag, values, step) -> None:
    exp = _current_exp()
    if exp is None:
        return
    stats = _histogram_stats(values)
    if not stats:
        return
    step = _to_step(step)
    for suffix, v in stats.items():
        safe_call(exp.log_metric, f"{tag}/{suffix}", v, step=step,
                  context="tensorboard.add_histogram")


# ── Value coercion helpers ────────────────────────────────────────────────────

def _to_float(value):
    """Best-effort float from a python number, numpy scalar, or 0-d tensor."""
    try:
        if hasattr(value, "item"):   # numpy scalar / 0-d torch tensor
            return float(value.item())
        return float(value)
    except Exception as e:
        debug_log(f"tensorboard value not scalar-coercible: {type(value).__name__}: {e}")
        return None


def _to_step(step):
    """Coerce global_step (int / numpy int / 0-d tensor / None) to int or None."""
    if step is None:
        return None
    try:
        if hasattr(step, "item"):
            return int(step.item())
        return int(step)
    except Exception:
        return None


def _histogram_stats(values):
    """Summarize a tensor/array of values as {mean, std, min, max}.

    Used to turn an activation/gradient histogram into scalar metrics. numpy is
    effectively always present alongside torch/tensorboardX; if the conversion
    fails we simply skip the histogram (best-effort).
    """
    try:
        import numpy as np
        arr = values.detach().cpu() if hasattr(values, "detach") else values
        arr = np.asarray(arr, dtype="float64").ravel()
        if arr.size == 0:
            return {}
        return {
            "mean": float(arr.mean()),
            "std": float(arr.std()),
            "min": float(arr.min()),
            "max": float(arr.max()),
        }
    except Exception as e:
        debug_log(f"histogram stats failed: {e}")
        return {}
