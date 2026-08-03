"""
exptrack/dashboard/routes/write_routes/compact.py

Storage compaction: strip git diffs, cell sources and timeline diffs,
plus the diff export that shares their sentinel handling.
"""
from __future__ import annotations

import sys

from exptrack.core.queries import find_experiment
from exptrack.core.utils import fmt_bytes


def api_compact(conn, body: dict) -> dict:
    """Compact experiments — supports git_diff, cells, timeline, deep modes.

    body.ids: list of experiment IDs (prefix match)
    body.mode: "diff" (default), "cells", "timeline", "deep" (all of the above)
    body.dry_run: if true, only preview what would be removed
    """
    ids = body.get("ids", [])
    if not ids:
        return {"error": "no ids provided"}

    mode = body.get("mode", "diff")
    dry_run = body.get("dry_run", False)
    do_deep = mode == "deep"
    do_diff = mode == "diff" or do_deep
    do_cells = mode == "cells" or do_deep
    do_timeline = mode == "timeline" or do_deep
    # Not part of "deep" — see the note in cli/admin_cmds.cmd_compact.
    do_code_changes = mode == "code-changes"

    # Resolve experiment IDs
    resolved_ids = []
    for eid in ids:
        row = find_experiment(conn, eid, "id")
        if row:
            resolved_ids.append(row["id"])
    if not resolved_ids:
        return {"ok": True, "compacted": 0, "freed": 0, "detail": "No matching experiments",
                "will_remove": []}

    if do_code_changes:
        from exptrack.core.storage import (
            compact_code_changes,
            preview_code_change_compact,
        )
        fn = preview_code_change_compact if dry_run else compact_code_changes
        st = fn(conn, resolved_ids)
        skipped = len(st["skipped_no_snapshot"])
        detail = (f"{st['rows']} summary row(s) across {st['runs']} run(s)"
                  if st["rows"] else "nothing to compact")
        if skipped:
            detail += f"; skipped {skipped} run(s) with no code snapshot"
        return {"ok": True, "dry_run": dry_run, "compacted": st["runs"],
                "freed": st["bytes"], "freed_fmt": fmt_bytes(st["bytes"]),
                "skipped_no_snapshot": skipped, "detail": detail,
                "will_remove": [detail] if dry_run else []}

    if dry_run:
        return _compact_preview(conn, resolved_ids, do_diff, do_cells, do_timeline)

    freed = 0
    detail_parts = []

    # ── 1. Git diff compaction ────────────────────────────────────────────
    if do_diff:
        from exptrack.core.storage import compact_git_diffs
        st = compact_git_diffs(conn, resolved_ids)
        freed += st["bytes"]
        if st["runs"]:
            detail_parts.append(f"diffs: {st['runs']}")

    # ── 2. Cell lineage source compaction ─────────────────────────────────
    if do_cells:
        cell_freed = _compact_cell_sources(conn, resolved_ids)
        freed += cell_freed
        if cell_freed:
            detail_parts.append(f"cells: {fmt_bytes(cell_freed)}")

    # ── 3. Timeline source_diff compaction ────────────────────────────────
    if do_timeline:
        tl_freed = _compact_timeline_sources(conn, resolved_ids)
        freed += tl_freed
        if tl_freed:
            detail_parts.append(f"timeline: {fmt_bytes(tl_freed)}")

    compacted = len(resolved_ids) if freed > 0 else 0
    detail = ", ".join(detail_parts) if detail_parts else "nothing to compact"
    return {"ok": True, "compacted": compacted, "freed": freed, "detail": detail}


def _compact_preview(conn, exp_ids: list, do_diff: bool, do_cells: bool,
                     do_timeline: bool) -> dict:
    """Preview what compact would remove, without modifying anything."""
    will_remove = []
    total_bytes = 0

    if do_diff:
        # Same selection the write uses, so the dry-run provably describes it.
        # Its `bytes` is what would leave the database, which for deduplicated
        # diffs is not the sum of the per-run sizes listed below — N runs
        # sharing one body reclaim one body.
        from exptrack.core.storage import preview_git_diff_compact
        st = preview_git_diff_compact(conn, exp_ids)
        total_bytes += st["bytes"]
        for d in st["details"]:
            files = d["files"]
            will_remove.append(
                f"Git diff ({fmt_bytes(d['bytes'])}, {len(files)} file(s): "
                + ", ".join(files[:3])
                + (f" +{len(files) - 3} more" if len(files) > 3 else "") + ")")

    if do_cells:
        placeholders = ",".join("?" * len(exp_ids))
        try:
            row = conn.execute(f"""
                SELECT COALESCE(SUM(LENGTH(cl.source)), 0) as sz,
                       COUNT(*) as cnt
                FROM cell_lineage cl
                WHERE cl.source IS NOT NULL AND LENGTH(cl.source) > 0
                AND cl.cell_hash IN (
                    SELECT DISTINCT cell_hash FROM timeline
                    WHERE exp_id IN ({placeholders}) AND cell_hash IS NOT NULL
                )
                AND cl.cell_hash NOT IN (
                    SELECT DISTINCT t.cell_hash FROM timeline t
                    WHERE t.exp_id NOT IN ({placeholders})
                      AND t.cell_hash IS NOT NULL
                      AND t.source_diff IS NOT NULL
                )
            """, exp_ids + exp_ids).fetchone()
            sz = row["sz"] if row else 0
            cnt = row["cnt"] if row else 0
            if sz:
                total_bytes += sz
                will_remove.append(f"Cell source code ({fmt_bytes(sz)}, {cnt} cell(s))")
        except Exception as e:
            print(f"[exptrack] warning: cell-source compact preview query failed: {e}",
                  file=sys.stderr)

    if do_timeline:
        # Same selection the write uses, so the dry-run provably describes it —
        # counting already-marked rows promised bytes the compact won't free.
        from exptrack.core.storage import preview_timeline_diff_compact
        try:
            tl = preview_timeline_diff_compact(conn, exp_ids)
            sz, cnt = tl["bytes"], tl["events"]
            if sz:
                total_bytes += sz
                will_remove.append(f"Timeline inline diffs ({fmt_bytes(sz)}, {cnt} event(s))")
        except Exception as e:
            print(f"[exptrack] warning: timeline-diff compact preview query failed: {e}",
                  file=sys.stderr)

    return {"ok": True, "dry_run": True, "will_remove": will_remove,
            "total_bytes": total_bytes, "total_fmt": fmt_bytes(total_bytes)}


