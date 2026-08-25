"""Regression tests for the comparison surfaces telling the truth.

Every test here corresponds to a 1.4 audit finding where a comparison surface
reported something confidently wrong: the wrong "last" value, a change that was
not a change, or an improvement coloured as a regression. They are grouped
because they share one rule — a comparison that is going to be believed has to
be right about what it is comparing.
"""
from __future__ import annotations

from types import SimpleNamespace

from conftest import capture as _capture


def test_step_less_metrics_report_the_last_value_not_the_first(tmp_project):
    """With every step NULL the `last` subquery's ORDER BY tied, and SQLite
    returned insert order — so `show` said 0.1 while the table said 0.9."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import get_experiment_detail, get_metrics_summary

    exp = Experiment(script="train.py")
    for v in (0.1, 0.5, 0.9):
        exp.log_metric("acc", v)      # no step — the plain log_metric case
    exp.finish()

    conn = get_db()
    detail = get_experiment_detail(conn, exp.id)
    acc = next(m for m in detail["metrics"] if m["key"] == "acc")
    assert acc["last"] == 0.9

    summary = next(m for m in get_metrics_summary(conn, exp.id) if m["key"] == "acc")
    assert summary["last"] == 0.9


def test_the_same_value_captured_two_ways_is_not_a_param_change(tmp_project):
    """`lr=0.01` from argparse (float) and from the pipeline CLI (string) is one
    configuration — param_study's own rule — so diff_runs must not report it."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import diff_runs

    a = Experiment(script="train.py", params={"lr": 0.01}); a.finish()
    b = Experiment(script="train.py", params={"lr": "0.01"}); b.finish()

    diff = diff_runs(get_db(), a.id, b.id)
    assert [c["key"] for c in diff["param_changes"]] == []


def test_param_changes_report_decoded_values_not_raw_json(tmp_project):
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import diff_runs

    a = Experiment(script="train.py", params={"opt": "adam"}); a.finish()
    b = Experiment(script="train.py", params={"opt": "sgd"}); b.finish()

    change = diff_runs(get_db(), a.id, b.id)["param_changes"][0]
    assert change["from"] == "adam" and change["to"] == "sgd"   # not '"adam"'


def test_cli_deltas_are_polarity_aware():
    """`compare` coloured green-when-bigger and `watch` hardcoded the opposite,
    so the same falling loss read as a regression on one and an improvement on
    the other. Both now share this one rule."""
    from exptrack.cli.inspect_cmds import _delta_is_better

    assert _delta_is_better("loss", -0.4) is True      # loss down = better
    assert _delta_is_better("loss", 0.4) is False
    assert _delta_is_better("val_acc", 0.4) is True    # accuracy up = better
    assert _delta_is_better("val_acc", -0.4) is False
    assert _delta_is_better("train/rmse", -0.1) is True   # path-qualified names


def test_cli_compare_does_not_mark_an_unchanged_metric(tmp_project):
    from exptrack.cli.inspect_cmds import cmd_compare
    from exptrack.core import Experiment

    a = Experiment(script="train.py"); a.log_metric("acc", 0.5); a.finish()
    b = Experiment(script="train.py"); b.log_metric("acc", 0.5); b.finish()

    out, _ = _capture(cmd_compare, SimpleNamespace(id1=a.id, id2=b.id))
    line = next(ln for ln in out.splitlines() if "acc" in ln)
    assert "<" not in line and "+" not in line.split("acc", 1)[1]


def test_ls_survives_a_null_metric_value(tmp_project):
    """cmd_ls formatted None with `:.4g` and took the whole command down."""
    from exptrack.cli.inspect_cmds import cmd_ls
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py"); exp.finish()
    conn = get_db()
    conn.execute("INSERT INTO metrics (exp_id, key, value, step) VALUES (?,?,?,?)",
                 (exp.id, "loss", None, 0))
    conn.commit()

    out, _ = _capture(cmd_ls, SimpleNamespace(n=10, tag=None, status=None,
                                              study=None, json_output=False))
    assert exp.id[:6] in out


def test_a_min_goal_run_with_a_null_row_still_has_a_best(tmp_project):
    """NULL sorts first under `value ASC`, so a min-goal run with real values
    reported best=None and dropped out of every best-basis ranking."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.primary_metric import primary_metric_batch

    exp = Experiment(script="train.py")
    exp.log_metric("loss", 0.5, step=1)
    exp.log_metric("loss", 0.3, step=2)
    exp.finish()

    conn = get_db()
    conn.execute("INSERT INTO metrics (exp_id, key, value, step) VALUES (?,?,?,?)",
                 (exp.id, "loss", None, 3))
    conn.commit()

    # `metrics` is what list_experiments already carries; the heuristic needs
    # something to pick from when no level is configured.
    runs = [{"id": exp.id, "metrics": {"loss": {"value": 0.3}}}]
    res = primary_metric_batch(conn, runs)[exp.id]
    assert res["goal"] == "min"
    assert res["best"] == 0.3


def test_an_ambiguous_prefix_is_reported_not_raised(tmp_project):
    """AmbiguousPrefixError escaping _resolve_ids 500'd all six param-study
    endpoints, contradicting their own "unknown ids are reported" contract."""
    from exptrack.core import get_db
    from exptrack.dashboard.routes.write_routes.param_study import _resolve_ids

    conn = get_db()
    # Two runs whose ids share a prefix, forced so the ambiguity is certain.
    for eid, name in (("dupdup1111", "a"), ("dupdup2222", "b")):
        conn.execute(
            "INSERT INTO experiments (id, name, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (eid, name, "done", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
    conn.commit()

    ids, unknown = _resolve_ids(conn, {"ids": ["dupdup"]})
    assert ids == []
    assert unknown == ["dupdup"]


def test_pareto_accepts_the_basis_field_it_documents(tmp_project):
    """api_pareto's docstring said `basis`; the code read only `rank_by`."""
    from exptrack.dashboard.routes.write_routes.param_study import _selection

    assert _selection({"basis": "best"})["rank_by"] == "best"
    assert _selection({"rank_by": "best"})["rank_by"] == "best"
    # An explicit rank_by still wins over basis, and the default is unchanged.
    assert _selection({})["rank_by"] == "final"
