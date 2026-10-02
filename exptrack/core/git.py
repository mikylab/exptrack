"""
exptrack/core/git.py — Git state capture
"""
from __future__ import annotations

import contextlib
import os
import subprocess

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


# Sentinel stored in git_diff when we ARE inside a git repo but the diff
# command itself failed (index.lock contention, timeout, git error). It keeps a
# capture failure from being silently indistinguishable from a genuinely clean
# tree (both would otherwise be ""), so "vs previous" / the diff view never
# reports "all changes committed" when the truth is "we couldn't tell".
CAPTURE_FAILED = "[capture-failed]"

# Sentinel for a repository with no commits yet (an unborn HEAD). `git diff`
# fails there because there is nothing to diff *against* — not because the
# capture broke — and this is the normal state of a project in the minutes
# after `git init` + `exptrack init`. Recording CAPTURE_FAILED made every early
# run claim its code capture had failed.
NO_COMMITS = "[no-commits-yet]"


# Within one `git_memo()` block, an identical `git <cmd>` runs once and every
# later caller gets the first result. Scope is a single user-facing operation —
# one session magic, one run's capture — where the working tree is one state by
# definition, so this can't serve a stale answer across a user's edit.
#
# It exists because a *process spawn* is the whole cost here: `rev-parse
# --short HEAD` does no work and still takes ~20 ms on Windows, and leaving a
# branch for a sibling ran `rev-parse` twice and the same `git diff <commit>`
# twice — the node being left refreshes its diff, then the node being entered
# computes the identical diff against the same checkpoint. `%exptrack branch`
# paid ~95 ms where half of it bought a byte-identical result.
_memo: dict[tuple, tuple[bool, str]] | None = None


@contextlib.contextmanager
def git_memo():
    """Collapse duplicate `git` invocations inside one operation.

    Nesting is safe: an inner block joins the outer memo rather than starting
    (and discarding) its own, so a helper that memoizes doesn't shorten the
    window of the magic that called it.
    """
    global _memo
    if _memo is not None:
        yield
        return
    _memo = {}
    try:
        yield
    finally:
        _memo = None


def _git_status(*cmd) -> tuple[bool, str]:
    """Run `git <cmd>`; return ``(ok, stripped_stdout)``.

    ``ok`` is False on a non-zero exit *or* any exception (git missing, timeout,
    contended lock). stdin is redirected from /dev/null and prompts are disabled
    (see ``_git_env``) so a git command can never freeze the caller — notably the
    interactive ``%exptrack checkpoint`` / ``branch`` magics in a notebook.

    Inside a ``git_memo()`` block an identical command is answered from the
    first result instead of spawning git again.
    """
    if _memo is not None and cmd in _memo:
        return _memo[cmd]
    ok, out = _run_git(*cmd)
    if _memo is not None:
        _memo[cmd] = (ok, out)
    return (ok, out)


def _run_git(*cmd) -> tuple[bool, str]:
    """Spawn `git <cmd>`. The uncached half of :func:`_git_status`."""
    try:
        r = subprocess.run(["git", *cmd], capture_output=True, text=True, timeout=10,
                           cwd=str(cfg.project_root()),
                           stdin=subprocess.DEVNULL, env=_git_env())
        return (r.returncode == 0, r.stdout.strip())
    except Exception as e:
        debug_log(f"git command failed: {e}")
        return (False, "")


def _git(*cmd) -> str:
    """Run a `git <cmd>` and return stripped stdout (empty string on failure).

    NOTE: for diff captures, call `git_diff(*range_args)` instead — it
    appends the config-driven `:(exclude,glob)<pattern>` pathspecs so
    callers don't bypass `git_diff_exclude`. Using `_git("diff", ...)`
    directly will skip the excludes.
    """
    ok, out = _git_status(*cmd)
    return out if ok else ""


def _is_git_repo() -> bool:
    """True if the project root is inside a git work tree."""
    ok, out = _git_status("rev-parse", "--is-inside-work-tree")
    return ok and out == "true"


