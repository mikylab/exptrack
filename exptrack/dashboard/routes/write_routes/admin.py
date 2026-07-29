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

    The confirm dialog is built from a *previous* request, so the delete call
    should pass back the exact ``paths`` it showed the user: this trashes only
    the intersection of that list with the paths still orphaned right now.
    Without it, anything written under ``outputs/`` between the two requests —
    a run that started in the meantime, a file dropped in by hand — was moved
    to the Trash having never appeared in the confirm. Omitting ``paths``
    keeps the old discover-and-act behaviour for existing callers.
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
    skipped = 0
    try:
        # Discover once and hand the list to whichever step follows: annotating
        # walks every orphan tree with rglob+stat, so it is skipped entirely on
        # the delete request (which discards the annotation anyway).
        paths = find_orphan_output_paths(conn)
        if body.get("delete_files"):
            confirmed = body.get("paths")
            if confirmed is not None:
                allowed = {str(p) for p in confirmed if p}
                kept = [p for p in paths if str(p) in allowed]
                skipped = len(paths) - len(kept)
                paths = kept
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
            "orphan_files": orphan_files, "file_stats": file_stats,
            "skipped_unconfirmed": skipped}


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
    """Database size, per-table bytes, metric hotspots and the biggest runs.

    Row counts alone never answered the question the panel is opened to ask —
    *what is taking the space, and which run do I act on*. The byte figures per
    table are exact (SQLite's dbstat); everything per-key and per-experiment is
    that total apportioned by row count, flagged as estimated in the UI.
    """
    from exptrack import config as cfg
    from exptrack.core.storage import (
        experiment_storage,
        free_space,
        metric_storage,
        orphan_storage,
        table_byte_sizes,
        trash_storage,
    )
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

    free = free_space(conn)
    table_bytes = table_byte_sizes(conn)
    metrics = metric_storage(conn, top=8, table_bytes=table_bytes)
    largest = experiment_storage(conn, limit=8, table_bytes=table_bytes)
    trash = trash_storage(conn, table_bytes=table_bytes)
    # The dashboard never sweeps on its own — the per-request close deliberately
    # skips it (anti-join counts are far too expensive per request), so unlike
    # the CLI a dashboard-only user keeps a legacy database's orphans until
    # something says they're there.
    orphans = orphan_storage(conn, table_bytes=table_bytes)

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
        "exact_sizes": bool(table_bytes),
        "free_bytes": free["bytes"],
        "free_pct": round(free["pct"], 1),
        "metrics_bytes": metrics["bytes"],
        "metric_keys": metrics["keys"],
        "metric_key_count": metrics["key_count"],
        "largest_experiments": largest,
        "trash": trash,
        "orphans": orphans,
    }


def api_prune_metrics(conn, body: dict) -> dict:
    """Thin already-stored metric points. Destructive unless ``dry_run``.

    body.ids: experiment ids to limit to (default: all)
    body.keys: metric keys to limit to (default: all)
    body.max_points / body.keep_every: the thinning target
    body.dry_run: preview only
    """
    from exptrack.core.storage import preview_metric_prune, prune_metrics

    keep_every = max(1, int(body.get("keep_every") or 1))
    max_points = max(0, int(body.get("max_points") or 0))
    if keep_every == 1 and not max_points:
        return {"error": "pass max_points or keep_every"}

    ids = [i for i in (body.get("ids") or []) if i] or None
    keys = [k for k in (body.get("keys") or []) if k] or None
    protect = body.get("protect_extremes", True)

    fn = preview_metric_prune if body.get("dry_run") else prune_metrics
    res = fn(conn, ids, keys, keep_every, max_points, protect)
    # The selected row ids are an internal handoff between preview and delete
    # within one process; a dry run over a large series would otherwise ship
    # millions of integers to the browser.
    res.pop("_ids", None)
    res["ok"] = True
    return res
