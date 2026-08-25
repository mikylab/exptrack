"""Tests for exptrack/core/leaderboard.py — top runs and the best-so-far curve.

The properties worth guarding are the ones that make a ranking trustworthy: it
agrees with the matrix's own best row, it never mixes two metrics into one
ranking, it never drops unscored runs to make itself look complete, and the
best-so-far curve stays in launch order no matter how the caller sorted.
"""
from __future__ import annotations

import time


def _run(params=None, metrics=None, script="train.py", status="done"):
    """A finished run carrying *params* and final *metrics*."""
    from exptrack.core import Experiment

    exp = Experiment(script=script, params=params or {})
    for k, v in (metrics or {}).items():
        exp.log_metric(k, v)
    if status == "failed":
        exp.fail("boom")
    else:
        exp.finish()
    # created_at has second resolution in places; keep launch order distinct.
    time.sleep(0.01)
    return exp.id


# ---------------------------------------------------------------------------
# Top runs
# ---------------------------------------------------------------------------

def test_ranks_by_the_goal(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import top_runs

    ids = [_run({"lr": 0.1}, {"val_acc": 0.7}),
           _run({"lr": 0.2}, {"val_acc": 0.9}),
           _run({"lr": 0.3}, {"val_acc": 0.8})]
    out = top_runs(get_db(), ids)

    assert [r["value"] for r in out["runs"]] == [0.9, 0.8, 0.7]
    assert [r["rank"] for r in out["runs"]] == [1, 2, 3]
    assert out["metric"]["goal"] == "max"


def test_lower_is_better_metric_ranks_the_other_way(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import top_runs

    ids = [_run({"lr": 0.1}, {"loss": 0.7}), _run({"lr": 0.2}, {"loss": 0.2})]
    out = top_runs(get_db(), ids)

    assert out["metric"] == {"key": "loss", "goal": "min"}
    assert out["runs"][0]["value"] == 0.2


def test_top_run_agrees_with_the_matrix_best_row(tmp_project):
    """One ranking rule, or two surfaces disagree over the same runs."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import top_runs
    from exptrack.core.param_study import build_matrix

    ids = [_run({"lr": 0.1}, {"val_acc": 0.7}),
           _run({"lr": 0.2}, {"val_acc": 0.9}),
           _run({"lr": 0.3}, {"val_acc": 0.85})]
    conn = get_db()

    assert top_runs(conn, ids)["runs"][0]["id"] == \
        build_matrix(conn, ids)["best_row_id"]


def test_matrix_best_row_agrees_with_top_runs_on_a_tie(tmp_project):
    """The agreement must hold when the leaders TIE, not only on distinct scores.

    Regression: build_matrix broke a score tie toward the *newest* run (min/max
    over a newest-first dict) while top_runs/best_so_far keep the *earlier* run,
    so the matrix highlighted a different 'best' than the Top-runs panel."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import top_runs
    from exptrack.core.param_study import build_matrix

    older = _run({"lr": 0.1}, {"val_acc": 0.9})   # launched first
    newer = _run({"lr": 0.2}, {"val_acc": 0.9})   # tied, launched later
    _run({"lr": 0.3}, {"val_acc": 0.5})
    conn = get_db()
    ids = [older, newer]

    top = top_runs(conn, ids)["runs"][0]["id"]
    assert top == older                                  # earlier run wins the tie
    assert build_matrix(conn, ids)["best_row_id"] == top  # matrix agrees


def test_limit_caps_the_list_but_not_the_counts(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import top_runs

    ids = [_run({"lr": i}, {"val_acc": i / 10}) for i in range(5)]
    out = top_runs(get_db(), ids, limit=2)

    assert len(out["runs"]) == 2
    assert out["n_runs"] == 5 and out["n_scored"] == 5


def test_unscored_runs_are_reported_not_dropped(tmp_project):
    """"Six of your twenty runs never logged the metric" is a fact about the
    search, not a rendering detail."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import top_runs

    scored = _run({"lr": 0.1}, {"val_acc": 0.7})
    bare = _run({"lr": 0.2})
    out = top_runs(get_db(), [scored, bare])

    assert [r["id"] for r in out["runs"]] == [scored]
    assert [r["id"] for r in out["unscored"]] == [bare]
    assert out["n_runs"] == 2 and out["n_scored"] == 1


def test_delta_from_best_is_relative_to_the_leader(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import top_runs

    ids = [_run({"lr": 0.1}, {"val_acc": 0.9}), _run({"lr": 0.2}, {"val_acc": 0.6})]
    out = top_runs(get_db(), ids)

    assert out["runs"][0]["delta_from_best"] == 0
    assert round(out["runs"][1]["delta_from_best"], 6) == -0.3


def test_ties_keep_launch_order(tmp_project):
    """An arbitrary tie-break would let the same set reorder between requests."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import top_runs

    first = _run({"lr": 0.1}, {"val_acc": 0.8})
    second = _run({"lr": 0.2}, {"val_acc": 0.8})
    out = top_runs(get_db(), [second, first])

    assert [r["id"] for r in out["runs"]] == [first, second]


def test_running_runs_are_excluded_and_counted(tmp_project):
    from exptrack.core import Experiment, get_db
    from exptrack.core.leaderboard import top_runs

    done = _run({"lr": 0.1}, {"val_acc": 0.7})
    live = Experiment(script="train.py", params={"lr": 0.2})
    live.log_metric("val_acc", 0.99)
    out = top_runs(get_db(), [done, live.id])

    assert [r["id"] for r in out["runs"]] == [done]
    assert out["excluded"]["running"] == 1


def test_rank_by_best_uses_the_peak_not_the_final_value(tmp_project):
    from exptrack.core import Experiment, get_db
    from exptrack.core.leaderboard import top_runs

    peaked = Experiment(script="train.py", params={"lr": 0.1})
    peaked.log_metric("val_acc", 0.95, step=1)
    peaked.log_metric("val_acc", 0.40, step=2)   # overfit late
    peaked.finish()
    steady = _run({"lr": 0.2}, {"val_acc": 0.60})

    conn = get_db()
    assert top_runs(conn, [peaked.id, steady])["runs"][0]["id"] == steady
    assert top_runs(conn, [peaked.id, steady],
                    rank_by="best")["runs"][0]["id"] == peaked.id


# ---------------------------------------------------------------------------
# One metric per set
# ---------------------------------------------------------------------------

def test_the_majority_metric_wins_not_the_newest_run(tmp_project):
    """Rows arrive newest-first; one legacy run must not define the axis."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import top_runs

    ids = [_run({"lr": 0.1}, {"val_acc": 0.7}),
           _run({"lr": 0.2}, {"val_acc": 0.8}),
           _run({"lr": 0.3}, {"loss": 0.1})]   # newest, odd one out
    out = top_runs(get_db(), ids)

    assert out["metric"]["key"] == "val_acc"
    assert out["n_scored"] == 2
    assert out["off_metric_runs"] == 1


def test_off_metric_runs_are_never_ranked_against_the_others(tmp_project):
    """Two numbers measuring different things do not share a ranking."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import top_runs

    ids = [_run({"lr": 0.1}, {"val_acc": 0.7}),
           _run({"lr": 0.2}, {"val_acc": 0.8}),
           _run({"lr": 0.3}, {"loss": 999.0})]
    out = top_runs(get_db(), ids)

    assert 999.0 not in [r["value"] for r in out["runs"]]


# ---------------------------------------------------------------------------
# Best so far
# ---------------------------------------------------------------------------

def test_curve_is_in_launch_order_however_the_ids_arrive(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import best_so_far

    a = _run({"lr": 0.1}, {"val_acc": 0.5})
    b = _run({"lr": 0.2}, {"val_acc": 0.9})
    c = _run({"lr": 0.3}, {"val_acc": 0.7})
    out = best_so_far(get_db(), [c, a, b])   # deliberately shuffled

    assert [p["id"] for p in out["points"]] == [a, b, c]
    assert [p["best_so_far"] for p in out["points"]] == [0.5, 0.9, 0.9]


def test_only_real_improvements_are_flagged(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import best_so_far

    a = _run({"lr": 0.1}, {"val_acc": 0.5})
    b = _run({"lr": 0.2}, {"val_acc": 0.4})
    c = _run({"lr": 0.3}, {"val_acc": 0.8})
    out = best_so_far(get_db(), [a, b, c])

    assert [p["improved"] for p in out["points"]] == [True, False, True]
    assert out["improvements"] == [a, c]
    assert out["best_run_id"] == c and out["best_value"] == 0.8


def test_lower_is_better_improves_downward(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import best_so_far

    a = _run({"lr": 0.1}, {"loss": 0.5})
    b = _run({"lr": 0.2}, {"loss": 0.2})
    out = best_so_far(get_db(), [a, b])

    assert [p["best_so_far"] for p in out["points"]] == [0.5, 0.2]
    assert out["best_run_id"] == b


def test_unscored_runs_keep_their_place_in_the_curve(tmp_project):
    """Dropping them would make a 30-run search look like it converged in 12."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import best_so_far

    a = _run({"lr": 0.1}, {"val_acc": 0.5})
    bare = _run({"lr": 0.2})
    c = _run({"lr": 0.3}, {"val_acc": 0.6})
    out = best_so_far(get_db(), [a, bare, c])

    assert [p["id"] for p in out["points"]] == [a, bare, c]
    assert [p["value"] for p in out["points"]] == [0.5, None, 0.6]
    assert [p["best_so_far"] for p in out["points"]] == [0.5, 0.5, 0.6]


def test_since_improvement_counts_every_run_that_followed(tmp_project):
    """Forty attempts that logged nothing are still forty that didn't win."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import best_so_far

    ids = [_run({"lr": 0.1}, {"val_acc": 0.9})]
    ids += [_run({"lr": i}, {"val_acc": 0.2}) for i in range(3)]
    ids.append(_run({"lr": 9}))          # unscored, still an attempt
    out = best_so_far(get_db(), ids)

    assert out["since_improvement"] == 4


def test_an_improvement_names_what_changed(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import best_so_far

    a = _run({"lr": 0.1, "seed": 1}, {"val_acc": 0.5})
    b = _run({"lr": 0.3, "seed": 1}, {"val_acc": 0.8})
    out = best_so_far(get_db(), [a, b])

    changed = out["points"][1]["changed"]
    assert set(changed) == {"lr"}
    assert changed["lr"]["before"] == 0.1 and changed["lr"]["after"] == 0.3


def test_a_parameter_absent_on_one_side_is_flagged_not_nulled(tmp_project):
    """MISSING is a variation, not a value — `None` is one a run can log."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import best_so_far

    a = _run({"lr": 0.1}, {"val_acc": 0.5})
    b = _run({"lr": 0.1, "dropout": 0.2}, {"val_acc": 0.8})
    out = best_so_far(get_db(), [a, b])

    changed = out["points"][1]["changed"]["dropout"]
    assert changed["before_missing"] is True
    assert changed["after_missing"] is False and changed["after"] == 0.2


def test_empty_selection_is_not_an_error(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import best_so_far, top_runs

    conn = get_db()
    assert top_runs(conn, [])["runs"] == []
    assert best_so_far(conn, [])["points"] == []
    assert best_so_far(conn, [])["since_improvement"] is None


# ---------------------------------------------------------------------------
# The trade-off frontier
# ---------------------------------------------------------------------------

def test_frontier_keeps_only_the_runs_nothing_beat_on_both(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import pareto_front

    # acc up / size down. b beats a on both; c and d each win one.
    a = _run({"n": 1}, {"acc": 0.80, "size_mb": 200.0})
    b = _run({"n": 2}, {"acc": 0.90, "size_mb": 100.0})
    c = _run({"n": 3}, {"acc": 0.95, "size_mb": 400.0})
    d = _run({"n": 4}, {"acc": 0.70, "size_mb": 50.0})
    # size_mb is not a name the goal heuristic can read, so it is stated —
    # which is exactly why the goals are parameters and ride on the payload.
    out = pareto_front(get_db(), [a, b, c, d], "acc", "size_mb", y_goal="min")

    assert out["x"] == {"key": "acc", "goal": "max"}
    assert out["y"] == {"key": "size_mb", "goal": "min"}
    assert set(out["frontier"]) == {b, c, d}
    dom = {p["id"]: p["dominated_by"] for p in out["points"] if not p["frontier"]}
    assert dom == {a: b}


def test_goals_are_inferred_from_the_metric_name(tmp_project):
    """`loss` and `latency` minimize without being told — the same heuristic
    the rest of the product colours deltas with."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import pareto_front

    ids = [_run({"n": 1}, {"acc": 0.9, "latency_ms": 10.0})]
    out = pareto_front(get_db(), ids, "acc", "latency_ms")

    assert out["x"]["goal"] == "max"
    assert out["y"]["goal"] == "min"


def test_an_explicit_goal_overrides_the_inference(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import pareto_front

    a = _run({"n": 1}, {"score": 0.9, "count": 10.0})
    b = _run({"n": 2}, {"score": 0.8, "count": 5.0})
    conn = get_db()

    high = pareto_front(conn, [a, b], "score", "count")
    assert set(high["frontier"]) == {a}          # a wins both when count is max
    low = pareto_front(conn, [a, b], "score", "count", y_goal="min")
    assert set(low["frontier"]) == {a, b}        # now they trade off


def test_identical_runs_are_both_on_the_frontier(tmp_project):
    """Neither beat the other, so calling either dominated would be a claim the
    data does not make."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import pareto_front

    a = _run({"n": 1}, {"acc": 0.9, "size_mb": 100.0})
    b = _run({"n": 2}, {"acc": 0.9, "size_mb": 100.0})
    out = pareto_front(get_db(), [a, b], "acc", "size_mb")

    assert set(out["frontier"]) == {a, b}


def test_a_tie_on_one_axis_is_still_domination_when_the_other_wins(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import pareto_front

    good = _run({"n": 1}, {"acc": 0.9, "size_mb": 100.0})
    same_acc_bigger = _run({"n": 2}, {"acc": 0.9, "size_mb": 300.0})
    out = pareto_front(get_db(), [good, same_acc_bigger], "acc", "size_mb",
                       y_goal="min")

    assert out["frontier"] == [good]
    assert [p["dominated_by"] for p in out["points"]
            if p["id"] == same_acc_bigger] == [good]


def test_runs_missing_either_metric_are_reported_not_dropped(tmp_project):
    """On a chart an absent point and an unmeasured one look identical, and the
    second is the one that changes what you do next."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import pareto_front

    full = _run({"n": 1}, {"acc": 0.9, "size_mb": 100.0})
    half = _run({"n": 2}, {"acc": 0.8})
    out = pareto_front(get_db(), [full, half], "acc", "size_mb")

    assert out["n_runs"] == 2 and out["n_placed"] == 1
    assert [(u["id"], u["missing_metrics"]) for u in out["unplaced"]] == \
        [(half, ["size_mb"])]


def test_frontier_is_ordered_for_drawing(tmp_project):
    """Best-x first, so the client can draw the line without re-sorting."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import pareto_front

    lo = _run({"n": 1}, {"acc": 0.70, "size_mb": 50.0})
    mid = _run({"n": 2}, {"acc": 0.85, "size_mb": 120.0})
    hi = _run({"n": 3}, {"acc": 0.95, "size_mb": 400.0})
    out = pareto_front(get_db(), [lo, mid, hi], "acc", "size_mb", y_goal="min")

    assert out["frontier"] == [hi, mid, lo]


def test_values_are_reported_as_recorded_not_negated(tmp_project):
    """The min-goal axis is flipped for the sweep only — a negated loss must
    never reach the screen."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import pareto_front

    ids = [_run({"n": 1}, {"acc": 0.9, "loss": 0.25})]
    point = pareto_front(get_db(), ids, "acc", "loss")["points"][0]

    assert point["x"] == 0.9 and point["y"] == 0.25


def test_available_metrics_are_ranked_by_coverage(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.leaderboard import pareto_front

    ids = [_run({"n": 1}, {"acc": 0.9, "size_mb": 100.0}),
           _run({"n": 2}, {"acc": 0.8, "size_mb": 90.0}),
           _run({"n": 3}, {"acc": 0.7, "oddball": 1.0})]
    out = pareto_front(get_db(), ids, "acc", "size_mb")

    assert out["available_metrics"][0]["key"] == "acc"
    assert {"key": "oddball", "n_runs": 1} in out["available_metrics"]


def test_no_axes_still_returns_the_pickable_metrics(tmp_project):
    """So the client can populate its pickers without a second, differently
    shaped request."""
    from exptrack.core import get_db
    from exptrack.core.leaderboard import pareto_front

    ids = [_run({"n": 1}, {"acc": 0.9, "size_mb": 100.0})]
    out = pareto_front(get_db(), ids, "", "")

    assert out["n_placed"] == 0
    assert [m["key"] for m in out["available_metrics"]] == ["acc", "size_mb"]
