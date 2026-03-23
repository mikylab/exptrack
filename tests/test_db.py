"""Tests for exptrack/core/db.py — schema, deletion, orphan cleanup, git diff dedup."""
from __future__ import annotations

import json
from datetime import datetime, timezone


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
