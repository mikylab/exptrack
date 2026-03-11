"""
exptrack/capture/argparse_patch.py — Argparse monkey-patching and raw argv capture
"""
from __future__ import annotations
import sys
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
        # Also try to parse the remaining args as free-form --key value
        if remaining:
            _capture_remaining(exp, remaining)
        return ns, remaining

    argparse.ArgumentParser.parse_args = _hooked_parse
    argparse.ArgumentParser.parse_known_args = _hooked_known


def _capture_namespace(exp: "Experiment", ns):
    from ..core import make_run_name
    d = {k: v for k, v in vars(ns).items()
         if not k.startswith("_") and v is not None}
    if d:
        exp.log_params(d)
        exp._rename(make_run_name(exp.script, exp._params))


def _capture_remaining(exp: "Experiment", args: list[str]):
    """Parse residual --key value / --key=value / -k value from remaining args."""
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
