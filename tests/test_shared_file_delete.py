"""Deleting a run must not be able to delete a *different* run's results.

The rule these cover: removing a run's records and removing a file another run
still needs are two decisions, and the second is never taken silently. Before
this, one delete answered both — deleting a stale run took the file the run that
replaced it was still using, and said nothing about it.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from exptrack.core import Experiment, get_db
from exptrack.core.db import (
    artifact_claims_by_others,
    delete_experiment,
    file_modified_after_run,
    get_delete_preview,
    run_end_ts,
)


def _run_writing(path: Path, content: bytes, script: str = "t.py") -> Experiment:
    exp = Experiment(script=script)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    exp.log_file(str(path))
    exp.finish()
    return exp


def test_a_shared_file_is_kept_and_the_preview_names_who_holds_it(tmp_project):
    plot = Path("files/plot.png")
    first = _run_writing(plot, b"first")
    second = _run_writing(plot, b"second")

    conn = get_db()
    prev = get_delete_preview(conn, first.id)
    row = next(a for a in prev["artifacts"] if a["path"].endswith("plot.png"))
    assert row["shared"] is True
    assert [h["id"] for h in row["shared_with"]] == [second.id]
    assert row["exists"] is False              # this delete would not remove it
    assert prev["artifacts_shared"] == 1
    assert prev["shared_bytes"] == row["size_bytes"] > 0

    stats = delete_experiment(conn, first.id, delete_files=True)
    conn.commit()
    assert stats["kept_shared"] == 1
    assert plot.read_bytes() == b"second"      # the survivor's output is intact


def test_the_delete_takes_a_shared_file_when_it_is_told_to(tmp_project):
    plot = Path("files/plot.png")
    first = _run_writing(plot, b"first")
    _run_writing(plot, b"second")

    conn = get_db()
    stats = delete_experiment(conn, first.id, delete_files=True,
                              delete_shared_files=True)
    conn.commit()
    assert stats["kept_shared"] == 0
    assert not plot.exists()                   # asked for, so taken


def test_a_file_written_after_the_run_ended_is_treated_as_shared(tmp_project):
    """The same situation with the second row missing.

    Runs recorded before the claim rule existed never got a row for a path they
    overwrote, so the only row for a live file belongs to the run whose output
    was replaced — the case that made a delete destroy the current results with
    nothing else in the database to object.
    """
    plot = Path("files/plot.png")
    first = _run_writing(plot, b"first")

    conn = get_db()
    # A later writer, with no run recording it: push the mtime past the slack
    # window rather than sleeping through it.
    plot.write_bytes(b"later")
    later = time.time() + 3600
    os.utime(plot, (later, later))

    prev = get_delete_preview(conn, first.id)
    row = next(a for a in prev["artifacts"] if a["path"].endswith("plot.png"))
    assert row["shared"] is True
    assert row["shared_with"] == []            # nobody claims it — mtime is the evidence
    assert row["modified_after_run"] is not None

    delete_experiment(conn, first.id, delete_files=True)
    conn.commit()
    assert plot.read_bytes() == b"later"


def test_a_runs_own_file_is_still_deleted(tmp_project):
    """The protection must not turn into "deletes never delete anything"."""
    out = Path("files/only.png")
    only = _run_writing(out, b"mine")

    conn = get_db()
    prev = get_delete_preview(conn, only.id)
    row = next(a for a in prev["artifacts"] if a["path"].endswith("only.png"))
    assert row["shared"] is False and row["exists"] is True

    delete_experiment(conn, only.id, delete_files=True)
    conn.commit()
    assert not out.exists()


def test_a_still_running_run_owns_what_it_wrote(tmp_project):
    """`run_end_ts` is None while a run is going, so nothing it wrote can be
    written off as out of date underneath it."""
    live = Experiment(script="live.py")
    f = Path("live.png")
    f.write_bytes(b"x")
    live.log_file(str(f))

    conn = get_db()
    assert run_end_ts(conn, live.id) is None
    assert file_modified_after_run(f, run_end_ts(conn, live.id)) is None


def test_claims_name_every_holder_once(tmp_project):
    shared = Path("shared.pt")
    a = _run_writing(shared, b"a", script="a.py")
    b = _run_writing(shared, b"b", script="b.py")
    c = _run_writing(shared, b"c", script="c.py")

    conn = get_db()
    from exptrack.core.db import _norm_path
    holders = artifact_claims_by_others(conn, a.id)[_norm_path(shared)]
    assert sorted(h["id"] for h in holders) == sorted([b.id, c.id])


def test_the_dashboard_route_needs_the_second_yes_too(tmp_project):
    """The two questions stay two over HTTP: `delete_files` alone never takes a
    file another run holds — the client has to send `delete_shared_files`."""
    from exptrack.dashboard.routes.write_routes import api_delete_permanent

    plot = Path("files/plot.png")
    first = _run_writing(plot, b"first")
    second = _run_writing(plot, b"second")

    conn = get_db()
    r = api_delete_permanent(conn, first.id, {"delete_files": True})
    assert r["ok"] is True and r["deleted_shared_files"] is False
    assert r["file_stats"]["kept_shared"] == 1
    assert plot.read_bytes() == b"second"

    r2 = api_delete_permanent(conn, second.id,
                              {"delete_files": True, "delete_shared_files": True})
    assert r2["deleted_shared_files"] is True
    assert not plot.exists()


def test_the_detail_payload_says_who_else_links_each_artifact(tmp_project):
    """The Artifacts table's "also in N runs" badge, and the unlink action next
    to it, both need the holders — an unlink offered without saying what else
    is attached is the same blind delete one level down."""
    from exptrack.core.queries import get_experiment_detail

    plot = Path("files/plot.png")
    first = _run_writing(plot, b"first")
    second = _run_writing(plot, b"second")

    solo_path = Path("files/only_mine.txt")
    solo_path.write_text("mine")
    first.log_file(str(solo_path))

    conn = get_db()
    detail = get_experiment_detail(conn, first.id)
    row = next(a for a in detail["artifacts"] if a["path"].endswith("plot.png"))
    assert [h["id"] for h in row["linked_by"]] == [second.id]
    assert row["linked_by"][0]["name"] == second.name

    # A file only this run holds carries an empty list, not a missing key: the
    # badge renderer reads it on every row.
    solo = next(a for a in detail["artifacts"] if a["path"].endswith("only_mine.txt"))
    assert solo["linked_by"] == []


def test_unlinking_the_other_holder_hands_the_file_back(tmp_project):
    """The dashboard's unlink is the same operation the delete consults.

    Unlink the stale run's record and the survivor owns the file again — which
    is the whole point of offering the action next to the run that holds it.
    """
    from exptrack.dashboard.routes.write_routes import (
        api_delete_artifact,
        api_delete_permanent,
    )

    plot = Path("files/plot.png")
    stale = _run_writing(plot, b"first")
    current = _run_writing(plot, b"second")

    conn = get_db()
    r = api_delete_artifact(conn, stale.id, {"label": "", "path": str(plot)})
    assert r["ok"] is True
    assert plot.is_file(), "unlink must never touch the file"

    api_delete_permanent(conn, current.id, {"delete_files": True})
    assert not plot.exists()
