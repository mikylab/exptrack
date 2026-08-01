"""
exptrack/core/storage.py — Storage measurement and metric reclamation.

Two jobs that belong together, because the second is only ever reached through
the first: *measuring* where the database's bytes actually went (per table, per
metric key, per experiment), and *reclaiming* the one category that grows
without bound — metric points logged inside a training loop.

Measurement is deliberately split into "true" and "estimated" numbers and the
callers are expected to say which is which. ``table_byte_sizes`` reads SQLite's
``dbstat`` virtual table, so its per-table figures are exact — they count real
pages, including each table's indexes and its free space. Everything below the
table level (a single metric key, a single experiment) has no page-level
identity at all, so those are apportioned from the true table total by row
count. That is the honest shape of the data: SQLite can tell you the ``metrics``
table is 41 MB, and it cannot tell you which 41 MB belongs to ``train/loss``.
"""
from __future__ import annotations

import sqlite3

from .db import REF_PREFIX, is_diff_sentinel
from .utils import debug_log, safe_call

# Fallback bytes-per-row for the estimate when dbstat is unavailable. Measured
# against real databases: a metrics row is ~48 bytes of payload plus its share
# of the (exp_id, key) index. Only used to keep the report meaningful on a
# SQLite built without SQLITE_ENABLE_DBSTAT_VTAB.
_FALLBACK_METRIC_ROW_BYTES = 90


def dbstat_available(conn: sqlite3.Connection) -> bool:
    """Whether this SQLite build exposes the ``dbstat`` virtual table."""
    try:
        conn.execute("SELECT name FROM dbstat LIMIT 1").fetchone()
        return True
    except Exception:
        return False


def table_byte_sizes(conn: sqlite3.Connection) -> dict:
    """Exact on-disk bytes per table, including each table's indexes.

    Returns ``{}`` when ``dbstat`` is unavailable so callers can fall back to
    row-count estimates rather than reporting a confident zero.

    Note this walks every page of the database, so it is a whole-file scan —
    fine for an explicitly-invoked storage report, not for a hot path.
    """
    if not dbstat_available(conn):
        return {}
    try:
        rows = conn.execute("""
            SELECT COALESCE(m.tbl_name, d.name) AS owner, SUM(d.pgsize) AS bytes
            FROM dbstat d
            LEFT JOIN sqlite_master m ON m.name = d.name
            GROUP BY owner
        """).fetchall()
    except Exception:
        return {}
    return {r["owner"]: int(r["bytes"] or 0) for r in rows}


def _row_bytes(conn: sqlite3.Connection, table_bytes: dict, table: str,
               total_rows: int | None = None) -> float:
    """Average bytes one row of *table* occupies, indexes and slack included.

    ``metrics`` falls back to a measured constant when dbstat is unavailable so
    the headline figure stays meaningful; other tables degrade to 0, since their
    payload is measured directly by string length instead.
    """
    if total_rows is None:
        total_rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if total_rows <= 0:
        return 0.0
    measured = table_bytes.get(table)
    if measured:
        return measured / total_rows
    return float(_FALLBACK_METRIC_ROW_BYTES) if table == "metrics" else 0.0


def metric_storage(conn: sqlite3.Connection, top: int = 12,
                   table_bytes: dict | None = None) -> dict:
    """Where the ``metrics`` table's bytes went, broken down by key.

    ``bytes`` on the whole table is exact when dbstat is available; the
    per-key figures are that total apportioned by point count, which is
    accurate because every metrics row is the same fixed-width shape apart
    from its key and source strings.
    """
    table_bytes = table_byte_sizes(conn) if table_bytes is None else table_bytes
    total_rows = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    per_row = _row_bytes(conn, table_bytes, "metrics", total_rows)
    total_bytes = table_bytes.get("metrics") or int(per_row * total_rows)

    # Two stacked GROUP BYs, not a window function. `COUNT(*) OVER (PARTITION
    # BY key, exp_id)` materialises one intermediate row per metric row before
    # the outer aggregate; the nested form is one aggregate pass over the
    # (exp_id, key) index and measured ~20x faster on a 2M-row table (2.96s →
    # 0.15s), for identical output.
    rows = conn.execute("""
        SELECT key,
               SUM(n)   AS points,
               COUNT(*) AS experiments,
               MAX(n)   AS max_per_exp
        FROM (SELECT key, exp_id, COUNT(*) AS n FROM metrics GROUP BY key, exp_id)
        GROUP BY key
        ORDER BY points DESC
    """).fetchall()

    keys = [{
        "key": r["key"],
        "points": r["points"],
        "experiments": r["experiments"],
        "max_per_exp": r["max_per_exp"],
        "bytes": int(r["points"] * per_row),
    } for r in rows]

    return {
        "bytes": int(total_bytes),
        "rows": total_rows,
        "bytes_per_row": per_row,
        "exact": bool(table_bytes.get("metrics")),
        "key_count": len(keys),
        "keys": keys[:top],
        "keys_omitted": max(0, len(keys) - top),
    }


