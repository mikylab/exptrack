"""
exptrack/cli/admin_cmds.py — Admin and project management commands

init, run, stale, upgrade, storage, ui
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import config as cfg
from ..core import get_db
from .formatting import C, G, R, W, Y, bold, col, dim


def cmd_init(args):
    cfg.init(project_name=args.name or "", here=args.here)


def cmd_run(args):
    """Hand off to __main__.py logic inline."""
    script = args.script
    sys.argv = ["exptrack", script, *args.script_args]
    from .. import __main__ as m
    m.main()


def cmd_ui(args):
    from ..dashboard.app import main as ui_main
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 7331)
    print(col(f"Launching dashboard -> http://{host}:{port}", C), file=sys.stderr)
    ui_main(host=host, port=port)


def cmd_stale(args):
    """Mark experiments that have been 'running' longer than --hours as timed-out."""
    from datetime import timedelta
    conn = get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    rows = conn.execute("""
        SELECT id, name, created_at FROM experiments
        WHERE status='running' AND created_at < ?
    """, (cutoff.isoformat(),)).fetchall()
    if not rows:
        print(dim(f"No stale experiments (running > {args.hours}h).")); return
    print(f"Marking {len(rows)} stale experiment(s) as timed-out:")
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        duration = (datetime.fromisoformat(now) -
                    datetime.fromisoformat(r["created_at"])).total_seconds()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO params (exp_id, key, value) VALUES (?,?,?)",
                (r["id"], "error", json.dumps(f"timed-out after {args.hours}h"))
            )
            conn.execute("""
                UPDATE experiments SET status='failed', updated_at=?, duration_s=? WHERE id=?
            """, (now, duration, r["id"]))
        print(f"  {col(r['id'][:6], C)}  {r['name'][:50]}")


def cmd_upgrade(args):
    """Run schema migrations and optionally reinstall the package."""
    conn = get_db()

    migrations = []

    cols = {row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()}

    new_cols = {
        "hostname":   "TEXT",
        "python_ver": "TEXT",
        "duration_s": "REAL",
        "notes":      "TEXT",
        "tags":       "TEXT",
        "command":    "TEXT",
    }
    for col_name, col_type in new_cols.items():
        if col_name not in cols:
            conn.execute(f"ALTER TABLE experiments ADD COLUMN {col_name} {col_type}")
            migrations.append(f"experiments.{col_name}")

    art_cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
    if "timeline_seq" not in art_cols:
        conn.execute("ALTER TABLE artifacts ADD COLUMN timeline_seq INTEGER")
        migrations.append("artifacts.timeline_seq")

    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    if "timeline" not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS timeline (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                exp_id      TEXT NOT NULL,
                seq         INTEGER NOT NULL,
                event_type  TEXT NOT NULL,
                cell_hash   TEXT,
                cell_pos    INTEGER,
                key         TEXT,
                value       TEXT,
                prev_value  TEXT,
                source_diff TEXT,
                ts          TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_timeline_exp_seq
                ON timeline(exp_id, seq);
            CREATE INDEX IF NOT EXISTS idx_timeline_exp_type
                ON timeline(exp_id, event_type);
        """)
        migrations.append("timeline table")

    if "cell_lineage" not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cell_lineage (
                cell_hash   TEXT PRIMARY KEY,
                notebook    TEXT NOT NULL,
                source      TEXT NOT NULL,
                parent_hash TEXT,
                created_at  TEXT NOT NULL
            );
        """)
        migrations.append("cell_lineage table")

    # New indexes
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_created ON experiments(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_status ON experiments(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_exp ON artifacts(exp_id)")
    except Exception as e:
        print(f"[exptrack] warning: could not create indexes: {e}", file=sys.stderr)

    conn.commit()

    if migrations:
        print(col(f"Migrations applied: {', '.join(migrations)}", G))
    else:
        print(dim("Schema is up to date."))

    if args.reinstall:
        root = cfg.project_root()
        print("Reinstalling package...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(root)],
                       check=True)
        print(col("Reinstalled.", G))



COMPACT_PREFIX = "[compacted"



def _fmt_bytes(b):
    if b < 1024: return f"{b} B"
    if b < 1024**2: return f"{b/1024:.1f} KB"
    return f"{b/1024**2:.1f} MB"


def _diff_file_summary(diff_text):
    """Extract a short file-list summary from a git diff for the compact marker."""
    files = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                files.append(parts[3].lstrip("b/"))
    return files


def cmd_compact(args):
    """Strip git_diff and/or cell data from experiments to reclaim space."""
    conn = get_db()
    dry_run = getattr(args, "dry_run", False)
    export_dir = getattr(args, "export", None)
    do_deep = getattr(args, "deep", False)
    do_cells = getattr(args, "cells", False) or do_deep
    do_timeline = getattr(args, "timeline", False) or do_deep
    do_snapshots = getattr(args, "snapshots", False) or do_deep
    do_dedup = getattr(args, "dedup", False)
    # Default: compact git diffs (unless only cell/timeline/snapshot/dedup modes)
    do_git_diff = not (do_cells or do_timeline or do_snapshots or do_dedup) or do_deep

    # ── Dedup mode (independent of experiment selection) ───────────────────
    if do_dedup:
        _compact_dedup(conn, dry_run)
        if not do_deep:
            return

    # ── Get target experiments ────────────────────────────────────────────
    exp_where, exp_args = _compact_exp_query(args)
    rows = conn.execute(
        f"SELECT id, name, git_commit, git_branch, git_diff, "
        f"COALESCE(LENGTH(git_diff), 0) as diff_len "
        f"FROM experiments WHERE {exp_where}",
        exp_args,
    ).fetchall()

    if not rows:
        print(dim("No matching experiments.")); return

    exp_ids = [r["id"] for r in rows]
    freed_total = 0

    if dry_run:
        modes = []
        if do_git_diff:
            diff_rows = [r for r in rows if r["git_diff"]
                         and not r["git_diff"].startswith(COMPACT_PREFIX)]
            total_diff = sum(r["diff_len"] for r in diff_rows)
            modes.append(f"git_diff (~{_fmt_bytes(total_diff)})")
        if do_cells:
            cell_bytes = _cell_lineage_size(conn, exp_ids)
            modes.append(f"cell_lineage.source (~{_fmt_bytes(cell_bytes)})")
        if do_timeline:
            tl_bytes = _timeline_diff_size(conn, exp_ids)
            modes.append(f"timeline.source_diff (~{_fmt_bytes(tl_bytes)})")
        if do_snapshots:
            snap_bytes = _snapshot_disk_size(exp_ids)
            modes.append(f"notebook_history/ (~{_fmt_bytes(snap_bytes)})")
        print(f"Would compact {len(rows)} experiment(s):")
        print(f"  Modes: {', '.join(modes)}")
        for r in rows[:10]:
            print(f"  {col(r['id'][:8], C)}  {r['name'][:50]}")
        if len(rows) > 10:
            print(dim(f"  ... and {len(rows) - 10} more"))
        return

    # ── 1. Git diff compaction ────────────────────────────────────────────
    if do_git_diff:
        if export_dir:
            out_path = Path(export_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            for r in rows:
                if r["git_diff"] and not r["git_diff"].startswith(COMPACT_PREFIX):
                    _export_one_diff(r, out_path)
            print(col(f"Exported diff(s) to {out_path}/", G))

        from ..core.db import resolve_git_diff
        diff_freed = 0
        for r in rows:
            if not r["git_diff"] or r["git_diff"].startswith(COMPACT_PREFIX):
                continue
            commit = r["git_commit"] or "unknown"
            full_diff = resolve_git_diff(conn, r["git_diff"])
            files = _diff_file_summary(full_diff)
            file_info = f"{len(files)} file(s): {', '.join(files[:5])}" if files else "no files"
            if len(files) > 5:
                file_info += f" +{len(files) - 5} more"
            summary = (f"[compacted — {_fmt_bytes(len(full_diff))} stripped — "
                       f"{file_info} — see git commit {commit}]")
            conn.execute("UPDATE experiments SET git_diff = ? WHERE id = ?",
                         (summary, r["id"]))
            diff_freed += len(full_diff)
        if diff_freed:
            conn.commit()
            freed_total += diff_freed
            print(col(f"  git_diff: freed ~{_fmt_bytes(diff_freed)}", G))

    # ── 2. Cell lineage source compaction ─────────────────────────────────
    if do_cells:
        cell_freed = _compact_cells(conn, exp_ids)
        freed_total += cell_freed
        if cell_freed:
            print(col(f"  cell_lineage.source: freed ~{_fmt_bytes(cell_freed)}", G))

    # ── 3. Timeline source_diff compaction ────────────────────────────────
    if do_timeline:
        tl_freed = _compact_timeline_diffs(conn, exp_ids)
        freed_total += tl_freed
        if tl_freed:
            print(col(f"  timeline.source_diff: freed ~{_fmt_bytes(tl_freed)}", G))

    # ── 4. Notebook history snapshot cleanup ──────────────────────────────
    if do_snapshots:
        snap_freed = _compact_snapshots(exp_ids)
        freed_total += snap_freed
        if snap_freed:
            print(col(f"  notebook_history/: freed ~{_fmt_bytes(snap_freed)}", G))

    if freed_total:
        print()
        print(col(f"Compacted {len(rows)} experiment(s), freed ~{_fmt_bytes(freed_total)} total.", G))
        for r in rows[:10]:
            print(f"  {col(r['id'][:8], C)}  {r['name'][:50]}")
        if len(rows) > 10:
            print(dim(f"  ... and {len(rows) - 10} more"))
    else:
        print(dim("Nothing to compact."))


def _compact_exp_query(args):
    """Build WHERE clause for selecting experiments to compact (no git_diff filter)."""
    from datetime import timedelta
    conditions = []
    query_args = []

    if args.ids:
        clauses = []
        for prefix in args.ids:
            clauses.append("id LIKE ?")
            query_args.append(prefix + "%")
        conditions.append(f"({' OR '.join(clauses)})")
    elif not getattr(args, "all", False):
        conditions.append("status = 'done'")

    older_than = getattr(args, "older_than", None)
    if older_than:
        age = older_than.rstrip("d")
        try:
            days = int(age)
        except ValueError:
            print(col(f"Invalid age: {older_than} (use e.g. 7d)", R), file=sys.stderr)
            return "1=0", []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conditions.append("created_at < ?")
        query_args.append(cutoff)

    where = " AND ".join(conditions) if conditions else "1=1"
    return where, query_args


def _compact_dedup(conn, dry_run=False):
    """Retroactively deduplicate raw git diffs into the git_diffs table."""
    from ..core.db import store_git_diff
    rows = conn.execute(
        "SELECT id, git_diff FROM experiments "
        "WHERE git_diff IS NOT NULL AND git_diff != '' "
        "AND git_diff NOT LIKE '[compacted%' AND git_diff NOT LIKE '[ref:%'"
    ).fetchall()
    if not rows:
        print(dim("  dedup: no raw diffs to deduplicate.")); return
    if dry_run:
        print(f"  dedup: would deduplicate {len(rows)} raw diff(s)")
        return
    unique_hashes = set()
    for r in rows:
        ref = store_git_diff(conn, r["git_diff"])
        unique_hashes.add(ref)
        conn.execute("UPDATE experiments SET git_diff = ? WHERE id = ?",
                     (ref, r["id"]))
    conn.commit()
    print(col(f"  dedup: {len(rows)} experiment(s) → {len(unique_hashes)} unique diff(s)", G))


def _cell_lineage_size(conn, exp_ids):
    """Estimate bytes in cell_lineage.source for cells used by given experiments."""
    if not exp_ids:
        return 0
    placeholders = ",".join("?" * len(exp_ids))
    try:
        row = conn.execute(f"""
            SELECT COALESCE(SUM(LENGTH(cl.source)), 0) as sz
            FROM cell_lineage cl
            WHERE cl.source IS NOT NULL
            AND cl.cell_hash IN (
                SELECT DISTINCT cell_hash FROM timeline
                WHERE exp_id IN ({placeholders}) AND cell_hash IS NOT NULL
            )
        """, exp_ids).fetchone()
        return row["sz"] if row else 0
    except Exception:
        return 0


def _timeline_diff_size(conn, exp_ids):
    """Estimate bytes in timeline.source_diff for given experiments."""
    if not exp_ids:
        return 0
    placeholders = ",".join("?" * len(exp_ids))
    try:
        row = conn.execute(f"""
            SELECT COALESCE(SUM(LENGTH(source_diff)), 0) as sz
            FROM timeline
            WHERE exp_id IN ({placeholders}) AND source_diff IS NOT NULL
        """, exp_ids).fetchone()
        return row["sz"] if row else 0
    except Exception:
        return 0


def _snapshot_disk_size(exp_ids):
    """Estimate bytes in notebook_history/ for given experiments."""
    try:
        root = cfg.project_root()
        hist_dir = root / cfg.load().get("notebook_history_dir",
                                          ".exptrack/notebook_history")
        if not hist_dir.exists():
            return 0
        total = 0
        exp_id_set = set(exp_ids)
        for fp in hist_dir.rglob("*.json"):
            try:
                snap = json.loads(fp.read_text())
                if snap.get("exp_id") in exp_id_set:
                    total += fp.stat().st_size
            except Exception:
                continue
        return total
    except Exception:
        return 0


def _compact_cells(conn, exp_ids):
    """NULL out cell_lineage.source for cells used only by finished experiments."""
    if not exp_ids:
        return 0
    placeholders = ",".join("?" * len(exp_ids))
    try:
        # Find size of source that would be freed
        size_row = conn.execute(f"""
            SELECT COALESCE(SUM(LENGTH(cl.source)), 0) as sz
            FROM cell_lineage cl
            WHERE cl.source IS NOT NULL
            AND cl.cell_hash IN (
                SELECT DISTINCT cell_hash FROM timeline
                WHERE exp_id IN ({placeholders}) AND cell_hash IS NOT NULL
            )
            AND cl.cell_hash NOT IN (
                SELECT DISTINCT cell_hash FROM timeline
                WHERE exp_id NOT IN ({placeholders})
                  AND cell_hash IS NOT NULL
                  AND exp_id IN (SELECT id FROM experiments WHERE status='running')
            )
        """, exp_ids + exp_ids).fetchone()
        freed = size_row["sz"] if size_row else 0
        if freed:
            conn.execute(f"""
                UPDATE cell_lineage SET source = NULL
                WHERE source IS NOT NULL
                AND cell_hash IN (
                    SELECT DISTINCT cell_hash FROM timeline
                    WHERE exp_id IN ({placeholders}) AND cell_hash IS NOT NULL
                )
                AND cell_hash NOT IN (
                    SELECT DISTINCT cell_hash FROM timeline
                    WHERE exp_id NOT IN ({placeholders})
                      AND cell_hash IS NOT NULL
                      AND exp_id IN (SELECT id FROM experiments WHERE status='running')
                )
            """, exp_ids + exp_ids)
            conn.commit()
        # Also clean up code_baselines superseded by cell_lineage
        try:
            conn.execute(
                "DELETE FROM code_baselines WHERE notebook IN "
                "(SELECT DISTINCT notebook FROM cell_lineage)"
            )
            conn.commit()
        except Exception:
            pass
        return freed
    except Exception as e:
        print(f"[exptrack] warning: could not compact cells: {e}", file=sys.stderr)
        return 0


def _compact_timeline_diffs(conn, exp_ids):
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
    except Exception as e:
        print(f"[exptrack] warning: could not compact timeline: {e}", file=sys.stderr)
        return 0


def _compact_snapshots(exp_ids):
    """Delete notebook_history/ JSON files for given experiments."""
    try:
        root = cfg.project_root()
        hist_dir = root / cfg.load().get("notebook_history_dir",
                                          ".exptrack/notebook_history")
        if not hist_dir.exists():
            return 0
        freed = 0
        exp_id_set = set(exp_ids)
        for fp in hist_dir.rglob("*.json"):
            try:
                snap = json.loads(fp.read_text())
                if snap.get("exp_id") in exp_id_set:
                    freed += fp.stat().st_size
                    fp.unlink()
            except Exception:
                continue
        # Clean up empty directories
        for d in sorted(hist_dir.rglob("*"), reverse=True):
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass
        return freed
    except Exception as e:
        print(f"[exptrack] warning: could not compact snapshots: {e}", file=sys.stderr)
        return 0


def _export_one_diff(row, out_path):
    """Write a single experiment's diff as a markdown file for lab notebooks."""
    exp_id = row["id"]
    name = row["name"] or exp_id[:8]
    branch = row["git_branch"] or ""
    commit = row["git_commit"] or ""
    from ..core.db import get_db as _get_db
    from ..core.db import resolve_git_diff
    _conn = _get_db()
    diff = resolve_git_diff(_conn, row["git_diff"])

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60]
    filename = f"{safe_name}__{exp_id[:8]}.md"

    lines = [
        f"# Diff: {name}",
        "",
        f"- **Experiment ID:** `{exp_id}`",
        f"- **Branch:** `{branch}`",
        f"- **Commit:** `{commit}`",
        "",
        "```diff",
        diff,
        "```",
        "",
    ]
    (out_path / filename).write_text("\n".join(lines), encoding="utf-8")


