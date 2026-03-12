"""
exptrack/core/git.py — Git state capture
"""
from __future__ import annotations
import subprocess
import sys

from .. import config as cfg


def _git(*cmd) -> str:
    try:
        r = subprocess.run(["git", *cmd], capture_output=True, text=True, timeout=10,
                           cwd=str(cfg.project_root()))
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception as e:
        print(f"[exptrack] warning: git command failed: {e}", file=sys.stderr)
        return ""


def git_info() -> dict:
    return {
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_diff":   _git("diff", "HEAD"),   # captures ALL uncommitted changes
    }
