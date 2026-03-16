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

from ..core import get_db
from .. import config as cfg
from .formatting import G, R, Y, C, W, col, dim, bold


def cmd_init(args):
    cfg.init(project_name=args.name or "", here=args.here)


def cmd_run(args):
    """Hand off to __main__.py logic inline."""
    script = args.script
    sys.argv = ["exptrack", script] + args.script_args
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


def _compact_query(args):
    """Build the WHERE clause and params for compact operations."""
    from datetime import timedelta
    conditions = [
        "git_diff IS NOT NULL", "git_diff != ''",
        "git_diff NOT LIKE '[compacted%'",
    ]
    query_args = []

    if args.ids:
        clauses = []
        for prefix in args.ids:
            clauses.append("id LIKE ?")
            query_args.append(prefix + "%")
        conditions.append(f"({' OR '.join(clauses)})")
    elif not getattr(args, "all", False):
        conditions.append("status = 'done'")
        conditions.append("git_commit IS NOT NULL")
        conditions.append("git_commit != ''")

    older_than = getattr(args, "older_than", None)
    if older_than:
        age = older_than.rstrip("d")
        try:
            days = int(age)
        except ValueError:
            return None, None, f"Invalid age: {older_than} (use e.g. 7d)"
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conditions.append("created_at < ?")
        query_args.append(cutoff)

    return " AND ".join(conditions), query_args, None


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
    """Strip git_diff from experiments to reclaim DB space, keeping all results."""
    conn = get_db()
    dry_run = getattr(args, "dry_run", False)
    export_dir = getattr(args, "export", None)

    where, query_args, err = _compact_query(args)
    if err:
        print(col(err, R), file=sys.stderr); return

    rows = conn.execute(
        f"SELECT id, name, git_commit, git_branch, git_diff, "
        f"LENGTH(git_diff) as diff_len FROM experiments WHERE {where}",
        query_args,
    ).fetchall()

    if not rows:
        print(dim("Nothing to compact.")); return

    total_bytes = sum(r["diff_len"] for r in rows)

    if dry_run:
        print(f"Would compact {len(rows)} experiment(s), freeing ~{_fmt_bytes(total_bytes)}:")
        for r in rows:
            print(f"  {col(r['id'][:8], C)}  {r['name'][:50]}  ({_fmt_bytes(r['diff_len'])})")
        return

    # Export diffs before stripping
    if export_dir:
        out_path = Path(export_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        for r in rows:
            _export_one_diff(r, out_path)
        print(col(f"Exported {len(rows)} diff(s) to {out_path}/", G))

    for r in rows:
        commit = r["git_commit"] or "unknown"
        files = _diff_file_summary(r["git_diff"])
        file_info = f"{len(files)} file(s): {', '.join(files[:5])}" if files else "no files"
        if len(files) > 5:
            file_info += f" +{len(files) - 5} more"
        summary = (f"[compacted — {_fmt_bytes(r['diff_len'])} stripped — "
                   f"{file_info} — see git commit {commit}]")
        conn.execute("UPDATE experiments SET git_diff = ? WHERE id = ?", (summary, r["id"]))
    conn.commit()

    print(col(f"Compacted {len(rows)} experiment(s), freed ~{_fmt_bytes(total_bytes)}.", G))
    for r in rows:
        print(f"  {col(r['id'][:8], C)}  {r['name'][:50]}")


def _export_one_diff(row, out_path):
    """Write a single experiment's diff as a markdown file for lab notebooks."""
    exp_id = row["id"]
    name = row["name"] or exp_id[:8]
    branch = row["git_branch"] or ""
    commit = row["git_commit"] or ""
    diff = row["git_diff"] or ""

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60]
    filename = f"{safe_name}__{exp_id[:8]}.md"

    lines = [
        f"# Diff: {name}",
        f"",
        f"- **Experiment ID:** `{exp_id}`",
        f"- **Branch:** `{branch}`",
        f"- **Commit:** `{commit}`",
        f"",
        f"```diff",
        diff,
        f"```",
        f"",
    ]
    (out_path / filename).write_text("\n".join(lines), encoding="utf-8")


def cmd_storage(args):
    """Show data storage breakdown for the exptrack database and outputs."""
    conn = get_db()

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

    git_diff_rows = conn.execute(
        "SELECT LENGTH(git_diff) as sz FROM experiments WHERE git_diff IS NOT NULL AND git_diff != ''"
    ).fetchall()
    git_diff_total = sum(r["sz"] for r in git_diff_rows)
    git_diff_avg = git_diff_total // len(git_diff_rows) if git_diff_rows else 0

    try:
        timeline_rows = conn.execute(
            "SELECT SUM(LENGTH(value)) + SUM(LENGTH(source_diff)) as sz FROM timeline"
        ).fetchone()
        timeline_size = timeline_rows["sz"] or 0
    except Exception as e:
        print(f"[exptrack] warning: could not compute timeline size: {e}", file=sys.stderr)
        timeline_size = 0

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
    print(f"  git_diff total:   {fmt(git_diff_total)}  "
          f"(avg {fmt(git_diff_avg)}/experiment, {len(git_diff_rows)} with diffs)")
    if git_diff_total > 1024 * 1024:
        print(col("    Tip: Run \"exptrack compact\" to strip old diffs "
                   "(or set \"max_git_diff_kb\" in config.json to cap future ones).", Y))
    if timeline_size > 1024 * 1024:
        print(col("    Tip: Timeline data is growing large. Use "
                   "\"exptrack clean\" to remove failed runs.", Y))
    if outputs_size > 100 * 1024 * 1024:
        print(col("    Tip: Outputs directory is large. Delete old experiments "
                   "with \"exptrack rm\" to reclaim space.", Y))
    print()
