"""
exptrack/core/script_snapshot.py — Script source capture (snapshot + git diff)

Lives in ``core/`` rather than ``capture/`` because ``core.experiment`` calls it
on every script run: a core→capture import is the layering inversion that moving
``dataset.py`` into ``core/`` was meant to end, and a function-local import only
hides such a dependency from the import graph rather than removing it. This
module itself depends on nothing outside ``core``/``config``, so the move is
free. ``capture/script_tracking.py`` remains as a re-export shim.
"""
from __future__ import annotations

import hashlib
import subprocess
from typing import TYPE_CHECKING

from .git import _git_env
from .utils import debug_log, summarize_changed_lines

if TYPE_CHECKING:
    from . import Experiment


# Derived facts about a script file, keyed by (abspath, mtime_ns, size).
#
# Every Experiment created in a process snapshots its script, so a param sweep
# constructing 100 runs in one loop would otherwise re-read, re-hash, re-insert
# and re-`git diff` the same byte-identical file 100 times — 100 subprocesses
# and 100 fsyncs for one snapshot's worth of information. The key includes
# mtime and size, so editing the file mid-process is picked up.
_facts_cache: dict = {}
_FACTS_CACHE_MAX = 64


def _tracked_status(root, rel) -> str:
    """``"clean"`` or ``"untracked"`` for a script whose diff came back empty.

    ``git diff HEAD -- untracked.py`` exits 0 with no output — byte-identical to
    the answer for a clean tree — so an empty diff on its own cannot say whether
    the script's source is recoverable from the commit. That difference is the
    whole point of the panel's empty state, so it is worth one extra process:
    it runs only on the empty-diff path and ``_script_facts`` memoizes the
    result per (path, mtime, size).
    """
    try:
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", str(rel)],
            capture_output=True, text=True, timeout=10, cwd=str(root),
            stdin=subprocess.DEVNULL, env=_git_env(),
        )
        return "clean" if r.returncode == 0 else "untracked"
    except Exception as e:
        debug_log(f"git ls-files failed for script: {e}")
        return ""


def _script_facts(script_path: str) -> dict | None:
    """`{src_hash, snapshot_hash, code_changes, code_status}` for a script, memoized.

    Returns None when the file can't be read. Does all the expensive work —
    read, hash, content-addressed store, `git diff` subprocess — exactly once
    per (path, mtime, size).
    """
    from pathlib import Path as _Path

    from .. import config as _cfg

    p = _Path(script_path)
    try:
        st = p.stat()
        key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
    except OSError as e:
        debug_log(f"could not stat script {script_path}: {e}")
        return None
    cached = _facts_cache.get(key)
    if cached is not None:
        return cached

    try:
        src = p.read_text()
    except Exception as e:
        debug_log(f"could not read script {script_path}: {e}")
        return None

    facts = {
        "src_hash": hashlib.md5(src.encode()).hexdigest()[:12],
        "snapshot_hash": None,
        "code_changes": "",
        # Why `code_changes` is empty, when it is — see `_tracked_status`. An
        # empty diff has three unrelated causes and only one of them means
        # "this script matches the commit".
        "code_status": "",
    }

    # Store the full script source, content-addressed + deduped, so the code
    # that ran is recoverable even when it was untracked / the project isn't a
    # git repo / the diff was excluded. Never .ipynb (handled by cell records).
    # Size-capped so a pathological file can't bloat the DB.
    try:
        cap_kb = int(_cfg.load().get("snapshot_max_kb", 512))
        if not str(script_path).endswith(".ipynb") and \
                len(src.encode("utf-8", "replace")) <= cap_kb * 1024:
            from .db import get_db, store_code_snapshot
            conn = get_db()
            facts["snapshot_hash"] = store_code_snapshot(
                conn, src, kind="script", path=str(script_path))
            conn.commit()
    except Exception as e:
        debug_log(f"could not store code snapshot: {e}")

    root = _cfg.project_root()
    try:
        rel = p.resolve().relative_to(root.resolve())
    except ValueError:
        rel = p
    try:
        r = subprocess.run(
            ["git", "diff", "HEAD", "--", str(rel)],
            capture_output=True, text=True, timeout=10,
            cwd=str(root), stdin=subprocess.DEVNULL, env=_git_env(),
        )
        if r.returncode != 0:
            # No repository here, or git is unusable. Either way there is no
            # commit to diff against, which is a different fact from "the
            # script matches the last commit" and must not render as one.
            script_diff, facts["code_status"] = "", "no_git"
        else:
            script_diff = r.stdout.strip()
            facts["code_status"] = ("changed" if script_diff
                                    else _tracked_status(root, rel))
    except Exception as e:
        debug_log(f"git diff failed for script: {e}")
        script_diff, facts["code_status"] = "", "no_git"

    changed = []
    for line in script_diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            changed.append(f"+ {line[1:].strip()}")
        elif line.startswith("-") and not line.startswith("---"):
            changed.append(f"- {line[1:].strip()}")
    facts["code_changes"] = summarize_changed_lines(changed)

    if len(_facts_cache) >= _FACTS_CACHE_MAX:
        _facts_cache.clear()      # bounded; a sweep only ever touches a few files
    _facts_cache[key] = facts
    return facts


