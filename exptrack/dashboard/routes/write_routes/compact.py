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

    # Resolve experiment IDs
    resolved_ids = []
    for eid in ids:
        row = find_experiment(conn, eid, "id")
        if row:
            resolved_ids.append(row["id"])
    if not resolved_ids:
        return {"ok": True, "compacted": 0, "freed": 0, "detail": "No matching experiments",
                "will_remove": []}

    if dry_run:
        return _compact_preview(conn, resolved_ids, do_diff, do_cells, do_timeline)

    freed = 0
    detail_parts = []

    # ── 1. Git diff compaction ────────────────────────────────────────────
    if do_diff:
        diff_freed, diff_count = _compact_git_diffs(conn, resolved_ids)
        freed += diff_freed
        if diff_count:
            detail_parts.append(f"diffs: {diff_count}")

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
    from exptrack.core.db import diff_b_path, is_diff_sentinel, resolve_git_diff
    will_remove = []
    total_bytes = 0

    if do_diff:
        for eid in exp_ids:
            row = conn.execute(
                "SELECT git_diff, git_commit FROM experiments WHERE id=?", (eid,)
            ).fetchone()
            if not row or not row["git_diff"] or is_diff_sentinel(row["git_diff"]):
                continue
            full_diff = resolve_git_diff(conn, row["git_diff"])
            if is_diff_sentinel(full_diff):
                continue  # e.g. a dangling ref — the real compact skips it too,
                          # so counting it here promised bytes that never free
            diff_len = len(full_diff)
            files = [diff_b_path(line.split()[-1])
                     for line in full_diff.splitlines()
                     if line.startswith("diff --git ") and len(line.split()) >= 4]
            total_bytes += diff_len
            will_remove.append(f"Git diff ({fmt_bytes(diff_len)}, {len(files)} file(s): {', '.join(files[:3])}"
                               + (f" +{len(files)-3} more" if len(files) > 3 else "") + ")")

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
        placeholders = ",".join("?" * len(exp_ids))
        try:
            row = conn.execute(f"""
                SELECT COALESCE(SUM(LENGTH(source_diff)), 0) as sz,
                       COUNT(*) as cnt
                FROM timeline
                WHERE exp_id IN ({placeholders}) AND source_diff IS NOT NULL
            """, exp_ids).fetchone()
            sz = row["sz"] if row else 0
            cnt = row["cnt"] if row else 0
            if sz:
                total_bytes += sz
                will_remove.append(f"Timeline inline diffs ({fmt_bytes(sz)}, {cnt} event(s))")
        except Exception as e:
            print(f"[exptrack] warning: timeline-diff compact preview query failed: {e}",
                  file=sys.stderr)

    return {"ok": True, "dry_run": True, "will_remove": will_remove,
            "total_bytes": total_bytes, "total_fmt": fmt_bytes(total_bytes)}


def _compact_git_diffs(conn, exp_ids: list) -> tuple:
    """Strip git_diff from experiments, returns (freed_bytes, count)."""
    from exptrack.core.db import diff_b_path, is_diff_sentinel, resolve_git_diff
    freed = 0
    count = 0
    for eid in exp_ids:
        row = conn.execute(
            "SELECT id, git_diff, git_commit FROM experiments WHERE id=?", (eid,)
        ).fetchone()
        if not row:
            continue
        raw_diff = row["git_diff"]
        if not raw_diff or is_diff_sentinel(raw_diff):
            continue
        full_diff = resolve_git_diff(conn, raw_diff)
        if is_diff_sentinel(full_diff):
            continue  # nothing to strip — a dangling ref has no body to compact
        diff_len = len(full_diff)
        commit = row["git_commit"] or "unknown"
        files = [diff_b_path(line.split()[-1])
                 for line in full_diff.splitlines()
                 if line.startswith("diff --git ") and len(line.split()) >= 4]
        file_info = f"{len(files)} file(s): {', '.join(files[:5])}" if files else "no files"
        if len(files) > 5:
            file_info += f" +{len(files) - 5} more"
        summary = f"[compacted — {fmt_bytes(diff_len)} stripped — {file_info} — see git commit {commit}]"
        conn.execute("UPDATE experiments SET git_diff = ? WHERE id = ?", (summary, row["id"]))
        # Delete the blob from git_diffs only if nothing else still points at it.
        # Session nodes reference these blobs too (a node's diff is stored
        # content-addressed, and materializing a node hands its ref to the new
        # experiment), so checking `experiments` alone would strip the body out
        # from under the session tree that shares it.
        if raw_diff.startswith("[ref:sha256:"):
            diff_hash = raw_diff[12:-1]
            other = conn.execute(
                "SELECT 1 FROM experiments WHERE git_diff=? AND id!=? "
                "UNION ALL "
                "SELECT 1 FROM session_nodes WHERE git_diff=? LIMIT 1",
                (raw_diff, eid, raw_diff),
            ).fetchone()
            if not other:
                conn.execute("DELETE FROM git_diffs WHERE diff_hash=?", (diff_hash,))
        freed += diff_len
        count += 1
    if count:
        conn.commit()
    return freed, count


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
    """NULL out timeline.source_diff for given experiments."""
    if not exp_ids:
        return 0
    placeholders = ",".join("?" * len(exp_ids))
    try:
        size_row = conn.execute(f"""
            SELECT COALESCE(SUM(LENGTH(source_diff)), 0) as sz
            FROM timeline
            WHERE exp_id IN ({placeholders}) AND source_diff IS NOT NULL
        """, exp_ids).fetchone()
        freed = size_row["sz"] if size_row else 0
        if freed:
            conn.execute(f"""
                UPDATE timeline SET source_diff = NULL
                WHERE exp_id IN ({placeholders}) AND source_diff IS NOT NULL
            """, exp_ids)
            conn.commit()
        return freed
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
