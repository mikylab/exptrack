"""Tests for exptrack/core/db.py — schema, deletion, orphan cleanup, git diff dedup."""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

def test_schema_creates_all_tables(db_conn):
    """_ensure_schema creates all expected tables."""
    tables = {
        r[0]
        for r in db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "experiments",
        "params",
        "metrics",
        "artifacts",
        "timeline",
        "cell_lineage",
        "code_baselines",
        "git_diffs",
    }
    missing = expected - tables
    assert not missing, f"Missing tables: {missing}"


def test_schema_version_stamped(db_conn):
    """_ensure_schema stamps user_version so future connections skip probes."""
    from exptrack.core.db import _SCHEMA_VERSION
    uv = db_conn.execute("PRAGMA user_version").fetchone()[0]
    assert uv == _SCHEMA_VERSION


# Fingerprint of the fully-migrated schema (all tables + indexes). This is the
# safety net for the manual `_SCHEMA_VERSION` bump: because the version stamp
# short-circuits _ensure_schema on already-stamped DBs, forgetting to bump it
# after a schema change means existing DBs silently never migrate. This test
# fails whenever the schema DDL changes, forcing a deliberate update here —
# and the message reminds you to bump `_SCHEMA_VERSION` at the same time.
_EXPECTED_SCHEMA_FINGERPRINT = "0a3728f30167f4e7"


def _schema_fingerprint(conn) -> str:
    import hashlib
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    norm = "\n".join(
        f"{r['type']}|{r['name']}|{' '.join((r['sql'] or '').split())}" for r in rows
    )
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def test_schema_fingerprint_matches_version(db_conn):
    """Guard the manual _SCHEMA_VERSION bump: any schema DDL change trips this.

    If this fails after an intentional schema change, update
    _EXPECTED_SCHEMA_FINGERPRINT below to the printed value AND bump
    _SCHEMA_VERSION in exptrack/core/db.py (otherwise existing databases,
    which skip _ensure_schema once stamped, never see the new migration)."""
    actual = _schema_fingerprint(db_conn)
    assert actual == _EXPECTED_SCHEMA_FINGERPRINT, (
        f"Schema changed (fingerprint {actual} != {_EXPECTED_SCHEMA_FINGERPRINT}). "
        f"If intentional: set _EXPECTED_SCHEMA_FINGERPRINT = {actual!r} here AND "
        f"bump _SCHEMA_VERSION in exptrack/core/db.py so existing DBs re-migrate."
    )


def test_schema_gate_short_circuits(db_conn, monkeypatch):
    """A stamped DB skips the migration probes entirely."""
    from exptrack.core import db as db_mod
    calls = []
    monkeypatch.setattr(db_mod, "_create_base_schema",
                        lambda conn: calls.append("base"))
    db_mod._ensure_schema(db_conn)  # stamp matches → returns before probing
    assert calls == []


def test_schema_gate_stale_version_remigrates(db_conn, monkeypatch):
    """A stale (older) stamp re-runs the full migration and re-stamps."""
    from exptrack.core import db as db_mod
    db_conn.execute("PRAGMA user_version = 0")
    calls = []
    real_base = db_mod._create_base_schema
    monkeypatch.setattr(db_mod, "_create_base_schema",
                        lambda conn: (calls.append("base"), real_base(conn)))
    db_mod._ensure_schema(db_conn)
    assert calls == ["base"]
    uv = db_conn.execute("PRAGMA user_version").fetchone()[0]
    assert uv == db_mod._SCHEMA_VERSION


def test_schema_gate_force_reruns(db_conn, monkeypatch):
    """force=True (exptrack upgrade) re-runs even when the stamp matches."""
    from exptrack.core import db as db_mod
    calls = []
    real_base = db_mod._create_base_schema
    monkeypatch.setattr(db_mod, "_create_base_schema",
                        lambda conn: (calls.append("base"), real_base(conn)))
    db_mod._ensure_schema(db_conn, force=True)
    assert calls == ["base"]


