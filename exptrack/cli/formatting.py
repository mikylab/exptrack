"""
exptrack/cli/formatting.py — ANSI color helpers and formatters
"""
from __future__ import annotations
from datetime import datetime

# ── ANSI ──────────────────────────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"
M = "\033[95m"; W = "\033[97m"; DIM = "\033[2m"; B = "\033[1m"; RST = "\033[0m"
STATUS_C = {"done": G, "running": Y, "failed": R}
STATUS_I = {"done": "+", "running": "~", "failed": "x"}
def col(t, c): return f"{c}{t}{RST}"
def dim(t): return f"{DIM}{t}{RST}"
def bold(t): return f"{B}{t}{RST}"


def fmt_dt(iso):
    if not iso: return dim("--")
    try: return datetime.fromisoformat(iso).strftime("%m/%d %H:%M")
    except Exception: return iso

def fmt_dur(s):
    if s is None: return dim("--")
    return f"{int(s//60)}m{int(s%60)}s" if s >= 60 else f"{s:.1f}s"
