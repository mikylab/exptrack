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
* ``json_dumps()`` — ``json.dumps`` that emits JSON every parser accepts.

stdlib only.
"""
from __future__ import annotations

import json
import math
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
    except Exception as e:
        label = context or getattr(fn, "__name__", "call")
        debug_log(f"{label} failed: {type(e).__name__}: {e}")
        return default


def _finite_only(obj: Any, _seen: frozenset = frozenset()) -> Any:
    """Recursively replace non-finite floats with ``None``.

    Only walked for a payload that actually contains one — see
    :func:`json_dumps`. Values ``json.dumps`` would hand to ``default=`` are
    left alone: that callable stringifies them, so no bare token survives.

    ``_seen`` carries the container ids on the current path. A cycle is
    returned untouched rather than followed, so a circular payload — which is
    the *other* thing ``json.dumps`` raises ``ValueError`` for — raises that
    same readable error from the retry instead of exhausting the stack here.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (dict, list, tuple)):
        if id(obj) in _seen:
            return obj
        seen = _seen | {id(obj)}
        if isinstance(obj, dict):
            return {k: _finite_only(v, seen) for k, v in obj.items()}
        return [_finite_only(v, seen) for v in obj]
    return obj


def json_dumps(data: Any, **kwargs: Any) -> str:
    """``json.dumps``, guaranteeing output that any JSON parser will accept.

    ``json.dumps`` renders ``inf``/``-inf`` as the bare tokens ``Infinity`` /
    ``-Infinity``. Python's own ``json.loads`` reads those back — a documented
    non-standard extension — but ``JSON.parse`` and most other parsers reject
    them outright, and they reject the *whole document*, not the one value.

    So a single non-finite metric made an entire response unreadable in the
    browser: ``/api/experiment/<id>`` failed to parse, so the detail panel
    reported "Experiment not found", and ``/api/metrics/<id>`` failed beside
    it with a bare fetch error. Nothing server-side noticed, because
    ``json.loads`` happily round-trips what ``json.dumps`` wrote. The same
    tokens would make a ``exptrack export --format json`` file unloadable by
    any other tool.

    ``Experiment.log_metric`` guards against writing such a value, but that
    guard postdates a lot of stored data and the ten other ``INSERT INTO
    metrics`` paths never had one — so the read side has to be the one that
    can't be broken by a row that already exists.

    Non-finite floats become ``null``: every consumer already types a metric
    value as a number, and a chart gap or a blank cell is the honest
    rendering of a measurement that isn't one.

    The fast path costs only the check the C encoder already performs; the
    sanitizing walk runs solely for a payload that tripped it.
    """
    kwargs["allow_nan"] = False
    try:
        return json.dumps(data, **kwargs)
    except ValueError:
        # Non-finite float somewhere in the payload. (Any other ValueError —
        # a circular reference — will raise again from the retry, as it should.)
        return json.dumps(_finite_only(data), **kwargs)


def fmt_bytes(b) -> str:
    """Human-readable byte size.

    Lives here rather than in ``cli/formatting.py`` because the dashboard
    routes need it too, and a dashboard module importing the CLI's ANSI
    helpers would be a layer inversion. ``cli/formatting`` re-exports it so
    CLI modules keep a single import site.

    There were four copies of this before, and they had drifted: only one
    handled GB, so the same 3 GB directory printed as "3072.0 MB" from one
    call site and "3.00 GB" from another.
    """
    if b < 1024: return f"{b} B"
    if b < 1024**2: return f"{b/1024:.1f} KB"
    if b < 1024**3: return f"{b/1024**2:.1f} MB"
    return f"{b/1024**3:.2f} GB"


# Default cap on the `_code_changes` / `_code_change/cell_N` summary string.
#
# This was 1000 chars for scripts and 500 for notebook cells, applied as a bare
# `[:N]` slice. Both are far too small for a working tree that has drifted from
# HEAD: `git diff HEAD -- script.py` returns *every* changed line, so 60 lines
# of unrelated drift consumed the whole budget and an edit below them — the
# `warmup = 100` → `200` the run was actually testing — was cut off entirely.
# The panel then read as "no such change", which is the one thing a code-change
# summary must never do.
CODE_CHANGE_MAX_CHARS = 20000


def summarize_changed_lines(fragments, max_chars: int | None = None) -> str:
    """Join `+ line` / `- line` fragments into a `_code_changes` summary.

    Truncation is **stated, never silent**. A bare slice stopped mid-fragment
    with nothing marking the cut, so a summary that had dropped the user's
    actual edit was indistinguishable from one that had captured everything.
    The marker names how many changed lines were kept out of how many there
    were, so the omission is visible and countable.
    """
    if max_chars is None:
        try:
            from .. import config as _cfg
            max_chars = int(_cfg.load().get("code_change_max_chars",
                                            CODE_CHANGE_MAX_CHARS))
        except Exception:
            max_chars = CODE_CHANGE_MAX_CHARS
    # A nonsensical cap (0, negative, hand-edited garbage) must not be the
    # reason a run records no code changes at all.
    if not isinstance(max_chars, int) or max_chars <= 0:
        max_chars = CODE_CHANGE_MAX_CHARS

    fragments = list(fragments)
    joined = "; ".join(fragments)
    if len(joined) <= max_chars:
        return joined

    # Cut on a fragment boundary so the summary never ends mid-line.
    kept, size = [], 0
    for f in fragments:
        add = len(f) + (2 if kept else 0)
        if size + add > max_chars:
            break
        kept.append(f)
        size += add
    # A first fragment longer than the whole cap (a minified line, a giant
    # literal) would keep nothing — a summary that drops the change entirely,
    # the exact failure this function exists to prevent. Keep that one
    # fragment hard-sliced instead: a visibly cut line beats no line.
    if not kept and fragments:
        kept = [fragments[0][:max_chars] + "…"]
    return "; ".join(kept) + \
        f"; … [truncated — {len(kept)} of {len(fragments)} changed lines shown]"
