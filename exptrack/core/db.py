"""
exptrack/core/db.py — Database schema, connections, and deletion helpers
"""
from __future__ import annotations
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from .. import config as cfg


# ── Database ──────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    root = cfg.project_root()
    conf = cfg.load()
    p = root / conf.get("db", ".exptrack/experiments.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


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
            groups      TEXT,
            output_dir  TEXT
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
            ts      TEXT
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

    # Add output_dir and groups to experiments if missing
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()}
        if "output_dir" not in cols:
            conn.execute("ALTER TABLE experiments ADD COLUMN output_dir TEXT")
        if "groups" not in cols:
            conn.execute("ALTER TABLE experiments ADD COLUMN groups TEXT")
        if "image_paths" not in cols:
            conn.execute("ALTER TABLE experiments ADD COLUMN image_paths TEXT")
    except sqlite3.OperationalError:
        pass  # column may already exist
    except Exception as e:
        print(f"[exptrack] warning: experiment migration error: {e}", file=sys.stderr)

    conn.commit()


# ── Deletion helpers ──────────────────────────────────────────────────────────

def delete_experiment(conn: sqlite3.Connection, exp_id: str,
                      delete_files: bool = True):
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
                         old_name: str, new_name: str):
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
    actual_dir = str(new_dir) if renamed else None
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
