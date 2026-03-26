"""
exptrack/core/artifact_protection.py — Pre-run conflict detection and archival

Before a new run starts, checks if any artifacts from previous completed runs
sit at paths that could be overwritten.  If so, moves the old file into
``outputs/<old_run_name>/`` and updates the DB record, so the original is
never silently lost.

Protection is project-wide (not per-script) so it catches cross-script
conflicts and default-parameter saves regardless of which script created
the artifact.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .. import config as cfg
from .db import get_db
from .naming import output_path


def protect_previous_artifacts(new_exp_id: str) -> list[str]:
    """Archive artifacts from earlier runs that would be overwritten.

    Checks ALL completed/failed experiments in the project — not just runs
    of the same script — so that default-parameter saves and cross-script
    path conflicts are caught.

    Only considers artifacts whose paths are NOT already inside the managed
    ``outputs/`` directory (those are already run-namespaced).

    Returns a list of original paths that were archived.
    """
    conf = cfg.load()
    root = cfg.project_root()
    outputs_base = str((root / conf.get("outputs_dir", "outputs")).resolve())

    archived: list[str] = []

    try:
        conn = get_db()
        # Use BEGIN IMMEDIATE to serialize with any concurrent run starts
        conn.execute("BEGIN IMMEDIATE")
    except Exception as e:
        print(f"[exptrack] warning: artifact protection DB access failed: {e}", file=sys.stderr)
        return archived

    try:
        rows = conn.execute("""
            SELECT a.id, a.path, a.content_hash, a.exp_id, e.name
            FROM artifacts a
            JOIN experiments e ON a.exp_id = e.id
            WHERE a.exp_id != ?
              AND e.status IN ('done', 'failed')
              AND a.path IS NOT NULL
        """, (new_exp_id,)).fetchall()

        for row in rows:
            art_path = row["path"]

            # Skip artifacts already inside the outputs directory
            if art_path.startswith(outputs_base):
                continue

            fp = Path(art_path)
            if not fp.is_file():
                continue

            # Move to outputs/<old_run_name>/<filename>
            old_run_name = row["name"] or row["exp_id"]
            dest = output_path(fp.name, old_run_name)

            # Avoid overwriting an already-archived copy
            if dest.exists():
                stem = dest.stem
                suffix = dest.suffix
                counter = 1
                while dest.exists():
                    dest = dest.with_name(f"{stem}_{counter}{suffix}")
                    counter += 1

            try:
                shutil.copy2(str(fp), str(dest))
            except OSError:
                continue

            # Update the artifact record to point to the archived copy
            conn.execute(
                "UPDATE artifacts SET path=? WHERE id=?",
                (str(dest.resolve()), row["id"])
            )
            archived.append(art_path)

        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass  # rollback failed; outer error is logged below
        print(f"[exptrack] artifact protection warning: {e}", file=sys.stderr)

    return archived
