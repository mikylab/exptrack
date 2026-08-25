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
import re
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


# SQLite's default bound-parameter limit is 999 (raised to 32766 only in 3.32),
# and a query binding an id list normally binds a few other values alongside it.
# One definition, because a margin duplicated in two modules diverges silently:
# lowering it in one leaves the other sitting near the ceiling, and nothing
# fails until a query hits the limit at runtime.
ID_CHUNK = 400


def chunked(items, size: int = ID_CHUNK):
    """Yield *items* in lists of at most *size*, for chunked ``IN (…)`` queries."""
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def placeholders(items) -> str:
    """``"?,?,?"`` for a sequence — the other half of the chunked-IN idiom."""
    return ",".join("?" * len(items))


# The one internal param that is not `_`-prefixed. `Experiment.fail()` writes
# the failure message as `error` for backward compatibility (the traceback got
# `_error_traceback` when it was added later, but the original key had already
# shipped). It is failure metadata, not a hyperparameter.
#
# This is an exception to the prefix rule, not a replacement for it: the rule
# stays the rule, and this set exists only because one key predates it.
LEGACY_INTERNAL_PARAM_KEYS = frozenset({"error"})


def is_user_param_key(key: str) -> bool:
    """Whether *key* is a real hyperparameter rather than exptrack bookkeeping.

    The rule is the ``_`` prefix, not a list of known keys — every internal
    param exptrack writes is ``_``-prefixed, and an enumeration silently misses
    each new one (which is exactly how ``_code_snapshot`` once became the
    headline row of the "What changed" card), plus
    ``LEGACY_INTERNAL_PARAM_KEYS`` for the one un-prefixed key that predates
    the convention.

    Lives here rather than beside any one consumer: which keys are exptrack's
    own is knowledge about the param namespace, not about whichever view is
    asking. Mirrors ``isUserParamKey`` in ``dashboard/static/js/core.js``.
    """
    k = str(key)
    return not k.startswith("_") and k not in LEGACY_INTERNAL_PARAM_KEYS


def decode_param_value(raw):
    """Decode a stored param value, degrading to the raw string.

    Params are written JSON-encoded, so the decode contract is the inverse of
    the writer and belongs in one place: three separate copies had already
    drifted on empty-string handling and on which exceptions they caught, which
    makes "what a param value decodes to" depend on which view is asking.
    """
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


# A clean ASCII decimal integer (no leading zeros, no underscores, no unicode
# digits) and a clean decimal float. bare int()/float() accept far more —
# "007", "1_000", Arabic-Indic "١٢٣", " 5 " — and would silently store a value
# that differs from what the user typed. We only coerce unambiguous literals.
_INT_RE = re.compile(r"[+-]?(?:0|[1-9][0-9]*)")
_FLOAT_RE = re.compile(
    r"[+-]?(?:[0-9]*\.[0-9]+|[0-9]+\.[0-9]*)(?:[eE][+-]?[0-9]+)?"  # dotted, opt exp
    r"|[+-]?[0-9]+[eE][+-]?[0-9]+"                                 # integer with exp
)


def coerce_scalar(v: str):
    """Coerce a raw ``--key value`` string to a scalar: bool, int, float, or str.

    The single source of truth for how a command-line value becomes a param,
    shared by the argparse/argv capture (`capture/argparse_patch`) and the shell
    pipeline parser (`cli/pipeline_cmds`) so a param means the same thing however
    the run was launched — the encode side of :func:`decode_param_value`, and for
    the same reason: copies had drifted.

    Only an unambiguous ASCII decimal literal is coerced to a number; anything
    else — a zero-padded id ("007"), an underscore-grouped literal ("1_000"),
    non-ASCII digits, surrounding whitespace, or a value that parses as a
    *non-finite* float ("inf"/"nan"/"1e999", which isn't valid JSON either) — is
    kept as its original string, so a param always round-trips to what was typed.
    """
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    if _INT_RE.fullmatch(v):
        return int(v)
    if _FLOAT_RE.fullmatch(v):
        f = float(v)
        return f if math.isfinite(f) else v
    return v