# Directory names that mean "this file is not the project's own code", checked
# per path component. An interpreter's `sys.modules` is mostly other people's
# code, and a virtualenv living *inside* the project root would otherwise put
# every installed dependency through the snapshot store.
_NOT_PROJECT_CODE = frozenset((
    "site-packages", "dist-packages", "__pycache__", ".git", ".exptrack",
    ".venv", "venv", "env", ".tox", ".mypy_cache", "node_modules",
))


def _exptrack_package_dir():
    """Directory of exptrack's own source, so a run never snapshots the tracker.

    In development the tracker *is* a project-local package (this repository
    tracks its own runs), so the project-root test alone would pull all of
    ``exptrack/`` into every run's snapshot.
    """
    from pathlib import Path as _Path
    return _Path(__file__).resolve().parent.parent


def _project_module_files(modules: dict, root, script_path: str) -> list:
    """Project-local ``.py`` files among *modules*, as (relative, absolute) pairs.

    Sorted by relative path so a run's capture is deterministic and two runs
    that imported the same files record them in the same order.
    """
    from pathlib import Path as _Path

    try:
        root_res = _Path(root).resolve()
    except OSError:
        return []
    pkg_dir = _exptrack_package_dir()
    try:
        script_res = _Path(script_path).resolve() if script_path else None
    except OSError:
        script_res = None

    found: dict[str, _Path] = {}
    for mod in list(modules.values()):
        f = getattr(mod, "__file__", None)
        if not f or not str(f).endswith(".py"):
            continue
        try:
            p = _Path(f).resolve()
        except OSError:
            continue
        if script_res is not None and p == script_res:
            continue        # already stored by capture_script_snapshot
        if p == pkg_dir or pkg_dir in p.parents:
            continue
        try:
            rel = p.relative_to(root_res)
        except ValueError:
            continue        # outside the project: the stdlib, site-packages, …
        if _NOT_PROJECT_CODE & set(rel.parts):
            continue
        found[rel.as_posix()] = p
    return [(rel, found[rel]) for rel in sorted(found)]


