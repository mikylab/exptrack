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
from ..core.db import COMPACT_PREFIX, is_diff_sentinel, resolve_git_diff
from ..core.queries import find_experiment
from .formatting import C, G, R, W, Y, bold, col, die, dim, fmt_bytes


def cmd_init(args):
    cfg.init(project_name=args.name or "", here=args.here)


# Paste-able guard that makes a notebook run with OR without exptrack installed.
# If exptrack is present it loads normally; if not, the %%scratch / %%setup /
# %%pin cell magics and %exptrack line magics are registered as harmless
# no-ops (the cell bodies still run) so the same notebook stays portable for
# collaborators who don't have exptrack. The fallback uses
# ip.register_magic_function(...) — the same API exptrack itself uses — so custom
# magic names register reliably across IPython versions.
NOTEBOOK_GUARD = '''\
# ── exptrack guard ──────────────────────────────────────────────────────────
# Makes this notebook run with OR without exptrack installed. Paste at the top.
# Installed  → loads normally (full tracking).
# Not there  → %%scratch / %%setup / %%pin and %exptrack lines become no-ops;
#              the cell bodies still run, so the notebook stays portable.
try:
    get_ipython().run_line_magic("load_ext", "exptrack")
except Exception:
    _ip = get_ipython()
    def _exptrack_passthrough(line, cell):
        _ip.run_cell(cell)            # run the body, ignore the magic label
    def _exptrack_noop(line):
        pass
    for _name in ("scratch", "setup", "pin"):
        _ip.register_magic_function(
            _exptrack_passthrough, magic_kind="cell", magic_name=_name)
    _ip.register_magic_function(
        _exptrack_noop, magic_kind="line", magic_name="exptrack")
    print("[exptrack-guard] exptrack not loaded — session magics are no-ops, "
          "cells still run.")
'''


def cmd_notebook_guard(args):
    """Print a paste-able guard cell so a notebook runs with or without exptrack.

    Without it, a notebook using %%scratch / %%setup / %%pin / %exptrack raises
    an "unknown magic" UsageError on any machine where exptrack isn't installed
    (and for a cell magic the whole cell body is skipped). The guard degrades
    those magics to no-ops that still run the cell body."""
    # Snippet to stdout so it can be piped/copied; the hint goes to stderr.
    print(NOTEBOOK_GUARD)
    print(
        col("Copy the cell above into the top of your notebook. ", G)
        + dim("It loads exptrack when present and otherwise makes the session "
              "magics harmless no-ops."),
        file=sys.stderr,
    )


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
    no_auth = getattr(args, "no_auth", False)

    # Handle --token / --clear-token. The token lives in the gitignored
    # .exptrack/dashboard_token (0600), never in the committable config.json.
    # A legacy token still sitting in config.json is warned about by ui_main.
    if getattr(args, "clear_token", False):
        removed = cfg.token_file_path().is_file()
        cfg.token_file_path().unlink(missing_ok=True)
        conf = cfg.load()
        if conf.pop("dashboard_token", None) is not None:
            cfg.save(conf)
            removed = True
        print(col("Dashboard token removed." if removed else "No dashboard token set.", G),
              file=sys.stderr)
    elif getattr(args, "token", None):
        tf = cfg.write_token(args.token)
        print(col(f"Dashboard token saved to {tf} (gitignored, mode 600)", G),
              file=sys.stderr)

    ui_main(host=host, port=port, no_auth=no_auth)


def cmd_ui_stop(args):
    """Kill any process listening on the dashboard port."""
    import os
    import signal
    import subprocess
    port = getattr(args, "port", 7331)

    # Both fuser (Linux) and lsof -ti (macOS/BSD) print PIDs to stdout
    # whitespace-separated; fuser's "<port>/tcp:" header goes to stderr.
    candidates = (
        ["fuser", f"{port}/tcp"],
        ["lsof", "-ti", f"tcp:{port}"],
    )
    for argv in candidates:
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

        pids = sorted({p for p in result.stdout.split() if p.isdigit()})
        if not pids:
            print(dim(f"No process is listening on port {port}."), file=sys.stderr)
            return

        killed = []
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGTERM)
                killed.append(pid)
            except ProcessLookupError:
                pass
            except PermissionError:
                print(col(f"Permission denied killing PID {pid}.", R), file=sys.stderr)

        if killed:
            print(col(f"Sent SIGTERM to {', '.join(killed)} on port {port}.", G),
                  file=sys.stderr)
        return

    print(col("Neither 'fuser' nor 'lsof' is available on this system. "
              f"Find and kill the process manually (listening on port {port}).", Y),
          file=sys.stderr)


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
    # One transaction for the whole batch instead of a commit (fsync) per row.
    with conn:
        for r in rows:
            duration = (datetime.fromisoformat(now) -
                        datetime.fromisoformat(r["created_at"])).total_seconds()
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

    # get_db() skips _ensure_schema when the user_version stamp matches; a
    # manual upgrade must always re-verify every table, so force a full run.
    from exptrack.core.db import _ensure_schema
    _ensure_schema(conn, force=True)

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






