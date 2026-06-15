"""
exptrack/core/utils.py — small shared helpers for defensive capture code.

exptrack monkey-patches argparse, IPython, and matplotlib inside the user's
own process, so a capture failure must *never* crash a training run. That
design forces a lot of ``try/except: <fallback>`` blocks, and historically
every one of them swallowed its exception silently — leaving no way to debug
why a variable, diff, or metric failed to capture.

This module provides the shared helpers for that pattern; capture/db sites are
migrated onto them incrementally:

* ``debug_enabled()`` / ``debug_log()`` — opt-in stderr diagnostics gated by
  the ``EXPTRACK_DEBUG`` environment variable, so silent swallows become
  visible when a user is actually trying to debug, and stay quiet otherwise.
* ``safe_call()`` — run a callable, returning a default (and logging via
  ``debug_log``) on any exception, so the ``try/except/fallback`` idiom is
  expressed once instead of being copy-pasted across modules.

stdlib only.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_TRUTHY = {"1", "true", "yes", "on", "debug"}


def debug_enabled() -> bool:
    """True when ``EXPTRACK_DEBUG`` is set to a truthy value.

    Read fresh each call (not cached) so a notebook user can toggle
    ``os.environ['EXPTRACK_DEBUG'] = '1'`` mid-session to start seeing
    capture diagnostics without restarting the kernel.
    """
    return os.environ.get("EXPTRACK_DEBUG", "").strip().lower() in _TRUTHY


def debug_log(msg: str) -> None:
    """Print a diagnostic to stderr, but only when ``EXPTRACK_DEBUG`` is set.

    Use this for the many defensive ``except`` blocks across capture/ that
    must not crash the user's run but whose failures are otherwise invisible.
    """
    if debug_enabled():
        try:
            print(f"[exptrack:debug] {msg}", file=sys.stderr)
        except Exception:
            # Logging itself must never raise into a capture hook.
            pass


def safe_call(
    fn: Callable[..., T],
    *args: Any,
    default: T | None = None,
    context: str = "",
    **kwargs: Any,
) -> T | None:
    """Call ``fn(*args, **kwargs)``, returning ``default`` on any exception.

    The exception is reported via :func:`debug_log` (so it is silent unless
    ``EXPTRACK_DEBUG`` is set) tagged with ``context`` for traceability. This
    is the one-liner replacement for the ``try: ...; except Exception: <default>``
    idiom that recurs throughout the capture and db layers.

    Example::

        shape = safe_call(lambda: arr.shape, default="?", context="ndarray.shape")
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 — intentional catch-all for capture safety
        label = context or getattr(fn, "__name__", "call")
        debug_log(f"{label} failed: {type(e).__name__}: {e}")
        return default