def free_space(conn: sqlite3.Connection) -> dict:
    """Space inside the database file that is free for reuse but not returned.

    Deleting rows in SQLite moves their pages to the file's *free list*; the
    file itself never shrinks until a VACUUM rewrites it. So a permanent delete
    genuinely removes the rows while the file on disk stays exactly the size it
    was — which reads, entirely reasonably, as "the delete didn't work". The
    storage report has to name that space or the breakdown silently fails to
    add up to the file size: delete a run holding 120k metric points and the
    tables account for 8 MB of a 12 MB file, with nothing saying where the
    other 4 MB went.

    Cheap — two pragmas, no page walk — so it is safe to call either side of a
    delete to report what that delete freed.
    """
    try:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
        total = conn.execute("PRAGMA page_count").fetchone()[0]
    except Exception as e:
        debug_log(f"storage: could not read free-page counts: {e}")
        return {"bytes": 0, "pages": 0, "total_pages": 0, "pct": 0.0}
    return {
        "bytes": int(pages) * int(page_size),
        "pages": int(pages),
        "total_pages": int(total),
        "pct": (pages / total * 100.0) if total else 0.0,
    }


def orphan_storage(conn: sqlite3.Connection, table_bytes: dict | None = None) -> dict:
    """Rows that reference an experiment which no longer exists, and their cost.

    Today's delete removes a run's children first and the schema's foreign keys
    would refuse it otherwise, so exptrack does not create these. They come from
    *history*: a database written by a version that deleted the experiment row
    only, a hand-edited or externally-scripted DB, a process killed mid-delete.
    The rows are invisible in every list (nothing joins to a missing run) while
    still occupying the file — which is exactly the "I deleted runs but the
    space is still there" case, one layer down.

    ``count_orphans`` has always been able to find them and the CLI has always
    swept them on exit; what was missing was anyone *saying so*. The storage
    report's warning fired only when the database held zero experiments, so a
    project with 5 runs and 20k orphaned metric rows reported perfect health.

    Cost is the same apportionment ``metric_storage`` uses, and is labelled
    estimated wherever it surfaces. Not cheap (anti-join counts over
    params/metrics/timeline, plus the snapshot scan) — report-time only, never
    a request hot path.
    """
    from .db import count_orphans

    table_bytes = table_byte_sizes(conn) if table_bytes is None else table_bytes
    counts = safe_call(count_orphans, conn, default={},
                       context="storage: orphan counts") or {}
    per_table = {}
    total = 0
    for table, n in counts.items():
        row_bytes = _row_bytes(conn, table_bytes, table)
        b = int(n * row_bytes)
        per_table[table] = {"rows": n, "bytes": b}
        total += b
    return {
        "counts": counts,
        "tables": per_table,
        "rows": sum(counts.values()),
        "bytes": total,
        "exact": bool(table_bytes),
    }


