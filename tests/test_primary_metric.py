"""Tests for exptrack/core/primary_metric.py — which metric judges a run.

The two properties worth guarding are the ones the module exists for:
a configured metric is never silently swapped for another, and every answer
says which level it came from.
"""
from __future__ import annotations

import json
import re

import pytest


def _run(script="train.py", metrics=None, studies=None, name=None):
    """Create a finished run with the given metrics, return its id."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script=script, name=name)
    for key, points in (metrics or {}).items():
        for step, value in points:
            exp.log_metric(key, value, step=step)
    exp.finish()
    if studies:
        conn = get_db()
        conn.execute("UPDATE experiments SET studies=? WHERE id=?",
                     (json.dumps(studies), exp.id))
        conn.commit()
    return exp.id


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key,goal", [
    ("accuracy", "max"), ("val_acc", "max"), ("f1", "max"), ("auroc", "max"),
    ("loss", "min"), ("val_loss", "min"), ("train/loss", "min"),
    ("smooth_loss", "min"), ("val_rmse", "min"), ("grad_err", "min"),
    ("latency", "min"), ("perplexity", "min"),
])
def test_goal_inferred_from_name(key, goal):
    from exptrack.core.primary_metric import goal_for_key
    assert goal_for_key(key) == goal


def test_python_and_js_lower_is_better_lists_match():
    """The heuristic is mirrored client-side; a one-sided edit must fail here.

    Otherwise the same metric colours as an improvement on one end and a
    regression on the other — the exact failure the polarity work removed.
    """
    from pathlib import Path

    from exptrack.core import primary_metric as pm

    js = (Path(__file__).parent.parent / "exptrack" / "dashboard" / "static"
          / "js" / "core.js").read_text(encoding="utf-8")
    m = re.search(r"const LOWER_IS_BETTER_RE\s*=\s*\n?\s*/\^\((.*?)\)\$/",
                  js, re.S)
    assert m, "LOWER_IS_BETTER_RE not found in js/core.js"
    js_names = set(re.sub(r"\s+", "", m.group(1)).split("|"))
    py_names = set(pm._LOWER_IS_BETTER.pattern
                   .replace("^(", "").replace(")$", "")
                   .replace("\n", "").replace(" ", "").split("|"))
    assert py_names == js_names


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------

def test_heuristic_prefers_a_result_type(tmp_project):
    """With nothing configured, the guess favours a configured result_type."""
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"grad_norm": [(1, 0.5)], "accuracy": [(1, 0.9)]})
    out = pm.primary_metric_for_run(
        get_db(), exp_id, metric_keys=["grad_norm", "accuracy"])
    assert out["key"] == "accuracy"
    assert out["source"] == "heuristic"
    assert out["goal"] == "max"


def test_project_default_beats_heuristic(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"accuracy": [(1, 0.9)], "val_loss": [(1, 0.3)]})
    pm.set_project_primary_metric("val_loss")
    out = pm.primary_metric_for_run(
        get_db(), exp_id, metric_keys=["accuracy", "val_loss"])
    assert out["key"] == "val_loss"
    assert out["source"] == "project"
    assert out["goal"] == "min"


def test_study_beats_project(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"accuracy": [(1, 0.9)], "f1": [(1, 0.8)]},
                  studies=["sweep-a"])
    pm.set_project_primary_metric("accuracy")
    pm.set_study_primary_metric("sweep-a", "f1")
    out = pm.primary_metric_for_run(get_db(), exp_id, studies=["sweep-a"],
                                    metric_keys=["accuracy", "f1"])
    assert out["key"] == "f1"
    assert out["source"] == "study"


def test_run_beats_study_and_project(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"accuracy": [(1, 0.9)], "f1": [(1, 0.8)],
                           "auroc": [(1, 0.7)]}, studies=["sweep-a"])
    # After finish(): Experiment.finish() closes the shared connection, so a
    # handle taken before the run would be dead here.
    conn = get_db()
    pm.set_project_primary_metric("accuracy")
    pm.set_study_primary_metric("sweep-a", "f1")
    pm.set_run_primary_metric(conn, exp_id, "auroc")
    out = pm.primary_metric_for_run(conn, exp_id, studies=["sweep-a"],
                                    metric_keys=["accuracy", "f1", "auroc"])
    assert out["key"] == "auroc"
    assert out["source"] == "run"


def test_explicit_goal_overrides_the_name_heuristic(tmp_project):
    """A metric named `loss` that is genuinely maximized must be respected."""
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"loss": [(1, 0.5), (2, 0.9)]})
    pm.set_project_primary_metric("loss", "max")
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["loss"])
    assert out["goal"] == "max"
    assert out["best"] == 0.9


# ---------------------------------------------------------------------------
# No silent substitution
# ---------------------------------------------------------------------------

def test_configured_metric_absent_is_missing_not_substituted(tmp_project):
    """The whole point: a run that never logged the configured metric reports
    it as missing rather than borrowing whatever else it logged."""
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"accuracy": [(1, 0.9)]})
    pm.set_project_primary_metric("val_auroc")
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["accuracy"])
    assert out["key"] == "val_auroc"
    assert out["source"] == "project"
    assert out["missing"] is True
    assert out["final"] is None and out["best"] is None


def test_no_metrics_and_nothing_configured_names_nothing(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={})
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=[])
    assert out["key"] == ""
    assert out["source"] is None
    assert out["missing"] is False


def test_heuristic_key_is_never_missing(tmp_project):
    """A guessed key comes from the run's own metrics, so it always has a value."""
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"accuracy": [(1, 0.9)]})
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["accuracy"])
    assert out["missing"] is False
    assert out["final"] == 0.9


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

