"""
exptrack/capture/argparse_patch.py — Argparse monkey-patching and raw argv capture
"""
from __future__ import annotations

import sys
import threading
from typing import TYPE_CHECKING

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
    from ..core import make_run_name
    d = {k: v for k, v in vars(ns).items()
         if not k.startswith("_") and v is not None}
    if d:
        exp.log_params(d)
        # Don't rename resumed experiments — their name and output dir
        # are already established and the script may depend on them.
        if not getattr(exp, '_resumed', False):
            exp._rename(make_run_name(exp.script, exp._params))


def _normalize_long_flag(key: str) -> str:
    """Match argparse's Namespace convention: `--batch-size` stored as `batch_size`."""
    return key.replace("-", "_")


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
                params[_normalize_long_flag(k)] = _coerce(v)
            elif i + 1 < len(args) and not args[i + 1].startswith("-"):
                params[_normalize_long_flag(key)] = _coerce(args[i + 1])
                i += 1
            else:
                params[_normalize_long_flag(key)] = True
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
                params[_normalize_long_flag(k)] = _coerce(v)
            elif i + 1 < len(args) and not args[i + 1].startswith("-"):
                params[_normalize_long_flag(key)] = _coerce(args[i + 1])
                i += 1
            else:
                params[_normalize_long_flag(key)] = True
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
    except (ValueError, TypeError): pass  # not an int, try float
    try:    return float(v)
    except (ValueError, TypeError): pass  # not a float, return as string
    return v