def trash_storage(conn: sqlite3.Connection, table_bytes: dict | None = None) -> dict:
    """What the Trash is costing — in the database *and* on disk.

    Soft delete is the default everywhere (a trashed run keeps its rows so
    Restore is lossless, and its output files are deliberately left in place),
    so the Trash is the one place in exptrack where storage accumulates with
    nothing in the UI saying how much. The storage report answered "which run
    is big" but never "how much would emptying the Trash give me back", which
    is usually the cheapest reclaim available and the only one that costs
    nothing you still want.

    Three separate numbers, because they are reclaimed by different actions and
    only the first two come back from a permanent delete:

    - ``db_bytes`` — estimated database bytes held by trashed experiments and
      trashed session nodes (apportioned exactly as ``experiment_storage``
      does; freed pages go to the free list, so a VACUUM is what returns them
      to the filesystem).
    - ``output_bytes`` — files on disk under the output directories those
      trashed runs own. Only removed if the permanent delete is asked to take
      files, and only for directories no *surviving* run also claims.
    - ``local_bytes`` — the ``.exptrack/trash/`` fallback directory, which
      holds files exptrack could not hand to the OS Trash. Nothing but the user
      deletes these.

    Best-effort throughout: this is a report, and a missing table or an
    unreadable directory degrades to zero rather than killing the whole thing.
    """
    table_bytes = table_byte_sizes(conn) if table_bytes is None else table_bytes
    out = {
        "experiments": 0, "exp_db_bytes": 0,
        "nodes": 0, "sessions": 0, "node_db_bytes": 0,
        "db_bytes": 0,
        "output_bytes": 0, "output_files": 0, "output_dirs": 0,
        "local_bytes": 0, "local_files": 0,
        "exact": bool(table_bytes),
    }
    runs = safe_call(experiment_storage, conn, 0, table_bytes,
                     default=[], context="storage: trashed experiment bytes")
    trashed = [r for r in runs if r.get("trashed")]
    out["experiments"] = len(trashed)
    out["exp_db_bytes"] = sum(r["db_bytes"] for r in trashed)

    out.update(safe_call(_trashed_session_bytes, conn, default={},
                         context="storage: trashed session bytes") or {})
    out["db_bytes"] = out["exp_db_bytes"] + out["node_db_bytes"]
    out.update(safe_call(_trashed_output_bytes, conn, trashed, default={},
                         context="storage: trashed output files") or {})
    out.update(safe_call(_local_trash_bytes, default={},
                         context="storage: local trash directory") or {})
    return out


def _trashed_session_bytes(conn: sqlite3.Connection) -> dict:
    """Rows held by trashed session nodes, and by nodes of trashed sessions.

    A trashed *session* doesn't mark its nodes, so both have to be counted —
    and a node under a trashed session must not be counted twice when it is
    itself trashed.
    """
    row = conn.execute("""
        SELECT COUNT(*) AS n,
               COALESCE(SUM(LENGTH(COALESCE(n.cell_source, '')) +
                            LENGTH(COALESCE(n.cell_outputs, '')) +
                            LENGTH(COALESCE(n.setup_source, '')) +
                            LENGTH(COALESCE(n.setup_outputs, '')) +
                            LENGTH(COALESCE(n.note, ''))), 0) AS text_bytes
        FROM session_nodes n
        LEFT JOIN sessions s ON s.id = n.session_id
        WHERE n.deleted_at IS NOT NULL OR s.deleted_at IS NOT NULL
    """).fetchone()
    sessions = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE deleted_at IS NOT NULL").fetchone()[0]

    # A node's diff is a shared blob like an experiment's, so charge it the
    # same per-holder share rather than the whole body.
    diff_bytes = _shared_diff_bytes(conn)
    diff_total = 0
    for r in conn.execute("""
            SELECT n.git_diff AS d FROM session_nodes n
            LEFT JOIN sessions s ON s.id = n.session_id
            WHERE (n.deleted_at IS NOT NULL OR s.deleted_at IS NOT NULL)
              AND n.git_diff IS NOT NULL AND n.git_diff != ''"""):
        diff_total += diff_bytes.get(r["d"], 0)
    return {"nodes": row["n"], "sessions": sessions,
            "node_db_bytes": int(row["text_bytes"]) + diff_total}


