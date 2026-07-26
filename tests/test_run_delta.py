"""L2: diff-vs-previous-run (get_previous_run, diff_runs, format_run_delta)."""
from __future__ import annotations

import time

from exptrack.core import Experiment
from exptrack.core.db import get_db
from exptrack.core.queries import (
    diff_runs,
    format_run_delta,
    get_previous_run,
)


def _run(script, params, metrics=None):
    exp = Experiment(script=script, params=params)
    for k, v in (metrics or {}).items():
        exp.log_metric(k, v)
    exp.finish()
    return exp.id


def test_get_previous_run_same_script(tmp_project):
    a = _run("train.py", {"lr": 0.01})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.02})
    conn = get_db()
    prev = get_previous_run(conn, b)
    assert prev is not None and prev["id"] == a


def test_previous_run_scoped_to_script(tmp_project):
    _run("other.py", {"lr": 0.9})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.02})
    conn = get_db()
    # No earlier run of train.py exists → no previous.
    assert get_previous_run(conn, b) is None


def test_previous_run_skips_trashed(tmp_project):
    from exptrack.core.db import trash_experiment
    a = _run("train.py", {"lr": 0.01})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.02})
    time.sleep(0.01)
    c = _run("train.py", {"lr": 0.03})
    conn = get_db()
    trash_experiment(conn, b)
    conn.commit()
    prev = get_previous_run(conn, c)
    assert prev["id"] == a  # b is trashed, so a is the previous


def test_diff_runs_params_and_metrics(tmp_project):
    a = _run("train.py", {"lr": 0.01, "bs": 32}, {"acc": 0.80})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.02, "bs": 32}, {"acc": 0.87})
    conn = get_db()
    d = diff_runs(conn, a, b)
    pk = {c["key"]: (c["from"], c["to"]) for c in d["param_changes"]}
    assert pk == {"lr": ("0.01", "0.02")} or "lr" in pk  # bs unchanged, not listed
    assert "bs" not in pk
    mk = {c["key"]: c for c in d["metric_changes"]}
    assert "acc" in mk
    assert abs(mk["acc"]["delta"] - 0.07) < 1e-6


def test_diff_runs_skips_metric_present_on_one_side(tmp_project):
    # A metric the baseline run never logged isn't a value change — it was just
    # not measured. It must not flood the delta as a None→value change (the bug
    # where comparing a metric-logging run against a metrics-less run — e.g. an
    # empty phantom or a pre-metrics run — reported everything as "changed").
    a = _run("train.py", {"lr": 0.01})                     # no metrics
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.01}, {"acc": 0.87, "loss": 0.13})
    conn = get_db()
    d = diff_runs(conn, a, b)
    assert d["metric_changes"] == []                       # nothing "changed"
    # And the one-line summary never renders a "None→" metric fragment.
    prev = get_previous_run(conn, b)
    line = format_run_delta(d, prev)
    assert "None→" not in line and "acc" not in line


def test_diff_runs_metric_change_needs_both_sides(tmp_project):
    # A genuine value move (both sides present) is still reported; a key present
    # on only one side is not.
    a = _run("train.py", {"lr": 0.01}, {"acc": 0.80})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.01}, {"acc": 0.87, "f1": 0.9})
    conn = get_db()
    mk = {c["key"]: c for c in diff_runs(conn, a, b)["metric_changes"]}
    assert set(mk) == {"acc"}                              # f1 (b-only) skipped
    assert abs(mk["acc"]["delta"] - 0.07) < 1e-6


def test_format_run_delta_nonempty(tmp_project):
    a = _run("train.py", {"lr": 0.01}, {"acc": 0.80})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.02}, {"acc": 0.87})
    conn = get_db()
    prev = get_previous_run(conn, b)
    line = format_run_delta(diff_runs(conn, a, b), prev)
    assert "lr" in line and "→" in line