def test_schema_wal_mode(db_conn):
    """Database uses WAL journal mode."""
    mode = db_conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_schema_has_expected_indexes(db_conn):
    """Schema creates indexes on key columns."""
    indexes = {
        r[0]
        for r in db_conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    expected = {
        "idx_metrics_exp",
        "idx_params_exp",
        "idx_exp_created",
        "idx_exp_status",
        "idx_artifacts_exp",
        "idx_timeline_exp_seq",
    }
    missing = expected - indexes
    assert not missing, f"Missing indexes: {missing}"


# ---------------------------------------------------------------------------
# delete_experiment
# ---------------------------------------------------------------------------

def test_delete_experiment_removes_all_related_rows(tmp_project):
    """delete_experiment removes the experiment row and all child table rows."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.db import delete_experiment

    exp = Experiment(script="train.py")
    exp.log_param("lr", 0.01)
    exp.log_metric("loss", 0.5, step=1)
    exp.log_event("var_set", key="x", value=42)
    exp.finish()
    eid = exp.id

    conn = get_db()

    # Verify data exists before deletion
    for table in ("params", "metrics", "timeline"):
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE exp_id=?", (eid,)
        ).fetchone()[0]
        assert n > 0, f"Expected rows in {table} before delete"

    delete_experiment(conn, eid, delete_files=False)
    conn.commit()

    # All related rows should be gone
    for table in ("experiments", "params", "metrics", "artifacts", "timeline"):
        col = "id" if table == "experiments" else "exp_id"
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (eid,)
        ).fetchone()[0]
        assert n == 0, f"Expected 0 rows in {table} after delete, got {n}"


# ---------------------------------------------------------------------------
# sweep_orphans
# ---------------------------------------------------------------------------

def test_sweep_orphans_cleans_orphaned_rows(tmp_project):
    """sweep_orphans removes child rows whose exp_id has no experiment."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.db import sweep_orphans

    exp = Experiment(script="train.py")
    exp.log_param("lr", 0.01)
    exp.log_metric("loss", 0.5, step=1)
    exp.finish()
    eid = exp.id

    conn = get_db()

    # Manually delete the experiment row (but not its children) to create orphans.
    # Temporarily disable foreign keys so we can create the orphan state.
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("DELETE FROM experiments WHERE id=?", (eid,))
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")

    # Orphaned rows should still exist
    n_params = conn.execute(
        "SELECT COUNT(*) FROM params WHERE exp_id=?", (eid,)
    ).fetchone()[0]
    assert n_params > 0, "Orphaned params should exist before sweep"

    # Sweep
    counts = sweep_orphans(conn)

    # Orphaned rows should now be gone
    for table in ("params", "metrics"):
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE exp_id=?", (eid,)
        ).fetchone()[0]
        assert n == 0, f"Expected 0 orphans in {table} after sweep, got {n}"

    assert sum(counts.values()) > 0, "sweep_orphans should report removed rows"


def test_close_db_sweep_false_skips_sweep(tmp_project, monkeypatch):
    """close_db(sweep=False) must not run the orphan-sweep anti-join scans."""
    from exptrack.core import Experiment, get_db
    from exptrack.core import db as db_mod

    exp = Experiment(script="train.py")
    exp.log_param("lr", 0.01)
    get_db()  # ensure a cached connection exists on this thread

    calls = []
    monkeypatch.setattr(db_mod, "_sweep_orphans",
                        lambda conn: calls.append("swept") or 0)
    db_mod.close_db(sweep=False)
    assert calls == [], "sweep=False should skip _sweep_orphans"


def test_finish_does_not_sweep(tmp_project, monkeypatch):
    """Experiment.finish() closes without sweeping (finishing can't orphan)."""
    from exptrack.core import Experiment
    from exptrack.core import db as db_mod

    calls = []
    monkeypatch.setattr(db_mod, "_sweep_orphans",
                        lambda conn: calls.append("swept") or 0)
    exp = Experiment(script="train.py")
    exp.log_metric("loss", 0.5, step=1)
    exp.finish()
    assert calls == [], "finish() should not run the orphan sweep"


