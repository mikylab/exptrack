"""
exptrack/capture/script_tracking.py — Script source change tracking via git diff
"""
from __future__ import annotations

import hashlib
import subprocess
from typing import TYPE_CHECKING

from ..core.utils import debug_log

if TYPE_CHECKING:
    from ..core import Experiment


def capture_script_snapshot(exp: Experiment, script_path: str):
    """
    Diff the script against the last git commit (HEAD) and log only the
    changed lines.  No full-source copies are stored — the committed file
    in git is always the reference point, keeping storage minimal.
    """
    from pathlib import Path as _Path

    from .. import config as _cfg

    try:
        src = _Path(script_path).read_text()
    except Exception as e:
        debug_log(f"could not read script {script_path}: {e}")
        return

    src_hash = hashlib.md5(src.encode()).hexdigest()[:12]
    exp.log_param("_script_hash", src_hash)

    # Store the full script source, content-addressed + deduped, so the code
    # that ran is recoverable even when it was untracked / the project isn't a
    # git repo / the diff was excluded. Never .ipynb (handled by cell records).
    # Size-capped so a pathological file can't bloat the DB.
    try:
        conf = _cfg.load()
        cap_kb = int(conf.get("snapshot_max_kb", 512))
        if not str(script_path).endswith(".ipynb") and len(src.encode("utf-8", "replace")) <= cap_kb * 1024:
            from ..core.db import get_db, store_code_snapshot
            conn = get_db()
            h = store_code_snapshot(conn, src, kind="script", path=str(script_path))
            conn.commit()
            if h:
                # Hand log_param the native list — it JSON-encodes values once.
                # (Pre-encoding here would double-wrap the column.)
                exp.log_param("_code_snapshot",
                              [{"hash": h, "kind": "script",
                                "path": str(script_path)}])
    except Exception as e:
        debug_log(f"could not store code snapshot: {e}")

    root = _cfg.project_root()
    try:
        rel = _Path(script_path).resolve().relative_to(root.resolve())
    except ValueError:
        rel = _Path(script_path)
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
    if script_diff:
        for line in script_diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                changed.append(f"+ {line[1:].strip()}")
            elif line.startswith("-") and not line.startswith("---"):
                changed.append(f"- {line[1:].strip()}")
        if changed:
            exp.log_param("_code_changes", "; ".join(changed)[:1000])

    exp.log_event(
        event_type="cell_exec",
        cell_hash=src_hash,
        key="script",
        value={"script": script_path, "hash": src_hash},
        source_diff="; ".join(changed)[:1000] if script_diff else None,
    )
