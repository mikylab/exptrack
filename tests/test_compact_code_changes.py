"""`exptrack compact --code-changes` — reclaim derived code-change summaries.

The summary is a per-run copy of the changed lines; the run's full source lives
content-addressed and deduped in `code_snapshots`. So compacting the summary is
cheap and lossless *only where a snapshot exists*. For a run without one the
summary is the only record of what changed, and stripping it is unrecoverable
data loss — that exclusion is the property these tests exist to pin down.
"""
import json

import pytest

from exptrack.core.db import get_db, store_code_snapshot
from exptrack.core.storage import (
    _runs_with_snapshot,
    compact_code_changes,
    preview_code_change_compact,
)


def _run(conn, exp_id, summary="- warmup = 100; + warmup = 200", snapshot_src=None):
    conn.execute(
        "INSERT INTO experiments (id, name, status, created_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (exp_id, exp_id, "done", "2026-08-01T00:00:00", "2026-08-01T00:00:00"),
    )
    if summary is not None:
        conn.execute(
            "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
            (exp_id, "_code_changes", json.dumps(summary), "auto"),
        )
    if snapshot_src is not None:
        h = store_code_snapshot(conn, snapshot_src, kind="script", path="t.py")
        conn.execute(
            "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
            (exp_id, "_code_snapshot",
             json.dumps([{"hash": h, "kind": "script", "path": "t.py"}]), "auto"),
        )
    conn.commit()
    return exp_id


def _summary(conn, exp_id):
    r = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key='_code_changes'", (exp_id,)
    ).fetchone()
    return r[0] if r else None


@pytest.fixture
def conn(tmp_project):
    return get_db()


def test_run_with_snapshot_is_compacted(conn):
    _run(conn, "withsnap", snapshot_src="warmup = 200\n")
    st = compact_code_changes(conn, ["withsnap"])
    assert st["runs"] == 1 and st["rows"] == 1 and st["bytes"] > 0
    assert st["skipped_no_snapshot"] == []
    assert "[compacted" in _summary(conn, "withsnap")


def test_run_without_snapshot_is_never_compacted(conn):
    """The load-bearing guard: no snapshot ⇒ the summary is the only copy."""
    original = _summary(conn, _run(conn, "nosnap", snapshot_src=None))
    st = compact_code_changes(conn, ["nosnap"])
    assert st["runs"] == 0 and st["rows"] == 0
    assert st["skipped_no_snapshot"] == ["nosnap"]
    assert _summary(conn, "nosnap") == original      # untouched


def test_dangling_snapshot_reference_does_not_count_as_a_backstop(conn):
    """A `_code_snapshot` naming a row that is gone is not a recoverable source."""
    _run(conn, "dangling", snapshot_src="warmup = 200\n")
    conn.execute("DELETE FROM code_snapshots")       # blob swept / never stored
    conn.commit()
    assert _runs_with_snapshot(conn, ["dangling"]) == set()
    st = compact_code_changes(conn, ["dangling"])
    assert st["rows"] == 0 and st["skipped_no_snapshot"] == ["dangling"]
    assert "[compacted" not in _summary(conn, "dangling")


def test_mixed_batch_compacts_only_the_recoverable_runs(conn):
    _run(conn, "a", snapshot_src="x = 1\n")
    _run(conn, "b", snapshot_src=None)
    st = compact_code_changes(conn, ["a", "b"])
    assert st["runs"] == 1
    assert st["skipped_no_snapshot"] == ["b"]
    assert "[compacted" in _summary(conn, "a")
    assert "[compacted" not in _summary(conn, "b")


def test_preview_describes_the_write_that_follows(conn):
    _run(conn, "p1", snapshot_src="x = 1\n")
    _run(conn, "p2", snapshot_src=None)
    before = preview_code_change_compact(conn, ["p1", "p2"])
    after = compact_code_changes(conn, ["p1", "p2"])
    assert before == after
    # And the preview genuinely did not write.
    assert before["rows"] == 1


def test_compaction_is_idempotent(conn):
    _run(conn, "idem", snapshot_src="x = 1\n")
    first = compact_code_changes(conn, ["idem"])
    second = compact_code_changes(conn, ["idem"])
    assert first["rows"] == 1
    assert second["rows"] == 0        # already carries the marker
    assert _summary(conn, "idem").count("[compacted") == 1