def _diff_file_summary(diff_text):
    """Extract a short file-list summary from a git diff for the compact marker."""
    from ..core.db import diff_b_path
    files = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                files.append(diff_b_path(parts[3]))
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
            # Same gate as the real path below, so the dry-run total can't
            # promise bytes that the actual compact then skips.
            diff_rows = [r for r in rows if r["git_diff"]
                         and not is_diff_sentinel(r["git_diff"])]
            total_diff = sum(r["diff_len"] for r in diff_rows)
            modes.append(f"git_diff (~{fmt_bytes(total_diff)})")
        if do_cells:
            cell_bytes = _cell_lineage_size(conn, exp_ids)
            modes.append(f"cell_lineage.source (~{fmt_bytes(cell_bytes)})")
        if do_timeline:
            tl_bytes = _timeline_diff_size(conn, exp_ids)
            modes.append(f"timeline.source_diff (~{fmt_bytes(tl_bytes)})")
        if do_snapshots:
            snap_bytes = _snapshot_disk_size(exp_ids)
            modes.append(f"notebook_history/ (~{fmt_bytes(snap_bytes)})")
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

        diff_freed = 0
        for r in rows:
            if not r["git_diff"] or is_diff_sentinel(r["git_diff"]):
                continue
            commit = r["git_commit"] or "unknown"
            full_diff = resolve_git_diff(conn, r["git_diff"])
            if is_diff_sentinel(full_diff):
                continue  # dangling ref / already-failed capture: no body to strip
            files = _diff_file_summary(full_diff)
            file_info = f"{len(files)} file(s): {', '.join(files[:5])}" if files else "no files"
            if len(files) > 5:
                file_info += f" +{len(files) - 5} more"
            summary = (f"[compacted — {fmt_bytes(len(full_diff))} stripped — "
                       f"{file_info} — see git commit {commit}]")
            conn.execute("UPDATE experiments SET git_diff = ? WHERE id = ?",
                         (summary, r["id"]))
            diff_freed += len(full_diff)
        if diff_freed:
            conn.commit()
            freed_total += diff_freed
            print(col(f"  git_diff: freed ~{fmt_bytes(diff_freed)}", G))

    # ── 2. Cell lineage source compaction ─────────────────────────────────
    if do_cells:
        cell_freed = _compact_cells(conn, exp_ids)
        freed_total += cell_freed
        if cell_freed:
            print(col(f"  cell_lineage.source: freed ~{fmt_bytes(cell_freed)}", G))

    # ── 3. Timeline source_diff compaction ────────────────────────────────
    if do_timeline:
        tl_freed = _compact_timeline_diffs(conn, exp_ids)
        freed_total += tl_freed
        if tl_freed:
            print(col(f"  timeline.source_diff: freed ~{fmt_bytes(tl_freed)}", G))

    # ── 4. Notebook history snapshot cleanup ──────────────────────────────
    if do_snapshots:
        snap_freed = _compact_snapshots(exp_ids)
        freed_total += snap_freed
        if snap_freed:
            print(col(f"  notebook_history/: freed ~{fmt_bytes(snap_freed)}", G))

    if freed_total:
        print()
        print(col(f"Compacted {len(rows)} experiment(s), freed ~{fmt_bytes(freed_total)} total.", G))
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
        "AND git_diff NOT LIKE '[compacted%' AND git_diff NOT LIKE '[ref:%' "
        "AND git_diff NOT LIKE '[capture-failed%'"
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
        except Exception as e:
            print(f"[exptrack] warning: could not prune superseded code_baselines: {e}",
                  file=sys.stderr)
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
    ]
    # A sentinel is a status, not a diff — writing it inside a ```diff fence
    # produced a lab-notebook file whose body was the literal marker. Matches
    # what api_export_diff reports for the same run.
    if is_diff_sentinel(diff):
        lines.append(f"_No diff body is available for this run: `{diff}`_")
    else:
        lines += ["```diff", diff, "```"]
    lines.append("")
    (out_path / filename).write_text("\n".join(lines), encoding="utf-8")


