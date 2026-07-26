"""
exptrack/core/db.py — Database schema, connections, and deletion helpers
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys

# ── Database ──────────────────────────────────────────────────────────────────
import threading
from pathlib import Path

from .. import config as cfg
from .utils import debug_log, safe_call

_local = threading.local()

# Schema generation stamp, stored in the SQLite ``user_version`` pragma.
# When a database's stored version matches, ``_ensure_schema`` (and the
# open-time ``quick_check``) are skipped entirely — the migration helpers are
# all idempotent, but re-probing every table on every fresh connection is
# wasted work in the steady state.
#
# BUMP THIS by +1 whenever the schema changes (new table/column/index in
# ``_create_base_schema`` or a new/changed ``_migrate_*`` helper), otherwise
# existing databases will never see the new migration. ``exptrack upgrade``
# always forces a full re-run regardless of the stamp.
_SCHEMA_VERSION = 3


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
        except Exception as e:
            # Cached connection went stale (db replaced, WAL reset, etc.).
            # Drop it and reconnect below; surface under EXPTRACK_DEBUG.
            debug_log(f"db: cached connection unusable, reconnecting: "
                      f"{type(e).__name__}: {e}")
            safe_call(conn.close, context="db: closing stale connection")
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

    # A matching schema stamp means this exptrack version has already opened
    # (and integrity-checked + migrated) this DB — skip both the full-file
    # quick_check scan and the per-table migration probes.
    if _stored_schema_version(conn) != _SCHEMA_VERSION:
        # Quick integrity check on first open of a new/pre-upgrade database
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


def close_db(sweep: bool = True) -> None:
    """Close the cached database connection for the current thread.

    Optionally sweeps orphaned rows, checkpoints the WAL, then closes the
    connection. The next get_db() call will open a fresh one.

    Pass ``sweep=False`` on hot paths that cannot create orphans —
    finishing/failing a run only UPDATEs its own row, so the anti-join
    COUNT scans over params/metrics/timeline are wasted work there. Orphans
    only appear after deletes; the CLI-exit close and ``exptrack clean``
    keep sweeping.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        if sweep:
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


# (table, WHERE-condition) pairs identifying orphaned child rows. Table/column
# names are fixed constants here — never user input — so the f-strings below are
# injection-safe.
_ORPHAN_SPECS = (
    ("params", "exp_id NOT IN (SELECT id FROM experiments)"),
    ("metrics", "exp_id NOT IN (SELECT id FROM experiments)"),
    ("artifacts", "exp_id NOT IN (SELECT id FROM experiments)"),
    ("timeline", "exp_id NOT IN (SELECT id FROM experiments)"),
    # cell_lineage: cells no longer referenced by any timeline row
    ("cell_lineage",
     "cell_hash NOT IN (SELECT DISTINCT cell_hash FROM timeline "
     "WHERE cell_hash IS NOT NULL)"),
)

# git_diffs: diff bodies no longer pointed at by any [ref:sha256:…] marker, on
# either an experiment or a session node.
_GIT_DIFFS_ORPHAN_COND = (
    "'[ref:sha256:' || diff_hash || ']' NOT IN ("
    "  SELECT git_diff FROM experiments WHERE git_diff LIKE '[ref:sha256:%'"
    "  UNION ALL"
    "  SELECT git_diff FROM session_nodes WHERE git_diff LIKE '[ref:sha256:%')"
)

# The two content-addressed blob tables are swept by *reference*, not by exp_id:
# a row survives while any live row still points at its hash. Trashed
# experiments still occupy `experiments`, so a soft-deleted run keeps its blobs
# (Restore must be lossless); only a permanent delete drops the last reference.
#
# They are kept out of `_ORPHAN_SPECS` — and off the `close_db` sweep — because
# neither can go stale without a delete, and both are expensive to check: the
# git_diffs condition full-scans experiments ∪ session_nodes (no index can serve
# a LIKE prefix over two tables), and the snapshot check reads every
# `_code_snapshot` param into Python. `delete_experiment` reclaims them inline,
# so paying that on every `exptrack` command exit bought a guaranteed zero.
# Matches a snapshot hash as written by ``store_code_snapshot`` (sha256[:16]).
_SNAPSHOT_HASH_RE = re.compile(r"\b[0-9a-f]{16}\b")


