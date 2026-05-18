"""
exptrack/core/db.py — Database schema, connections, and deletion helpers
"""
from __future__ import annotations

import json
import os
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
    conn.execute("PRAGMA foreign_keys=ON")

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

    Sweeps orphaned rows, checkpoints the WAL, then closes the connection.
    The next get_db() call will open a fresh one.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            _sweep_orphans(conn)
        except (sqlite3.Error, OSError):
            pass  # best-effort cleanup on close
        try:
            # TRUNCATE mode flushes all WAL pages to the DB and then
            # truncates the WAL file to zero bytes.  This is safe because
            # we're about to close the only connection on this thread.
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass  # checkpoint may fail if other connections exist
        try:
            conn.close()
        except sqlite3.Error:
            pass  # connection may already be closed
        _local.conn = None
        _local.db_path = None


def _sweep_orphans(conn: sqlite3.Connection) -> int:
    """Silently delete rows in child tables whose exp_id has no experiment.

    Returns the total number of orphaned rows removed.
    Uses SELECT COUNT checks first to avoid starting implicit transactions
    with zero-row DELETEs (which would dirty pages after VACUUM).
    """
    total = 0
    for table in ("params", "metrics", "artifacts", "timeline"):
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE exp_id NOT IN (SELECT id FROM experiments)"
        ).fetchone()[0]
        if n:
            conn.execute(
                f"DELETE FROM {table} "
                f"WHERE exp_id NOT IN (SELECT id FROM experiments)"
            )
            total += n
    # cell_lineage: remove cells no longer referenced by any timeline row
    n = conn.execute(
        "SELECT COUNT(*) FROM cell_lineage "
        "WHERE cell_hash NOT IN ("
        "  SELECT DISTINCT cell_hash FROM timeline WHERE cell_hash IS NOT NULL"
        ")"
    ).fetchone()[0]
    if n:
        conn.execute(
            "DELETE FROM cell_lineage "
            "WHERE cell_hash NOT IN ("
            "  SELECT DISTINCT cell_hash FROM timeline WHERE cell_hash IS NOT NULL"
            ")"
        )
        total += n
    if total:
        conn.commit()
    return total


