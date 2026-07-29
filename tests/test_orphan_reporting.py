"""Orphaned rows are found and named, not just silently swept.

Today's delete removes a run's children first, and the schema's foreign keys
would refuse it otherwise — so exptrack does not create orphans. They come from
history: a database written by a version that deleted the experiment row only, a
hand-edited one, a process killed mid-delete. Those rows are invisible in every
list while still occupying the file, and the storage report's warning used to
fire only when the project held *zero* experiments — so 5 runs alongside 20k
orphaned metric rows reported perfect health.
"""
from __future__ import annotations


def _run(name, points=500):
    from exptrack.core import Experiment

    exp = Experiment(name=name, script="train.py", params={"lr": 0.01})
    for i in range(points):
        exp.log_metric("loss", 1.0 / (i + 1), step=i)
    exp.finish()
    return exp


def _orphan_a_run(conn, exp_id):
    """Delete only the experiment row, as an older version's delete did."""
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("DELETE FROM experiments WHERE id=?", (exp_id,))
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")


def test_todays_delete_leaves_no_orphans(tmp_project):
    """The first thing to be sure of: the current delete cleans up after itself."""
    from exptrack.core import get_db
    from exptrack.core.db import count_orphans
    from exptrack.dashboard.routes import write_routes

    keep = _run("keep")
    doomed = _run("doomed")
    conn = get_db()

    write_routes.api_delete_permanent(conn, doomed.id, {"delete_files": False})

    assert count_orphans(conn) == {}, "a dashboard delete must not strand rows"
    # …and the surviving run is untouched.
    assert conn.execute("SELECT COUNT(*) FROM metrics WHERE exp_id=?",
                        (keep.id,)).fetchone()[0] == 500


def test_soft_delete_keeps_the_rows_and_they_are_not_orphans(tmp_project):
    """Trash is not a delete: the row stays, so nothing is orphaned."""
    from exptrack.core import get_db
    from exptrack.core.db import count_orphans, trash_experiment

    exp = _run("trashed")
    conn = get_db()
    trash_experiment(conn, exp.id)
    conn.commit()

    assert count_orphans(conn) == {}
    assert conn.execute("SELECT COUNT(*) FROM metrics WHERE exp_id=?",
                        (exp.id,)).fetchone()[0] == 500


def test_legacy_orphans_are_reported_with_their_cost(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.storage import orphan_storage

    _run("keep")
    stranded = _run("stranded")
    conn = get_db()
    assert orphan_storage(conn)["rows"] == 0

    _orphan_a_run(conn, stranded.id)

    o = orphan_storage(conn)
    assert o["counts"]["metrics"] == 500
    assert o["rows"] >= 500
    assert o["bytes"] > 0, "orphans must be costed, not just counted"
    assert o["tables"]["metrics"]["rows"] == 500


def test_orphans_reported_even_when_experiments_remain(tmp_project):
    """The old check only fired on an empty database — this is the regression."""
    from exptrack.core import get_db
    from exptrack.core.storage import orphan_storage

    for i in range(3):
        _run(f"live{i}")
    stranded = _run("stranded")
    conn = get_db()
    _orphan_a_run(conn, stranded.id)

    assert conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 3
    assert orphan_storage(conn)["rows"] >= 500


def test_dashboard_storage_panel_and_clean_see_the_same_orphans(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    _run("keep")
    stranded = _run("stranded")
    conn = get_db()
    _orphan_a_run(conn, stranded.id)

    info = write_routes.api_storage_info(conn)
    assert info["orphans"]["rows"] >= 500

    cleaned = write_routes.api_clean_db(conn, {})
    assert cleaned["removed"] == info["orphans"]["rows"]

    after = write_routes.api_storage_info(conn)
    assert after["orphans"]["rows"] == 0
    assert after["orphans"]["bytes"] == 0


def test_orphan_storage_never_raises_on_a_broken_database(tmp_project, monkeypatch):
    from exptrack.core import db as core_db
    from exptrack.core import get_db, storage

    monkeypatch.setattr(core_db, "count_orphans",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    o = storage.orphan_storage(get_db())
    assert o["rows"] == 0 and o["bytes"] == 0
