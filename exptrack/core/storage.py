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
    from .db import dir_file_stats, output_dirs_owned_by

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
            n_files, n_bytes, _ = dir_file_stats(d)
            files += n_files
            total += n_bytes
    return {"output_bytes": total, "output_files": files, "output_dirs": dirs}


def _local_trash_bytes() -> dict:
    """Size of the ``.exptrack/trash/`` OS-trash fallback directory."""
    from .db import dir_file_stats, local_trash_dir

    d = local_trash_dir()
    if not d.is_dir():
        return {}
    files, total, _ = dir_file_stats(d)
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


# ── Code-change summary compaction ──────────────────────────────────────────
#
# `_code_changes` / `_code_change/cell_N` are *derived* text: a per-run copy of
# the changed lines. The run's full source already lives in `code_snapshots`,
# content-addressed and deduped by hash — so N runs of an unchanged file store
# one copy of the source while each still pays for its own summary. Measured on
# a real pair of runs the summaries cost ~2x the snapshots while holding strictly
# less information, which is what makes this the cheapest thing to reclaim.
#
# It is only cheap where a snapshot exists. For a run with no snapshot — a
# notebook-only run, or one recorded before snapshot capture — the summary IS
# the only record of what changed, so compacting it is real, unrecoverable data
# loss. `_runs_with_snapshot` is that guard and every path here goes through it.

_CODE_CHANGE_KEYS_SQL = "(key = '_code_changes' OR key LIKE '\\_code\\_change/%' ESCAPE '\\')"

# Param values are JSON-encoded, so a stored marker reads `"[compacted …]"` —
# leading quote and all. Matching only the bare form silently re-compacted an
# already-compacted row on every run, which broke idempotence and let the
# reported "freed" bytes count the marker itself over and over.
_NOT_ALREADY_COMPACT_SQL = (
    "value NOT LIKE '[compacted%' AND value NOT LIKE '\"[compacted%'"
)


def _snapshot_refs(conn, exp_ids: list | None = None) -> dict:
    """{exp_id: set(hash)} from `_code_snapshot` params, optionally filtered.

    The one hash-token scan behind `_runs_with_snapshot` and
    `sole_source_holders` — like `db._referenced_snapshot_hashes` it is
    deliberately generous (regex over the raw value, tolerating all three
    encodings the param has had), and keeping the scan in one place keeps the
    compaction guard and the sole-holder warning superset-compatible.
    """
    from .db import _SNAPSHOT_HASH_RE
    sql = ("SELECT exp_id, value FROM params WHERE key='_code_snapshot' "
           "AND value IS NOT NULL")
    args: list = []
    if exp_ids is not None:
        if not exp_ids:
            return {}
        sql += f" AND exp_id IN ({','.join('?' * len(exp_ids))})"
        args = list(exp_ids)
    refs: dict = {}
    for exp_id, value in conn.execute(sql, args):
        hashes = set(_SNAPSHOT_HASH_RE.findall(value))
        if hashes:
            refs.setdefault(exp_id, set()).update(hashes)
    return refs


def _runs_with_snapshot(conn, exp_ids: list) -> set:
    """Of `exp_ids`, those whose source is recoverable from `code_snapshots`.

    A run qualifies only when its `_code_snapshot` param names a hash whose row
    is actually still present — a dangling reference is not a backstop.
    """
    if not exp_ids:
        return set()
    stored = {h for (h,) in conn.execute("SELECT hash FROM code_snapshots")}
    if not stored:
        return set()
    return {exp_id for exp_id, hashes in _snapshot_refs(conn, exp_ids).items()
            if hashes & stored}