def _referenced_snapshot_hashes(conn: sqlite3.Connection) -> set[str]:
    """Every ``code_snapshots.hash`` still referenced by a ``_code_snapshot`` param.

    Scans the raw param text for hash-shaped tokens rather than decoding it: the
    value has had three shapes (a JSON list of ``{hash, kind, path}``, a
    double-encoded version of the same, and a pre-encoded JSON string from
    pipeline runs). Over-retention is harmless — the blob survives another sweep
    — while under-retention destroys a run's only copy of its source, so the
    scan is deliberately a superset of any single decoder.
    """
    refs: set[str] = set()
    for (value,) in conn.execute(
        "SELECT value FROM params WHERE key='_code_snapshot' AND value IS NOT NULL"
    ):
        refs.update(_SNAPSHOT_HASH_RE.findall(value))
    return refs


def _unreferenced_snapshots(conn: sqlite3.Connection) -> set[str]:
    """Hashes in ``code_snapshots`` that no run references any more."""
    stored = {h for (h,) in conn.execute("SELECT hash FROM code_snapshots")}
    return stored - _referenced_snapshot_hashes(conn) if stored else set()


def _sweep_blobs(conn: sqlite3.Connection) -> dict[str, int]:
    """Delete unreferenced content-addressed blobs. Returns per-table counts."""
    counts: dict[str, int] = {}
    dead = _unreferenced_snapshots(conn)
    if dead:
        conn.executemany("DELETE FROM code_snapshots WHERE hash=?",
                         [(h,) for h in dead])
        counts["code_snapshots"] = len(dead)
    n = conn.execute(
        f"SELECT COUNT(*) FROM git_diffs WHERE {_GIT_DIFFS_ORPHAN_COND}"
    ).fetchone()[0]
    if n:
        conn.execute(f"DELETE FROM git_diffs WHERE {_GIT_DIFFS_ORPHAN_COND}")
        counts["git_diffs"] = n
    return counts


def count_orphans(conn: sqlite3.Connection, blobs: bool = True) -> dict[str, int]:
    """Count what a sweep would remove, per table, without deleting anything.

    Built from the same specs as :func:`sweep_orphans` so a preview / dry-run
    and the deletion can't disagree about what an orphan is.
    """
    counts = {}
    for table, cond in _ORPHAN_SPECS:
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {cond}").fetchone()[0]
        if n:
            counts[table] = n
    if blobs:
        n_snaps = len(_unreferenced_snapshots(conn))
        if n_snaps:
            counts["code_snapshots"] = n_snaps
        n_diffs = conn.execute(
            f"SELECT COUNT(*) FROM git_diffs WHERE {_GIT_DIFFS_ORPHAN_COND}"
        ).fetchone()[0]
        if n_diffs:
            counts["git_diffs"] = n_diffs
    return counts


def _sweep_orphans_counts(conn: sqlite3.Connection,
                          blobs: bool = True) -> dict[str, int]:
    """Delete orphaned child rows, returning ``{table: rows_deleted}``.

    COUNTs before each DELETE so a zero-row sweep never starts an implicit
    transaction (which would dirty pages right after a VACUUM). Pass
    ``blobs=False`` to skip the expensive reference-counted blob tables (see
    ``_GIT_DIFFS_ORPHAN_COND``).
    """
    counts: dict[str, int] = {}
    for table, cond in _ORPHAN_SPECS:
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {cond}").fetchone()[0]
        if n:
            conn.execute(f"DELETE FROM {table} WHERE {cond}")
            counts[table] = n
    if blobs:
        counts.update(_sweep_blobs(conn))
    if counts:
        conn.commit()
    return counts


def _sweep_orphans(conn: sqlite3.Connection) -> int:
    """Silently delete orphaned child rows; return the total removed.

    The ``close_db`` path, so blob tables are skipped — they can only go stale
    after a delete, which reclaims them inline.
    """
    return sum(_sweep_orphans_counts(conn, blobs=False).values())


def sweep_orphans(conn: sqlite3.Connection, blobs: bool = True) -> dict:
    """Public API for orphan cleanup. Returns counts per table."""
    return _sweep_orphans_counts(conn, blobs=blobs)


