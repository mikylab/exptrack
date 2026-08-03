"""`exptrack source` — read back the code a run actually ran.

The source was always stored (a script's snapshot in `code_snapshots`, a
notebook's cells in `cell_lineage`) but nothing outside `compare_run_code` could
reach it, so "show me this run's code" had no answer. That matters most when the
code is hardest to get any other way: the file has since been edited, or was
never committed.
"""
import json

import pytest

from exptrack.core.db import get_db, store_code_snapshot
from exptrack.core.queries import get_run_source


def _exp(conn, exp_id, script="train.py"):
    conn.execute(
        "INSERT INTO experiments (id, name, status, created_at, updated_at, script) "
        "VALUES (?,?,?,?,?,?)",
        (exp_id, exp_id, "done", "2026-08-01T00:00:00", "2026-08-01T00:00:00", script),
    )
    conn.commit()
    return exp_id


@pytest.fixture
def conn(tmp_project):
    return get_db()


def test_script_source_round_trips(conn):
    src = "warmup = 200\nif i == -1:\n    pass\n"
    _exp(conn, "s1")
    h = store_code_snapshot(conn, src, kind="script", path="train.py")
    conn.execute(
        "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
        ("s1", "_code_snapshot",
         json.dumps([{"hash": h, "kind": "script", "path": "train.py"}]), "auto"),
    )
    conn.commit()
    out = get_run_source(conn, "s1")
    assert out["kind"] == "script"
    assert out["files"][0]["label"] == "train.py"
    assert out["files"][0]["content"] == src


def test_notebook_cells_are_returned_in_execution_order(conn):
    _exp(conn, "n1", script="nb.ipynb")
    for seq, (h, s, pos) in enumerate([("h1", "a = 1", 1), ("h2", "b = 2", 2)]):
        conn.execute(
            "INSERT INTO cell_lineage (cell_hash, notebook, source, created_at) "
            "VALUES (?,?,?,?)", (h, "nb.ipynb", s, "2026-08-01T00:00:00"))
        conn.execute(
            "INSERT INTO timeline (exp_id, seq, event_type, cell_hash, cell_pos, ts) "
            "VALUES (?,?,?,?,?,?)",
            ("n1", seq, "cell_exec", h, pos, "2026-08-01T00:00:00"))
    conn.commit()
    out = get_run_source(conn, "n1")
    assert out["kind"] == "cells"
    assert [f["content"] for f in out["files"]] == ["a = 1", "b = 2"]


def test_run_with_no_captured_source_reports_none(conn):
    """Distinguishable from an empty file — this is the unrecoverable case."""
    _exp(conn, "bare")
    out = get_run_source(conn, "bare")
    assert out["kind"] is None and out["files"] == []
    assert out["id"] == "bare"          # the run itself still resolved


def test_unknown_id_is_not_an_exception(conn):
    out = get_run_source(conn, "nope")
    assert out == {"kind": None, "id": None, "name": None, "files": []}


def test_source_survives_the_file_being_edited_or_deleted(conn):
    """The whole point: the snapshot is independent of the file on disk."""
    _exp(conn, "gone", script="/tmp/deleted-since.py")
    h = store_code_snapshot(conn, "original = 1\n", kind="script", path="/tmp/x.py")
    conn.execute(
        "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
        ("gone", "_code_snapshot",
         json.dumps([{"hash": h, "kind": "script", "path": "/tmp/x.py"}]), "auto"),
    )
    conn.commit()
    assert get_run_source(conn, "gone")["files"][0]["content"] == "original = 1\n"


# ── Delete-time source-loss warning ─────────────────────────────────────────

def _with_snapshot(conn, exp_id, src):
    from exptrack.core.db import store_code_snapshot
    _exp(conn, exp_id)
    h = store_code_snapshot(conn, src, kind="script", path="t.py")
    conn.execute(
        "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
        (exp_id, "_code_snapshot",
         json.dumps([{"hash": h, "kind": "script", "path": "t.py"}]), "auto"))
    conn.commit()
    return h


def test_last_holder_of_a_snapshot_is_flagged(conn):
    from exptrack.core.storage import sole_source_holder
    _with_snapshot(conn, "only", "a = 1\nb = 2\n")
    r = sole_source_holder(conn, "only")
    assert r["sole"] is True and r["lines"] == 2