def cmd_backup(args):
    """Create a backup of the experiment database using sqlite3.backup()."""
    import sqlite3

    conn = get_db()
    root = cfg.project_root()

    if args.path:
        dest = Path(args.path)
    else:
        backup_dir = root / ".exptrack" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = backup_dir / f"{timestamp}.db"

    if dest.exists() and not getattr(args, "force", False):
        print(col(f"Backup file already exists: {dest}", R), file=sys.stderr)
        print("Use --force to overwrite.", file=sys.stderr)
        return

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        backup_conn = sqlite3.connect(str(dest))
        conn.backup(backup_conn)
        backup_conn.close()
    except Exception as e:
        print(col(f"Backup failed: {e}", R), file=sys.stderr)
        return

    size = dest.stat().st_size
    print(col(f"Backup saved to {dest} ({fmt_bytes(size)})", G))


def cmd_restore(args):
    """Restore the experiment database from a backup file using sqlite3.backup()."""
    import sqlite3

    source = Path(args.path)
    if not source.exists():
        print(col(f"Backup file not found: {source}", R), file=sys.stderr)
        return

    conf = cfg.load()
    root = cfg.project_root()
    db_path = root / conf.get("db", ".exptrack/experiments.db")

    if not getattr(args, "yes", False):
        print(f"This will overwrite the current database at {db_path}")
        print(f"with the backup from {source}")
        try:
            answer = input("Continue? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    # Close the current connection so we can overwrite the DB
    from ..core.db import close_db
    close_db()

    try:
        backup_conn = sqlite3.connect(str(source))
        dest_conn = sqlite3.connect(str(db_path))
        backup_conn.backup(dest_conn)
        dest_conn.close()
        backup_conn.close()
    except Exception as e:
        print(col(f"Restore failed: {e}", R), file=sys.stderr)
        return

    print(col(f"Database restored from {source}", G))


# ── storage report ──────────────────────────────────────────────────────────
# Split into a gather half (collect_storage_stats and its per-area helpers,
# which touch nothing but the DB and the filesystem) and a render half (the
# _print_storage_* section functions). The whole thing used to be one function
# of 212 lines and 48 branches with no test coverage, largely because the
# numbers were unreachable without capturing stdout. The stats are now a plain
# dict that tests can assert on directly.
#
# Every gather helper is best-effort: a query against a table an older DB
# doesn't have must degrade to zero rather than take down the report.

def _q1(conn, sql, warn=""):
    """First column of the first row, or 0 if the query fails."""
    return _qrow(conn, sql, (0,), warn)[0]


def _qrow(conn, sql, defaults, warn=""):
    """First row as a tuple, falling back to `defaults` per column on failure.

    Use this rather than several _q1 calls when the values come from the same
    table. ``SUM(LENGTH(col))`` cannot use an index, so every extra query is a
    full re-read of the column — and the three tables measured here
    (``session_nodes``, ``cell_lineage``, ``git_diffs``) are exactly the ones
    holding the large TEXT blobs that make a report worth running.
    """
    try:
        row = conn.execute(sql).fetchone()
        if not row:
            return defaults
        return tuple(row[i] if row[i] is not None else d
                     for i, d in enumerate(defaults))
    except Exception as e:
        if warn:
            print(f"[exptrack] warning: {warn}: {e}", file=sys.stderr)
        return defaults


def _storage_disk_usage(conf, root):
    """Sizes that come from the filesystem rather than the DB."""
    db_path = root / conf.get("db", ".exptrack/experiments.db")
    stats = {
        "db_path": db_path,
        "db_size": db_path.stat().st_size if db_path.exists() else 0,
        "outputs_size": 0, "outputs_count": 0,
        "hist_size": 0, "hist_count": 0,
    }

    outputs_dir = root / conf.get("outputs_dir", "outputs")
    if outputs_dir.is_dir():
        for fp in outputs_dir.rglob("*"):
            if fp.is_file():
                stats["outputs_size"] += fp.stat().st_size
                stats["outputs_count"] += 1

    hist_dir = root / conf.get("notebook_history_dir", ".exptrack/notebook_history")
    if hist_dir.is_dir():
        for fp in hist_dir.rglob("*.json"):
            if fp.is_file():
                stats["hist_size"] += fp.stat().st_size
                stats["hist_count"] += 1
    return stats


def _storage_row_counts(conn):
    return {
        "exp_count": _q1(conn, "SELECT COUNT(*) FROM experiments"),
        "param_count": _q1(conn, "SELECT COUNT(*) FROM params"),
        "metric_count": _q1(conn, "SELECT COUNT(*) FROM metrics"),
        "artifact_count": _q1(conn, "SELECT COUNT(*) FROM artifacts"),
        "timeline_count": _q1(conn, "SELECT COUNT(*) FROM timeline",
                              warn="could not count timeline rows"),
    }


def _storage_git_diff_stats(conn):
    """Inline (legacy) diffs on experiments vs. deduped bodies in git_diffs."""
    try:
        rows = conn.execute(
            "SELECT LENGTH(git_diff) as sz FROM experiments "
            "WHERE git_diff IS NOT NULL AND git_diff != '' "
            "AND git_diff NOT LIKE '[ref:%'"
        ).fetchall()
    except Exception:
        rows = []
    inline = sum(r["sz"] for r in rows)
    dedup_count, dedup_size = _qrow(
        conn, "SELECT COUNT(*), COALESCE(SUM(LENGTH(diff_text)), 0) FROM git_diffs", (0, 0))
    return {
        "git_diff_inline": inline,
        "git_diff_rows": len(rows),
        "dedup_count": dedup_count,
        "dedup_size": dedup_size,
        "ref_count": _q1(conn, "SELECT COUNT(*) FROM experiments "
                               "WHERE git_diff LIKE '[ref:%'"),
        # Session nodes reference these blobs too, so a report counting only
        # experiments would show a live blob as referenced by nothing.
        "node_ref_count": _q1(conn, "SELECT COUNT(*) FROM session_nodes "
                                    "WHERE git_diff LIKE '[ref:%'"),
        "git_diff_total": inline + dedup_size,
    }


def _storage_cell_stats(conn):
    """Notebook cell sources and timeline diffs — the 'deep compact' targets."""
    timeline_size, tl_diff_total = _qrow(
        conn,
        "SELECT SUM(LENGTH(value)) + SUM(LENGTH(source_diff)), "
        "       COALESCE(SUM(CASE WHEN source_diff IS NOT NULL "
        "                         THEN LENGTH(source_diff) ELSE 0 END), 0) "
        "FROM timeline",
        (0, 0), warn="could not compute timeline size")
    cl_count, cl_size, cl_compacted = _qrow(
        conn,
        "SELECT COUNT(source), COALESCE(SUM(LENGTH(source)), 0), "
        "       COUNT(*) - COUNT(source) "
        "FROM cell_lineage",
        (0, 0, 0))
    return {
        "timeline_size": timeline_size,
        "tl_diff_total": tl_diff_total,
        "cl_count": cl_count,
        "cl_size": cl_size,
        "cl_compacted": cl_compacted,
    }


def _storage_session_stats(conn):
    snode_count, cells, diffs, notes = _qrow(
        conn,
        "SELECT COUNT(*), "
        "       COALESCE(SUM(LENGTH(cell_source)), 0), "
        "       COALESCE(SUM(LENGTH(git_diff)), 0), "
        "       COALESCE(SUM(LENGTH(note)), 0) "
        "FROM session_nodes",
        (0, 0, 0, 0))
    return {
        "sess_count": _q1(conn, "SELECT COUNT(*) FROM sessions"),
        "snode_count": snode_count,
        "snode_cells_size": cells,
        "snode_diff_size": diffs,
        "snode_size": cells + diffs + notes,
    }


def _storage_metric_stats(conn):
    """Bytes held by the metrics table, broken down by key.

    Metrics are the only table exptrack writes inside the user's training loop,
    so on any real project they are the largest thing in the database — and
    until this landed the report counted their rows without ever saying what
    those rows cost.
    """
    from ..core.storage import metric_storage, table_byte_sizes
    table_bytes = table_byte_sizes(conn)
    m = metric_storage(conn, table_bytes=table_bytes)
    return {
        "table_bytes": table_bytes,
        "metrics_size": m["bytes"],
        "metrics_exact": m["exact"],
        "metric_keys": m["keys"],
        "metric_key_count": m["key_count"],
        "metric_keys_omitted": m["keys_omitted"],
    }


def collect_storage_stats(conn, conf=None, root=None):
    """Every number the storage report shows, as one flat dict.

    Pure gathering — no printing — so the figures can be asserted on directly
    and reused (the dashboard's storage panel wants the same numbers).
    """
    conf = cfg.load() if conf is None else conf
    root = cfg.project_root() if root is None else root
    stats = {}
    stats.update(_storage_disk_usage(conf, root))
    stats.update(_storage_row_counts(conn))
    stats.update(_storage_metric_stats(conn))
    stats.update(_storage_git_diff_stats(conn))
    stats.update(_storage_cell_stats(conn))
    stats.update(_storage_session_stats(conn))
    from ..core.storage import free_space
    stats["free_space"] = free_space(conn)
    return stats


def _print_storage_summary(s):
    print()
    print(bold(col("  Storage Report", W)))
    print(dim("  " + "-" * 50))
    print(f"  {bold('Database file:')}     {fmt_bytes(s['db_size'])}")
    free = s.get("free_space") or {}
    if free.get("bytes"):
        # Without this line the breakdown below simply doesn't add up to the
        # file size after a delete, which reads as "the delete didn't work".
        print(f"    of which free:     {fmt_bytes(free['bytes'])}  "
              + dim(f"({free['pct']:.0f}% reusable — deleted rows, "
                    f"returned to disk by \"exptrack clean --vacuum\")"))
    print(f"  {bold('Outputs directory:')} {fmt_bytes(s['outputs_size'])}  "
          f"({s['outputs_count']} files)")
    print(f"  {bold('Total:')}             {fmt_bytes(s['db_size'] + s['outputs_size'])}")


def _print_db_breakdown(s):
    print()
    print(bold(col("  Database Breakdown", W)))
    print(dim("  " + "-" * 50))
    print(f"  Experiments:   {s['exp_count']:>8,} rows")
    print(f"  Params:        {s['param_count']:>8,} rows")
    print(f"  Metrics:       {s['metric_count']:>8,} rows  "
          f"(~{fmt_bytes(s['metrics_size'])})")
    print(f"  Artifacts:     {s['artifact_count']:>8,} rows")
    print(f"  Timeline:      {s['timeline_count']:>8,} rows  (~{fmt_bytes(s['timeline_size'])})")
    if s["sess_count"] or s["snode_count"]:
        print(f"  Sessions:      {s['sess_count']:>8,} rows  "
              f"({s['snode_count']} nodes, ~{fmt_bytes(s['snode_size'])})")


def _print_metric_hotspot(s, by_metric=False):
    """The metrics line, plus an optional per-key breakdown."""
    exact = "" if s.get("metrics_exact") else "  (estimated)"
    print(f"  metrics:              {fmt_bytes(s['metrics_size'])}  "
          f"({s['metric_count']:,} points across {s['metric_key_count']} keys)"
          f"{exact}")
    if not by_metric:
        return
    for k in s.get("metric_keys", []):
        per_run = dim(f"{k['max_per_exp']:,} max/run")
        print(f"    {k['key'][:28]:<28} {fmt_bytes(k['bytes']):>9}  "
              f"{k['points']:>9,} pts  {per_run}")
    if s.get("metric_keys_omitted"):
        print(dim(f"    … and {s['metric_keys_omitted']} more keys"))


def _print_storage_hotspots(s, by_metric=False):
    print()
    print(bold(col("  Storage Hotspots", W)))
    print(dim("  " + "-" * 50))

    _print_metric_hotspot(s, by_metric)

    if s["dedup_count"]:
        print(f"  git_diff total:       {fmt_bytes(s['git_diff_total'])}")
        refs = f"{s['ref_count']} experiments ref"
        if s.get("node_ref_count"):
            refs += f", {s['node_ref_count']} session nodes ref"
        print(f"    deduped diffs:      {fmt_bytes(s['dedup_size'])}  "
              f"({s['dedup_count']} unique, {refs})")
        if s["git_diff_inline"]:
            print(f"    inline (legacy):    {fmt_bytes(s['git_diff_inline'])}  "
                  f"({s['git_diff_rows']} experiments)")
            print(col("      Tip: Run \"exptrack compact --dedup\" to deduplicate legacy diffs.", Y))
    else:
        avg = s["git_diff_inline"] // s["git_diff_rows"] if s["git_diff_rows"] else 0
        print(f"  git_diff total:       {fmt_bytes(s['git_diff_inline'])}  "
              f"(avg {fmt_bytes(avg)}/experiment, {s['git_diff_rows']} with diffs)")

    print(f"  cell_lineage.source:  {fmt_bytes(s['cl_size'])}  "
          f"({s['cl_count']} cells with source, {s['cl_compacted']} compacted)")
    print(f"  timeline.source_diff: {fmt_bytes(s['tl_diff_total'])}")
    print(f"  notebook_history/:    {fmt_bytes(s['hist_size'])}  ({s['hist_count']} snapshots)")
    if s["snode_count"]:
        print(f"  session_nodes.cell_source: {fmt_bytes(s['snode_cells_size'])}  "
              f"({s['snode_count']} nodes)")
        print(f"  session_nodes.git_diff:    {fmt_bytes(s['snode_diff_size'])}")
    print()

    cell_total = s["cl_size"] + s["tl_diff_total"] + s["hist_size"]
    # Metrics are usually the biggest table and, unlike diffs and cell sources,
    # compaction does not touch them — point them at prune instead.
    if s["metrics_size"] > 1024 * 1024:
        busiest = (s.get("metric_keys") or [{}])[0].get("max_per_exp", 0)
        if busiest > 2000:
            print(col(f"    Tip: metrics are {fmt_bytes(s['metrics_size'])} and one series "
                      f"reaches {busiest:,} points in a single run. Run "
                      f"\"exptrack prune --max-points 500 --dry-run\" to preview thinning "
                      f"them (charts downsample to 500 points anyway).", Y))
    if s["git_diff_total"] > 1024 * 1024:
        print(col("    Tip: Run \"exptrack compact\" to strip old git diffs "
                  "(or set \"max_git_diff_kb\" in config.json to cap future ones).", Y))
    if cell_total > 1024 * 1024:
        print(col("    Tip: Cell data is large. Run \"exptrack compact --deep\" to strip "
                  "cell sources, timeline diffs, and notebook snapshots.", Y))
    if s["outputs_size"] > 100 * 1024 * 1024:
        print(col("    Tip: Outputs directory is large. Delete old experiments "
                  "with \"exptrack rm\" to reclaim space.", Y))


def _print_largest_experiments(conn, s, top=5):
    """Which runs are actually holding the space.

    The whole-database totals above answer "what kind of data is big"; this
    answers "which run do I delete or prune", which is the question that
    actually leads to an action.
    """
    if not top:
        return
    from ..core.storage import experiment_storage
    rows = experiment_storage(conn, limit=top, table_bytes=s.get("table_bytes"))
    if not rows:
        return
    print()
    print(bold(col(f"  Largest Experiments (top {len(rows)}, estimated)", W)))
    print(dim("  " + "-" * 50))
    print(dim(f"    {'ID':<9} {'NAME':<24} {'TOTAL':>9} {'METRICS':>9} "
              f"{'POINTS':>9}"))
    for e in rows:
        name = e["name"] or "(unnamed)"
        if len(name) > 23:
            name = name[:22] + "…"
        flag = col(" [trash]", Y) if e["trashed"] else ""
        print(f"    {e['id'][:8]:<9} {name:<24} {fmt_bytes(e['db_bytes']):>9} "
              f"{fmt_bytes(e['metrics_bytes']):>9} {e['n_metrics']:>9,}{flag}")
    print(dim("    Sizes are database bytes only — output files are not counted."))


def _print_trash_storage(conn):
    """What emptying the Trash would give back.

    Soft delete keeps every row and leaves output files in place, so this is
    the one place storage accumulates with nothing else in the report showing
    it. Silent when the Trash is empty — a permanent "Trash: 0 B" line is noise
    on the overwhelmingly common case.
    """
    from ..core.storage import trash_storage
    t = trash_storage(conn)
    if not (t["experiments"] or t["nodes"] or t["sessions"] or t["local_files"]):
        return
    print()
    print(bold(col("  Trash", W)))
    print(dim("  " + "-" * 50))
    if t["experiments"]:
        print(f"  Trashed experiments: {t['experiments']:>6,}  "
              f"(~{fmt_bytes(t['exp_db_bytes'])} in the database)")
    if t["nodes"] or t["sessions"]:
        print(f"  Trashed session nodes: {t['nodes']:>4,}  "
              f"(~{fmt_bytes(t['node_db_bytes'])}"
              + (f", {t['sessions']} whole session(s)" if t["sessions"] else "") + ")")
    if t["output_files"]:
        print(f"  Their output files:  {t['output_files']:>6,}  "
              f"({fmt_bytes(t['output_bytes'])} across {t['output_dirs']} dir(s), "
              f"kept until you delete permanently with files)")
    if t["local_files"]:
        print(f"  .exptrack/trash/:    {t['local_files']:>6,} files  "
              f"({fmt_bytes(t['local_bytes'])})")
        print(dim("    Files exptrack could not hand to the OS Trash. "
                  "Delete the directory when you're sure."))
    reclaim = t["db_bytes"] + t["output_bytes"]
    if reclaim:
        print(col(f"  Reclaimable: ~{fmt_bytes(reclaim)}", Y)
              + dim("  (permanently delete from the dashboard's Trash view, "
                    "then \"exptrack clean --vacuum\")"))


def _print_storage_health(conn, s):
    print()
    print(bold(col("  Database Health", W)))
    print(dim("  " + "-" * 50))
    wal_path = Path(str(s["db_path"]) + "-wal")
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"  Journal mode:    {journal_mode.upper()}")
    print(f"  WAL file:        {fmt_bytes(wal_size)}")
    if wal_size > 10 * 1024 * 1024:
        print(col("    WAL file is large. Run \"exptrack storage --checkpoint\" to reclaim.", Y))
    elif wal_size > s["db_size"] * 2 and wal_size > 100 * 1024:
        print(col("    WAL file is larger than the database. "
                  "Run \"exptrack storage --checkpoint\" to reclaim.", Y))

    # Rows that outlived the experiment they belonged to — a database written
    # by an older version that deleted the run row only, a hand-edited one, or
    # a process killed mid-delete. This used to fire only when the project held
    # *zero* experiments, so 5 runs alongside 20k orphaned metric rows reported
    # perfect health. They are invisible in every list while still occupying
    # the file, which is the whole reason to name them.
    from ..core.storage import orphan_storage
    orphans = orphan_storage(conn)
    if orphans["rows"]:
        detail = ", ".join(f"{v['rows']:,} {t}" for t, v in orphans["tables"].items())
        print(col(f"    {orphans['rows']:,} orphaned row(s) "
                  f"(~{fmt_bytes(orphans['bytes'])}): {detail}", Y))
        print(dim("    Rows whose experiment no longer exists — swept "
                  "automatically when a CLI command exits, or now with "
                  "\"exptrack clean --orphans\"."))

    # Runs left 'running' — usually a killed process, not a live job.
    stale_running = _q1(conn, "SELECT COUNT(*) FROM experiments WHERE status='running' "
                              "AND created_at < datetime('now', '-24 hours')")
    if stale_running:
        print(col(f"    {stale_running} experiment(s) running for >24h — "
                  f"possible orphans. Use \"exptrack stale\" to review.", Y))
    print()