def test_final_is_the_last_point_best_is_the_extreme(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"accuracy": [(1, 0.5), (2, 0.95), (3, 0.80)]})
    pm.set_project_primary_metric("accuracy")
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["accuracy"])
    assert out["final"] == 0.80
    assert out["best"] == 0.95
    assert out["best_step"] == 2


def test_best_for_a_minimized_metric_is_the_lowest(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"val_loss": [(1, 0.9), (2, 0.2), (3, 0.4)]})
    pm.set_project_primary_metric("val_loss")
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["val_loss"])
    assert out["best"] == 0.2
    assert out["best_step"] == 2
    assert out["final"] == 0.4


def test_best_ties_resolve_to_the_earliest_step(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"accuracy": [(1, 0.7), (2, 0.9), (3, 0.9)]})
    pm.set_project_primary_metric("accuracy")
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["accuracy"])
    assert out["best_step"] == 2


def test_step_less_series_resolves_final_by_insert_order(tmp_project):
    """`log_metric(k, v)` with no step must still report the last value, not
    an arbitrary one from a set of rows all tied at NULL."""
    from exptrack.core import Experiment, get_db
    from exptrack.core import primary_metric as pm

    exp = Experiment(script="train.py")
    for v in (0.1, 0.5, 0.3):
        exp.log_metric("accuracy", v)
    exp.finish()
    pm.set_project_primary_metric("accuracy")
    out = pm.primary_metric_for_run(get_db(), exp.id, metric_keys=["accuracy"])
    assert out["final"] == 0.3
    assert out["best"] == 0.5


# ---------------------------------------------------------------------------
# Batch + payload integration
# ---------------------------------------------------------------------------

def test_batch_matches_single_and_handles_mixed_keys(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    a = _run(metrics={"accuracy": [(1, 0.9)]})
    b = _run(metrics={"val_loss": [(1, 0.2)]})
    conn = get_db()
    pm.set_run_primary_metric(conn, b, "val_loss")

    runs = [{"id": a, "studies": [], "metrics": {"accuracy": None}},
            {"id": b, "studies": [], "metrics": {"val_loss": None}}]
    batch = pm.primary_metric_batch(conn, runs)
    assert batch[a]["key"] == "accuracy" and batch[a]["final"] == 0.9
    assert batch[b]["key"] == "val_loss" and batch[b]["final"] == 0.2
    assert batch[b]["goal"] == "min"


def test_same_key_opposite_goals_both_resolve_correctly(tmp_project):
    """Two runs can resolve one key with different directions; grouping the
    value lookup by key alone would give one of them the wrong `best`."""
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    a = _run(metrics={"score": [(1, 0.2), (2, 0.8)]})
    b = _run(metrics={"score": [(1, 0.2), (2, 0.8)]})
    conn = get_db()
    pm.set_project_primary_metric("score", "max")
    pm.set_run_primary_metric(conn, b, "score", "min")

    runs = [{"id": a, "studies": [], "metrics": {"score": None}},
            {"id": b, "studies": [], "metrics": {"score": None}}]
    batch = pm.primary_metric_batch(conn, runs)
    assert batch[a]["best"] == 0.8, "max run should take the high point"
    assert batch[b]["best"] == 0.2, "min run should take the low point"


def test_list_experiments_carries_the_payload(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.queries import list_experiments

    _run(metrics={"accuracy": [(1, 0.9), (2, 0.85)]})
    pm.set_project_primary_metric("accuracy")
    rows = list_experiments(get_db(), limit=10)
    got = rows[0]["primary_metric"]
    assert got["key"] == "accuracy"
    assert got["final"] == 0.85 and got["best"] == 0.9
    assert got["source"] == "project"


def test_experiment_detail_carries_the_payload(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.queries import get_experiment_detail

    exp_id = _run(metrics={"val_loss": [(1, 0.9), (2, 0.4)]})
    pm.set_project_primary_metric("val_loss")
    detail = get_experiment_detail(get_db(), exp_id)
    assert detail["primary_metric"]["key"] == "val_loss"
    assert detail["primary_metric"]["best"] == 0.4


# ---------------------------------------------------------------------------
# Bad input degrades, never raises
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [0, -1, [], {}, "   ", None])
def test_unusable_config_value_falls_through_to_the_next_level(tmp_project, bad):
    """A hand-edited config must not be why a run has no primary metric."""
    from exptrack import config
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"accuracy": [(1, 0.9)]})
    conf = config.load()
    conf["primary_metric"] = bad
    config.save(conf)
    config.reload()
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["accuracy"])
    assert out["key"] == "accuracy"
    assert out["source"] == "heuristic"