def _trashed_output_bytes(conn: sqlite3.Connection, trashed: list) -> dict:
    """Disk usage of the output directories owned by trashed runs.

    Ownership goes through ``output_dirs_owned_by`` — the same rule the
    permanent delete uses — so this can never advertise space that deleting
    the run would leave alone because a surviving run also claims it.
    """
    from .db import output_dirs_owned_by

    if not trashed:
        return {}
    ids = ",".join("?" * len(trashed))
    rows = conn.execute(
        f"SELECT id, name, output_dir FROM experiments WHERE id IN ({ids})",
        [r["id"] for r in trashed]).fetchall()
    seen: set[str] = set()
    total = files = dirs = 0
    for r in rows:
        for d in output_dirs_owned_by(conn, r["id"], r["name"], r["output_dir"]):
            key = str(d)
            if key in seen or not d.exists():
                continue
            seen.add(key)
            dirs += 1
            for fp in d.rglob("*"):
                if fp.is_file():
                    total += fp.stat().st_size
                    files += 1
    return {"output_bytes": total, "output_files": files, "output_dirs": dirs}


def _local_trash_bytes() -> dict:
    """Size of the ``.exptrack/trash/`` OS-trash fallback directory."""
    from .db import local_trash_dir

    d = local_trash_dir()
    if not d.is_dir():
        return {}
    total = files = 0
    for fp in d.rglob("*"):
        if fp.is_file():
            total += fp.stat().st_size
            files += 1
    return {"local_bytes": total, "local_files": files}


def experiment_storage(conn: sqlite3.Connection, limit: int = 10,
                       table_bytes: dict | None = None,
                       include_trashed: bool = True) -> list:
    """Estimated database bytes per experiment, largest first.

    Every figure here is an *estimate*: rows have no page-level identity, so
    each table's true byte total is apportioned across its rows. Blob columns
    (``timeline.value``, ``params.value``) are measured by string length
    instead, which is exact for the payload and ignores per-row overhead —
    the two together are close enough to rank runs, which is the whole point.

    Best-effort like the rest of the storage report: an older database missing
    a table degrades to an empty ranking rather than killing the report.
    """
    try:
        return _experiment_storage(conn, limit, table_bytes, include_trashed)
    except Exception as e:
        debug_log(f"storage: could not rank experiments by size: {e}")
        return []


def _experiment_storage(conn: sqlite3.Connection, limit: int,
                        table_bytes: dict | None, include_trashed: bool) -> list:
    table_bytes = table_byte_sizes(conn) if table_bytes is None else table_bytes

    counts = {t: _row_bytes(conn, table_bytes, t)
              for t in ("metrics", "params", "timeline", "artifacts")}
    diff_bytes = _shared_diff_bytes(conn)

    # One aggregate pass per child table joined on exp_id, rather than six
    # correlated subqueries evaluated per experiment row. The two SUM(LENGTH(…))
    # ones cannot be index-only (they read the payload), so per-row evaluation
    # scaled with blob size, not just row count.
    where = "WHERE e.deleted_at IS NULL" if not include_trashed else ""
    rows = conn.execute(f"""
        SELECT e.id, e.name, e.deleted_at, e.git_diff,
               COALESCE(m.n, 0) AS n_metrics,
               COALESCE(p.n, 0) AS n_params,
               COALESCE(t.n, 0) AS n_timeline,
               COALESCE(a.n, 0) AS n_artifacts,
               COALESCE(p.text_bytes, 0) AS params_text,
               COALESCE(t.text_bytes, 0) AS timeline_text
        FROM experiments e
        LEFT JOIN (SELECT exp_id, COUNT(*) n FROM metrics GROUP BY exp_id) m
               ON m.exp_id = e.id
        LEFT JOIN (SELECT exp_id, COUNT(*) n,
                          SUM(LENGTH(key) + LENGTH(value)) text_bytes
                     FROM params GROUP BY exp_id) p ON p.exp_id = e.id
        LEFT JOIN (SELECT exp_id, COUNT(*) n,
                          SUM(LENGTH(COALESCE(value, '')) +
                              LENGTH(COALESCE(source_diff, ''))) text_bytes
                     FROM timeline GROUP BY exp_id) t ON t.exp_id = e.id
        LEFT JOIN (SELECT exp_id, COUNT(*) n FROM artifacts GROUP BY exp_id) a
               ON a.exp_id = e.id
        {where}
    """).fetchall()

    out = []
    for r in rows:
        metrics_b = int(r["n_metrics"] * counts["metrics"])
        params_b = int(r["params_text"] + r["n_params"] * counts["params"])
        timeline_b = int(r["timeline_text"] + r["n_timeline"] * counts["timeline"])
        artifacts_b = int(r["n_artifacts"] * counts["artifacts"])
        diff_b = diff_bytes.get(r["git_diff"], 0) if r["git_diff"] else 0
        out.append({
            "id": r["id"],
            "name": r["name"],
            "trashed": bool(r["deleted_at"]),
            "n_metrics": r["n_metrics"],
            "n_artifacts": r["n_artifacts"],
            "metrics_bytes": metrics_b,
            "params_bytes": params_b,
            "timeline_bytes": timeline_b,
            "artifacts_bytes": artifacts_b,
            "diff_bytes": diff_b,
            "db_bytes": metrics_b + params_b + timeline_b + artifacts_b + diff_b,
        })
    out.sort(key=lambda e: e["db_bytes"], reverse=True)
    return out[:limit] if limit else out