def _stored_schema_version(conn) -> int:
    """Read the DB's schema stamp (``PRAGMA user_version``); 0 on any error."""
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    except Exception:
        return 0


def _ensure_schema(conn, force: bool = False):
    """Create the base schema and apply idempotent column migrations.

    Each ``_migrate_*`` helper checks column existence (PRAGMA table_info)
    before issuing an ALTER, so this is safe to run on every connection and
    on every ``exptrack upgrade``. Helpers are individually wrapped so a
    failure in one table's migration doesn't abort the others, and each is
    small enough to test in isolation.

    A DB whose ``user_version`` stamp already equals ``_SCHEMA_VERSION`` is
    skipped entirely (the steady-state fast path) unless *force* is True —
    ``exptrack upgrade`` forces a full re-run so a manual upgrade always
    re-verifies every table.
    """
    if not force and _stored_schema_version(conn) == _SCHEMA_VERSION:
        return
    _create_base_schema(conn)
    _migrate_sessions(conn)
    _migrate_session_nodes(conn)
    _migrate_experiment_session_link(conn)
    _migrate_artifacts(conn)
    _migrate_metrics(conn)
    _migrate_params(conn)
    _migrate_experiments(conn)
    # Stamp the DB so future connections skip the probes above. Constant is
    # a module-level int — never user input — so the f-string is safe
    # (PRAGMA doesn't accept bound parameters).
    conn.execute(f"PRAGMA user_version = {int(_SCHEMA_VERSION)}")
    conn.commit()