def _diff_excludes() -> list[str]:
    """Return trailing pathspec args (`-- :(exclude)…`) from config, or []."""
    patterns = cfg.load().get("git_diff_exclude") or []
    if not patterns:
        return []
    args = ["--"]
    for p in patterns:
        args.append(f":(exclude,glob){p}")
    return args


def _has_unborn_head() -> bool:
    """True when the repo exists but has no commits yet.

    ``git rev-parse --verify HEAD`` is the cheap, non-interactive check; it
    fails on exactly the unborn-HEAD case.
    """
    ok, _ = _git_status("rev-parse", "--verify", "--quiet", "HEAD")
    return not ok


def git_diff(*range_args) -> str:
    """`git diff <range_args>` with config-driven pathspec excludes appended.

    Distinguishes a clean tree from a capture failure: a genuinely empty diff
    returns ``""``, but if the diff command errored *while inside a git repo* the
    sentinel ``CAPTURE_FAILED`` is returned so a failed capture is never recorded
    (or rendered) as "no changes". Outside a git repo an empty result is honest
    (nothing to diff) and stays ``""``.
    """
    ok, out = _git_status("diff", *range_args, *_diff_excludes())
    if ok:
        return out
    if not _is_git_repo():
        return ""
    return NO_COMMITS if _has_unborn_head() else CAPTURE_FAILED


def git_info() -> dict[str, str]:
    return {
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_diff":   git_diff("HEAD"),   # uncommitted changes minus excludes
    }


# ── Links to the hosted repository ──────────────────────────────────────────
# An export names the commit a run was made against; a reader who wants to see
# that code (or where a changed line goes) had to find the repository and paste
# the hash. These turn the `origin` remote into web links for the hosts whose
# URL scheme is known. The remote is read from the repository's config file,
# never by spawning git: an export must not cost a subprocess per run.

_WEB_SCHEMES = {
    # kind: (commit path, file path, line anchor)
    "github": ("/commit/{sha}", "/blob/{sha}/{path}", "#L{a}-L{b}"),
    "gitlab": ("/-/commit/{sha}", "/-/blob/{sha}/{path}", "#L{a}-{b}"),
    "bitbucket": ("/commits/{sha}", "/src/{sha}/{path}", "#lines-{a}:{b}"),
}


def _git_config_path(root) -> str | None:
    """The config file of the repository at *root*, following a worktree's
    ``.git`` file to its common directory."""
    from pathlib import Path
    # The exptrack root may sit below the repository's top level.
    start = Path(root).resolve()
    dot = next((p / ".git" for p in (start, *start.parents) if (p / ".git").exists()),
               start / ".git")
    root = dot.parent
    try:
        if dot.is_dir():
            return str(dot / "config")
        if dot.is_file():
            text = dot.read_text(encoding="utf-8", errors="replace").strip()
            if not text.startswith("gitdir:"):
                return None
            gitdir = Path(text[7:].strip())
            if not gitdir.is_absolute():
                gitdir = (Path(root) / gitdir).resolve()
            common = gitdir / "commondir"
            if common.is_file():
                c = Path(common.read_text(encoding="utf-8").strip())
                gitdir = c if c.is_absolute() else (gitdir / c).resolve()
            return str(gitdir / "config")
    except OSError:
        return None
    return None


def _origin_url(root) -> str:
    import configparser
    path = _git_config_path(root)
    if not path:
        return ""
    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return ""
    return parser.get('remote "origin"', "url", fallback="").strip()