def test_a_shared_snapshot_is_not_a_loss(conn):
    """Two runs of identical source share one blob — deleting one loses nothing."""
    from exptrack.core.storage import sole_source_holder
    h1 = _with_snapshot(conn, "one", "same = 1\n")
    h2 = _with_snapshot(conn, "two", "same = 1\n")
    assert h1 == h2                      # content-addressed: one blob
    assert sole_source_holder(conn, "one")["sole"] is False
    assert sole_source_holder(conn, "two")["sole"] is False


def test_run_without_a_snapshot_is_not_flagged(conn):
    from exptrack.core.storage import sole_source_holder
    _exp(conn, "nosnap")
    assert sole_source_holder(conn, "nosnap")["sole"] is False


def test_delete_preview_carries_the_flag(conn):
    from exptrack.core.db import get_delete_preview
    _with_snapshot(conn, "prev", "x = 1\n")
    assert get_delete_preview(conn, "prev")["source_only_copy"]["sole"] is True


def test_delete_preview_never_breaks_on_a_source_check_failure(conn):
    """The warning is advisory; it must not be able to break the delete dialog."""
    from exptrack.core import db as D
    _with_snapshot(conn, "boom", "x = 1\n")
    orig = D._sole_source
    try:
        conn.execute("DROP TABLE code_snapshots")
        conn.commit()
        out = get_delete_preview_safe(conn, "boom")
        assert out["source_only_copy"] == {"sole": False, "hashes": [], "lines": 0}
    finally:
        D._sole_source = orig


def get_delete_preview_safe(conn, exp_id):
    from exptrack.core.db import get_delete_preview
    return get_delete_preview(conn, exp_id)


def test_bulk_delete_of_all_sharers_is_flagged_batch_aware(conn):
    """Per-run checks see the other runs in the same doomed batch as
    surviving holders — deleting the only two runs sharing a snapshot must
    still warn, because the batch destroys the last copies."""
    from exptrack.core.storage import sole_source_holder, sole_source_holders
    _with_snapshot(conn, "s1", "shared = 1\n")
    _with_snapshot(conn, "s2", "shared = 1\n")
    # Per-run: each sees the other as a holder — correctly not sole.
    assert sole_source_holder(conn, "s1")["sole"] is False
    # Batch of both: the blob dies with the batch.
    r = sole_source_holders(conn, ["s1", "s2"])
    assert r["sole"] is True and r["lines"] == 1 and len(r["hashes"]) == 1


def test_batch_with_an_outside_holder_is_not_flagged(conn):
    from exptrack.core.storage import sole_source_holders
    _with_snapshot(conn, "in1", "kept = 1\n")
    _with_snapshot(conn, "in2", "kept = 1\n")
    _with_snapshot(conn, "outside", "kept = 1\n")   # survives the delete
    assert sole_source_holders(conn, ["in1", "in2"])["sole"] is False
    assert sole_source_holders(conn, [])["sole"] is False


def test_bulk_delete_preview_route_carries_the_batch_flag(conn):
    from exptrack.dashboard.routes.write_routes import api_bulk_delete_preview
    _with_snapshot(conn, "b1", "batch = 1\n")
    _with_snapshot(conn, "b2", "batch = 1\n")
    p = api_bulk_delete_preview(conn, {"ids": ["b1", "b2"]})
    assert p["source_only_copy"]["sole"] is True


def test_source_code_storage_reports_exact_bytes(conn):
    """The storage report's source-code line: snapshots + summaries, exact."""
    from exptrack.core.storage import compact_code_changes, source_code_storage
    _with_snapshot(conn, "st1", "line = 1\n")
    conn.execute(
        "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
        ("st1", "_code_changes", json.dumps("- line = 0; + line = 1"), "auto"))
    conn.commit()
    s = source_code_storage(conn)
    assert s["snapshot_count"] == 1
    assert s["snapshot_bytes"] == len("line = 1\n")
    assert s["summary_rows"] == 1
    assert s["summary_bytes"] == len(json.dumps("- line = 0; + line = 1"))
    assert s["bytes"] == s["snapshot_bytes"] + s["summary_bytes"]
    # A compacted marker is bookkeeping, not reclaimable source.
    compact_code_changes(conn, ["st1"])
    assert source_code_storage(conn)["summary_rows"] == 0
