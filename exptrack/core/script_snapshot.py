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

from .utils import debug_log

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


def _script_facts(script_path: str) -> dict | None:
    """`{src_hash, snapshot_hash, code_changes}` for a script, memoized.

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
            cwd=str(root),
        )
        script_diff = r.stdout.strip() if r.returncode == 0 else ""
    except Exception as e:
        debug_log(f"git diff failed for script: {e}")
        script_diff = ""

    changed = []
    for line in script_diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            changed.append(f"+ {line[1:].strip()}")
        elif line.startswith("-") and not line.startswith("---"):
            changed.append(f"- {line[1:].strip()}")
    facts["code_changes"] = "; ".join(changed)[:1000]

    if len(_facts_cache) >= _FACTS_CACHE_MAX:
        _facts_cache.clear()      # bounded; a sweep only ever touches a few files
    _facts_cache[key] = facts
    return facts


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

    exp.log_event(
        event_type="cell_exec",
        cell_hash=src_hash,
        key="script",
        value={"script": script_path, "hash": src_hash},
        source_diff=facts["code_changes"] or None,
    )