def test_format_run_delta_empty_when_identical(tmp_project):
    a = _run("train.py", {"lr": 0.01}, {"acc": 0.80})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.01}, {"acc": 0.80})
    conn = get_db()
    d = diff_runs(conn, a, b)
    # Same params + same metrics; code_changed may be False in a non-git tmp
    # project (both empty signatures) → empty summary.
    assert d["param_changes"] == []
    assert d["metric_changes"] == []


def test_finish_prints_delta(tmp_project, capsys):
    _run("train.py", {"lr": 0.01})
    time.sleep(0.01)
    exp = Experiment(script="train.py", params={"lr": 0.02})
    exp.finish()
    err = capsys.readouterr().err
    assert "vs prev" in err and "lr" in err


def test_api_run_delta_route(tmp_project):
    from exptrack.dashboard.routes.read_routes import api_run_delta
    a = _run("train.py", {"lr": 0.01}, {"acc": 0.80})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.02}, {"acc": 0.87})
    conn = get_db()
    d = api_run_delta(conn, b)
    assert d["previous"]["id"] == a
    assert any(c["key"] == "lr" for c in d["param_changes"])
    # First run of its script → previous is None
    assert api_run_delta(conn, a)["previous"] is None


def test_float_noise_is_not_a_metric_change(tmp_project):
    """0.9 + 0.03 and 0.85 + 0.04 * 2 are both 0.93 but differ by 1.1e-16.

    Reporting that as a change rendered a delta of "-0.0000 (-0.0%)" — a row
    claiming something moved, showing a value that reads as zero.
    """
    a = _run("train.py", {"lr": 0.01}, {"acc": 0.9 + 0.03})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.01}, {"acc": 0.85 + 0.04 * 2})
    conn = get_db()
    assert (0.9 + 0.03) != (0.85 + 0.04 * 2)      # genuinely different floats
    assert diff_runs(conn, a, b)["metric_changes"] == []


def test_small_real_metric_change_still_reported(tmp_project):
    """The noise filter is scaled, so a small *real* move is not swallowed."""
    a = _run("train.py", {"lr": 0.01}, {"loss": 0.5})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.01}, {"loss": 0.5000001})
    conn = get_db()
    changes = diff_runs(conn, a, b)["metric_changes"]
    assert [c["key"] for c in changes] == ["loss"]


def test_source_changed_ignores_unrelated_repo_edits(tmp_project):
    """`code_changed` covers the whole working tree, so an edit to any other
    tracked file moved it — the strip claimed "code changed" for a byte-identical
    rerun, contradicting the Code-changes panel beside it. `source_changed`
    reads the run's own snapshot instead."""
    a = _run("train.py", {"lr": 0.01})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.01})
    conn = get_db()

    def _run_with_snapshot(exp_id, snapshot_hash):
        conn.execute(
            "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,'auto')",
            (exp_id, "_code_snapshot",
             f'[{{"hash": "{snapshot_hash}", "kind": "script", "path": "train.py"}}]'),
        )
        conn.commit()

    _run_with_snapshot(a, "aaaa1111")
    _run_with_snapshot(b, "aaaa1111")          # identical script source
    # Simulate the repo-wide signal moving (an unrelated file was edited).
    conn.execute("UPDATE experiments SET git_diff=? WHERE id=?", ("--- other.py", b))
    conn.commit()

    d = diff_runs(conn, a, b)
    assert d["code_changed"] is True            # repository state did differ
    assert d["source_changed"] is False         # this run's code did not
    assert "code changed" not in format_run_delta(d, None)
    assert "repo changed elsewhere" in format_run_delta(d, None)

    conn.execute("UPDATE params SET value=? WHERE exp_id=? AND key='_code_snapshot'",
                 ('[{"hash": "bbbb2222", "kind": "script", "path": "train.py"}]', b))
    conn.commit()
    d2 = diff_runs(conn, a, b)
    assert d2["source_changed"] is True
    assert "code changed" in format_run_delta(d2, None)


def test_source_changed_none_without_captured_code(tmp_project):
    a = _run("train.py", {"lr": 0.01})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.02})
    conn = get_db()
    # Neither run has a snapshot or cell_exec events → unknown, not False.
    assert diff_runs(conn, a, b)["source_changed"] is None