# ---------------------------------------------------------------------------
# store_git_diff / resolve_git_diff round-trip
# ---------------------------------------------------------------------------

def test_store_and_resolve_git_diff(db_conn):
    """store_git_diff stores diff text and resolve_git_diff retrieves it."""
    from exptrack.core.db import resolve_git_diff, store_git_diff

    diff_text = (
        "diff --git a/train.py b/train.py\n"
        "--- a/train.py\n"
        "+++ b/train.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-lr = 0.01\n"
        "+lr = 0.001\n"
    )

    ref = store_git_diff(db_conn, diff_text)
    db_conn.commit()

    # Reference should be in the expected format
    assert ref.startswith("[ref:sha256:"), f"Unexpected ref format: {ref}"
    assert ref.endswith("]")

    # Resolving should return the original text
    resolved = resolve_git_diff(db_conn, ref)
    assert resolved == diff_text


def test_resolve_git_diff_inline(db_conn):
    """resolve_git_diff returns plain text unchanged (non-ref input)."""
    from exptrack.core.db import resolve_git_diff

    plain = "some inline diff text"
    assert resolve_git_diff(db_conn, plain) == plain


def test_resolve_git_diff_empty(db_conn):
    """resolve_git_diff returns empty string for None / empty input."""
    from exptrack.core.db import resolve_git_diff

    assert resolve_git_diff(db_conn, None) == ""
    assert resolve_git_diff(db_conn, "") == ""


# ---------------------------------------------------------------------------
# Schema migration robustness (idempotency + split helpers)
# ---------------------------------------------------------------------------

def _cols(conn, table):
    from exptrack.core.db import _table_columns
    return _table_columns(conn, table)


def test_ensure_schema_is_idempotent(db_conn):
    """Running _ensure_schema repeatedly must not raise or alter the schema."""
    from exptrack.core.db import _ensure_schema

    before = _cols(db_conn, "experiments")
    # Re-run several times — every migration helper checks column existence,
    # so this is a no-op the 2nd..Nth time.
    for _ in range(3):
        _ensure_schema(db_conn)
    after = _cols(db_conn, "experiments")
    assert before == after


def test_migrated_columns_present(db_conn):
    """All columns added by the _migrate_* helpers exist after schema setup."""
    assert {"session_node_id", "deleted_at", "name_is_auto", "studies",
            "stage", "stage_name", "output_dir"} <= _cols(db_conn, "experiments")
    assert {"timeline_seq", "content_hash", "size_bytes"} <= _cols(db_conn, "artifacts")
    assert "source" in _cols(db_conn, "metrics")
    assert "source" in _cols(db_conn, "params")
    assert {"deleted_at", "cell_outputs", "setup_source", "setup_outputs",
            "images"} <= _cols(db_conn, "session_nodes")


def test_migration_helpers_are_individually_idempotent(db_conn):
    """Each _migrate_* helper can be called standalone without error."""
    from exptrack.core import db as _db

    for fn in (_db._migrate_session_nodes, _db._migrate_experiment_session_link,
               _db._migrate_artifacts, _db._migrate_metrics,
               _db._migrate_params, _db._migrate_experiments):
        fn(db_conn)  # must not raise on an already-migrated db


def test_add_columns_adds_only_missing_and_is_idempotent(db_conn):
    """_add_columns adds absent columns once and reports the empty set after."""
    from exptrack.core.db import _add_columns, _table_columns

    db_conn.execute("CREATE TABLE t_ac (a TEXT)")
    # First pass: b and c are missing, a already exists → only b, c added.
    added = _add_columns(db_conn, "t_ac", {"a": "TEXT", "b": "INTEGER", "c": "TEXT"})
    assert added == {"b", "c"}
    assert {"a", "b", "c"} <= _table_columns(db_conn, "t_ac")
    # Second pass with the same spec is a no-op (proves idempotency).
    assert _add_columns(db_conn, "t_ac", {"a": "TEXT", "b": "INTEGER", "c": "TEXT"}) == set()