def web_base_from_remote(url: str) -> tuple[str, str] | None:
    """``(kind, https base)`` for a remote URL on a known host, else None.

    Credentials are never carried over: an https remote can embed a token
    (``https://user:ghp_…@github.com/…``), and a link built from it would put
    the token into every exported document.
    """
    import re
    u = (url or "").strip()
    m = (re.match(r"^[\w.-]+@([^:/]+):(.+)$", u)                      # scp-like ssh
         or re.match(r"^(?:ssh|git)://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)$", u)
         or re.match(r"^https?://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)$", u))
    if not m:
        return None
    host, repo = m.group(1).lower(), m.group(2).strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    kind = next((k for k in _WEB_SCHEMES if k in host), None)
    if not kind or not repo:
        return None
    return kind, f"https://{host}/{repo}"


def repo_web_links(root) -> dict | None:
    """``{"kind", "base"}`` for the project's origin remote, or None.

    Swallows every failure: a missing remote, an unreadable config or an
    unknown host all mean "no link", never an error in an export.
    """
    try:
        found = web_base_from_remote(_origin_url(root))
    except Exception as e:  # a link is optional, the export is not
        debug_log(f"repo_web_links: {e}")
        return None
    return {"kind": found[0], "base": found[1]} if found else None


def commit_web_url(links: dict | None, sha: str) -> str:
    if not links or not sha:
        return ""
    return links["base"] + _WEB_SCHEMES[links["kind"]][0].format(sha=sha)


def file_web_url(links: dict | None, sha: str, path: str,
                 start: int = 0, end: int = 0) -> str:
    """A file at *sha*, opened at lines *start*–*end* when given."""
    if not links or not sha or not path:
        return ""
    _, file_t, anchor_t = _WEB_SCHEMES[links["kind"]]
    url = links["base"] + file_t.format(sha=sha, path=path.replace("\\", "/"))
    if start:
        url += anchor_t.format(a=start, b=max(start, end or start))
    return url


def parse_diff_files(diff: str) -> dict:
    """A unified diff split per file, with each hunk's line ranges.

    ``{"files": [{"path", "old_path", "status", "added", "removed",
    "hunks": [{"old_start", "old_len", "new_start", "new_len"}], "patch"}],
    "trailer": str}``. ``patch`` is that file's section verbatim — headers,
    hunks, context and indentation — so it applies with ``git apply`` on its
    own. ``trailer`` is anything after the last file (the capture's
    truncation marker), kept so a cut diff says it was cut.

    The export used to show a run's code change as the ``+ line``/``- line``
    fragments `_code_changes` stores, which drop indentation, file and line
    number — nothing a reader could paste back into the right place.
    """
    import re
    files: list[dict] = []
    trailer: list[str] = []
    cur = None
    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    for line in str(diff or "").split("\n"):
        if line.startswith("diff --git "):
            m = re.match(r"^diff --git a/(.*) b/(.*)$", line)
            old, new = (m.group(1), m.group(2)) if m else (line[11:], line[11:])
            cur = {"path": new, "old_path": old, "status": "modified",
                   "added": 0, "removed": 0, "hunks": [], "lines": [line]}
            files.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("\n[truncated") or line.startswith("[truncated"):
            trailer.append(line)
            cur = None
            continue
        cur["lines"].append(line)
        if line.startswith("new file mode"):
            cur["status"] = "added"
        elif line.startswith("deleted file mode"):
            cur["status"] = "deleted"
        elif line.startswith("rename to "):
            cur["status"] = "renamed"
        elif line.startswith(("+++", "---")):
            continue
        elif line.startswith("@@"):
            m = hunk_re.match(line)
            if m:
                cur["hunks"].append({
                    "old_start": int(m.group(1)),
                    "old_len": int(m.group(2)) if m.group(2) is not None else 1,
                    "new_start": int(m.group(3)),
                    "new_len": int(m.group(4)) if m.group(4) is not None else 1,
                })
        elif line.startswith("+"):
            cur["added"] += 1
        elif line.startswith("-"):
            cur["removed"] += 1
    for f in files:
        lines = f.pop("lines")
        while lines and not lines[-1].strip():
            lines.pop()
        f["patch"] = "\n".join(lines)
    return {"files": files, "trailer": "\n".join(t for t in trailer if t.strip())}
