"""
exptrack/dashboard/routes/write_routes/admin.py

Database maintenance: clean, vacuum, reset, storage info.
"""
from __future__ import annotations

import sys
from pathlib import Path


def api_clean_db(conn, body: dict | None = None) -> dict:
    """Remove orphaned DB rows; report (and only on request, trash) orphaned
    output paths.

    Row cleanup always runs — it's reversible-by-nature bookkeeping. Files are
    a separate, opt-in step: pass ``{"delete_files": true}`` to move the
    orphaned paths to the OS Trash (never unlinked — an "orphan" here is a
    heuristic that also matches files a user kept deliberately when permanently
    deleting a run). Without the flag this reports them under ``orphan_files``
    and touches nothing on disk.
    """
    from exptrack.core.db import (
        describe_orphan_output_paths,
        find_orphan_output_paths,
        sweep_orphans,
        trash_orphan_output_paths,
    )

    body = body or {}
    counts = sweep_orphans(conn)
    total = sum(counts.values())

    file_stats: dict = {}
    orphan_files: list = []
    try:
        # Discover once and hand the list to whichever step follows: annotating
        # walks every orphan tree with rglob+stat, so it is skipped entirely on
        # the delete request (which discards the annotation anyway).
        paths = find_orphan_output_paths(conn)
        if body.get("delete_files"):
            if paths:
                file_stats = trash_orphan_output_paths(conn, paths)
                counts["output_paths"] = sum(file_stats.values())
                total += counts["output_paths"]
        else:
            orphan_files = describe_orphan_output_paths(conn, paths)
    except Exception as e:
        print(f"[exptrack] warning: api_clean_db output-dir cleanup failed: {e}",
              file=sys.stderr)

    return {"ok": True, "removed": total, "details": counts,
            "orphan_files": orphan_files, "file_stats": file_stats}


def api_vacuum_db(conn) -> dict:
    """Checkpoint WAL and VACUUM the database to reclaim space."""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def api_reset_db(conn) -> dict:
    """Delete ALL experiments and data, then VACUUM.

    Clears every table in ``_RESET_TABLES`` — including ``code_snapshots`` and
    the Session Trees pair, which a previous hardcoded list omitted, so "erase
    everything" left full script sources and every notebook cell body/output
    sitting in the database. Output files go to the OS Trash rather than being
    rmtree'd, matching every other destructive path in the codebase.
    """
    from exptrack import config as cfg
    from exptrack.core.db import _trash_or_local, delete_experiment, reset_all_tables

    rows = conn.execute("SELECT id FROM experiments").fetchall()
    n_exp = len(rows)
    for r in rows:
        # No per-run blob reclaim: reset_all_tables truncates both blob tables
        # wholesale on the next line.
        delete_experiment(conn, r["id"], reclaim_blobs=False)
    cleared = reset_all_tables(conn)
    conn.commit()
    # Clean outputs directory (recoverable — OS Trash, local fallback)
    try:
        root = cfg.project_root()
        conf = cfg.load()
        outputs_dir = root / conf.get("outputs_dir", "outputs")
        if outputs_dir.is_dir():
            for child in sorted(outputs_dir.iterdir()):
                _trash_or_local(child, label="output")
    except Exception as e:
        print(f"[exptrack] warning: api_reset_db outputs cleanup failed: {e}",
              file=sys.stderr)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    except Exception as e:
        print(f"[exptrack] warning: api_reset_db VACUUM failed "
              f"(another connection may be open): {e}", file=sys.stderr)
    return {"ok": True, "deleted_experiments": n_exp, "cleared": cleared}


def api_storage_info(conn) -> dict:
    """Return database size and WAL size info."""
    from exptrack import config as cfg
    root = cfg.project_root()
    conf = cfg.load()
    db_path = root / conf.get("db", ".exptrack/experiments.db")
    wal_path = Path(str(db_path) + "-wal")
    db_size = db_path.stat().st_size if db_path.exists() else 0
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    n_exp = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    n_params = conn.execute("SELECT COUNT(*) FROM params").fetchone()[0]
    n_metrics = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    n_artifacts = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    n_timeline = conn.execute("SELECT COUNT(*) FROM timeline").fetchone()[0]
    return {
        "ok": True,
        "db_bytes": db_size,
        "wal_bytes": wal_size,
        "total_bytes": db_size + wal_size,
        "experiments": n_exp,
        "params": n_params,
        "metrics": n_metrics,
        "artifacts": n_artifacts,
        "timeline": n_timeline,
    }
