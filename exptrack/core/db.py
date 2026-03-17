"""
exptrack/core/db.py — Database schema, connections, and deletion helpers
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys

# ── Database ──────────────────────────────────────────────────────────────────
import threading
from pathlib import Path

from .. import config as cfg

_local = threading.local()


def get_db() -> sqlite3.Connection:
    """Return a cached per-thread database connection.

    Reuses the same connection across calls within a thread (important for
    long-lived processes like notebooks where start() may be called many times).
    """
    # Check for a cached connection that's still alive
    conn = getattr(_local, "conn", None)
    db_path = getattr(_local, "db_path", None)

    root = cfg.project_root()
    conf = cfg.load()
    p = root / conf.get("db", ".exptrack/experiments.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    p_str = str(p)

    if conn is not None and db_path == p_str:
        # Verify the connection is still usable
        try:
            conn.execute("SELECT 1")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            _local.conn = None

    # Warn if WAL/SHM files are missing when DB exists (potential corruption)
    if p.exists():
        wal = Path(str(p) + "-wal")
        shm = Path(str(p) + "-shm")
        if wal.exists() and not shm.exists():
            print("[exptrack] warning: WAL file exists without SHM file — "
                  "database may be in an inconsistent state", file=sys.stderr)

    conn = sqlite3.connect(p_str, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    # Quick integrity check on first open
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()
        if result and result[0] != "ok":
            print(f"[exptrack] warning: database integrity check failed: {result[0]}",
                  file=sys.stderr)
    except Exception as e:
        print(f"[exptrack] warning: could not check database integrity: {e}",
              file=sys.stderr)

    _ensure_schema(conn)
    _local.conn = conn
    _local.db_path = p_str
    return conn


def close_db() -> None:
    """Close the cached database connection for the current thread.

    Call this to release any lingering connections, e.g. from a notebook
    cell: `from exptrack.core import close_db; close_db()`

    The next get_db() call will open a fresh connection.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None
        _local.db_path = None


