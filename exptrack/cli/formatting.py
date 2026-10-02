"""
exptrack/cli/formatting.py — ANSI color helpers and formatters
"""
from __future__ import annotations

import codecs
import os
import sys
from datetime import datetime

# Re-exported so CLI modules have one import site for formatting helpers;
# the implementation is layer-neutral because the dashboard needs it too.
from ..core.utils import fmt_bytes  # noqa: F401

# ── Color control ─────────────────────────────────────────────────────────────
# Respect NO_COLOR (https://no-color.org/), --no-color flag, and non-TTY output
_no_color = (
    "NO_COLOR" in os.environ
    or "--no-color" in sys.argv
    or not hasattr(sys.stdout, "isatty")
    or not sys.stdout.isatty()
)

# ── ANSI ──────────────────────────────────────────────────────────────────────
if _no_color:
    G = R = Y = C = M = W = DIM = B = RST = ""
else:
    G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"
    M = "\033[95m"; W = "\033[97m"; DIM = "\033[2m"; B = "\033[1m"; RST = "\033[0m"
STATUS_C = {"done": G, "running": Y, "failed": R}
STATUS_I = {"done": "+", "running": "~", "failed": "x"}
# What the CLI's glyphs mean in ASCII, for a console that cannot spell them.
# `errors="replace"` alone keeps the command alive but turns `exptrack session
# show` into a wall of `?` — the tree is drawn almost entirely out of
# characters cp1252 lacks, so every rail, every arrow and every separator
# becomes the same mark and the shape the view exists to show is gone.
_ASCII_FALLBACK = {
    "─": "-", "│": "|", "├": "+", "└": "`", "┬": "+", "┼": "+", "╰": "`",
    "→": "->", "←": "<-", "⤷": "->", "›": ">", "·": ".", "—": "-", "–": "-",
    "…": "...", "⧉": "[]", "⇄": "<>", "⑂": "Y", "✓": "v", "✗": "x", "⚠": "!",
    "★": "*", "☰": "=", "▸": ">", "▾": "v", "■": "#", "●": "o", "○": "o",
    "“": '"', "”": '"', "‘": "'", "’": "'", "🖼": "[img]", "⏹": "[stop]",
}


def _ascii_fallback_handler(err):
    """Codec error handler: spell an unmappable glyph in ASCII, else `?`."""
    bad = err.object[err.start:err.end]
    return ("".join(_ASCII_FALLBACK.get(ch, "?") for ch in bad), err.end)


codecs.register_error("exptrack_ascii", _ascii_fallback_handler)


def harden_stdio() -> None:
    """Make an unencodable character degrade instead of killing the command.

    On Windows the console encoding is the system ANSI codepage unless the user
    opted into UTF-8, and none of the glyphs this CLI draws with — `├── └──`,
    `→`, `—` — exist in cp1252. `print()` then raises UnicodeEncodeError and the
    command dies with a traceback where its output should be: `exptrack session
    show` died on the tree's first branch, and `exptrack notebook-guard` — the
    command whose entire job is to make a notebook shareable — could not print
    its own cell.

    The stream keeps its own encoding (re-encoding it to UTF-8 would hand a
    cp1252 console mojibake for every accented run name); only the error
    handler changes. It is not `replace`, because that turns the session tree
    into a wall of identical `?` marks: `exptrack_ascii` spells the glyph the
    CLI actually draws with — `+--` for a rail, `->` for an arrow — and falls
    back to `?` for anything it doesn't know. A UTF-8 console is left
    untouched, and a stream that cannot be reconfigured — pytest's capture, any
    wrapper — is skipped rather than raising on the way to printing.
    """
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc in ("utf8", "utf8sig") or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(errors="exptrack_ascii")
        except Exception:
            pass  # a stream we can't harden is one we must not crash on either


def col(t, c): return f"{c}{t}{RST}" if c else str(t)
def dim(t): return f"{DIM}{t}{RST}" if DIM else str(t)
def bold(t): return f"{B}{t}{RST}" if B else str(t)


def confirm(prompt: str, assume_yes: bool = False) -> bool:
    """Ask a yes/no question. True only on an explicit yes.

    The one confirmation prompt for every destructive command. A bare
    ``input()`` raises ``EOFError`` when stdin is not a terminal — a cron job,
    a CI step, a piped command — and the user saw a raw traceback from a delete
    they never got to answer. Some commands guarded that and some didn't, so
    the same pipeline broke differently depending on which one it reached.

    EOF and Ctrl-C both mean "no": on a destructive action, an unanswered
    question is a refusal. *assume_yes* (the commands' ``--yes`` flag) is the
    supported way to run these non-interactively.
    """
    if assume_yes:
        return True
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled (no terminal to confirm on — pass --yes to proceed).",
              file=sys.stderr)
        return False


def parse_age_delta(age_str: str):
    """``"30d"`` → ``timedelta(days=30)``. Dies on anything else.

    One validator for every ``--older-than``. `clean` validated strictly and
    `compact` accepted bare ``30`` and ``30dd`` while printing an error and
    exiting 0 for a genuinely bad value — so the same typo was a hard failure
    on one command and a silent no-op on the other. The grammar itself lives in
    ``core.utils.parse_age``, shared with ``ls --since``; this wrapper only adds
    the CLI's die-on-invalid contract.
    """
    from ..core.utils import parse_age
    delta = parse_age(age_str)
    if delta is None:
        die(f"Invalid age format: '{age_str}'. Use format like '30d', '24h' or '90m'.")
    return delta


def die(msg: str, code: int = 1):
    """Print an error to stderr (red) and exit with a non-zero code.

    Standard exit path for hard-error / not-found cases so scripts can detect
    failure (`exptrack show $ID || ...`).
    """
    print(col(msg, R), file=sys.stderr)
    sys.exit(code)


def fmt_dt(iso):
    if not iso: return dim("--")
    try: return datetime.fromisoformat(iso).strftime("%m/%d %H:%M")
    except Exception: return iso

def fmt_dur(s):
    if s is None: return dim("--")
    return f"{int(s//60)}m{int(s%60)}s" if s >= 60 else f"{s:.1f}s"