def sweep_orphans(conn: sqlite3.Connection) -> dict:
    """Public API for orphan cleanup. Returns counts per table."""
    counts = {}
    for table in ("params", "metrics", "artifacts", "timeline"):
        cur = conn.execute(
            f"DELETE FROM {table} "
            f"WHERE exp_id NOT IN (SELECT id FROM experiments)"
        )
        if cur.rowcount:
            counts[table] = cur.rowcount
    cur = conn.execute(
        "DELETE FROM cell_lineage "
        "WHERE cell_hash NOT IN ("
        "  SELECT DISTINCT cell_hash FROM timeline WHERE cell_hash IS NOT NULL"
        ")"
    )
    if cur.rowcount:
        counts["cell_lineage"] = cur.rowcount
    if counts:
        conn.commit()
    return counts


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

        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            notebook    TEXT,
            status      TEXT DEFAULT 'active',
            git_branch  TEXT,
            git_commit  TEXT,
            created_at  REAL NOT NULL,
            ended_at    REAL
        );

        CREATE TABLE IF NOT EXISTS session_nodes (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL REFERENCES sessions(id),
            parent_id   TEXT REFERENCES session_nodes(id),
            node_type   TEXT NOT NULL,
            label       TEXT NOT NULL,
            note        TEXT,
            cell_source TEXT,
            git_diff    TEXT,
            git_commit  TEXT,
            seq         INTEGER NOT NULL,
            created_at  REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_session_nodes_session
            ON session_nodes(session_id, seq);
        CREATE INDEX IF NOT EXISTS idx_session_nodes_parent
            ON session_nodes(parent_id);
    """)

    # Add session_node_id to experiments if missing
    try:
        ecols = {row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()}
        if "session_node_id" not in ecols:
            conn.execute("ALTER TABLE experiments ADD COLUMN session_node_id TEXT")
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        print(f"[exptrack] warning: session_node_id migration error: {e}", file=sys.stderr)

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

    # Add source column to params (auto vs manual). Backfill existing params
    # on manually-created experiments (hostname/python_ver are NULL there).
    try:
        pcols = {row[1] for row in conn.execute("PRAGMA table_info(params)").fetchall()}
        if "source" not in pcols:
            conn.execute("ALTER TABLE params ADD COLUMN source TEXT DEFAULT 'auto'")
            conn.execute(
                "UPDATE params SET source='manual' WHERE exp_id IN "
                "(SELECT id FROM experiments "
                " WHERE hostname IS NULL AND python_ver IS NULL)"
            )
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        print(f"[exptrack] warning: params source migration error: {e}", file=sys.stderr)

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
        if "deleted_at" not in cols:
            conn.execute("ALTER TABLE experiments ADD COLUMN deleted_at TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_deleted_at ON experiments(deleted_at)")
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
    diff_hash = hashlib.sha256(diff_text.encode()).hexdigest()[:32]
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
                      delete_files: bool = True) -> dict:
    """Delete an experiment and all related DB records.

    If *delete_files* is True, also sends artifact files, the experiment's
    output directory (``outputs/<name>/``), and any notebook history
    snapshots to the OS Trash (with a local ``.exptrack/trash/`` fallback —
    never unlinked outright). Returns a dict of per-bucket trash counts
    (``os_trash`` / ``local_trash`` / ``missing`` / ``failed``), or an empty
    dict when *delete_files* is False.
    """
    file_stats: dict = {}
    if delete_files:
        file_stats = _delete_experiment_files(conn, exp_id)
    for table in ("metrics", "params", "artifacts", "timeline"):
        conn.execute(f"DELETE FROM {table} WHERE exp_id=?", (exp_id,))
    conn.execute("DELETE FROM experiments WHERE id=?", (exp_id,))
    # Remove cell_lineage rows no longer referenced by any remaining timeline.
    # Always do the general check (not just for this experiment's hashes),
    # because cell_lineage is content-addressed and may have entries that
    # were never linked to any timeline row.
    conn.execute("""
        DELETE FROM cell_lineage
        WHERE cell_hash NOT IN (
            SELECT DISTINCT cell_hash FROM timeline
            WHERE cell_hash IS NOT NULL
        )
    """)
    return file_stats


# ── OS-trash helpers ──────────────────────────────────────────────────────────

def _send_to_os_trash(path: Path) -> bool:
    """Move *path* to the user's OS Trash. Returns True on success.

    Uses platform-native mechanisms so the file is recoverable from Finder
    (macOS) or the user's Files app (Linux, XDG spec). Other platforms return
    False so the caller can use a local-trash fallback.
    """
    if not path.exists():
        return False
    abs_path = str(path.resolve())
    plat = sys.platform

    if plat == "darwin":
        import subprocess
        escaped = abs_path.replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "Finder" to delete POSIX file "{escaped}"'
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True, capture_output=True, timeout=20,
            )
            return True
        except Exception as e:
            print(f"[exptrack] warning: osascript trash failed for {path}: {e}",
                  file=sys.stderr)
            return False

    if plat.startswith("linux"):
        # XDG trash spec: $XDG_DATA_HOME/Trash/{files,info}
        import urllib.parse
        from datetime import datetime
        try:
            data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
            trash_root = Path(data_home) / "Trash"
            files_dir = trash_root / "files"
            info_dir = trash_root / "info"
            files_dir.mkdir(parents=True, exist_ok=True)
            info_dir.mkdir(parents=True, exist_ok=True)
            dest = files_dir / path.name
            i = 1
            while dest.exists():
                dest = files_dir / f"{path.name}.{i}"
                i += 1
            shutil.move(abs_path, str(dest))
            info_path = info_dir / (dest.name + ".trashinfo")
            info_path.write_text(
                "[Trash Info]\n"
                f"Path={urllib.parse.quote(abs_path)}\n"
                f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n"
            )
            return True
        except Exception as e:
            print(f"[exptrack] warning: XDG trash failed for {path}: {e}",
                  file=sys.stderr)
            return False

    # Windows / other: no stdlib OS-trash path; caller falls back to local.
    return False


def _trash_or_local(path: Path, label: str = "file") -> str:
    """Send *path* to the OS Trash; on failure, move it to ``.exptrack/trash/``.

    Never falls through to a destructive ``unlink``/``rmtree`` — if both
    OS-trash and local-fallback fail, the file is left alone with a warning.
    Returns one of ``'os_trash'``, ``'local_trash'``, ``'missing'``, ``'failed'``.
    """
    if not path.exists():
        return "missing"
    if _send_to_os_trash(path):
        return "os_trash"
    try:
        local_trash = cfg.project_root() / ".exptrack" / "trash"
        local_trash.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = local_trash / f"{stamp}__{path.name}"
        i = 1
        base = dest
        while dest.exists():
            dest = local_trash / f"{base.name}.{i}"
            i += 1
        shutil.move(str(path), str(dest))
        return "local_trash"
    except Exception as e:
        print(f"[exptrack] warning: could not trash {label} {path}: {e}",
              file=sys.stderr)
        return "failed"


def _delete_experiment_files(conn: sqlite3.Connection, exp_id: str) -> dict:
    """Move artifact files, output directory, and notebook history snapshots
    to the OS Trash (with a local ``.exptrack/trash/`` fallback).

    Returns counts: ``{"os_trash": N, "local_trash": N, "failed": N, "missing": N}``.
    """
    stats = {"os_trash": 0, "local_trash": 0, "failed": 0, "missing": 0}

    def _bump(result: str):
        stats[result] = stats.get(result, 0) + 1

    # Resolve output directories first so we can skip individual artifacts that
    # live inside them (they're handled by the directory move).
    exp_row = conn.execute(
        "SELECT name, output_dir FROM experiments WHERE id=?", (exp_id,)
    ).fetchone()
    output_dirs: list[Path] = []
    if exp_row:
        if exp_row["output_dir"]:
            output_dirs.append(Path(exp_row["output_dir"]))
        if exp_row["name"]:
            try:
                conf = cfg.load()
                output_dirs.append(
                    cfg.project_root() / conf.get("outputs_dir", "outputs") / exp_row["name"]
                )
            except Exception as e:
                print(f"[exptrack] warning: could not resolve output dir: {e}",
                      file=sys.stderr)
    handled_dirs: list[str] = []
    for out_dir in output_dirs:
        try:
            if out_dir.is_dir():
                resolved = str(out_dir.resolve())
                _bump(_trash_or_local(out_dir, label="output dir"))
                handled_dirs.append(resolved)
        except Exception as e:
            print(f"[exptrack] warning: could not process output dir {out_dir}: {e}",
                  file=sys.stderr)

    # Individual artifact files that live OUTSIDE the moved output_dir(s).
    rows = conn.execute(
        "SELECT path FROM artifacts WHERE exp_id=?", (exp_id,)
    ).fetchall()
    for r in rows:
        p = r["path"]
        if not p:
            continue
        try:
            fp = Path(p)
            if not fp.is_file():
                continue
            rp = str(fp.resolve())
            if any(rp == hd or rp.startswith(hd + os.sep) for hd in handled_dirs):
                continue  # already moved with the output directory
            _bump(_trash_or_local(fp, label="artifact"))
        except Exception as e:
            print(f"[exptrack] warning: could not trash artifact {p}: {e}",
                  file=sys.stderr)

    # Notebook history snapshots for this experiment.
    nb_count = _delete_notebook_history(exp_id)
    for k, n in nb_count.items():
        stats[k] = stats.get(k, 0) + n

    return stats


def _delete_notebook_history(exp_id: str) -> dict:
    """Trash notebook history snapshot files belonging to this experiment.

    Returns counts matching ``_trash_or_local`` keys so the caller can
    aggregate per-experiment trash statistics.
    """
    stats = {"os_trash": 0, "local_trash": 0, "failed": 0, "missing": 0}
    try:
        conf = cfg.load()
        root = cfg.project_root()
        hist_root = root / conf.get("notebook_history_dir", ".exptrack/notebook_history")
        if not hist_root.is_dir():
            return stats
        for nb_dir in hist_root.iterdir():
            if not nb_dir.is_dir():
                continue
            for snap_file in nb_dir.glob("*.json"):
                try:
                    import json as _json
                    snap = _json.loads(snap_file.read_text())
                    if snap.get("exp_id") == exp_id:
                        result = _trash_or_local(snap_file, label="notebook snapshot")
                        stats[result] = stats.get(result, 0) + 1
                except Exception as e:
                    print(f"[exptrack] warning: could not process snapshot {snap_file}: {e}", file=sys.stderr)
            # Remove the notebook dir if empty (an empty bookkeeping dir is
            # not worth sending to Trash — just rmdir it).
            try:
                if nb_dir.is_dir() and not any(nb_dir.iterdir()):
                    nb_dir.rmdir()
            except Exception as e:
                print(f"[exptrack] warning: could not remove empty dir {nb_dir}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[exptrack] warning: notebook history cleanup failed: {e}", file=sys.stderr)
    return stats


def trash_experiment(conn: sqlite3.Connection, exp_id: str) -> bool:
    """Soft-delete: mark deleted_at = now(). No file ops, fully reversible."""
    from datetime import datetime, timezone
    cur = conn.execute(
        "UPDATE experiments SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
        (datetime.now(timezone.utc).isoformat(), exp_id),
    )
    return cur.rowcount > 0


def restore_experiment(conn: sqlite3.Connection, exp_id: str) -> bool:
    """Undo soft-delete: clear deleted_at."""
    cur = conn.execute(
        "UPDATE experiments SET deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL",
        (exp_id,),
    )
    return cur.rowcount > 0


def get_delete_preview(conn: sqlite3.Connection, exp_id: str) -> dict:
    """Summarize what permanent deletion of an experiment would remove."""
    exp = conn.execute(
        "SELECT id, name, output_dir, deleted_at FROM experiments WHERE id=?", (exp_id,)
    ).fetchone()
    if not exp:
        return {"error": "not found"}

    n_metrics = conn.execute(
        "SELECT COUNT(*) AS n FROM metrics WHERE exp_id=?", (exp_id,)
    ).fetchone()["n"]
    n_params = conn.execute(
        "SELECT COUNT(*) AS n FROM params WHERE exp_id=?", (exp_id,)
    ).fetchone()["n"]
    n_timeline = conn.execute(
        "SELECT COUNT(*) AS n FROM timeline WHERE exp_id=?", (exp_id,)
    ).fetchone()["n"]

    art_rows = conn.execute(
        "SELECT label, path, size_bytes FROM artifacts WHERE exp_id=?", (exp_id,)
    ).fetchall()
    artifacts: list[dict] = []
    artifact_bytes = 0
    artifact_files_exist = 0
    for r in art_rows:
        p = r["path"] or ""
        exists = False
        size = r["size_bytes"] or 0
        if p:
            try:
                fp = Path(p)
                if fp.is_file():
                    exists = True
                    artifact_files_exist += 1
                    if not size:
                        size = fp.stat().st_size
            except Exception:
                pass
        artifact_bytes += size
        artifacts.append({
            "label": r["label"] or "",
            "path": p,
            "size_bytes": size,
            "exists": exists,
        })

    output_dir = exp["output_dir"] or ""
    output_dir_exists = False
    output_dir_bytes = 0
    output_dir_files = 0
    candidates: list[Path] = []
    if output_dir:
        candidates.append(Path(output_dir))
    if exp["name"]:
        try:
            conf = cfg.load()
            candidates.append(
                cfg.project_root() / conf.get("outputs_dir", "outputs") / exp["name"]
            )
        except Exception:
            pass
    for d in candidates:
        try:
            if d.is_dir():
                output_dir_exists = True
                if not output_dir:
                    output_dir = str(d)
                for sub in d.rglob("*"):
                    try:
                        if sub.is_file():
                            output_dir_files += 1
                            output_dir_bytes += sub.stat().st_size
                    except Exception:
                        pass
                break
        except Exception:
            pass

    n_history = 0
    try:
        conf = cfg.load()
        hist_root = cfg.project_root() / conf.get(
            "notebook_history_dir", ".exptrack/notebook_history"
        )
        if hist_root.is_dir():
            for nb_dir in hist_root.iterdir():
                if not nb_dir.is_dir():
                    continue
                for snap in nb_dir.glob("*.json"):
                    try:
                        import json as _json
                        if _json.loads(snap.read_text()).get("exp_id") == exp_id:
                            n_history += 1
                    except Exception:
                        pass
    except Exception:
        pass

    return {
        "id": exp["id"],
        "name": exp["name"] or "",
        "deleted_at": exp["deleted_at"],
        "metrics_count": n_metrics,
        "params_count": n_params,
        "timeline_count": n_timeline,
        "artifacts_count": len(artifacts),
        "artifacts_existing": artifact_files_exist,
        "artifacts": artifacts,
        "artifact_bytes": artifact_bytes,
        "output_dir": output_dir,
        "output_dir_exists": output_dir_exists,
        "output_dir_files": output_dir_files,
        "output_dir_bytes": output_dir_bytes,
        "notebook_history_count": n_history,
    }


def list_trashed_experiments(conn: sqlite3.Connection) -> list[dict]:
    """List experiments soft-deleted via trash_experiment, newest-trashed first."""
    rows = conn.execute(
        "SELECT id, name, status, created_at, deleted_at, "
        "       git_branch, git_commit, output_dir, tags, studies "
        "FROM experiments WHERE deleted_at IS NOT NULL "
        "ORDER BY deleted_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


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