def cmd_storage(args):
    """Show data storage breakdown for the exptrack database and outputs."""
    conn = get_db()

    # Checkpoint before measuring so the sizes reflect the real state. May
    # fail if another process (e.g. the dashboard) holds a connection — fine,
    # the WAL size is reported either way.
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass

    if getattr(args, "checkpoint", False):
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        print(col("WAL checkpoint complete.", G))
        return

    stats = collect_storage_stats(conn)
    _print_storage_summary(stats)
    _print_db_breakdown(stats)
    _print_storage_hotspots(stats, by_metric=getattr(args, "by_metric", False))
    _print_largest_experiments(conn, stats, top=getattr(args, "top", 5))
    _print_trash_storage(conn)
    _print_storage_health(conn, stats)


def _resolve_prune_scope(conn, args):
    """(exp_ids, keys, protect_extremes, scope-label) for a prune request."""
    exp_ids = []
    for prefix in (getattr(args, "id", None) or []):
        row = find_experiment(conn, prefix, "id, name")
        if not row:
            die(f"Not found: {prefix}")
        exp_ids.append(row["id"])
    keys = getattr(args, "key", None) or None
    scope = f"{len(exp_ids)} experiment(s)" if exp_ids else "all experiments"
    if keys:
        scope += f", keys: {', '.join(keys)}"
    return exp_ids, keys, not getattr(args, "no_protect_extremes", False), scope