def _code_change_selection(conn, exp_ids: list) -> tuple:
    """(stats, eligible) — the one selection preview and compact both use.

    Shared so the preview provably describes the write that follows it (the
    same rule `prune_metrics` follows): two independent computations can only
    *happen* to agree, and the eligibility scan is the expensive half.

    `eligible` is "recoverable from a snapshot", which is not the same as "has a
    summary to strip": the runs actually written are those holding an
    un-compacted summary *and* backed by a snapshot. `stats["run_ids"]` names
    exactly that set, so a caller reporting which runs would change reads it
    from here rather than re-deriving it — the CLI dry-run did the latter and
    announced every run it had merely considered.
    """
    eligible = _runs_with_snapshot(conn, exp_ids)
    # "Skipped" means a summary exists but its snapshot backstop doesn't — a
    # run holding no summary at all has nothing to skip, and naming it reads
    # as data being withheld.
    unbacked = [e for e in exp_ids if e not in eligible]
    skipped = []
    if unbacked:
        marks = ",".join("?" * len(unbacked))
        has_rows = {r[0] for r in conn.execute(
            f"SELECT DISTINCT exp_id FROM params WHERE exp_id IN ({marks}) "
            f"AND {_CODE_CHANGE_KEYS_SQL} AND {_NOT_ALREADY_COMPACT_SQL}",
            unbacked)}
        skipped = [e for e in unbacked if e in has_rows]
    if not eligible:
        return ({"runs": 0, "rows": 0, "bytes": 0, "run_ids": [],
                 "skipped_no_snapshot": skipped}, eligible)
    marks = ",".join("?" * len(eligible))
    row = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(LENGTH(value)),0), COUNT(DISTINCT exp_id) "
        f"FROM params WHERE exp_id IN ({marks}) AND {_CODE_CHANGE_KEYS_SQL} "
        f"AND {_NOT_ALREADY_COMPACT_SQL}", list(eligible)
    ).fetchone()
    run_ids = [r[0] for r in conn.execute(
        f"SELECT DISTINCT exp_id FROM params WHERE exp_id IN ({marks}) "
        f"AND {_CODE_CHANGE_KEYS_SQL} AND {_NOT_ALREADY_COMPACT_SQL}",
        list(eligible))]
    return ({"runs": row[2], "rows": row[0], "bytes": row[1],
             "run_ids": run_ids, "skipped_no_snapshot": skipped}, eligible)


def preview_code_change_compact(conn, exp_ids: list) -> dict:
    """What `compact_code_changes` would reclaim — same selection, no delete."""
    return _code_change_selection(conn, exp_ids)[0]


def compact_code_changes(conn, exp_ids: list) -> dict:
    """Replace stored code-change summaries with a `[compacted…]` marker.

    Returns the same shape as the preview, so a dry-run provably describes the
    write that follows it. Runs whose source is not recoverable from a snapshot
    are skipped and reported, never compacted.
    """
    stats, eligible = _code_change_selection(conn, exp_ids)
    if not eligible or not stats["rows"]:
        return stats
    marks = ",".join("?" * len(eligible))
    # The marker keeps the panel honest: it says the summary was reclaimed,
    # rather than rendering as "nothing changed" — the exact failure the
    # truncation fix exists to prevent. The byte count is stamped per row in
    # SQL (LENGTH(value), the same basis the preview sums) — a single
    # aggregate figure stamped into every row named the wrong number on each.
    conn.execute(
        f"UPDATE params SET value = "
        f"'\"[compacted — ' || LENGTH(value) || "
        f"' B stripped; full source in snapshot]\"' "
        f"WHERE exp_id IN ({marks}) "
        f"AND {_CODE_CHANGE_KEYS_SQL} AND {_NOT_ALREADY_COMPACT_SQL}",
        list(eligible),
    )
    conn.commit()
    return stats


# `timeline.source_diff` is a bare column (not JSON-encoded like a param
# value), so only the unquoted marker form can appear here.
_TIMELINE_NOT_COMPACT_SQL = "source_diff NOT LIKE '[compacted%'"


def _timeline_diff_selection(conn, exp_ids: list) -> tuple:
    """(stats, where-params) — the one selection preview and compact share.

    Same rule as `_code_change_selection`: the dry-run must provably describe
    the write that follows it, and both had to skip already-marked rows or a
    second pass counts the marker itself as reclaimable and then destroys the
    evidence it stands for.
    """
    if not exp_ids:
        return ({"events": 0, "bytes": 0}, [])
    marks = ",".join("?" * len(exp_ids))
    where = (f"exp_id IN ({marks}) AND source_diff IS NOT NULL "
             f"AND {_TIMELINE_NOT_COMPACT_SQL}")
    row = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(LENGTH(source_diff)), 0) "
        f"FROM timeline WHERE {where}", exp_ids).fetchone()
    return ({"events": row[0], "bytes": row[1]}, where)