def capture_module_snapshots(exp: Experiment, modules: dict | None = None) -> int:
    """Snapshot the project-local modules this run imported. Returns the count.

    The entry script used to be the only source a run recorded, which made a
    perfectly ordinary layout invisible: ``main.py`` imports ``script.py``, you
    edit ``script.py`` and rerun ``main.py``, and both runs stored the same
    ``main.py`` — so ``compare_run_code`` reported *no code change* for two runs
    that executed different code, and the run detail filed the edit under
    "Other files in the working tree" beneath a headline saying the script
    matched the commit. The working-tree diff held the answer the whole time
    and nothing connected it to the run.

    Called at finish rather than at construction: the imports have happened by
    then, so ``sys.modules`` is the record of what the run actually loaded —
    which is narrower and more honest than walking the project for ``.py``
    files, most of which this run never touched.

    Everything here is bounded, because a run must never pay for the tracker:
    only files under the project root, never the tracker's own package, never a
    vendored/virtualenv path (``_NOT_PROJECT_CODE``), each capped at
    ``snapshot_max_kb`` and the set capped at ``snapshot_max_files``. Hitting
    the cap records ``_code_files_truncated`` — the number of candidates — so a
    partial capture is never presented as the whole of what ran.

    Idempotent: entries are keyed by relative path, so a second call (a
    finish-after-finish, a notebook re-run) adds nothing.
    """
    import sys as _sys

    from .. import config as _cfg
    from .db import get_db, store_code_snapshot

    if modules is None:
        modules = _sys.modules
    try:
        conf = _cfg.load()
        root = _cfg.project_root()
    except Exception as e:
        debug_log(f"module capture: could not resolve project root: {e}")
        return 0

    try:
        cap_kb = int(conf.get("snapshot_max_kb", 512))
    except (TypeError, ValueError, OverflowError):
        cap_kb = 512
    try:
        max_files = max(0, int(conf.get("snapshot_max_files", 50)))
    except (TypeError, ValueError, OverflowError):
        max_files = 50
    if not max_files:
        return 0

    candidates = _project_module_files(modules, root,
                                      exp._script_snapshotted or "")
    if not candidates:
        return 0

    existing = exp._params.get("_code_snapshot")
    if not isinstance(existing, list):
        existing = []
    have = {e.get("path") for e in existing
            if isinstance(e, dict) and e.get("kind") == "module"}

    conn = get_db()
    added = []
    for rel, abs_path in candidates[:max_files]:
        if rel in have:
            continue
        try:
            src = abs_path.read_text()
        except Exception as e:
            debug_log(f"module capture: could not read {abs_path}: {e}")
            continue
        if len(src.encode("utf-8", "replace")) > cap_kb * 1024:
            debug_log(f"module capture: {rel} over snapshot_max_kb, skipped")
            continue
        try:
            h = store_code_snapshot(conn, src, kind="module", path=rel)
        except Exception as e:
            debug_log(f"module capture: could not store {rel}: {e}")
            continue
        if h:
            added.append({"hash": h, "kind": "module", "path": rel})

    if not added:
        return 0
    try:
        conn.commit()
    except Exception as e:
        debug_log(f"module capture: commit failed: {e}")
    exp.log_param("_code_snapshot", existing + added)
    if len(candidates) > max_files:
        exp.log_param("_code_files_truncated", len(candidates))
    return len(added)


def capture_script_snapshot(exp: Experiment, script_path: str):
    """
    Diff the script against the last git commit (HEAD) and log only the
    changed lines.  No full-source copies are stored — the committed file
    in git is always the reference point, keeping storage minimal.
    """
    # Idempotence is the Experiment's own state (`_script_snapshotted`, declared
    # and reset there); this only reads and stamps it. Callers reach this through
    # `Experiment._maybe_snapshot_script`, which is the single entry point.
    if exp._script_snapshotted == str(script_path):
        return

    facts = _script_facts(script_path)
    if facts is None:
        return
    exp._script_snapshotted = str(script_path)

    src_hash = facts["src_hash"]
    exp.log_param("_script_hash", src_hash)
    if facts["snapshot_hash"]:
        # Hand log_param the native list — it JSON-encodes values once.
        # (Pre-encoding here would double-wrap the column.)
        exp.log_param("_code_snapshot",
                      [{"hash": facts["snapshot_hash"], "kind": "script",
                        "path": str(script_path)}])
    if facts["code_changes"]:
        exp.log_param("_code_changes", facts["code_changes"])
    elif facts["code_status"] in ("untracked", "no_git"):
        # Only the two cases where an empty code panel would mislead. A clean
        # tree deliberately writes nothing: no `_code_changes` plus a captured
        # commit already means "matched that commit", and a row on every clean
        # run would be pure noise on the most common path there is.
        exp.log_param("_code_status", facts["code_status"])

    exp.log_event(
        event_type="cell_exec",
        cell_hash=src_hash,
        key="script",
        value={"script": script_path, "hash": src_hash},
        source_diff=facts["code_changes"] or None,
    )