def test_per_cell_notebook_summaries_are_covered(conn):
    exp = _run(conn, "cells", summary=None, snapshot_src="x = 1\n")
    for i in (1, 2):
        conn.execute(
            "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
            (exp, f"_code_change/cell_{i}", json.dumps(f"+ line {i}"), "auto"),
        )
    conn.commit()
    st = compact_code_changes(conn, [exp])
    assert st["rows"] == 2
    vals = [r[0] for r in conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key LIKE '_code_change/%'", (exp,))]
    assert all("[compacted" in v for v in vals)


def test_marker_says_the_source_is_still_available(conn):
    """The panel must not read as 'nothing changed' after compaction."""
    _run(conn, "msg", snapshot_src="x = 1\n")
    compact_code_changes(conn, ["msg"])
    assert "snapshot" in _summary(conn, "msg")


def test_empty_id_list_is_a_no_op(conn):
    st = compact_code_changes(conn, [])
    assert st == {"runs": 0, "rows": 0, "bytes": 0, "run_ids": [],
                  "skipped_no_snapshot": []}


def test_source_is_still_recoverable_after_compaction(conn):
    """The whole justification: the snapshot survives and still has the code."""
    from exptrack.core.db import get_code_snapshot
    _run(conn, "rec", snapshot_src="warmup = 200\nprint('a')\n")
    compact_code_changes(conn, ["rec"])
    raw = conn.execute(
        "SELECT value FROM params WHERE exp_id='rec' AND key='_code_snapshot'"
    ).fetchone()[0]
    h = json.loads(raw)[0]["hash"]
    assert get_code_snapshot(conn, h)["content"] == "warmup = 200\nprint('a')\n"


def test_marker_states_each_rows_own_bytes(conn):
    """The marker exists to be honest about what was removed — an aggregate
    total stamped into every row named the wrong number on each."""
    short = "- a = 1; + a = 2"
    long = "- warmup = 100; + warmup = 200; - lr = 0.1; + lr = 0.01"
    _run(conn, "short", summary=short, snapshot_src="a = 2\n")
    _run(conn, "long", summary=long, snapshot_src="warmup = 200\n")
    compact_code_changes(conn, ["short", "long"])
    # LENGTH(value) counts the stored JSON encoding, quotes included — the
    # same basis the preview sums, so the two figures reconcile.
    assert f"{len(json.dumps(short))} B stripped" in _summary(conn, "short")
    assert f"{len(json.dumps(long))} B stripped" in _summary(conn, "long")
    assert _summary(conn, "short") != _summary(conn, "long")


def test_skipped_only_names_runs_that_hold_a_summary(conn):
    """A run with no summary has nothing to skip — naming it reads as data
    being withheld ("summary is their only copy" of nothing)."""
    _run(conn, "no-snap-with-summary", snapshot_src=None)
    _run(conn, "no-snap-no-summary", summary=None, snapshot_src=None)
    stats = preview_code_change_compact(
        conn, ["no-snap-with-summary", "no-snap-no-summary"])
    assert stats["skipped_no_snapshot"] == ["no-snap-with-summary"]
    stats2 = compact_code_changes(
        conn, ["no-snap-with-summary", "no-snap-no-summary"])
    assert stats2["skipped_no_snapshot"] == ["no-snap-with-summary"]


# ── Timeline compaction must be provable, not inferred from absence ──────────

def test_a_never_compacted_run_is_not_reported_as_compacted(conn):
    """A script run against a clean tree stores no source_diff at all. Reading
    "no diff" as "diff was stripped" made the detail header claim a run had
    been compacted that nothing had ever touched — and sent the user looking
    for source that was never missing."""
    from exptrack.core.queries import _get_compact_status
    _run(conn, "clean", summary=None, snapshot_src="x = 1\n")
    conn.execute(
        "INSERT INTO timeline (exp_id, seq, event_type, cell_hash, ts, source_diff) "
        "VALUES (?,?,?,?,?,NULL)",
        ("clean", 1, "cell_exec", "abc123", "2026-08-01T00:00:00"))
    conn.commit()
    assert _get_compact_status(conn, "clean", "")["timeline"] == "none"


def test_timeline_compaction_leaves_provable_evidence(conn):
    from exptrack.cli.admin_cmds import _compact_timeline_diffs
    from exptrack.core.queries import _get_compact_status
    _run(conn, "tl", summary=None, snapshot_src="x = 1\n")
    conn.execute(
        "INSERT INTO timeline (exp_id, seq, event_type, cell_hash, ts, source_diff) "
        "VALUES (?,?,?,?,?,?)",
        ("tl", 1, "cell_exec", "h1", "2026-08-01T00:00:00", "- a = 1; + a = 2"))
    conn.commit()
    assert _get_compact_status(conn, "tl", "")["timeline"] == "stored"

    freed = _compact_timeline_diffs(conn, ["tl"])
    assert freed == len("- a = 1; + a = 2")
    assert _get_compact_status(conn, "tl", "")["timeline"] == "compacted"
    marker = conn.execute(
        "SELECT source_diff FROM timeline WHERE exp_id='tl'").fetchone()[0]
    assert marker.startswith("[compacted")
    # Idempotent: re-running must not re-count the marker as freed bytes.
    assert _compact_timeline_diffs(conn, ["tl"]) == 0


@pytest.mark.parametrize("entry", ["cli", "dashboard"])
def test_both_timeline_compact_entry_points_behave_identically(conn, entry):
    """The CLI and the dashboard must not drift on this.

    They kept separate copies of the UPDATE, and only the CLI's was fixed to
    write a marker — so compacting from the dashboard still NULLed the column,
    and since a NULL `source_diff` is also the normal state for a clean-tree
    script run, the status read back as "never compacted" right after the user
    compacted it. A second dashboard pass then counted a CLI-written marker as
    reclaimable and erased the evidence it stands for.
    """
    from exptrack.core.queries import _get_compact_status
    if entry == "cli":
        from exptrack.cli.admin_cmds import _compact_timeline_diffs as compact
    else:
        from exptrack.dashboard.routes.write_routes.compact import (
            _compact_timeline_sources as compact,
        )
    _run(conn, "tl", summary=None, snapshot_src="x = 1\n")
    body = "- a = 1; + a = 2"
    conn.execute(
        "INSERT INTO timeline (exp_id, seq, event_type, cell_hash, ts, source_diff) "
        "VALUES (?,?,?,?,?,?)",
        ("tl", 1, "cell_exec", "h1", "2026-08-01T00:00:00", body))
    conn.commit()

    assert compact(conn, ["tl"]) == len(body)
    stored = conn.execute(
        "SELECT source_diff FROM timeline WHERE exp_id='tl'").fetchone()[0]
    assert stored is not None, "must leave evidence, not NULL"
    assert stored.startswith("[compacted")
    assert str(len(body)) in stored, "each row states its own byte count"
    assert _get_compact_status(conn, "tl", "")["timeline"] == "compacted"

    # Re-running frees nothing and preserves the marker.
    assert compact(conn, ["tl"]) == 0
    assert conn.execute(
        "SELECT source_diff FROM timeline WHERE exp_id='tl'").fetchone()[0] == stored


def test_timeline_compact_preview_describes_the_write(conn):
    """The dry-run must not promise bytes the compact won't free."""
    from exptrack.core.storage import (
        compact_timeline_diffs,
        preview_timeline_diff_compact,
    )
    _run(conn, "tl", summary=None, snapshot_src="x = 1\n")
    conn.execute(
        "INSERT INTO timeline (exp_id, seq, event_type, cell_hash, ts, source_diff) "
        "VALUES (?,?,?,?,?,?)",
        ("tl", 1, "cell_exec", "h1", "2026-08-01T00:00:00", "- a = 1; + a = 2"))
    conn.commit()

    preview = preview_timeline_diff_compact(conn, ["tl"])
    assert compact_timeline_diffs(conn, ["tl"])["bytes"] == preview["bytes"]
    # And an already-compacted row is offered by neither.
    assert preview_timeline_diff_compact(conn, ["tl"]) == {"events": 0, "bytes": 0}



def test_selection_names_the_runs_it_would_write(conn):
    """`eligible` is "recoverable from a snapshot", which is not the same set as
    "has a summary to strip" — a run can be snapshot-backed and hold nothing.

    The CLI dry-run reported the wider set, so `compact --code-changes` on a
    project of 50 runs announced "Would compact 50 experiment(s)" beside a modes
    line reading "1 row(s) in 1 run(s)".
    """
    from exptrack.core.storage import _code_change_selection

    _run(conn, "has-summary", snapshot_src="print(1)")
    _run(conn, "snapshot-only", summary=None, snapshot_src="print(2)")

    stats, eligible = _code_change_selection(conn, ["has-summary", "snapshot-only"])
    assert stats["run_ids"] == ["has-summary"]
    assert stats["runs"] == 1
    # The wider eligibility set holds both — it answers a different question.
    assert set(eligible) == {"has-summary", "snapshot-only"}


def test_run_ids_match_what_the_compact_actually_wrote(conn):
    """The dry-run's named set must be the set the write touches."""
    _run(conn, "a", snapshot_src="print(1)")
    _run(conn, "b", summary=None, snapshot_src="print(2)")
    ids = preview_code_change_compact(conn, ["a", "b"])["run_ids"]

    compact_code_changes(conn, ["a", "b"])
    changed = [e for e in ("a", "b")
               if str(json.loads(_summary(conn, e) or '""')).startswith("[compacted")]
    assert ids == changed