def preview_timeline_diff_compact(conn, exp_ids: list) -> dict:
    """What `compact_timeline_diffs` would reclaim — same selection, no write."""
    return _timeline_diff_selection(conn, exp_ids)[0]


def compact_timeline_diffs(conn, exp_ids: list) -> dict:
    """Replace `timeline.source_diff` with a `[compacted…]` marker.

    Returns the preview's shape. This used to NULL the column, which left no
    evidence the diff had ever existed — and "no diff stored" is the *normal*
    state for a script run against a clean tree, so the status check read every
    such run as compacted and the detail header claimed a compaction that never
    happened. A marker makes the claim provable, and states each row's own byte
    count (a single aggregate figure stamped into every row names the wrong
    number on each).
    """
    stats, where = _timeline_diff_selection(conn, exp_ids)
    if not stats["bytes"]:
        return stats
    conn.execute(
        f"UPDATE timeline SET source_diff = "
        f"'[compacted — ' || LENGTH(source_diff) || ' B stripped]' "
        f"WHERE {where}", exp_ids)
    conn.commit()
    return stats


# ── git-diff compaction ───────────────────────────────────────────────────
# Same rule as the two selections above — one implementation shared by the
# preview and the write — for the same reason it was needed there, plus one
# specific to this mode. A deduplicated diff stores a ~45-byte
# `[ref:sha256:…]` pointer in the column and its body once in `git_diffs`,
# shared by every run with the same working tree. So the UPDATE alone frees the
# pointer and nothing else, and a byte figure is wrong in two opposite ways:
# summing the *columns* under-reports a thousandfold (the CLI dry-run promised
# ~1 KB where 1.6 MB would go), while summing the *bodies* those pointers
# address over-reports by however many runs share each one (the dashboard
# reported 1,030,170 bytes freed for 30 runs sharing one 34 KB body — 30x).
# N runs sharing one body reclaim one body, and a body still held by a run
# outside the selection, or by a session node, is not reclaimed at all.


def _diff_files(diff_text: str) -> list:
    """`b/`-side paths named by a unified diff's `diff --git` headers."""
    from .db import diff_b_path
    out = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                out.append(diff_b_path(parts[3]))
    return out


def _compacted_diff_summary(diff_len: int, files: list, commit: str) -> str:
    """The `[compacted…]` marker left in place of a stripped diff."""
    from .utils import fmt_bytes
    info = f"{len(files)} file(s): {', '.join(files[:5])}" if files else "no files"
    if len(files) > 5:
        info += f" +{len(files) - 5} more"
    return (f"[compacted — {fmt_bytes(diff_len)} stripped — {info} "
            f"— see git commit {commit}]")


def _doomed_blob_bytes(conn, hashes: set, exp_ids: list) -> int:
    """Bytes of `git_diffs` bodies left unreferenced once `exp_ids` let go.

    Simulated rather than measured after the fact, so the preview and the write
    quote the same number: a hash still pointed at by a run outside the
    selection, or by any session node, survives and is not counted.

    This is deliberately a hand-written twin of `db._GIT_DIFFS_ORPHAN_COND`
    (the condition `_sweep_blobs` deletes on) rather than a use of it: the
    constant is evaluated against the database as it stands, and what is wanted
    here is the state *after* `exp_ids` let go, which no current-state
    condition can express. The two must stay in step — a third table that ever
    references `git_diffs` has to be added in both places.
    """
    if not hashes:
        return 0
    marks = ",".join("?" * len(exp_ids)) if exp_ids else "''"
    cut = len(REF_PREFIX) + 1
    try:
        held = {r[0] for r in conn.execute(
            f"SELECT SUBSTR(git_diff, {cut}, LENGTH(git_diff) - {cut}) "
            f"FROM experiments WHERE git_diff LIKE '{REF_PREFIX}%' "
            f"AND id NOT IN ({marks})", list(exp_ids))}
        held |= {r[0] for r in conn.execute(
            f"SELECT SUBSTR(git_diff, {cut}, LENGTH(git_diff) - {cut}) "
            f"FROM session_nodes WHERE git_diff LIKE '{REF_PREFIX}%'")}
        doomed = [h for h in hashes if h not in held]
        if not doomed:
            return 0
        row = conn.execute(
            f"SELECT COALESCE(SUM(LENGTH(diff_text)), 0) FROM git_diffs "
            f"WHERE diff_hash IN ({','.join('?' * len(doomed))})", doomed).fetchone()
        return row[0] if row else 0
    except sqlite3.Error as e:
        debug_log(f"doomed-blob measurement failed: {e}")
        return 0