def _shared_diff_bytes(conn: sqlite3.Connection) -> dict:
    """Map every stored ``git_diff`` column value to the bytes it costs its holder.

    A ``[ref:sha256:…]`` pointer means the body lives in ``git_diffs`` and may be
    shared with sibling runs and session nodes, so charging its full size to
    every holder would over-count the database several times over — the body is
    split evenly across everything referencing it.

    Built in three queries for the whole database rather than three per
    experiment. Per-experiment it was quadratic: the body lookup compared
    ``'[ref:sha256:' || hash || ']'`` to the marker, a computed expression that
    defeats the ``git_diffs`` primary key, and neither holder count can use an
    index — so every run full-scanned ``git_diffs``, ``experiments`` and
    ``session_nodes``.
    """
    out: dict = {}
    try:
        holders: dict = {}
        for table in ("experiments", "session_nodes"):
            for r in conn.execute(
                    f"SELECT git_diff AS d, COUNT(*) AS n FROM {table} "
                    f"WHERE git_diff IS NOT NULL AND git_diff != '' GROUP BY git_diff"):
                holders[r["d"]] = holders.get(r["d"], 0) + r["n"]

        for marker in holders:
            if is_diff_sentinel(marker):
                out[marker] = 0
            elif not marker.startswith(REF_PREFIX):
                out[marker] = len(marker)      # inline (legacy) body

        for r in conn.execute(
                "SELECT diff_hash, LENGTH(diff_text) AS sz FROM git_diffs"):
            marker = f"{REF_PREFIX}{r['diff_hash']}]"
            if marker in holders:
                out[marker] = int((r["sz"] or 0) / max(1, holders[marker]))
    except Exception as e:
        debug_log(f"storage: could not size shared git diffs: {e}")
    return out


# ── Metric pruning ────────────────────────────────────────────────────────────
#
# `metric_keep_every` and `thin_every` only ever applied at write time, so a run
# already recorded at every iteration had no way back — the points were simply
# permanent. These two functions are that way back. Both take the same selection
# so a preview provably describes the delete that follows it.