def _confirm_prune() -> bool:
    """Ask before a destructive, unrecoverable delete."""
    try:
        answer = input("  Prune these points? This cannot be undone [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        answer = ""
    if answer.strip().lower() in ("y", "yes"):
        return True
    print(dim("  Cancelled."), file=sys.stderr)
    return False


def cmd_prune(args):
    """Thin already-stored metric points: exptrack prune [id...] --max-points N

    ``metric_keep_every``/``thin_every`` only ever applied at write time, so a
    run recorded at every iteration was stuck at that resolution forever. This
    is the way back — and it is destructive, hence the preview-and-confirm.
    """
    from ..core.storage import preview_metric_prune, prune_metrics, table_byte_sizes
    conn = get_db()

    keep_every = max(1, getattr(args, "keep_every", 1) or 1)
    max_points = max(0, getattr(args, "max_points", 0) or 0)
    if keep_every == 1 and not max_points:
        die("Nothing to do: pass --keep-every N or --max-points N "
            "(e.g. \"exptrack prune --max-points 500\")")

    exp_ids, keys, protect, scope = _resolve_prune_scope(conn, args)

    # One whole-file page scan for the whole command: the preview and the
    # delete both need bytes-per-row, and computing it is not cheap.
    table_bytes = table_byte_sizes(conn)
    metrics_before = table_bytes.get("metrics", 0)
    p = preview_metric_prune(conn, exp_ids or None, keys, keep_every,
                             max_points, protect, table_bytes)
    if not p["points"]:
        print(dim(f"Nothing to prune ({scope}); "
                  f"{p['total_points']:,} points already at or under the target."),
              file=sys.stderr)
        return

    doomed = col(format(p["points"], ","), Y)
    print(f"  Scope:     {scope}", file=sys.stderr)
    print(f"  Would remove: {doomed} of {p['total_points']:,} points "
          f"(~{fmt_bytes(p['freed'])}), leaving {p['remaining']:,}", file=sys.stderr)
    if protect:
        print(dim("  Keeping the first, last, min and max of every series."),
              file=sys.stderr)
    if getattr(args, "dry_run", False):
        print(dim("  Dry run — nothing removed."), file=sys.stderr)
        return
    if not getattr(args, "yes", False) and not _confirm_prune():
        return

    # Delete exactly the previewed set rather than re-deriving it.
    r = prune_metrics(conn, table_bytes=table_bytes, doomed=p["_ids"])
    print(col(f"  Pruned {r['deleted']:,} points (~{fmt_bytes(r['freed'])}).", G),
          file=sys.stderr)

    if getattr(args, "vacuum", False):
        # The one VACUUM implementation — it checkpoints the WAL on both sides,
        # which is load-bearing and non-obvious.
        from .mutate_cmds import _clean_vacuum
        _clean_vacuum(conn)
    else:
        # Deleted pages go to the database's free list, not back to the OS.
        print(dim("  Freed pages are reused as the database grows. "
                  "Run \"exptrack clean --vacuum\" to return them to the filesystem."),
              file=sys.stderr)

    # Derived from the report: re-measuring would be a third whole-file scan
    # for numbers already in hand.
    if metrics_before:
        print(dim(f"  metrics now ~{fmt_bytes(max(0, metrics_before - r['freed']))} "
                  f"across {r['remaining']:,} points."), file=sys.stderr)