def _git_diff_selection(conn, exp_ids: list) -> tuple:
    """(stats, targets) — the one selection preview and compact both use.

    `targets` is one record per run to be written (`id`, `raw`, `summary`,
    `bytes`, `files`) and `stats["details"]` *is* that list, not a parallel
    copy of it: the write needs the first three fields and callers render the
    last two, and building two lists in lockstep from one loop is two things to
    keep in step for no gain.
    """
    stats = {"runs": 0, "bytes": 0, "run_ids": [], "details": []}
    if not exp_ids:
        return stats, []
    from .db import resolve_git_diff
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT id, git_diff, git_commit FROM experiments "
        f"WHERE id IN ({','.join('?' * len(exp_ids))})", list(exp_ids))}
    targets, inline, hashes, bodies = [], 0, set(), {}
    for eid in exp_ids:
        row = rows.get(eid)
        if not row or not row["git_diff"] or is_diff_sentinel(row["git_diff"]):
            continue
        raw = row["git_diff"]
        # Memoized by pointer, as `_resolve_node_diff` is for session nodes and
        # for the same reason: runs sharing a working tree share one body, which
        # would otherwise be read once per run holding a pointer at it.
        if raw not in bodies:
            resolved = resolve_git_diff(conn, raw)
            bodies[raw] = (resolved, _diff_files(resolved))
        body, files = bodies[raw]
        # A dangling ref has no body to strip, so counting it here would promise
        # bytes the write then skips.
        if is_diff_sentinel(body):
            continue
        targets.append({
            "id": row["id"], "raw": raw, "bytes": len(body), "files": files,
            "summary": _compacted_diff_summary(
                len(body), files, row["git_commit"] or "unknown"),
        })
        if raw.startswith(REF_PREFIX) and raw.endswith("]"):
            hashes.add(raw[len(REF_PREFIX):-1])
        else:
            inline += len(body)          # stored before dedup existed
    ids = [t["id"] for t in targets]
    stats["runs"], stats["run_ids"], stats["details"] = len(targets), ids, targets
    stats["bytes"] = inline + _doomed_blob_bytes(conn, hashes, ids)
    return stats, targets


def preview_git_diff_compact(conn, exp_ids: list) -> dict:
    """What `compact_git_diffs` would reclaim — same selection, no write."""
    return _git_diff_selection(conn, exp_ids)[0]


def compact_git_diffs(conn, exp_ids: list) -> dict:
    """Replace each run's `git_diff` with a `[compacted…]` marker.

    Then sweep the bodies that orphans. Without the sweep, compacting a project
    whose diffs are 90% of the database reclaimed *nothing* while reporting
    success — the pointers went and the bodies stayed, and `clean`'s default
    path never collects them.
    """
    stats, targets = _git_diff_selection(conn, exp_ids)
    stats["blobs_swept"] = 0
    if not targets:
        return stats
    for t in targets:
        conn.execute("UPDATE experiments SET git_diff = ? WHERE id = ?",
                     (t["summary"], t["id"]))
    conn.commit()
    if any(t["raw"].startswith(REF_PREFIX) for t in targets):
        from .db import _sweep_blobs
        # Strictly-unreferenced only, so a body a run outside this selection or
        # a session node still holds is left alone.
        stats["blobs_swept"] = _sweep_blobs(conn).get("git_diffs", 0)
        conn.commit()
    return stats