def normalize_flag_key(key: str) -> str:
    """Match argparse's Namespace convention: ``--batch-size`` stored as
    ``batch_size``. Shared so a param logged via the shell pipeline lands under
    the same key as the same flag captured from argparse — otherwise the two
    compare as different params."""
    return key.replace("-", "_")


def is_value_token(tok: str) -> bool:
    """Is ``tok`` the *value* of the preceding flag, or the next flag?

    A ``--``-prefixed token is always a flag; a single-dash token is a value only
    when it parses as a number — so ``--lr -0.5`` / ``--eps -1e-4`` keep their
    (negative) values while ``--a --b`` / ``-a -b`` read as two booleans. Shared
    by the argparse and pipeline parsers so both answer this the same way.
    """
    if tok.startswith("--"):
        return False
    if tok.startswith("-"):
        try:
            float(tok)
        except (ValueError, TypeError):
            return False
    return True


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


_METRIC_SEP_RE = re.compile(r"[\s\-]+")


def normalize_metric_key(key: str) -> str:
    """The comparison form of a metric name: base name, lowercased, ``_``-joined.

    ``train/Val Acc`` and ``val-acc`` both become ``val_acc``. One spelling of
    "the same metric name" for every surface that matches keys — the polarity
    heuristic and the alias table each had their own copy, so changing one
    would have stopped aliases resolving while polarity still matched, with
    nothing failing to say so. Deliberately not a stemmer: guessing that
    ``val_acc ≈ val_accuracy`` would eventually merge two genuinely different
    measurements and silently average them.
    """
    base = str(key or "").rsplit("/", 1)[-1].lower()
    return _METRIC_SEP_RE.sub("_", base).strip("_")


def like_prefix(prefix: str) -> str:
    """Escape a user-supplied id prefix for a ``LIKE ? ESCAPE '\\'`` match.

    An id prefix is user input, and ``%`` / ``_`` are LIKE wildcards: without
    this, ``exptrack show _`` matched every run whose id had any second
    character, and an ambiguity check that should have refused silently picked
    one. Every LIKE over a user prefix goes through this and pairs it with
    ``ESCAPE '\\'`` — the escaping was hand-inlined in four modules and the
    copy that mattered most (``resolve_experiment_id``) never got it.
    """
    return (str(prefix or "").replace("\\", "\\\\")
            .replace("%", "\\%").replace("_", "\\_"))


def parse_age(spec: str):
    """``"30d"`` / ``"24h"`` / ``"90m"`` → a ``timedelta``, or None.

    One grammar for every age the CLI accepts. ``--older-than`` parsed only
    ``Nd`` while ``--since`` (added the same day) parsed ``Nd`` and ``Nh``, so
    ``--since 24h`` worked and ``--older-than 24h`` was a hard error in the
    same CLI. Returning None rather than raising leaves the "what do we do
    about it" decision — die, or fall through to a date parse — to the caller.
    """
    from datetime import timedelta
    m = re.fullmatch(r"(\d+)\s*([dhm])", str(spec or "").strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "d":
        return timedelta(days=n)
    if unit == "h":
        return timedelta(hours=n)
    return timedelta(minutes=n)


def resolve_script_identity(script: str) -> str:
    """The stored form of a run's ``script`` field.

    A real file path is resolved to an absolute path; a label from the shell
    pipeline ("pipeline", "train") is kept as written. Shared with the lookup
    side so a caller searching for a run *by* script normalizes the name the
    same way the writer did — `%exp_log` searched for the raw detected
    notebook name while runs stored the resolved absolute path, so in every
    JupyterLab deployment that reports a relative name the post-hoc logging
    feature silently found nothing.
    """
    from pathlib import Path as _Path
    if script and (_Path(script).is_file() or os.path.sep in script
                   or script.startswith("/")):
        try:
            return str(_Path(script).resolve())
        except OSError:
            return script
    return script
