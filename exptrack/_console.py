"""
exptrack/_console.py — output that survives a console which can't spell it

A leaf module (stdlib only, imports nothing from exptrack) because every entry
point needs it — the CLI's `main()`, `python -m exptrack`, and the notebook
extension — and the notebook paying for an import of the whole CLI package to
reach it cost ~15 ms per kernel for two lines of work.
"""
from __future__ import annotations

import codecs
import os
import sys

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


def harden_stdio(redirected_utf8: bool = False) -> None:
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

    *redirected_utf8* (the CLI's entry point only): a stdout that is not a
    terminal is a file or a pipe, and a file is UTF-8. `exptrack export
    --format csv > runs.csv` on a cp1252 console wrote 0x97 for an em dash and
    `pandas.read_csv` refused it; `exptrack diff > x.patch` had the same fault.
    Not applied inside a user's script (``Experiment()``, the notebook), whose
    redirected output is the script's own business, nor when
    ``PYTHONIOENCODING`` names an encoding — that is the user's own choice.
    """
    if redirected_utf8 and not os.environ.get("PYTHONIOENCODING"):
        try:
            out = sys.stdout
            enc = (getattr(out, "encoding", "") or "").lower().replace("-", "")
            if (not out.isatty() and hasattr(out, "reconfigure")
                    and enc not in ("utf8", "utf8sig")):
                out.reconfigure(encoding="utf-8")
        except Exception:
            pass  # an unusual stream keeps whatever it had
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc in ("utf8", "utf8sig") or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(errors="exptrack_ascii")
        except Exception:
            pass  # a stream we can't harden is one we must not crash on either