def source_code_storage(conn) -> dict:
    """Exact bytes held by captured source code, split by what reclaims it.

    Two stores, two different actions: `code_snapshots` (content-addressed
    full source — the durable record, freed only by deleting the last run
    referencing a blob) and the derived code-change summary params (freed by
    `exptrack compact --code-changes`, snapshot-gated). Both figures are exact
    sums of stored text, not dbstat apportionment, so they can be shown
    without an "estimated" label. Already-compacted markers are excluded from
    the summary figure — a marker is bookkeeping, not reclaimable source.
    """
    try:
        snap_count, snap_bytes = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(content)), 0) "
            "FROM code_snapshots").fetchone()
        sum_rows, sum_bytes = conn.execute(
            f"SELECT COUNT(*), COALESCE(SUM(LENGTH(value)), 0) FROM params "
            f"WHERE {_CODE_CHANGE_KEYS_SQL} AND {_NOT_ALREADY_COMPACT_SQL}"
        ).fetchone()
    except Exception:
        snap_count = snap_bytes = sum_rows = sum_bytes = 0
    return {"snapshot_count": snap_count, "snapshot_bytes": snap_bytes,
            "summary_rows": sum_rows, "summary_bytes": sum_bytes,
            "bytes": snap_bytes + sum_bytes}


def sole_source_holder(conn, exp_id: str) -> dict:
    """Is this run the last thing holding its captured source?

    Snapshots are content-addressed and reference-counted, so deleting a run
    that shares its source with another loses nothing — but deleting the *last*
    holder destroys the only copy of that code, and nothing in the delete
    confirm said so. Porting the hash to a surviving run is not the answer:
    that would claim the other run executed code it never ran and corrupt every
    diff drawn from it. The honest move is to warn before the loss and point at
    `exptrack source --out`.

    Returns ``{sole: bool, hashes: [...], lines: int}``. ``sole`` is False when
    the run has no snapshot at all — there is nothing exclusive to lose.
    """
    return sole_source_holders(conn, [exp_id])


def sole_source_holders(conn, exp_ids: list) -> dict:
    """Batch form of `sole_source_holder`: which snapshot blobs die if *all*
    of `exp_ids` are permanently deleted together.

    This is not a loop over the single-run check, and can't be: per-run
    "does anyone else hold this hash?" sees the other runs *in the same
    doomed batch* as holders, so bulk-deleting the only two runs sharing a
    snapshot reports ``sole: False`` for both while the batch destroys the
    last copies. A blob is doomed exactly when every run referencing it is
    in the batch — the same all-holders-inside rule the documented
    ``claimed_output_paths`` bulk-collision hazard is about.

    Best-effort: this backs an *advisory* warning on the delete-confirm
    dialogs, so an internal failure degrades to the not-sole shape (logged
    via ``debug_log``) rather than breaking the dialog — one guard here
    instead of a divergent try/except at every caller.
    """
    empty = {"sole": False, "hashes": [], "lines": 0}
    try:
        ids = set(exp_ids)
        if not ids:
            return empty
        holders: dict = {}
        for exp_id, hashes in _snapshot_refs(conn).items():
            for h in hashes:
                holders.setdefault(h, set()).add(exp_id)
        doomed = [h for h, held_by in holders.items() if held_by <= ids]
        if not doomed:
            return empty

        exclusive, lines = [], 0
        marks = ",".join("?" * len(doomed))
        for h, content in conn.execute(
            f"SELECT hash, content FROM code_snapshots WHERE hash IN ({marks})",
            doomed,
        ):
            # No stored body ⇒ nothing left to lose (already swept/compacted).
            if content:
                exclusive.append(h)
                lines += len(content.splitlines())
        if not exclusive:
            return empty
        return {"sole": True, "hashes": exclusive, "lines": lines}
    except Exception as e:
        from .utils import debug_log
        debug_log(f"sole-source check failed: {e}")
        return empty
