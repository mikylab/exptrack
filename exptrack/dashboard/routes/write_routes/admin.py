"""
exptrack/dashboard/routes/write_routes/admin.py

Database maintenance: clean, vacuum, reset, storage info.
"""
from __future__ import annotations

import sys
import threading
import time
import uuid
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
        source_code_storage,
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
        "source_code": source_code_storage(conn),
    }


# Doomed row-id sets from prune dry-runs, held server-side so the confirmed
# delete removes exactly the set the confirm dialog described — a fresh
# selection at delete time would also take any points logged while the dialog
# was open, i.e. a delete larger than (and different from) the one confirmed.
# The ids themselves never go to the browser (millions of integers), so unlike
# the clean-orphans confirm — which round-trips the paths it displayed — the
# client can only round-trip a token.
#
# Memory is bounded two ways, because each entry can be millions of ints: a TTL,
# swept on both the stash and the claim path (sweeping only on stash left an
# abandoned dialog's set resident until the *next* preview, which may never
# come), and a hard cap on entries, oldest evicted first. The cap is above 1 so
# two browser tabs don't invalidate each other, and an evicted token fails
# closed — the claim refuses rather than re-selecting.
_PRUNE_PREVIEW_TTL_S = 600
_PRUNE_PREVIEW_MAX = 4
# The dashboard serves requests on threads, so guard the dict like read_routes
# guards its scan cache.
_prune_previews: dict = {}
_prune_previews_lock = threading.Lock()


def _sweep_prune_previews(now: float) -> None:
    for tok in [t for t, (ts, _, _) in _prune_previews.items()
                if now - ts > _PRUNE_PREVIEW_TTL_S]:
        del _prune_previews[tok]


def _stash_prune_preview(doomed: list, table_bytes: dict | None) -> str:
    token = uuid.uuid4().hex
    now = time.monotonic()
    with _prune_previews_lock:
        _sweep_prune_previews(now)
        while len(_prune_previews) >= _PRUNE_PREVIEW_MAX:
            del _prune_previews[min(_prune_previews,
                                    key=lambda t: _prune_previews[t][0])]
        _prune_previews[token] = (now, doomed, table_bytes)
    return token


def _claim_prune_preview(token: str):
    """The stashed (doomed, table_bytes) for `token`, or None if it's gone."""
    with _prune_previews_lock:
        _sweep_prune_previews(time.monotonic())
        entry = _prune_previews.pop(token, None)
    return None if entry is None else (entry[1], entry[2])


def api_prune_metrics(conn, body: dict) -> dict:
    """Thin already-stored metric points. Destructive unless ``dry_run``.

    body.ids: experiment ids to limit to (default: all)
    body.keys: metric keys to limit to (default: all)
    body.max_points / body.keep_every: the thinning target
    body.dry_run: preview only (returns ``preview_token``)
    body.preview_token: delete exactly the previewed set (see above)
    """
    from exptrack.core.db import checkpoint_truncate
    from exptrack.core.storage import (
        preview_metric_prune,
        prune_metrics,
        table_byte_sizes,
    )

    try:
        keep_every = max(1, int(body.get("keep_every") or 1))
        max_points = max(0, int(body.get("max_points") or 0))
    except (TypeError, ValueError, OverflowError):
        return {"error": "keep_every and max_points must be integers"}
    if keep_every == 1 and not max_points:
        return {"error": "pass max_points or keep_every"}

    ids = [i for i in (body.get("ids") or []) if i] or None
    keys = [k for k in (body.get("keys") or []) if k] or None
    protect = body.get("protect_extremes", True)

    if body.get("dry_run"):
        # Sizing walks every page of the database, so hand the result to the
        # confirmed delete rather than letting it walk again.
        table_bytes = table_byte_sizes(conn)
        res = preview_metric_prune(conn, ids, keys, keep_every, max_points,
                                   protect, table_bytes)
        res["preview_token"] = _stash_prune_preview(res.pop("_ids", []),
                                                   table_bytes)
        res["ok"] = True
        return res

    doomed = table_bytes = None
    token = body.get("preview_token")
    if token:
        claimed = _claim_prune_preview(token)
        if claimed is None:
            # The preview this confirm was built from is gone (server restart,
            # TTL, eviction) — refuse rather than silently deleting a different
            # set than the one the user was shown.
            return {"error": "preview expired — run the preview again"}
        doomed, table_bytes = claimed
    res = prune_metrics(conn, ids, keys, keep_every, max_points, protect,
                        table_bytes, doomed=doomed)
    res.pop("_ids", None)
    # Same rationale as the delete-permanent routes: a prune is routinely the
    # largest delete the dashboard performs, and the per-request checkpoint is
    # deliberately PASSIVE — without a bounded TRUNCATE the freed pages sit in
    # a ballooned -wal file until the server exits.
    checkpoint_truncate(conn)
    res["ok"] = True
    return res
