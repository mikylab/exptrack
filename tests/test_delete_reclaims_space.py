"""A permanent delete removes the rows — and says what it freed.

Deleting a run does drop every metric/param/artifact/timeline row, but SQLite
moves the freed pages onto the file's free list instead of shrinking the file,
and (through the dashboard) leaves the WAL sitting at the size of what was
deleted. Both make a delete that worked look like a delete that did nothing.
These tests pin the row removal, the reported free space, and the WAL cleanup.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _big_run(name="doomed", points=3000):
    from exptrack.core import Experiment

    exp = Experiment(name=name, script="train.py", params={"lr": 0.01})
    for i in range(points):
        exp.log_metrics({"loss": 1.0 / (i + 1), "acc": i / points}, step=i)
    exp.finish()
    return exp


def _counts(conn, exp_id):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE exp_id=?",
                            (exp_id,)).fetchone()[0]
            for t in ("metrics", "params", "artifacts", "timeline")}


def test_delete_removes_every_child_row(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.db import delete_experiment

    exp = _big_run()
    conn = get_db()
    assert _counts(conn, exp.id)["metrics"] == 6000

    delete_experiment(conn, exp.id, delete_files=False)
    conn.commit()

    assert _counts(conn, exp.id) == {"metrics": 0, "params": 0,
                                     "artifacts": 0, "timeline": 0}
    assert conn.execute("SELECT COUNT(*) FROM experiments WHERE id=?",
                        (exp.id,)).fetchone()[0] == 0


def test_delete_frees_pages_but_not_the_file_until_vacuum(tmp_project):
    """The heart of "delete didn't reclaim anything": both halves are true."""
    from exptrack.core import get_db
    from exptrack.core.db import delete_experiment
    from exptrack.core.storage import free_space

    exp = _big_run()
    conn = get_db()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    size_before = db_path.stat().st_size
    free_before = free_space(conn)["bytes"]

    delete_experiment(conn, exp.id, delete_files=False)
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    freed = free_space(conn)["bytes"] - free_before
    assert freed > 0, "the deleted pages must show up as free space"
    assert db_path.stat().st_size == size_before, \
        "SQLite does not shrink the file — this is what looks like a failed delete"

    # …and the one operation that does hand the space back. In WAL mode the
    # rebuilt pages land in the WAL, so the file only shrinks once they are
    # checkpointed back — which is why `clean --vacuum` checkpoints on both
    # sides of the VACUUM.
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert db_path.stat().st_size < size_before
    assert free_space(conn)["bytes"] == 0


def test_free_space_is_zero_on_a_fresh_project(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.storage import free_space

    f = free_space(get_db())
    assert f["bytes"] == 0
    assert f["total_pages"] > 0
    assert f["pct"] == 0.0


def test_checkpoint_truncate_empties_the_wal(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.db import checkpoint_truncate, delete_experiment

    exp = _big_run()
    conn = get_db()
    delete_experiment(conn, exp.id, delete_files=False)
    conn.commit()
    wal = Path(str(Path(conn.execute("PRAGMA database_list").fetchone()[2])) + "-wal")
    assert wal.exists() and wal.stat().st_size > 0, "the delete went through the WAL"

    assert checkpoint_truncate(conn) is True
    assert wal.stat().st_size == 0


def test_checkpoint_truncate_gives_up_quickly_under_a_writer(tmp_project):
    """It must never wait on a live training run — bounded, and non-fatal."""
    import time

    from exptrack.core import get_db
    from exptrack.core.db import checkpoint_truncate

    conn = get_db()
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    other = sqlite3.connect(db_path, timeout=5)
    other.execute("BEGIN IMMEDIATE")
    other.execute("INSERT INTO experiments (id, name, status, created_at, updated_at) "
                  "VALUES ('zz', 'writer', 'running', '2026-01-01', '2026-01-01')")
    try:
        t0 = time.monotonic()
        ok = checkpoint_truncate(conn, timeout_ms=100)
        elapsed = time.monotonic() - t0
        assert ok is False, "a blocked checkpoint reports failure rather than raising"
        assert elapsed < 2.0, f"must not wait on the writer (took {elapsed:.2f}s)"
    finally:
        other.rollback()
        other.close()

    # The connection's own busy_timeout is restored, not left at 100ms.
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_dashboard_delete_reports_what_it_freed(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    exp = _big_run()
    conn = get_db()
    r = write_routes.api_delete_permanent(conn, exp.id, {"delete_files": False})
    assert r["ok"]
    assert r["freed_bytes"] > 0, "the response must say what the delete freed"
    assert conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 0


def test_dashboard_bulk_delete_reports_what_it_freed(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    ids = [_big_run(f"run{i}").id for i in range(2)]
    conn = get_db()
    r = write_routes.api_bulk_delete_permanent(conn, {"ids": ids})
    assert r["ok"] and r["deleted"] == 2
    assert r["freed_bytes"] > 0
    assert conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 0


def test_storage_info_exposes_free_space(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    exp = _big_run()
    conn = get_db()
    write_routes.api_delete_permanent(conn, exp.id, {"delete_files": False})
    info = write_routes.api_storage_info(conn)
    assert info["free_bytes"] > 0
    assert info["free_pct"] > 0