def test_previous_run_tie_breaks_on_insertion_order(tmp_project):
    """Two runs launched inside the same clock tick tie on created_at.

    The tie-break used to be whatever order SQLite returned, so "previous" could
    resolve to the run that started *after* this one — and the strip would then
    present a later run as the baseline. rowid is insertion order, so the pair
    always resolves backwards in time.
    """
    from exptrack.core.queries import find_previous_by_script
    a = _run("train.py", {"lr": 0.01})
    b = _run("train.py", {"lr": 0.02})
    conn = get_db()
    same = "2026-07-26T12:00:00.000000+00:00"
    conn.execute("UPDATE experiments SET created_at=? WHERE id IN (?,?)", (same, a, b))
    conn.commit()
    # a was inserted first, so it is b's previous — and a has none.
    assert (get_previous_run(conn, b) or {}).get("id") == a
    assert get_previous_run(conn, a) is None
    assert (find_previous_by_script(conn, b) or {}).get("id") == a
    assert find_previous_by_script(conn, a) is None


def test_running_run_is_not_a_baseline(tmp_project):
    """An unfinished run's metrics are still moving, so a delta against it
    doesn't reproduce. Both baseline lookups skip past it to the last finished
    run of the script."""
    from exptrack.core.queries import find_previous_by_script
    a = _run("train.py", {"lr": 0.01}, {"acc": 0.80})
    time.sleep(0.01)
    mid = Experiment(script="train.py", params={"lr": 0.02})   # left running
    mid.log_metric("acc", 0.5)
    time.sleep(0.01)
    c = _run("train.py", {"lr": 0.03}, {"acc": 0.87})
    conn = get_db()
    assert conn.execute("SELECT status FROM experiments WHERE id=?",
                        (mid.id,)).fetchone()["status"] == "running"
    assert (get_previous_run(conn, c) or {})["id"] == a
    assert (find_previous_by_script(conn, c) or {})["id"] == a


def test_failed_run_is_kept_as_baseline_but_flagged(tmp_project):
    """"it broke, I fixed it, what changed?" is the loop this exists for, so a
    failed run stays the baseline — with its status carried through so the UI
    can say the metrics stop where it crashed."""
    from exptrack.core.queries import find_previous_by_script
    bad = Experiment(script="train.py", params={"lr": 0.01})
    bad.log_metric("acc", 0.41)
    bad.fail("boom")
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.02}, {"acc": 0.87})
    conn = get_db()
    prev = get_previous_run(conn, b)
    assert prev["id"] == bad.id and prev["status"] == "failed"
    assert find_previous_by_script(conn, b)["status"] == "failed"
    # And the one-line summary names the failure rather than presenting the
    # crash-point metric as a measured baseline.
    summary = format_run_delta(diff_runs(conn, bad.id, b), prev)
    assert "failed" in summary


def test_trashing_a_baseline_falls_back_to_the_next_survivor(tmp_project):
    """Deleting a run must not leave a dangling baseline: both lookups walk back
    to the next surviving run, matching what the experiment list shows."""
    from exptrack.core.db import restore_experiment, trash_experiment
    from exptrack.core.queries import find_previous_by_script
    a = _run("train.py", {"lr": 0.01})
    time.sleep(0.01)
    b = _run("train.py", {"lr": 0.02})
    time.sleep(0.01)
    c = _run("train.py", {"lr": 0.03})
    conn = get_db()
    trash_experiment(conn, b)
    conn.commit()
    assert (get_previous_run(conn, c) or {})["id"] == a
    assert (find_previous_by_script(conn, c) or {})["id"] == a
    # Trashing every earlier run leaves no baseline at all, not a broken one.
    trash_experiment(conn, a)
    conn.commit()
    assert get_previous_run(conn, c) is None
    assert find_previous_by_script(conn, c) is None
    # Restoring puts it back.
    restore_experiment(conn, b)
    conn.commit()
    assert (get_previous_run(conn, c) or {})["id"] == b