def test_unusable_goal_falls_back_to_the_name_heuristic(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"val_loss": [(1, 0.9), (2, 0.2)]})
    pm.set_project_primary_metric("val_loss", "sideways")
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["val_loss"])
    assert out["goal"] == "min"
    assert out["best"] == 0.2


def test_bare_string_config_shorthand_works(tmp_project):
    from exptrack import config
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"f1": [(1, 0.7)]})
    conf = config.load()
    conf["primary_metric"] = "f1"
    config.save(conf)
    config.reload()
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["f1"])
    assert out["key"] == "f1" and out["source"] == "project"


def test_clearing_returns_to_the_heuristic(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"accuracy": [(1, 0.9)]})
    pm.set_project_primary_metric("val_loss")
    pm.set_project_primary_metric("")
    out = pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["accuracy"])
    assert out["source"] == "heuristic" and out["key"] == "accuracy"


# ---------------------------------------------------------------------------
# The dashboard's picker
# ---------------------------------------------------------------------------

def test_a_study_answer_names_its_study(tmp_project):
    """The picker's Clear removes the level that answered, so a study answer
    has to say which study."""
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm

    exp_id = _run(metrics={"f1": [(1, 0.8)]}, studies=["sweep-a"])
    pm.set_study_primary_metric("sweep-a", "f1")
    out = pm.primary_metric_for_run(get_db(), exp_id, studies=["sweep-a"],
                                    metric_keys=["f1"])
    assert out["source"] == "study" and out["study"] == "sweep-a"
    assert "study" not in pm.primary_metric_for_run(get_db(), exp_id, metric_keys=["f1"])


def test_the_route_sets_each_level_it_is_told_to(tmp_project):
    """Every ranking in the dashboard runs on this, and it used to be settable
    from the terminal only. The level is named, never inferred. Each call gets
    its own connection, as each request does: saving the config reloads it,
    which closes the handle a previous call held."""
    from exptrack import config
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.dashboard.routes.write_routes import api_set_primary_metric

    exp_id = _run(metrics={"val_acc": [(1, 0.9)], "loss": [(1, 0.2)]},
                  studies=["sweep-a"])
    assert api_set_primary_metric(get_db(), {"key": "val_acc", "goal": "max"})["ok"]
    assert config.load()["primary_metric"] == {"key": "val_acc", "goal": "max"}
    assert api_set_primary_metric(get_db(), {"key": "loss", "level": "study",
                                         "study": "sweep-a"})["ok"]
    assert config.load()["primary_metric_by_study"]["sweep-a"]["key"] == "loss"
    r = api_set_primary_metric(get_db(), {"key": "val_acc", "level": "run", "run": exp_id[:8]})
    assert r["ok"] and pm.run_primary_metric(get_db(), exp_id)["key"] == "val_acc"
    # clearing is an empty key at the named level
    assert api_set_primary_metric(get_db(), {"key": "", "level": "project"})["ok"]
    assert not config.load().get("primary_metric")


def test_the_route_refuses_what_it_cannot_place(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes.write_routes import api_set_primary_metric

    conn = get_db()
    _run(metrics={"acc": [(1, 0.9)]})
    assert "error" in api_set_primary_metric(conn, {"key": "acc", "goal": "up"})
    assert "error" in api_set_primary_metric(conn, {"key": "acc", "level": "study"})
    assert "error" in api_set_primary_metric(conn, {"key": "acc", "level": "galaxy"})
    # an empty run id would match every run and set the first one
    assert "error" in api_set_primary_metric(conn, {"key": "acc", "level": "run", "run": ""})


def test_the_matrix_states_where_its_metric_was_chosen():
    """The Matrix's "Judged by" used to guess this client-side from the first
    configured row, naming `run` for a mixed set and then having no run to
    clear. The broadest configured level is what decided the set."""
    from exptrack.core.param_study import consensus_source

    guess = {"a": {"key": "acc", "source": "heuristic"}}
    assert consensus_source(guess, "acc") == {"source": "heuristic", "study": ""}
    mixed = {"a": {"key": "acc", "source": "run"},
             "b": {"key": "acc", "source": "study", "study": "s1"},
             "c": {"key": "loss", "source": "project"}}
    assert consensus_source(mixed, "acc") == {"source": "study", "study": "s1"}
    mixed["d"] = {"key": "acc", "source": "project"}
    assert consensus_source(mixed, "acc")["source"] == "project"