def _ensure_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS experiments (
            id          TEXT PRIMARY KEY,
            project     TEXT,
            name        TEXT NOT NULL,
            status      TEXT DEFAULT 'running',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            script      TEXT,
            command     TEXT,
            git_branch  TEXT,
            git_commit  TEXT,
            git_diff    TEXT,
            hostname    TEXT,
            python_ver  TEXT,
            duration_s  REAL,
            notes       TEXT,
            tags        TEXT,
            studies     TEXT,
            output_dir  TEXT,
            stage       INTEGER,
            stage_name  TEXT
        );
        CREATE TABLE IF NOT EXISTS params (
            exp_id  TEXT NOT NULL REFERENCES experiments(id),
            key     TEXT NOT NULL,
            value   TEXT,
            PRIMARY KEY (exp_id, key)
        );
        CREATE TABLE IF NOT EXISTS metrics (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            exp_id  TEXT NOT NULL REFERENCES experiments(id),
            key     TEXT NOT NULL,
            value   REAL,
            step    INTEGER,
            ts      TEXT,
            source  TEXT DEFAULT 'auto'
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            exp_id      TEXT NOT NULL REFERENCES experiments(id),
            label       TEXT,
            path        TEXT,
            created_at  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_metrics_exp ON metrics(exp_id, key);
        CREATE INDEX IF NOT EXISTS idx_params_exp  ON params(exp_id);

        CREATE INDEX IF NOT EXISTS idx_exp_created  ON experiments(created_at);
        CREATE INDEX IF NOT EXISTS idx_exp_status   ON experiments(status);
        CREATE INDEX IF NOT EXISTS idx_artifacts_exp ON artifacts(exp_id);

        CREATE TABLE IF NOT EXISTS code_baselines (
            notebook    TEXT NOT NULL,
            cell_seq    INTEGER NOT NULL,
            source      TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (notebook, cell_seq)
        );

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

        CREATE TABLE IF NOT EXISTS cell_lineage (
            cell_hash   TEXT PRIMARY KEY,
            notebook    TEXT NOT NULL,
            source      TEXT NOT NULL,
            parent_hash TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS git_diffs (
            diff_hash   TEXT PRIMARY KEY,
            diff_text   TEXT NOT NULL,
            file_list   TEXT,
            created_at  TEXT NOT NULL
        );
    """)

    # Add timeline_seq, content_hash, size_bytes to artifacts if missing
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        if "timeline_seq" not in cols:
            conn.execute("ALTER TABLE artifacts ADD COLUMN timeline_seq INTEGER")
        if "content_hash" not in cols:
            conn.execute("ALTER TABLE artifacts ADD COLUMN content_hash TEXT")
        if "size_bytes" not in cols:
            conn.execute("ALTER TABLE artifacts ADD COLUMN size_bytes INTEGER")
    except sqlite3.OperationalError:
        pass  # column may already exist
    except Exception as e:
        print(f"[exptrack] warning: artifact migration error: {e}", file=sys.stderr)

    # Add source column to metrics and migrate _result:* params
    try:
        mcols = {row[1] for row in conn.execute("PRAGMA table_info(metrics)").fetchall()}
        if "source" not in mcols:
            conn.execute("ALTER TABLE metrics ADD COLUMN source TEXT DEFAULT 'auto'")
            # Migrate existing _result:* params into metrics table
            result_params = conn.execute(
                "SELECT exp_id, key, value FROM params WHERE key LIKE '_result:%'"
            ).fetchall()
            if result_params:
                from datetime import datetime, timezone
                ts = datetime.now(timezone.utc).isoformat()
                conn.executemany(
                    "INSERT INTO metrics (exp_id, key, value, step, ts, source) "
                    "VALUES (?,?,?,NULL,?,?)",
                    [(r["exp_id"], r["key"][8:], float(json.loads(r["value"])),
                      ts, "manual") for r in result_params]
                )
                conn.execute("DELETE FROM params WHERE key LIKE '_result:%'")
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        print(f"[exptrack] warning: metrics source migration error: {e}", file=sys.stderr)

    # Add output_dir, studies, stage columns to experiments if missing
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()}
        if "output_dir" not in cols:
            conn.execute("ALTER TABLE experiments ADD COLUMN output_dir TEXT")
        if "studies" not in cols:
            conn.execute("ALTER TABLE experiments ADD COLUMN studies TEXT")
            # Migrate data from old 'groups' column if it exists
            if "groups" in cols:
                conn.execute("UPDATE experiments SET studies = groups WHERE groups IS NOT NULL")
        if "stage" not in cols:
            conn.execute("ALTER TABLE experiments ADD COLUMN stage INTEGER")
        if "stage_name" not in cols:
            conn.execute("ALTER TABLE experiments ADD COLUMN stage_name TEXT")
        if "image_paths" not in cols:
            conn.execute("ALTER TABLE experiments ADD COLUMN image_paths TEXT")
        if "log_paths" not in cols:
            conn.execute("ALTER TABLE experiments ADD COLUMN log_paths TEXT")
        # Drop old 'groups' column if it exists (renamed to 'studies')
        if "groups" in cols:
            try:
                conn.execute("ALTER TABLE experiments DROP COLUMN groups")
            except sqlite3.OperationalError:
                pass  # SQLite < 3.35 doesn't support DROP COLUMN; harmless dead column
    except sqlite3.OperationalError:
        pass  # column may already exist
    except Exception as e:
        print(f"[exptrack] warning: experiment migration error: {e}", file=sys.stderr)

    conn.commit()


# ── Git diff deduplication ────────────────────────────────────────────────────

def resolve_git_diff(conn: sqlite3.Connection, raw_diff: str | None) -> str:
    """Resolve git_diff — inline text, a [ref:sha256:...] pointer, or a [compacted...] marker."""
    if not raw_diff:
        return ""
    if raw_diff.startswith("[ref:sha256:"):
        h = raw_diff[12:-1]
        row = conn.execute(
            "SELECT diff_text FROM git_diffs WHERE diff_hash=?", (h,)
        ).fetchone()
        return row["diff_text"] if row else raw_diff
    return raw_diff


def store_git_diff(conn: sqlite3.Connection, diff_text: str) -> str:
    """Store diff text in git_diffs table (deduped) and return a reference marker."""
    import hashlib
    from datetime import datetime, timezone
    diff_hash = hashlib.sha256(diff_text.encode()).hexdigest()[:16]
    # Extract file list for summary
    files = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 4:
                files.append(parts[3].lstrip("b/"))
    conn.execute(
        "INSERT OR IGNORE INTO git_diffs (diff_hash, diff_text, file_list, created_at) "
        "VALUES (?, ?, ?, ?)",
        (diff_hash, diff_text, json.dumps(files) if files else None,
         datetime.now(timezone.utc).isoformat()),
    )
    return f"[ref:sha256:{diff_hash}]"


# ── Deletion helpers ──────────────────────────────────────────────────────────

def delete_experiment(conn: sqlite3.Connection, exp_id: str,
                      delete_files: bool = True) -> None:
    """Delete an experiment and all related DB records.

    If *delete_files* is True, also removes artifact files on disk, the
    experiment's output directory (``outputs/<name>/``), and any notebook
    history snapshots tied to this experiment.
    """
    if delete_files:
        _delete_experiment_files(conn, exp_id)
    for table in ("metrics", "params", "artifacts", "timeline"):
        conn.execute(f"DELETE FROM {table} WHERE exp_id=?", (exp_id,))
    conn.execute("DELETE FROM experiments WHERE id=?", (exp_id,))


def _delete_experiment_files(conn: sqlite3.Connection, exp_id: str):
    """Remove artifact files, the experiment output directory, and notebook
    history snapshot files from disk."""
    # Delete individual artifact files
    rows = conn.execute(
        "SELECT path FROM artifacts WHERE exp_id=?", (exp_id,)
    ).fetchall()
    for r in rows:
        p = r["path"]
        if not p:
            continue
        try:
            fp = Path(p)
            if fp.is_file():
                fp.unlink()
        except Exception as e:
            print(f"[exptrack] warning: could not delete artifact {p}: {e}", file=sys.stderr)

    # Delete the experiment's output directory
    exp_row = conn.execute(
        "SELECT name, output_dir FROM experiments WHERE id=?", (exp_id,)
    ).fetchone()
    if exp_row:
        dirs_to_try = []
        # Prefer the tracked output_dir (survives renames)
        if exp_row["output_dir"]:
            dirs_to_try.append(Path(exp_row["output_dir"]))
        # Also try the name-based path as fallback
        if exp_row["name"]:
            try:
                conf = cfg.load()
                dirs_to_try.append(
                    cfg.project_root() / conf.get("outputs_dir", "outputs") / exp_row["name"]
                )
            except Exception as e:
                print(f"[exptrack] warning: could not resolve output dir: {e}", file=sys.stderr)
        for out_dir in dirs_to_try:
            try:
                if out_dir.is_dir():
                    shutil.rmtree(str(out_dir), ignore_errors=True)
            except Exception as e:
                print(f"[exptrack] warning: could not remove output dir {out_dir}: {e}", file=sys.stderr)

    # Delete notebook history snapshots for this experiment
    _delete_notebook_history(exp_id)


def _delete_notebook_history(exp_id: str):
    """Remove notebook history snapshot files belonging to this experiment."""
    try:
        conf = cfg.load()
        root = cfg.project_root()
        hist_root = root / conf.get("notebook_history_dir", ".exptrack/notebook_history")
        if not hist_root.is_dir():
            return
        for nb_dir in hist_root.iterdir():
            if not nb_dir.is_dir():
                continue
            for snap_file in nb_dir.glob("*.json"):
                try:
                    import json as _json
                    snap = _json.loads(snap_file.read_text())
                    if snap.get("exp_id") == exp_id:
                        snap_file.unlink()
                except Exception as e:
                    print(f"[exptrack] warning: could not process snapshot {snap_file}: {e}", file=sys.stderr)
            # Remove the notebook dir if empty
            try:
                if nb_dir.is_dir() and not any(nb_dir.iterdir()):
                    nb_dir.rmdir()
            except Exception as e:
                print(f"[exptrack] warning: could not remove empty dir {nb_dir}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[exptrack] warning: notebook history cleanup failed: {e}", file=sys.stderr)


def rename_output_folder(conn: sqlite3.Connection, exp_id: str,
                         old_name: str, new_name: str) -> None:
    """Rename the output folder on disk and update artifact paths + output_dir.

    Called when an experiment is renamed so the output directory stays in sync.
    If the folder can't be renamed (e.g. doesn't exist), falls back to
    tracking by experiment ID.
    """
    conf = cfg.load()
    outputs_base = cfg.project_root() / conf.get("outputs_dir", "outputs")
    old_dir = outputs_base / old_name
    new_dir = outputs_base / new_name

    renamed = False
    if old_dir.is_dir() and not new_dir.exists():
        try:
            old_dir.rename(new_dir)
            renamed = True
        except OSError:
            pass

    # Update output_dir in experiments table
    if renamed:
        conn.execute("UPDATE experiments SET output_dir=? WHERE id=?",
                     (str(new_dir), exp_id))
    elif old_dir.is_dir():
        # Couldn't rename — keep tracking the old path by ID
        conn.execute("UPDATE experiments SET output_dir=? WHERE id=?",
                     (str(old_dir), exp_id))

    # Update artifact paths that lived inside the old output directory
    if renamed:
        old_prefix = str(old_dir)
        rows = conn.execute(
            "SELECT id, path FROM artifacts WHERE exp_id=?", (exp_id,)
        ).fetchall()
        for r in rows:
            if r["path"] and r["path"].startswith(old_prefix):
                new_path = str(new_dir) + r["path"][len(old_prefix):]
                conn.execute("UPDATE artifacts SET path=? WHERE id=?",
                             (new_path, r["id"]))


def finish_experiment(exp_id: str) -> bool:
    """Manually mark any experiment as done by ID (prefix match).

    Useful from scripts that manage experiments externally.
    Returns True if the experiment was updated, False if not found or already done.
    """
    from datetime import datetime, timezone
    conn = get_db()
    exp = conn.execute(
        "SELECT id, status, created_at FROM experiments WHERE id LIKE ?",
        (exp_id + "%",)
    ).fetchone()
    if not exp or exp["status"] == "done":
        return False
    now = datetime.now(timezone.utc).isoformat()
    duration = (datetime.fromisoformat(now) -
                datetime.fromisoformat(exp["created_at"])).total_seconds()
    conn.execute("""
        UPDATE experiments SET status='done', updated_at=?, duration_s=? WHERE id=?
    """, (now, duration, exp["id"]))
    conn.commit()
    return True
