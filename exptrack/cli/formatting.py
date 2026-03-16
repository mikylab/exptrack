"""
exptrack/cli/formatting.py — ANSI color helpers and formatters
"""
from __future__ import annotations
import os
import sys
from datetime import datetime

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
def col(t, c): return f"{c}{t}{RST}" if c else str(t)
def dim(t): return f"{DIM}{t}{RST}" if DIM else str(t)
def bold(t): return f"{B}{t}{RST}" if B else str(t)


def fmt_dt(iso):
    if not iso: return dim("--")
    try: return datetime.fromisoformat(iso).strftime("%m/%d %H:%M")
    except Exception: return iso

def fmt_dur(s):
    if s is None: return dim("--")
    return f"{int(s//60)}m{int(s%60)}s" if s >= 60 else f"{s:.1f}s"