def _create_base_schema(conn):
    """Create all tables and indexes if they don't already exist (idempotent)."""
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
        CREATE INDEX IF NOT EXISTS idx_cell_lineage_notebook
            ON cell_lineage(notebook);

        CREATE TABLE IF NOT EXISTS git_diffs (
            diff_hash   TEXT PRIMARY KEY,
            diff_text   TEXT NOT NULL,
            file_list   TEXT,
            created_at  TEXT NOT NULL
        );

        -- Content-addressed source snapshots (L3): the full text of a run's
        -- script + any small untracked files it needed + the calling shell
        -- script. Deduped by content hash, so ten unchanged re-runs store one
        -- copy. Never holds .ipynb documents (notebook state is captured as
        -- cell records). A run references its snapshots via the _code_snapshot
        -- param (a JSON list of {hash, kind, path}).
        CREATE TABLE IF NOT EXISTS code_snapshots (
            hash        TEXT PRIMARY KEY,
            content     TEXT NOT NULL,
            kind        TEXT NOT NULL,
            path        TEXT,
            size_bytes  INTEGER,
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
            cell_outputs TEXT,
            setup_source TEXT,
            setup_outputs TEXT,
            images      TEXT,
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


def _table_columns(conn, table):
    """Return the set of existing column names for *table*."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_columns(conn, table, columns, existing=None):
    """Idempotently add any missing *columns* to *table*.

    *columns* maps column name → the DDL fragment that follows
    ``ADD COLUMN <name>`` (e.g. ``"TEXT"``, ``"INTEGER DEFAULT 0"``). Only
    columns absent from the table are added. Returns the set of column names
    actually added, so callers can gate one-time backfills / index creation on
    a *real* migration (an already-migrated DB returns an empty set, the
    property the idempotency tests assert).

    Pass *existing* (a pre-fetched column-name set) when the caller already
    snapshotted the table, to avoid a redundant ``PRAGMA table_info`` query.
    """
    if existing is None:
        existing = _table_columns(conn, table)
    added = set()
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            added.add(name)
    return added


def _migrate_sessions(conn):
    # Soft-delete column for whole sessions (Trash + restore), mirroring the
    # session_nodes / experiments soft-delete pattern. Non-null deleted_at = the
    # session is trashed (recoverable); a permanent purge hard-deletes the rows.
    try:
        added = _add_columns(conn, "sessions", {"deleted_at": "REAL"})
        if "deleted_at" in added:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_deleted "
                "ON sessions(deleted_at)"
            )
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        print(f"[exptrack] warning: sessions migration error: {e}",
              file=sys.stderr)


def _migrate_session_nodes(conn):
    # Soft-delete column + per-cell output capture for session_nodes.
    #   deleted_at    — soft-delete / Trash marker
    #   cell_outputs  — mirrors cell_source: one SEP-joined output per cell, so
    #                   the dashboard can show "what the branch produced"
    #   setup_source / setup_outputs — *demoted* parallel to cell_source for
    #                   %%setup prep cells (own byte budget, kept out of lineage)
    #   images        — JSON list of by-reference plot paths saved on the node
    try:
        added = _add_columns(conn, "session_nodes", {
            "deleted_at": "REAL",
            "cell_outputs": "TEXT",
            "setup_source": "TEXT",
            "setup_outputs": "TEXT",
            "images": "TEXT",
        })
        if "deleted_at" in added:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_session_nodes_deleted "
                "ON session_nodes(session_id, deleted_at)"
            )
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        print(f"[exptrack] warning: session_nodes migration error: {e}",
              file=sys.stderr)


def _migrate_experiment_session_link(conn):
    # Add session_node_id to experiments if missing
    try:
        _add_columns(conn, "experiments", {"session_node_id": "TEXT"})
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        print(f"[exptrack] warning: session_node_id migration error: {e}", file=sys.stderr)


def _migrate_artifacts(conn):
    # Add timeline_seq, content_hash, size_bytes to artifacts if missing
    try:
        _add_columns(conn, "artifacts", {
            "timeline_seq": "INTEGER",
            "content_hash": "TEXT",
            "size_bytes": "INTEGER",
        })
    except sqlite3.OperationalError:
        pass  # column may already exist
    except Exception as e:
        print(f"[exptrack] warning: artifact migration error: {e}", file=sys.stderr)


def _migrate_metrics(conn):
    # Add source column to metrics and migrate _result:* params
    try:
        added = _add_columns(conn, "metrics", {"source": "TEXT DEFAULT 'auto'"})
        if "source" in added:
            # Migrate existing _result:* params into metrics table. Per-row
            # tolerant: one un-parseable value must not abort the whole backfill,
            # because the `source` column already exists after this so a future
            # connection skips this block entirely — a single bad row would
            # otherwise strand *every* _result:* param forever. Only rows that
            # migrate successfully are deleted; bad ones stay in params.
            result_params = conn.execute(
                "SELECT exp_id, key, value FROM params WHERE key LIKE '_result:%'"
            ).fetchall()
            if result_params:
                from datetime import datetime, timezone
                ts = datetime.now(timezone.utc).isoformat()
                migrated, to_delete = [], []
                for r in result_params:
                    try:
                        val = float(json.loads(r["value"]))
                    except Exception:
                        print(f"[exptrack] warning: could not migrate param "
                              f"{r['key']!r} to metrics", file=sys.stderr)
                        continue
                    migrated.append((r["exp_id"], r["key"][8:], val, ts, "manual"))
                    to_delete.append((r["exp_id"], r["key"]))
                if migrated:
                    conn.executemany(
                        "INSERT INTO metrics (exp_id, key, value, step, ts, source) "
                        "VALUES (?,?,?,NULL,?,?)", migrated)
                    conn.executemany(
                        "DELETE FROM params WHERE exp_id=? AND key=?", to_delete)
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        print(f"[exptrack] warning: metrics source migration error: {e}", file=sys.stderr)


def _migrate_params(conn):
    # Add source column to params (auto vs manual). Backfill existing params
    # on manually-created experiments (hostname/python_ver are NULL there).
    try:
        added = _add_columns(conn, "params", {"source": "TEXT DEFAULT 'auto'"})
        if "source" in added:
            conn.execute(
                "UPDATE params SET source='manual' WHERE exp_id IN "
                "(SELECT id FROM experiments "
                " WHERE hostname IS NULL AND python_ver IS NULL)"
            )
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        print(f"[exptrack] warning: params source migration error: {e}", file=sys.stderr)


def _migrate_experiments(conn):
    # Add output_dir, studies, stage columns to experiments if missing
    try:
        cols = _table_columns(conn, "experiments")  # snapshot for the 'groups' checks
        added = _add_columns(conn, "experiments", {
            "output_dir": "TEXT",
            "studies": "TEXT",
            "stage": "INTEGER",
            "stage_name": "TEXT",
            "image_paths": "TEXT",
            "log_paths": "TEXT",
            "deleted_at": "TEXT",
            # 1 = run still carries its generated name (never renamed by the user).
            "name_is_auto": "INTEGER DEFAULT 0",
        }, existing=cols)
        # Migrate data from old 'groups' column into the new 'studies' column
        if "studies" in added and "groups" in cols:
            conn.execute("UPDATE experiments SET studies = groups WHERE groups IS NOT NULL")
        if "deleted_at" in added:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_deleted_at ON experiments(deleted_at)")
        if "name_is_auto" in added:
            # Backfill the existing backlog: flag rows whose name still matches
            # the generated-name fingerprint so old un-renamed runs surface too.
            try:
                from .naming import looks_auto_named
                rows = conn.execute("SELECT id, name FROM experiments").fetchall()
                auto_ids = [(r[0],) for r in rows if looks_auto_named(r[1] or "")]
                if auto_ids:
                    conn.executemany(
                        "UPDATE experiments SET name_is_auto=1 WHERE id=?", auto_ids
                    )
            except Exception as e:
                print(f"[exptrack] warning: name_is_auto backfill error: {e}", file=sys.stderr)
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


# ── Git diff deduplication ────────────────────────────────────────────────────

# A stored ``[ref:sha256:…]`` pointer whose git_diffs row no longer exists. The
# diff body is unrecoverable, which is distinct from an empty diff ("no
# changes"), a failed capture (``core.git.CAPTURE_FAILED``) and a deliberate
# ``[compacted…]`` strip — so it carries its own marker rather than falling back
# to the raw pointer text.
DIFF_UNAVAILABLE = "[diff-unavailable]"

# Prefix of the marker `exptrack compact` leaves in place of a stripped diff.
COMPACT_PREFIX = "[compacted"


def is_diff_sentinel(diff: str | None) -> bool:
    """True when a git_diff value is a status marker rather than diff text.

    The three markers — ``[capture-failed]``, ``[diff-unavailable]`` and
    ``[compacted …]`` — each say "there is no diff body here, for this reason".
    None of them may be measured, rendered, exported or compacted as content.
    Lives beside :func:`resolve_git_diff`, which produces two of them, so a
    caller can classify what it just resolved without reaching into another
    layer; works on a raw column value as well as a resolved one.
    """
    from .git import CAPTURE_FAILED
    return bool(diff) and (diff in (CAPTURE_FAILED, DIFF_UNAVAILABLE)
                           or diff.startswith(COMPACT_PREFIX))


def diff_sentinel_kind(diff: str | None) -> str | None:
    """Classify a sentinel for the client: ``capture_failed`` / ``unavailable``
    / ``compacted``, else None. Lets the dashboard branch on a field instead of
    re-hardcoding the marker strings in JS."""
    from .git import CAPTURE_FAILED
    if not diff:
        return None
    if diff == CAPTURE_FAILED:
        return "capture_failed"
    if diff == DIFF_UNAVAILABLE:
        return "unavailable"
    if diff.startswith(COMPACT_PREFIX):
        return "compacted"
    return None

def diff_b_path(token: str) -> str:
    """Strip the leading ``b/`` from a ``diff --git a/… b/…`` right-hand path.

    Uses a prefix check, not ``str.lstrip("b/")`` — lstrip strips a *char set*,
    so ``b/backbone.py`` would wrongly become ``ackbone.py``.
    """
    return token[2:] if token.startswith("b/") else token


def resolve_git_diff(conn: sqlite3.Connection, raw_diff: str | None) -> str:
    """Resolve git_diff — inline text, a [ref:sha256:...] pointer, or a [compacted...] marker.

    A pointer whose ``git_diffs`` row is gone resolves to ``DIFF_UNAVAILABLE``
    rather than to the raw marker, so no consumer can render the literal
    ``[ref:sha256:…]`` string as though it were the diff body. Classify the
    result with :func:`is_diff_sentinel` before measuring or displaying it.
    """
    if not raw_diff:
        return ""
    if raw_diff.startswith("[ref:sha256:"):
        h = raw_diff[12:-1]
        row = conn.execute(
            "SELECT diff_text FROM git_diffs WHERE diff_hash=?", (h,)
        ).fetchone()
        return row["diff_text"] if row else DIFF_UNAVAILABLE
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
                files.append(diff_b_path(parts[3]))
    conn.execute(
        "INSERT OR IGNORE INTO git_diffs (diff_hash, diff_text, file_list, created_at) "
        "VALUES (?, ?, ?, ?)",
        (diff_hash, diff_text, json.dumps(files) if files else None,
         datetime.now(timezone.utc).isoformat()),
    )
    return f"[ref:sha256:{diff_hash}]"


def store_code_snapshot(conn: sqlite3.Connection, content: str,
                        kind: str = "script", path: str = "") -> str:
    """Store a full-source snapshot (deduped by content hash) and return its
    hash. Content-addressed: identical content across runs is stored once.
    Returns "" for empty content."""
    import hashlib
    from datetime import datetime, timezone
    if not content:
        return ""
    h = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()[:16]
    conn.execute(
        "INSERT OR IGNORE INTO code_snapshots "
        "(hash, content, kind, path, size_bytes, created_at) VALUES (?,?,?,?,?,?)",
        (h, content, kind, path or None, len(content.encode("utf-8", "replace")),
         datetime.now(timezone.utc).isoformat()),
    )
    return h


def get_code_snapshot(conn: sqlite3.Connection, snapshot_hash: str) -> dict | None:
    """Fetch a stored code snapshot by hash, or None."""
    row = conn.execute(
        "SELECT hash, content, kind, path, size_bytes, created_at "
        "FROM code_snapshots WHERE hash=?", (snapshot_hash,)
    ).fetchone()
    return dict(row) if row else None


# ── Deletion helpers ──────────────────────────────────────────────────────────

def delete_experiment(conn: sqlite3.Connection, exp_id: str,
                      delete_files: bool = True,
                      reclaim_blobs: bool = True) -> dict:
    """Delete an experiment and all related DB records.

    If *delete_files* is True, also sends artifact files, the experiment's
    output directory (``outputs/<name>/``), and any notebook history
    snapshots to the OS Trash (with a local ``.exptrack/trash/`` fallback —
    never unlinked outright). Returns a dict of per-bucket trash counts
    (``os_trash`` / ``local_trash`` / ``missing`` / ``failed``), or an empty
    dict when *delete_files* is False.

    Content-addressed blobs the run was the last referrer of — its
    ``code_snapshots`` source text and its ``git_diffs`` diff body — are
    reclaimed too, so a permanently-deleted run doesn't leave its full script
    source and working-tree diff readable in the database. Both survive a *soft*
    delete (the trashed row still holds the reference, so Restore is lossless).

    Pass ``reclaim_blobs=False`` when deleting in a loop and call
    :func:`_sweep_blobs` once afterwards — each reclaim scans every
    ``_code_snapshot`` param plus experiments ∪ session_nodes, so doing it
    per-run made a 200-run bulk delete 200 full scans.
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
    # Reclaim the blobs this run was the last referrer of. Must come *after* the
    # params/experiments DELETEs above, which drop the references themselves.
    if reclaim_blobs:
        _sweep_blobs(conn)
    return file_stats


# Every table a full reset must clear, in foreign-key-safe order (children
# before parents: session_nodes references sessions). Shared by `exptrack clean
# --reset` and the dashboard's Reset button so the two can't drift.
_RESET_TABLES = (
    "params",
    "metrics",
    "artifacts",
    "timeline",
    "cell_lineage",
    "code_baselines",
    "code_snapshots",
    "git_diffs",
    "session_nodes",
    "sessions",
)


def reset_all_tables(conn: sqlite3.Connection) -> dict[str, int]:
    """Clear every data table (see ``_RESET_TABLES``). Returns rows-cleared per
    table. Does not commit, delete files, or VACUUM — the callers do that."""
    cleared: dict[str, int] = {}
    for table in _RESET_TABLES:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if n:
                conn.execute(f"DELETE FROM {table}")
                cleared[table] = n
        except sqlite3.Error as e:
            print(f"[exptrack] warning: could not clear table {table}: {e}",
                  file=sys.stderr)
    return cleared


def find_orphan_output_paths(conn: sqlite3.Connection) -> list[Path]:
    """Paths under ``outputs/`` that no experiment row claims.

    A directory is claimed by an experiment's ``output_dir`` or by its name; a
    loose file is claimed by living inside a claimed directory. Trashed
    experiments still occupy the ``experiments`` table, so their outputs are
    never reported here.

    This only *identifies* candidates — it never touches the filesystem. Both
    callers (the CLI and the dashboard) show the list and require an explicit
    opt-in before moving anything, because "orphan" is a heuristic: a run
    permanently deleted with `delete_files=False` deliberately left its files
    behind, and anything the user dropped into ``outputs/`` by hand looks
    identical to real debris.
    """
    root = cfg.project_root()
    conf = cfg.load()
    outputs_dir = root / conf.get("outputs_dir", "outputs")
    if not outputs_dir.is_dir():
        return []
    exp_dirs = {
        str(Path(r["output_dir"]).resolve())
        for r in conn.execute(
            "SELECT output_dir FROM experiments WHERE output_dir IS NOT NULL"
        ).fetchall()
    }
    exp_names = {r[0] for r in conn.execute("SELECT name FROM experiments").fetchall()}
    orphans: list[Path] = []
    for child in sorted(outputs_dir.iterdir()):
        try:
            resolved = str(child.resolve())
        except OSError:
            continue
        if child.is_dir():
            if resolved not in exp_dirs and child.name not in exp_names:
                orphans.append(child)
        elif not any(resolved == d or resolved.startswith(d + os.sep)
                     for d in exp_dirs):
            orphans.append(child)
    return orphans


def describe_orphan_output_paths(conn: sqlite3.Connection,
                                 paths: list[Path] | None = None) -> list[dict]:
    """``find_orphan_output_paths`` annotated with file count and total bytes,
    so a confirm dialog can say exactly what is about to be moved.

    Pass *paths* to reuse an already-computed list — the annotation walks every
    orphan tree with ``rglob`` + ``stat``, which is the expensive half, and
    orphaned output dirs are routinely checkpoint trees.
    """
    out: list[dict] = []
    for p in (find_orphan_output_paths(conn) if paths is None else paths):
        files, size = 0, 0
        try:
            if p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file():
                        files += 1
                        size += f.stat().st_size
            elif p.is_file():
                files, size = 1, p.stat().st_size
        except OSError:
            pass
        out.append({"name": p.name, "path": str(p), "is_dir": p.is_dir(),
                    "files": files, "bytes": size})
    return out


def trash_orphan_output_paths(conn: sqlite3.Connection,
                              paths: list[Path] | None = None) -> dict[str, int]:
    """Move every orphaned output path to the OS Trash (local fallback).

    Returns ``_trash_or_local`` bucket counts. Never unlinks or rmtrees — an
    "orphan" here is a heuristic, and the files are frequently model
    checkpoints, so removal has to stay recoverable. Pass *paths* to reuse an
    already-computed list instead of re-running discovery.
    """
    counts = {"os_trash": 0, "local_trash": 0, "missing": 0, "failed": 0}
    for p in (find_orphan_output_paths(conn) if paths is None else paths):
        res = _trash_or_local(p, label="orphaned output")
        counts[res] = counts.get(res, 0) + 1
    return counts


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
            # Claim the name by creating the .trashinfo record *first*, with
            # O_EXCL. The XDG spec requires this ordering — a file in
            # Trash/files with no matching record is a blob no file manager
            # will restore — and the exclusive create makes the name
            # reservation atomic against a concurrent trash.
            import itertools
            for name in itertools.chain(
                [path.name], (f"{path.name}.{i}" for i in itertools.count(1))
            ):
                dest = files_dir / name
                info_path = info_dir / (name + ".trashinfo")
                if dest.exists():
                    continue
                try:
                    fd = os.open(str(info_path),
                                 os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    continue  # a stale record claims this name
                break
            with os.fdopen(fd, "w") as f:
                f.write(
                    "[Trash Info]\n"
                    f"Path={urllib.parse.quote(abs_path)}\n"
                    f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n"
                )
            try:
                shutil.move(abs_path, str(dest))
            except Exception:
                # Never leave an info record pointing at nothing — that is the
                # mirror-image corruption of the bug above.
                info_path.unlink(missing_ok=True)
                raise
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
        except OSError as e:
            print(f"[exptrack] warning: could not rename output dir "
                  f"{old_dir} → {new_dir}: {e}", file=sys.stderr)

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
