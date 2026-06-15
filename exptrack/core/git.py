"""
exptrack/core/git.py — Git state capture
"""
from __future__ import annotations

import os
import subprocess
import sys

from .. import config as cfg
from .utils import debug_log


# Env that prevents git from ever blocking interactively. Inside a Jupyter
# kernel git inherits the kernel's stdin, so anything that makes it prompt
# (a credential helper, a terminal prompt) would hang forever on a stream
# that never answers — the subprocess timeout doesn't reliably cover a child
# blocked on inherited stdin. GIT_TERMINAL_PROMPT=0 / GIT_ASKPASS turn prompts
# into immediate failures; GIT_OPTIONAL_LOCKS=0 lets read-only commands
# (rev-parse, diff) skip waiting on a contended index.lock.
def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _git(*cmd) -> str:
    """Run a `git <cmd>` and return stripped stdout (empty string on failure).

    NOTE: for diff captures, call `git_diff(*range_args)` instead — it
    appends the config-driven `:(exclude,glob)<pattern>` pathspecs so
    callers don't bypass `git_diff_exclude`. Using `_git("diff", ...)`
    directly will skip the excludes.

    stdin is redirected from /dev/null and prompts are disabled (see
    `_git_env`) so a git command can never freeze the caller — notably the
    interactive `%exptrack checkpoint` / `branch` magics in a notebook.
    """
    try:
        r = subprocess.run(["git", *cmd], capture_output=True, text=True, timeout=10,
                           cwd=str(cfg.project_root()),
                           stdin=subprocess.DEVNULL, env=_git_env())
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception as e:
        debug_log(f"git command failed: {e}")
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