def _compact_cell_sources(conn, exp_ids: list) -> int:
    """Strip cell_lineage.source for cells that no longer need source text.

    Sets source to '' (empty string) since the column has NOT NULL constraint.
    A cell is safe to strip when ALL experiments referencing it either:
      - are in the current compact batch, OR
      - have already had their timeline source_diff stripped (compacted)
    """
    if not exp_ids:
        return 0
    placeholders = ",".join("?" * len(exp_ids))
    # Find cells used by target experiments, excluding cells still needed
    # by other non-compacted experiments
    query = f"""
        SELECT COALESCE(SUM(LENGTH(cl.source)), 0) as sz
        FROM cell_lineage cl
        WHERE cl.source IS NOT NULL AND LENGTH(cl.source) > 0
        AND cl.cell_hash IN (
            SELECT DISTINCT cell_hash FROM timeline
            WHERE exp_id IN ({placeholders}) AND cell_hash IS NOT NULL
        )
        AND cl.cell_hash NOT IN (
            SELECT DISTINCT t.cell_hash FROM timeline t
            WHERE t.exp_id NOT IN ({placeholders})
              AND t.cell_hash IS NOT NULL
              AND t.source_diff IS NOT NULL
        )
    """
    update_query = f"""
        UPDATE cell_lineage SET source = ''
        WHERE source IS NOT NULL AND LENGTH(source) > 0
        AND cell_hash IN (
            SELECT DISTINCT cell_hash FROM timeline
            WHERE exp_id IN ({placeholders}) AND cell_hash IS NOT NULL
        )
        AND cell_hash NOT IN (
            SELECT DISTINCT t.cell_hash FROM timeline t
            WHERE t.exp_id NOT IN ({placeholders})
              AND t.cell_hash IS NOT NULL
              AND t.source_diff IS NOT NULL
        )
    """
    try:
        size_row = conn.execute(query, exp_ids + exp_ids).fetchone()
        freed = size_row["sz"] if size_row else 0
        if freed:
            conn.execute(update_query, exp_ids + exp_ids)
            conn.commit()
        return freed
    except Exception:
        return 0


def _compact_timeline_sources(conn, exp_ids: list) -> int:
    """Freed bytes from `storage.compact_timeline_diffs` (the one implementation).

    This used to keep its own copy that NULLed the column. The CLI's copy was
    fixed to write a `[compacted…]` marker — because a NULL `source_diff` is
    also the *normal* state for a script run against a clean tree, so the status
    check read every such run as compacted — but this sibling was left behind,
    so compacting from the dashboard still reported "not compacted" afterwards,
    and a second pass over a CLI-marked run counted the marker as reclaimable
    and then erased the evidence it stands for.
    """
    from exptrack.core.storage import compact_timeline_diffs
    try:
        return compact_timeline_diffs(conn, exp_ids)["bytes"]
    except Exception:
        return 0


def api_export_diff(conn, exp_id: str) -> dict:
    """Return the git diff for an experiment as downloadable markdown."""
    exp = find_experiment(conn, exp_id, "id, name, git_branch, git_commit, git_diff")
    if not exp:
        return {"error": "not found"}
    from exptrack.core.db import resolve_git_diff
    diff = resolve_git_diff(conn, exp["git_diff"])
    from exptrack.core.db import diff_sentinel_kind
    kind = diff_sentinel_kind(diff)
    if kind == "compacted":
        return {"error": "diff already compacted", "compacted": True}
    if kind == "capture_failed":
        return {"error": "diff capture failed for this run", "capture_failed": True}
    if kind == "unavailable":
        return {"error": "the stored diff for this run is no longer available",
                "unavailable": True}
    name = exp["name"] or exp["id"][:8]
    md = (f"# Diff: {name}\n\n"
          f"- **Experiment ID:** `{exp['id']}`\n"
          f"- **Branch:** `{exp['git_branch'] or ''}`\n"
          f"- **Commit:** `{exp['git_commit'] or ''}`\n\n"
          f"```diff\n{diff}\n```\n")
    return {"ok": True, "markdown": md, "filename": f"{name}__{exp['id'][:8]}.md"}
