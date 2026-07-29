"""What the Trash is costing, in the database and on disk.

Soft delete keeps every row and deliberately leaves output files in place, so
the Trash is the one place storage accumulates with nothing in the UI saying
how much. ``core/storage.trash_storage`` is that number; these tests pin the
three components it reports and the rule that output files are only counted
when the trashed run actually owns the directory.
"""
from __future__ import annotations


def _run(tmp_project, name, n_metrics=20):
    from exptrack.core import Experiment

    exp = Experiment(name=name, script="train.py", params={"lr": 0.01})
    for i in range(n_metrics):
        exp.log_metric("loss", 1.0 / (i + 1), step=i)
    out = tmp_project / "outputs" / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.pt").write_bytes(b"x" * 2048)
    exp.log_artifact(str(out / "model.pt"), label="model")
    exp.finish()
    return exp


def test_empty_trash_is_all_zeros(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.storage import trash_storage

    _run(tmp_project, "kept")
    t = trash_storage(get_db())
    assert t["experiments"] == 0
    assert t["db_bytes"] == 0
    assert t["output_bytes"] == 0
    assert t["local_bytes"] == 0


def test_trashing_a_run_counts_its_db_bytes_and_output_files(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.db import trash_experiment
    from exptrack.core.storage import trash_storage

    _run(tmp_project, "kept")
    doomed = _run(tmp_project, "doomed")
    conn = get_db()
    trash_experiment(conn, doomed.id)
    conn.commit()

    t = trash_storage(conn)
    assert t["experiments"] == 1
    assert t["db_bytes"] > 0, "a trashed run still occupies rows"
    # Soft delete never touches files, so its outputs are still on disk.
    assert t["output_files"] == 1
    assert t["output_bytes"] == 2048
    assert t["output_dirs"] == 1


def test_restoring_a_run_removes_it_from_the_trash_total(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.db import restore_experiment, trash_experiment
    from exptrack.core.storage import trash_storage

    exp = _run(tmp_project, "doomed")
    conn = get_db()
    trash_experiment(conn, exp.id)
    conn.commit()
    assert trash_storage(conn)["experiments"] == 1

    restore_experiment(conn, exp.id)
    conn.commit()
    t = trash_storage(conn)
    assert t["experiments"] == 0 and t["db_bytes"] == 0 and t["output_bytes"] == 0


def test_output_files_a_surviving_run_claims_are_not_counted(tmp_project):
    """The Trash must never advertise space a permanent delete would leave alone.

    Two runs can carry the same name (rename accepts anything), and only one
    owns ``outputs/<name>``. Sizing the directory for the trashed one would
    promise bytes the delete deliberately refuses to take — and would count
    another run's checkpoints as reclaimable.
    """
    from exptrack.core import get_db
    from exptrack.core.db import trash_experiment
    from exptrack.core.storage import trash_storage

    keeper = _run(tmp_project, "shared-name")
    doomed = _run(tmp_project, "other")
    conn = get_db()   # after both runs — finishing one closes the shared handle
    # Give the doomed run the keeper's name, with no output_dir of its own, so
    # its only candidate directory is the one the keeper still claims.
    conn.execute("UPDATE experiments SET name='shared-name', output_dir=NULL WHERE id=?",
                 (doomed.id,))
    trash_experiment(conn, doomed.id)
    conn.commit()
    assert keeper.id  # the keeper is untouched and still claims the directory

    t = trash_storage(conn)
    assert t["experiments"] == 1
    assert t["output_bytes"] == 0, "another run owns that directory"


def test_local_trash_directory_is_measured(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.db import local_trash_dir
    from exptrack.core.storage import trash_storage

    d = local_trash_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "20260101_000000__model.pt").write_bytes(b"y" * 500)
    t = trash_storage(get_db())
    assert t["local_files"] == 1
    assert t["local_bytes"] == 500
    # It is not reclaimed by a permanent delete, so it stays out of db_bytes.
    assert t["db_bytes"] == 0


def test_trashed_session_nodes_and_sessions_are_counted(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.storage import trash_storage

    conn = get_db()
    conn.execute("INSERT INTO sessions (id, name, notebook, status, created_at) "
                 "VALUES ('s1', 'live', 'nb', 'active', 0)")
    conn.execute("INSERT INTO sessions (id, name, notebook, status, created_at, deleted_at) "
                 "VALUES ('s2', 'gone', 'nb', 'ended', 0, 1)")
    conn.execute("INSERT INTO session_nodes (id, session_id, node_type, label, "
                 "cell_source, seq, created_at, deleted_at) "
                 "VALUES ('n1', 's1', 'branch', 'trashed node', ?, 1, 0, 1)",
                 ("x" * 300,))
    conn.execute("INSERT INTO session_nodes (id, session_id, node_type, label, "
                 "cell_source, seq, created_at) "
                 "VALUES ('n2', 's1', 'branch', 'live node', 'kept', 2, 0)")
    # A node under a trashed *session* counts too — the session's deletion
    # doesn't stamp its nodes.
    conn.execute("INSERT INTO session_nodes (id, session_id, node_type, label, "
                 "cell_source, seq, created_at) "
                 "VALUES ('n3', 's2', 'checkpoint', 'under trashed session', ?, 1, 0)",
                 ("y" * 200,))
    conn.commit()

    t = trash_storage(conn)
    assert t["sessions"] == 1
    assert t["nodes"] == 2, "the trashed node plus the one under the trashed session"
    assert t["node_db_bytes"] >= 500
    assert t["db_bytes"] == t["exp_db_bytes"] + t["node_db_bytes"]


def test_trash_storage_survives_a_broken_database(tmp_project, monkeypatch):
    """It's a report — a failure degrades to zeros, it never kills the panel."""
    from exptrack.core import get_db, storage

    monkeypatch.setattr(storage, "experiment_storage",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    t = storage.trash_storage(get_db())
    assert t["experiments"] == 0 and t["db_bytes"] == 0