def cmd_storage(args):
    """Show data storage breakdown for the exptrack database and outputs."""
    conn = get_db()

    # Always try to checkpoint WAL before reporting sizes so the numbers
    # reflect the real state.  TRUNCATE may fail if another process (e.g.
    # dashboard) holds a connection — that's fine, we'll show the WAL size.
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass

    if getattr(args, "checkpoint", False):
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        print(col("WAL checkpoint complete.", G))
        return

    conf = cfg.load()
    root = cfg.project_root()
    db_path = root / conf.get("db", ".exptrack/experiments.db")
    db_size = db_path.stat().st_size if db_path.exists() else 0

    outputs_dir = root / conf.get("outputs_dir", "outputs")
    outputs_size = 0
    outputs_count = 0
    if outputs_dir.is_dir():
        for fp in outputs_dir.rglob("*"):
            if fp.is_file():
                outputs_size += fp.stat().st_size
                outputs_count += 1

    exp_count = conn.execute("SELECT COUNT(*) as n FROM experiments").fetchone()["n"]
    param_count = conn.execute("SELECT COUNT(*) as n FROM params").fetchone()["n"]
    metric_count = conn.execute("SELECT COUNT(*) as n FROM metrics").fetchone()["n"]
    artifact_count = conn.execute("SELECT COUNT(*) as n FROM artifacts").fetchone()["n"]
    try:
        timeline_count = conn.execute("SELECT COUNT(*) as n FROM timeline").fetchone()["n"]
    except Exception as e:
        print(f"[exptrack] warning: could not count timeline rows: {e}", file=sys.stderr)
        timeline_count = 0

    # Git diff stats (inline diffs in experiments table)
    git_diff_rows = conn.execute(
        "SELECT LENGTH(git_diff) as sz FROM experiments "
        "WHERE git_diff IS NOT NULL AND git_diff != '' "
        "AND git_diff NOT LIKE '[ref:%'"
    ).fetchall()
    git_diff_inline = sum(r["sz"] for r in git_diff_rows)

    # Deduped diffs in git_diffs table
    try:
        dedup_row = conn.execute(
            "SELECT COUNT(*) as n, COALESCE(SUM(LENGTH(diff_text)), 0) as sz FROM git_diffs"
        ).fetchone()
        dedup_count = dedup_row["n"]
        dedup_size = dedup_row["sz"]
    except Exception:
        dedup_count, dedup_size = 0, 0

    ref_count = conn.execute(
        "SELECT COUNT(*) as n FROM experiments WHERE git_diff LIKE '[ref:%'"
    ).fetchone()["n"]
    git_diff_total = git_diff_inline + dedup_size

    # Timeline stats
    try:
        timeline_rows = conn.execute(
            "SELECT SUM(LENGTH(value)) + SUM(LENGTH(source_diff)) as sz FROM timeline"
        ).fetchone()
        timeline_size = timeline_rows["sz"] or 0
    except Exception as e:
        print(f"[exptrack] warning: could not compute timeline size: {e}", file=sys.stderr)
        timeline_size = 0

    try:
        tl_diff_total = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(source_diff)), 0) as sz "
            "FROM timeline WHERE source_diff IS NOT NULL"
        ).fetchone()["sz"]
    except Exception:
        tl_diff_total = 0

    # Cell lineage stats
    try:
        cl_row = conn.execute(
            "SELECT COUNT(*) as n, COALESCE(SUM(LENGTH(source)), 0) as sz "
            "FROM cell_lineage WHERE source IS NOT NULL"
        ).fetchone()
        cl_count, cl_size = cl_row["n"], cl_row["sz"]
        cl_compacted = conn.execute(
            "SELECT COUNT(*) as n FROM cell_lineage WHERE source IS NULL"
        ).fetchone()["n"]
    except Exception:
        cl_count, cl_size, cl_compacted = 0, 0, 0

    # Notebook history disk usage
    hist_dir = root / conf.get("notebook_history_dir", ".exptrack/notebook_history")
    hist_size, hist_count = 0, 0
    if hist_dir.is_dir():
        for fp in hist_dir.rglob("*.json"):
            if fp.is_file():
                hist_size += fp.stat().st_size
                hist_count += 1

    def fmt(b):
        if b < 1024: return f"{b} B"
        if b < 1024**2: return f"{b/1024:.1f} KB"
        if b < 1024**3: return f"{b/1024**2:.1f} MB"
        return f"{b/1024**3:.2f} GB"

    print()
    print(bold(col("  Storage Report", W)))
    print(dim("  " + "-" * 50))
    print(f"  {bold('Database file:')}     {fmt(db_size)}")
    print(f"  {bold('Outputs directory:')} {fmt(outputs_size)}  ({outputs_count} files)")
    print(f"  {bold('Total:')}             {fmt(db_size + outputs_size)}")
    print()
    print(bold(col("  Database Breakdown", W)))
    print(dim("  " + "-" * 50))
    print(f"  Experiments:   {exp_count:>8,} rows")
    print(f"  Params:        {param_count:>8,} rows")
    print(f"  Metrics:       {metric_count:>8,} rows")
    print(f"  Artifacts:     {artifact_count:>8,} rows")
    print(f"  Timeline:      {timeline_count:>8,} rows  (~{fmt(timeline_size)})")
    print()
    print(bold(col("  Storage Hotspots", W)))
    print(dim("  " + "-" * 50))

    # Git diff breakdown
    if dedup_count:
        print(f"  git_diff total:       {fmt(git_diff_total)}")
        print(f"    deduped diffs:      {fmt(dedup_size)}  "
              f"({dedup_count} unique, {ref_count} experiments ref)")
        if git_diff_inline:
            print(f"    inline (legacy):    {fmt(git_diff_inline)}  "
                  f"({len(git_diff_rows)} experiments)")
            print(col("      Tip: Run \"exptrack compact --dedup\" to deduplicate legacy diffs.", Y))
    else:
        git_diff_avg = git_diff_inline // len(git_diff_rows) if git_diff_rows else 0
        print(f"  git_diff total:       {fmt(git_diff_inline)}  "
              f"(avg {fmt(git_diff_avg)}/experiment, {len(git_diff_rows)} with diffs)")

    # Cell/notebook breakdown
    print(f"  cell_lineage.source:  {fmt(cl_size)}  "
          f"({cl_count} cells with source, {cl_compacted} compacted)")
    print(f"  timeline.source_diff: {fmt(tl_diff_total)}")
    print(f"  notebook_history/:    {fmt(hist_size)}  ({hist_count} snapshots)")
    print()

    cell_total = cl_size + tl_diff_total + hist_size
    if git_diff_total > 1024 * 1024:
        print(col("    Tip: Run \"exptrack compact\" to strip old git diffs "
                   "(or set \"max_git_diff_kb\" in config.json to cap future ones).", Y))
    if cell_total > 1024 * 1024:
        print(col("    Tip: Cell data is large. Run \"exptrack compact --deep\" to strip "
                   "cell sources, timeline diffs, and notebook snapshots.", Y))
    if outputs_size > 100 * 1024 * 1024:
        print(col("    Tip: Outputs directory is large. Delete old experiments "
                   "with \"exptrack rm\" to reclaim space.", Y))
    print()

    # Database health
    print(bold(col("  Database Health", W)))
    print(dim("  " + "-" * 50))
    wal_path = Path(str(db_path) + "-wal")
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"  Journal mode:    {journal_mode.upper()}")
    print(f"  WAL file:        {fmt(wal_size)}")
    if wal_size > 10 * 1024 * 1024:
        print(col("    WAL file is large. Run \"exptrack storage --checkpoint\" to reclaim.", Y))
    elif wal_size > db_size * 2 and wal_size > 100 * 1024:
        print(col("    WAL file is larger than the database. "
                  "Run \"exptrack storage --checkpoint\" to reclaim.", Y))
    # Check for orphaned rows (data not linked to any experiment)
    if exp_count == 0 and (param_count or metric_count or artifact_count or
                           timeline_count or cl_count or hist_count):
        print(col("    Orphaned data detected (no experiments, but rows remain). "
                  "Run \"exptrack clean --orphans\" to purge.", Y))
    # Check for stale running experiments (potential leaked connections)
    stale_running = conn.execute(
        "SELECT COUNT(*) as n FROM experiments WHERE status='running' "
        "AND created_at < datetime('now', '-24 hours')"
    ).fetchone()["n"]
    if stale_running:
        print(col(f"    {stale_running} experiment(s) running for >24h — "
                  f"possible orphans. Use \"exptrack stale\" to review.", Y))
    print()
