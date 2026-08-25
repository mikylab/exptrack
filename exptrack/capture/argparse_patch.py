"""
exptrack/capture/argparse_patch.py — Argparse monkey-patching and raw argv capture
"""
from __future__ import annotations

import sys
import threading
from typing import TYPE_CHECKING

from ..core.utils import coerce_scalar, debug_log, is_value_token, normalize_flag_key, safe_call

if TYPE_CHECKING:
    from ..core import Experiment

# ── Argparse patch ────────────────────────────────────────────────────────────

_patched = False
_orig_parse = None
_orig_known = None
_patch_lock = threading.Lock()
# The experiment currently receiving captured params. The hooks are installed
# once (globally, on the ArgumentParser class) but must not close over a single
# Experiment — otherwise a second run in the same process (a notebook kernel,
# programmatic reuse, back-to-back runs) would keep logging params onto the
# *first* experiment forever. Each patch_argparse(exp) call retargets this, and
# the hooks read it at parse time.
_active_exp: Experiment | None = None

def patch_argparse(exp: Experiment):
    """
    Monkey-patch ArgumentParser.parse_args AND parse_known_args once, and point
    capture at ``exp``. When the user's script calls either parser method, params
    flow into the *currently active* experiment automatically. After capture, the
    run name is refreshed to include real param values.

    Safe to call repeatedly: the class methods are patched only once, but every
    call retargets capture to the given experiment (fixes params leaking onto the
    first experiment when several are created in one process).
    """
    global _patched, _orig_parse, _orig_known, _active_exp
    with _patch_lock:
        _active_exp = exp
        if _patched:
            return
        _patched = True

        import argparse
        # Save originals only if not already saved (avoid capturing hooked versions)
        if _orig_parse is None:
            _orig_parse = argparse.ArgumentParser.parse_args
        if _orig_known is None:
            _orig_known = argparse.ArgumentParser.parse_known_args

        def _hooked_parse(self_ap, args=None, namespace=None):
            ns = _orig_parse(self_ap, args, namespace)
            if _active_exp is not None:
                _capture_namespace(_active_exp, ns)
            return ns

        def _hooked_known(self_ap, args=None, namespace=None):
            ns, remaining = _orig_known(self_ap, args, namespace)
            if _active_exp is not None:
                _capture_namespace(_active_exp, ns)
                # Also try to parse the remaining args as free-form --key value
                if remaining:
                    _capture_remaining(_active_exp, remaining)
            return ns, remaining

        argparse.ArgumentParser.parse_args = _hooked_parse
        argparse.ArgumentParser.parse_known_args = _hooked_known


def _capture_namespace(exp: Experiment, ns):
    # This runs *inside* the user's parse_args(). A capture failure here — a
    # param value that isn't JSON-serializable (e.g. argparse type=Path/enum),
    # or a locked DB during a parallel sweep — must never abort the user's run.
    # The body is multi-statement (log + rename), hence an inline try/except
    # rather than the safe_call() the single-call capture paths use below.
    try:
        d = {k: v for k, v in vars(ns).items()
             if not k.startswith("_") and v is not None}
        if d:
            exp.log_params(d)
            _drop_shadowed_argv_params(exp, d)
            _refresh_auto_name(exp)
    except Exception as e:
        debug_log(f"_capture_namespace failed: {type(e).__name__}: {e}")


def _refresh_auto_name(exp: Experiment, quiet: bool = False):
    """Re-generate the run name now that params are known.

    Thin wrapper: the guards live on ``Experiment`` so the notebook path
    applies the same ones. Kept as a name because the capture modules and
    tests call it.
    """
    exp.refresh_auto_name(quiet=quiet)


def _drop_shadowed_argv_params(exp: Experiment, captured: dict):
    """Retract raw-argv keys that argparse has just re-captured under its dest.

    Both capture paths run under ``exptrack run``: argv first (so a
    non-argparse script is still covered), then the namespace. When a flag's
    ``dest`` differs from its spelling — ``--learning-rate`` with
    ``dest="lr"`` — one hyperparameter landed under two keys, and "what varies"
    then reported two axes for one knob. The argv spelling is the one that
    goes: argparse's dest is what the script itself calls the value.
    """
    argv_keys = getattr(exp, "_argv_param_keys", None)
    if not argv_keys:
        return
    # Matched through the one param-equality rule, not a value probe of its
    # own: raw argv captures `--lr 0.01` as the *string* while argparse hands
    # back the float, so a probe comparing them literally saw two different
    # values and kept the duplicate key in exactly the case this function
    # exists for.
    from ..core.param_study import params_differ
    values = list(captured.values())
    shadowed = []
    for k in argv_keys:
        if k in captured:
            continue                       # same key — argparse just updated it
        v = exp._params.get(k)
        if any(not params_differ(v, cv) for cv in values):
            shadowed.append(k)
    if shadowed:
        exp.forget_params(shadowed)
        exp._argv_param_keys = [k for k in argv_keys if k not in shadowed]


def _capture_remaining(exp: Experiment, args: list[str]):
    """Parse residual --key value / --key=value / -k value from remaining args."""
    params = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                params[normalize_flag_key(k)] = coerce_scalar(v)
            elif i + 1 < len(args) and is_value_token(args[i + 1]):
                params[normalize_flag_key(key)] = coerce_scalar(args[i + 1])
                i += 1
            else:
                params[normalize_flag_key(key)] = True
        elif a.startswith("-") and len(a) == 2:
            key = a[1:]
            if i + 1 < len(args) and is_value_token(args[i + 1]):
                params[key] = coerce_scalar(args[i + 1])
                i += 1
            else:
                params[key] = True
        i += 1
    if params:
        # A capture failure must not escape into the user's parse_known_args().
        safe_call(exp.log_params, params, context="_capture_remaining")


# ── Raw argv fallback ─────────────────────────────────────────────────────────

def capture_argv(exp: Experiment):
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
                params[normalize_flag_key(k)] = coerce_scalar(v)
            elif i + 1 < len(args) and is_value_token(args[i + 1]):
                params[normalize_flag_key(key)] = coerce_scalar(args[i + 1])
                i += 1
            else:
                params[normalize_flag_key(key)] = True
        elif a.startswith("-") and len(a) == 2:
            key = a[1:]
            if i + 1 < len(args) and is_value_token(args[i + 1]):
                params[key] = coerce_scalar(args[i + 1])
                i += 1
            else:
                params[key] = True
        i += 1
    if params:
        # capture_argv runs at launch, before the user's script starts; an
        # unguarded failure here would abort the launch outright.
        safe_call(exp.log_params, params, context="capture_argv")
        # Remember what argv contributed, so a later argparse capture can
        # retract a key it has just re-captured under a different dest.
        exp._argv_param_keys = list(params)
        # A non-argparse script (click, manual sys.argv, a bare
        # `if len(sys.argv)`) never reaches _capture_namespace, so without this
        # its run name never picked up the params that were captured — two runs
        # of different models were indistinguishable by name.
        # Quiet: under `exptrack run` (and now under a bare `python train.py`)
        # argparse capture usually follows a moment later and announces the
        # final name, so a second "-> name" line just reports an intermediate
        # state the user never had.
        safe_call(_refresh_auto_name, exp, True, context="capture_argv rename")
