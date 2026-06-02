"""
exptrack/core/git.py — Git state capture
"""
from __future__ import annotations

import subprocess
import sys

from .. import config as cfg


def _git(*cmd) -> str:
    """Run a `git <cmd>` and return stripped stdout (empty string on failure).

    NOTE: for diff captures, call `git_diff(*range_args)` instead — it
    appends the config-driven `:(exclude,glob)<pattern>` pathspecs so
    callers don't bypass `git_diff_exclude`. Using `_git("diff", ...)`
    directly will skip the excludes.
    """
    try:
        r = subprocess.run(["git", *cmd], capture_output=True, text=True, timeout=10,
                           cwd=str(cfg.project_root()))
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception as e:
        print(f"[exptrack] warning: git command failed: {e}", file=sys.stderr)
        return ""


def _diff_excludes() -> list[str]:
    """Return trailing pathspec args (`-- :(exclude)…`) from config, or []."""
    patterns = cfg.load().get("git_diff_exclude") or []
    if not patterns:
        return []
    args = ["--"]
    for p in patterns:
        args.append(f":(exclude,glob){p}")
    return args


def git_diff(*range_args) -> str:
    """`git diff <range_args>` with config-driven pathspec excludes appended."""
    return _git("diff", *range_args, *_diff_excludes())


def git_info() -> dict[str, str]:
    return {
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_diff":   git_diff("HEAD"),   # uncommitted changes minus excludes
    }
