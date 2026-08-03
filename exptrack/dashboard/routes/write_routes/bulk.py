"""
exptrack/dashboard/routes/write_routes/bulk.py

Multi-experiment operations and the project-folder export writer.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from exptrack.core.queries import find_experiment

from ._shared import body_str


def api_bulk_delete(conn, body: dict) -> dict:
    """Bulk soft-delete (Trash). Use /api/bulk-delete-permanent for permanent."""
    ids = body.get("ids", [])
    if not ids:
        return {"error": "no ids provided"}
    from exptrack.core.db import trash_experiment
    trashed = 0
    for eid in ids:
        exp = find_experiment(conn, eid)
        if exp and trash_experiment(conn, exp["id"]):
            trashed += 1
    conn.commit()
    return {"ok": True, "trashed": trashed}


def api_bulk_restore(conn, body: dict) -> dict:
    ids = body.get("ids", [])
    if not ids:
        return {"error": "no ids provided"}
    from exptrack.core.db import restore_experiment
    restored = 0
    for eid in ids:
        exp = find_experiment(conn, eid)
        if exp and restore_experiment(conn, exp["id"]):
            restored += 1
    conn.commit()
    return {"ok": True, "restored": restored}


def api_bulk_delete_permanent(conn, body: dict) -> dict:
    """Permanently delete N experiments. With delete_files=True, files on disk
    are moved to the OS Trash (recoverable in Finder/Files) with a local
    ``.exptrack/trash/`` fallback — never unlinked outright.
    """
    ids = body.get("ids", [])
    if not ids:
        return {"error": "no ids provided"}
    delete_files = bool(body.get("delete_files", False))
    from exptrack.core.db import _sweep_blobs, checkpoint_truncate, delete_experiment
    from exptrack.core.storage import free_space
    free_before = free_space(conn)["bytes"]
    deleted = 0
    totals = {"os_trash": 0, "local_trash": 0, "failed": 0, "missing": 0}
    for eid in ids:
        exp = find_experiment(conn, eid)
        if exp:
            stats = delete_experiment(conn, exp["id"], delete_files=delete_files,
                                      reclaim_blobs=False)
            for k, v in (stats or {}).items():
                totals[k] = totals.get(k, 0) + v
            deleted += 1
    if deleted:
        _sweep_blobs(conn)  # once for the batch, not once per run
    conn.commit()
    freed = max(0, free_space(conn)["bytes"] - free_before)
    checkpoint_truncate(conn)   # see api_delete_permanent: PASSIVE won't shrink it
    return {"ok": True, "deleted": deleted, "deleted_files": delete_files,
            "file_stats": totals, "freed_bytes": freed}


def api_bulk_delete_preview(conn, body: dict) -> dict:
    """Aggregate preview of what permanent bulk delete would remove."""
    ids = body.get("ids", [])
    if not ids:
        return {"error": "no ids provided"}
    # Function-local so it reads the module attribute at call time — the same
    # reason dir_file_stats resolves the cap per call.
    from exptrack.core.db import DIR_STAT_MAX_FILES, get_delete_preview
    items: list[dict] = []
    totals = {
        "experiments": 0,
        "metrics": 0,
        "params": 0,
        "artifacts": 0,
        "artifacts_existing": 0,
        "artifact_bytes": 0,
        "output_dirs_existing": 0,
        "output_dir_files": 0,
        "output_dir_bytes": 0,
        "notebook_history": 0,
        "linked_dirs": 0,
        "linked_dir_files": 0,
        "linked_dir_bytes": 0,
        # Any run whose directory walk hit the cap makes the aggregate a
        # lower bound too, so the batch confirm has to say "at least" as
        # well — a total summed from partial figures is still partial.
        "dir_sizes_truncated": False,
        # The cap itself, echoed once from the constant rather than taken from
        # whichever run happened to be last in the loop — an empty or
        # all-skipped batch would otherwise ship 0 and the dialog would fall
        # back to saying "the walk limit" instead of naming the number.
        "dir_stat_max_files": DIR_STAT_MAX_FILES,
    }
    for eid in ids:
        exp = find_experiment(conn, eid)
        if not exp:
            continue
        p = get_delete_preview(conn, exp["id"], source_check=False)
        if "error" in p:
            continue
        items.append({
            "id": p["id"], "name": p["name"],
            "artifacts": p["artifacts_count"],
            "artifact_bytes": p["artifact_bytes"],
            "output_dir": p["output_dir"],
            "output_dir_bytes": p["output_dir_bytes"],
        })
        totals["experiments"] += 1
        totals["metrics"] += p["metrics_count"]
        totals["params"] += p["params_count"]
        totals["artifacts"] += p["artifacts_count"]
        totals["artifacts_existing"] += p["artifacts_existing"]
        totals["artifact_bytes"] += p["artifact_bytes"]
        totals["output_dirs_existing"] += 1 if p["output_dir_exists"] else 0
        totals["output_dir_files"] += p["output_dir_files"]
        totals["output_dir_bytes"] += p["output_dir_bytes"]
        totals["notebook_history"] += p["notebook_history_count"]
        totals["linked_dirs"] += len(p.get("linked_dirs") or [])
        totals["linked_dir_files"] += p.get("linked_dir_files", 0)
        totals["linked_dir_bytes"] += p.get("linked_dir_bytes", 0)
        if p.get("output_dir_truncated") or p.get("linked_dir_truncated"):
            totals["dir_sizes_truncated"] = True
    # Batch-aware on purpose: the per-run sole-source check sees the other
    # runs in this same doomed batch as surviving holders, so deleting the
    # only two runs sharing a snapshot would warn on neither. Best-effort
    # inside sole_source_holders itself — an internal failure degrades to
    # the not-sole shape rather than breaking the preview.
    from exptrack.core.storage import sole_source_holders
    source_only = sole_source_holders(conn, [it["id"] for it in items])
    return {"items": items, "totals": totals, "source_only_copy": source_only}


def api_bulk_export(conn, body: dict) -> dict | list:
    from exptrack.core.queries import (
        format_export_csv,
        format_export_markdown,
        get_batch_export_data,
    )
    ids = body.get("ids", [])
    fmt = body.get("format", "json")
    if not ids:
        return {"error": "no ids provided"}
    batch = get_batch_export_data(conn, exp_ids=ids, full=bool(body.get("full")))
    if not batch:
        return {"error": "no experiments found"}
    if fmt in ("csv", "tsv"):
        delimiter = "\t" if fmt == "tsv" else ","
        return {"format": fmt, "content": format_export_csv(batch, delimiter=delimiter)}
    elif fmt == "markdown":
        md_parts = [format_export_markdown(d) for d in batch]
        return {"format": "markdown", "content": "\n\n---\n\n".join(md_parts)}
    else:
        return batch


def api_save_export(body: dict) -> dict:
    """Write an export string to <project_root>/<exports_dir>/, picking a
    non-clashing filename (foo.md, foo_2.md, foo_3.md, ...). Existing files
    are never overwritten."""
    from exptrack.config import load as load_config
    from exptrack.config import project_root
    filename = body_str(body, "filename")
    content = body.get("content", "")
    if not filename:
        return {"error": "filename required"}
    safe = Path(filename).name
    if not safe or safe in (".", ".."):
        return {"error": "invalid filename"}

    root = project_root()
    out_dir = root / load_config().get("exports_dir", "exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem, ext = Path(safe).stem, Path(safe).suffix

    # Try the requested name, then _2…_999, then a microsecond timestamp
    # fallback so we never silently fail.
    candidates = [safe] + [f"{stem}_{n}{ext}" for n in range(2, 1000)]
    candidates.append(f"{stem}_{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}{ext}")
    for name in candidates:
        target = out_dir / name
        try:
            with target.open("x", encoding="utf-8") as f:
                f.write(content)
            return {
                "ok": True,
                "filename": name,
                "path": str(target.relative_to(root)),
                "absolute": str(target),
            }
        except FileExistsError:
            continue
    return {"error": "could not find a non-conflicting filename"}