def _prune_target_ids(conn: sqlite3.Connection, exp_ids: list | None,
                      keys: list | None, keep_every: int, max_points: int,
                      protect_extremes: bool) -> list:
    """Row ids the prune would delete, for one (exp_id, key) series at a time.

    Selection runs per series rather than across the whole table because
    "every Nth point" is only meaningful within a single curve — striding
    across the interleaved rows of five metrics would thin each one by a
    different, arbitrary amount.
    """
    where, args = ["1=1"], []
    if exp_ids:
        where.append(f"exp_id IN ({','.join('?' * len(exp_ids))})")
        args += list(exp_ids)
    if keys:
        where.append(f"key IN ({','.join('?' * len(keys))})")
        args += list(keys)
    clause = " AND ".join(where)

    series = conn.execute(
        f"SELECT exp_id, key, COUNT(*) AS n FROM metrics WHERE {clause} "
        f"GROUP BY exp_id, key", args).fetchall()

    doomed = []
    for s in series:
        n = s["n"]
        if n <= 2:
            continue  # first and last are always kept; nothing to thin
        stride = keep_every
        if max_points and n > max_points:
            # Round up so the survivors land at or under the requested cap.
            stride = max(stride, -(-n // max_points))
        if stride <= 1:
            continue

        rows = conn.execute(
            "SELECT id, value FROM metrics WHERE exp_id=? AND key=? "
            "ORDER BY COALESCE(step, id), id", (s["exp_id"], s["key"])).fetchall()
        if not rows:
            continue

        keep = {rows[0]["id"], rows[-1]["id"]}
        keep.update(r["id"] for i, r in enumerate(rows) if i % stride == 0)
        if protect_extremes:
            # The peak and trough are the two points a chart is read for; a
            # blind stride will eventually land either side of them and quietly
            # flatten the curve it was supposed to preserve.
            vals = [r for r in rows if r["value"] is not None]
            if vals:
                keep.add(min(vals, key=lambda r: r["value"])["id"])
                keep.add(max(vals, key=lambda r: r["value"])["id"])
        doomed.extend(r["id"] for r in rows if r["id"] not in keep)
    return doomed


def _prune_report(conn: sqlite3.Connection, doomed: list,
                  table_bytes: dict | None = None) -> dict:
    """Shape the point count into the report both prune entry points return.

    Takes ``table_bytes`` for the same reason its siblings do: computing it is a
    whole-file page scan, and a prune otherwise paid for one in the preview and
    another in the delete.
    """
    table_bytes = table_byte_sizes(conn) if table_bytes is None else table_bytes
    total_rows = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    per_row = _row_bytes(conn, table_bytes, "metrics", total_rows)
    return {
        "points": len(doomed),
        "total_points": total_rows,
        "freed": int(len(doomed) * per_row),
        "remaining": total_rows - len(doomed),
    }


def preview_metric_prune(conn: sqlite3.Connection, exp_ids: list | None = None,
                         keys: list | None = None, keep_every: int = 1,
                         max_points: int = 0, protect_extremes: bool = True,
                         table_bytes: dict | None = None) -> dict:
    """What ``prune_metrics`` would remove, without removing it.

    The selected row ids come back on ``_ids`` so a caller that goes on to
    prune can hand them straight to ``prune_metrics(doomed=…)`` — the preview
    then *is* the delete, rather than a second run of the same selection that
    is merely expected to agree with it.
    """
    doomed = _prune_target_ids(conn, exp_ids, keys, keep_every, max_points,
                              protect_extremes)
    report = _prune_report(conn, doomed, table_bytes)
    report["_ids"] = doomed
    return report


def prune_metrics(conn: sqlite3.Connection, exp_ids: list | None = None,
                  keys: list | None = None, keep_every: int = 1,
                  max_points: int = 0, protect_extremes: bool = True,
                  table_bytes: dict | None = None,
                  doomed: list | None = None) -> dict:
    """Permanently thin stored metric points.

    The first point, the last point and (unless disabled) the minimum and
    maximum of every series survive, so a pruned chart keeps its endpoints and
    its extremes — the run's final value read off the chart stays exact.

    Pass ``doomed`` (from ``preview_metric_prune``'s ``_ids``) to delete exactly
    the set that was previewed and skip re-running the selection.

    Deleting rows returns their pages to the database's free list rather than
    to the filesystem; run ``exptrack clean --vacuum`` to hand them back.
    """
    if doomed is None:
        doomed = _prune_target_ids(conn, exp_ids, keys, keep_every, max_points,
                                   protect_extremes)
    # Measured before the delete: afterwards the rows are gone, so the
    # bytes-per-row figure would be apportioned over the survivors and the
    # report would understate what it just freed.
    report = _prune_report(conn, doomed, table_bytes)
    for i in range(0, len(doomed), 500):
        chunk = doomed[i:i + 500]
        conn.execute(f"DELETE FROM metrics WHERE id IN ({','.join('?' * len(chunk))})",
                     chunk)
    conn.commit()
    report["deleted"] = len(doomed)
    return report