def test_add_columns_applies_ddl_default(db_conn):
    """The DDL fragment (incl. DEFAULT) is applied to the new column."""
    from exptrack.core.db import _add_columns

    db_conn.execute("CREATE TABLE t_def (a TEXT)")
    db_conn.execute("INSERT INTO t_def (a) VALUES ('x')")
    _add_columns(db_conn, "t_def", {"src": "TEXT DEFAULT 'auto'"})
    assert db_conn.execute("SELECT src FROM t_def").fetchone()[0] == "auto"


# ---------------------------------------------------------------------------
# _migrate_metrics: _result:* param backfill is per-row tolerant
# ---------------------------------------------------------------------------

def _build_legacy_result_db(tmp_path):
    """Create a pre-`source` metrics DB with one good + one bad _result param.

    Returns nothing — the DB is written to the project's configured path so the
    next get_db() opens and migrates it.
    """
    import sqlite3

    db_path = tmp_path / ".exptrack" / "experiments.db"
    conn = sqlite3.connect(str(db_path))
    # Legacy metrics table: no `source` column (the pre-migration shape).
    # experiments carries `status` because base-schema indexes reference it.
    conn.executescript("""
        CREATE TABLE experiments (
            id TEXT PRIMARY KEY, name TEXT, status TEXT DEFAULT 'done',
            created_at TEXT, updated_at TEXT);
        CREATE TABLE params (
            exp_id TEXT, key TEXT, value TEXT, PRIMARY KEY (exp_id, key));
        CREATE TABLE metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exp_id TEXT, key TEXT, value REAL, step INTEGER, ts TEXT);
    """)
    conn.execute("INSERT INTO experiments (id, name, created_at, updated_at) "
                 "VALUES ('e1','n','2026-01-01','2026-01-01')")
    conn.execute("INSERT INTO params VALUES ('e1','_result:acc', ?)", (json.dumps("0.9"),))
    conn.execute("INSERT INTO params VALUES ('e1','_result:junk', ?)",
                 (json.dumps("not-a-number"),))
    conn.commit()
    conn.close()


def test_migrate_metrics_backfill_is_row_tolerant(tmp_project):
    """A single un-parseable _result param must not strand the whole backfill."""
    from exptrack.core.db import get_db

    _build_legacy_result_db(tmp_project)
    conn = get_db()  # triggers _ensure_schema → _migrate_metrics

    # Good row migrated into metrics with source='manual', key prefix stripped.
    row = conn.execute(
        "SELECT value, source FROM metrics WHERE exp_id='e1' AND key='acc'"
    ).fetchone()
    assert row is not None
    assert abs(row["value"] - 0.9) < 1e-9
    assert row["source"] == "manual"

    # Good row deleted from params; bad row LEFT IN PLACE (not deleted).
    remaining = {r["key"] for r in conn.execute(
        "SELECT key FROM params WHERE exp_id='e1'").fetchall()}
    assert remaining == {"_result:junk"}

    # No stray metric was inserted for the bad row.
    assert conn.execute(
        "SELECT COUNT(*) FROM metrics WHERE exp_id='e1' AND key='junk'"
    ).fetchone()[0] == 0


def test_migrate_metrics_second_open_is_noop(tmp_project):
    """Re-opening a migrated DB doesn't re-migrate or crash (source col exists)."""
    from exptrack.core import db as _db

    _build_legacy_result_db(tmp_project)
    _db.get_db()
    _db.close_db()
    # Reset cached connection and reopen — must be a clean no-op.
    _db._local.conn = None
    _db._local.db_path = None
    conn = _db.get_db()
    # Bad param still present; good one still gone.
    remaining = {r["key"] for r in conn.execute(
        "SELECT key FROM params WHERE exp_id='e1'").fetchall()}
    assert remaining == {"_result:junk"}
