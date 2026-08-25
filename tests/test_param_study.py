"""Tests for exptrack/core/param_study.py — reading runs as a parameter search.

The properties worth guarding: a parameter missing from some runs counts as a
variation, values are compared after normalization (so one setting captured two
ways is one value), and internal bookkeeping params never surface.
"""
from __future__ import annotations

import pytest


def _run(params, script="train.py"):
    """Create a finished run carrying *params*, return its id."""
    from exptrack.core import Experiment

    exp = Experiment(script=script, params=params)
    exp.finish()
    return exp.id


def _by_key(analysis, section="varying"):
    return {p["key"]: p for p in analysis[section]}


# ---------------------------------------------------------------------------
# Varying vs constant
# ---------------------------------------------------------------------------

def test_splits_varying_from_constant(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    a = _run({"lr": 0.1, "batch_size": 32})
    b = _run({"lr": 0.2, "batch_size": 32})
    out = analyze_params(get_db(), [a, b])

    assert [p["key"] for p in out["varying"]] == ["lr"]
    assert [p["key"] for p in out["constant"]] == ["batch_size"]
    assert out["n_runs"] == 2


def test_values_carry_counts(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    ids = [_run({"lr": 0.1}), _run({"lr": 0.1}), _run({"lr": 0.5})]
    lr = _by_key(analyze_params(get_db(), ids))["lr"]

    assert lr["n_values"] == 2
    assert [(v["value"], v["count"]) for v in lr["values"]] == [(0.1, 2), (0.5, 1)]


def test_counts_always_sum_to_the_run_count(tmp_project):
    """Every run contributes exactly one entry, so a value's share of the set
    is readable straight off `count`."""
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    ids = [_run({"lr": 0.1}), _run({"lr": 0.2}), _run({"other": 1})]
    out = analyze_params(get_db(), ids)
    for p in out["varying"] + out["constant"]:
        assert sum(v["count"] for v in p["values"]) == len(ids), p["key"]


def test_varying_is_ordered_most_varied_first(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    ids = [_run({"lr": 0.1, "seed": 1}), _run({"lr": 0.2, "seed": 1}),
           _run({"lr": 0.3, "seed": 2})]
    out = analyze_params(get_db(), ids)
    assert [p["key"] for p in out["varying"]] == ["lr", "seed"]


def test_single_run_has_no_varying_params(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    # The run must exist before get_db(): finish() closes the shared connection,
    # and arguments evaluate left to right.
    exp_id = _run({"lr": 0.1, "seed": 3})
    out = analyze_params(get_db(), [exp_id])
    assert out["varying"] == []
    assert {p["key"] for p in out["constant"]} == {"lr", "seed"}


# ---------------------------------------------------------------------------
# Missing is a variation, and is distinct from None
# ---------------------------------------------------------------------------

def test_param_on_some_runs_only_counts_as_varying(tmp_project):
    """Adding a flag partway through a sweep is a real change to what was
    tested — it must not read as a blank cell in a constant column."""
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    ids = [_run({"lr": 0.1}), _run({"lr": 0.1, "dropout": 0.5})]
    out = analyze_params(get_db(), ids)
    keys = _by_key(out)

    assert "dropout" in keys
    assert keys["dropout"]["varies"] is True
    assert keys["dropout"]["n_missing"] == 1
    missing = [v for v in keys["dropout"]["values"] if v["missing"]]
    assert len(missing) == 1 and missing[0]["count"] == 1


def test_missing_is_not_conflated_with_a_logged_null(tmp_project):
    """`None` is a value a run can genuinely log; collapsing it with "never
    had this param" would report a value the user never tried."""
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    ids = [_run({"lr": 0.1}), _run({"lr": 0.1, "sched": None})]
    sched = _by_key(analyze_params(get_db(), ids))["sched"]

    assert sched["n_values"] == 2, "missing and null must be distinct values"
    assert sched["n_missing"] == 1
    assert sum(1 for v in sched["values"] if not v["missing"]) == 1


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_number_and_its_string_spelling_are_one_value(tmp_project):
    """argparse capture stores a float, the pipeline CLI stores a string —
    the same setting must not read as two values tried."""
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    ids = [_run({"lr": 0.01}), _run({"lr": "0.01"})]
    out = analyze_params(get_db(), ids)
    assert out["varying"] == []
    assert _by_key(out, "constant")["lr"]["n_values"] == 1


def test_bool_and_its_string_spelling_are_one_value(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    ids = [_run({"amp": True}), _run({"amp": "true"})]
    out = analyze_params(get_db(), ids)
    assert out["varying"] == []


def test_bool_is_not_the_number_one(tmp_project):
    """`epochs=1` and `epochs=True` are not the same intent."""
    from exptrack.core.param_study import _norm

    assert _norm(True) != _norm(1)
    assert _norm(False) != _norm(0)


def test_lists_compare_by_normalized_members_in_order(tmp_project):
    from exptrack.core.param_study import _norm

    assert _norm([1, 2]) == _norm(["1", "2"])
    assert _norm([1, 2]) != _norm([2, 1]), "a list param is ordered data"


def test_kind_classification(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import (
        KIND_BOOL,
        KIND_CATEGORICAL,
        KIND_MIXED,
        KIND_NUMERIC,
        analyze_params,
    )

    ids = [_run({"lr": 0.1, "amp": True, "opt": "adam", "mix": 1}),
           _run({"lr": 0.2, "amp": False, "opt": "sgd", "mix": "auto"})]
    keys = _by_key(analyze_params(get_db(), ids))

    assert keys["lr"]["kind"] == KIND_NUMERIC
    assert keys["amp"]["kind"] == KIND_BOOL
    assert keys["opt"]["kind"] == KIND_CATEGORICAL
    assert keys["mix"]["kind"] == KIND_MIXED


def test_non_finite_values_never_compare_equal_to_a_number(tmp_project):
    from exptrack.core.param_study import _norm

    assert _norm(float("inf")) != _norm(1e308)
    assert _norm("nan") != _norm(0.0)


# ---------------------------------------------------------------------------
# Internal params stay out
# ---------------------------------------------------------------------------

def test_internal_params_never_surface(tmp_project):
    """The rule is the `_` prefix, not a list of known keys — every internal
    param is prefixed and an enumeration silently misses each new one."""
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    a = _run({"lr": 0.1})
    b = _run({"lr": 0.2})
    out = analyze_params(get_db(), [a, b])
    all_keys = [p["key"] for p in out["varying"] + out["constant"]]

    assert all_keys == ["lr"]
    assert not any(k.startswith("_") for k in all_keys)


def test_is_user_param_key_matches_the_js_rule():
    from exptrack.core.param_study import is_user_param_key

    assert is_user_param_key("lr")
    assert not is_user_param_key("_code_snapshot")
    assert not is_user_param_key("_variant_of")


def test_failure_message_is_not_a_swept_parameter(tmp_project):
    """`Experiment.fail()` writes the message as the un-prefixed `error` param
    (backward compat), so the prefix rule alone lets it through — and then every
    failed run adds an `error` column whose message makes each failed config
    look like a distinct configuration."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.param_study import analyze_params

    ok = _run({"lr": 0.1})
    bad = Experiment(script="train.py", params={"lr": 0.2})
    bad.fail("CUDA out of memory")
    out = analyze_params(get_db(), [ok, bad.id])

    keys = [p["key"] for p in out["varying"] + out["constant"]]
    assert "error" not in keys
    assert keys == ["lr"]


def test_two_runs_that_failed_differently_are_still_duplicate_configs(tmp_project):
    """The failure message must not split one configuration into two."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.param_study import classify_duplicates

    a = Experiment(script="train.py", params={"lr": 0.1})
    a.fail("CUDA out of memory")
    b = Experiment(script="train.py", params={"lr": 0.1})
    b.fail("connection reset")
    assert len(classify_duplicates(get_db(), [a.id, b.id])) == 1


# ---------------------------------------------------------------------------
# Filtered-set semantics
# ---------------------------------------------------------------------------

def test_what_varies_depends_on_the_set_posted(tmp_project):
    """The whole reason this takes ids rather than a study name: narrow the
    set and a parameter stops varying."""
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params

    a = _run({"lr": 0.1, "seed": 1})
    b = _run({"lr": 0.1, "seed": 2})
    c = _run({"lr": 0.9, "seed": 2})
    conn = get_db()

    wide = analyze_params(conn, [a, b, c])
    assert {p["key"] for p in wide["varying"]} == {"lr", "seed"}

    narrow = analyze_params(conn, [b, c])
    assert [p["key"] for p in narrow["varying"]] == ["lr"]
    assert [p["key"] for p in narrow["constant"]] == ["seed"]


# ---------------------------------------------------------------------------
# Duplicate configurations (the fingerprint primitive)
# ---------------------------------------------------------------------------

def test_identical_configs_are_grouped(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import classify_duplicates

    a = _run({"lr": 0.1, "bs": 32})
    b = _run({"lr": 0.1, "bs": 32})
    c = _run({"lr": 0.2, "bs": 32})
    dupes = classify_duplicates(get_db(), [a, b, c])

    assert len(dupes) == 1
    assert set(dupes[0]["exp_ids"]) == {a, b}
    assert dupes[0]["n"] == 2


def test_duplicate_detection_normalizes_capture_differences(tmp_project):
    """Two runs of the same config captured different ways are duplicates."""
    from exptrack.core import get_db
    from exptrack.core.param_study import classify_duplicates

    a = _run({"lr": 0.01, "amp": True})
    b = _run({"lr": "0.01", "amp": "true"})
    assert len(classify_duplicates(get_db(), [a, b])) == 1


def test_a_missing_param_makes_configs_distinct(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import classify_duplicates

    a = _run({"lr": 0.1})
    b = _run({"lr": 0.1, "dropout": 0.5})
    assert classify_duplicates(get_db(), [a, b]) == []


def test_internal_params_do_not_prevent_a_duplicate_match(tmp_project):
    """`_code_snapshot` names a per-file hash and always differs, so counting
    internals would mean no two runs are ever duplicates."""
    from exptrack.core import get_db
    from exptrack.core.param_study import config_fingerprint, load_params

    a = _run({"lr": 0.1})
    b = _run({"lr": 0.1})
    params = load_params(get_db(), [a, b], include_internal=True)
    assert config_fingerprint(params[a]) == config_fingerprint(params[b])


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

def test_route_returns_the_analysis(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    a = _run({"lr": 0.1})
    b = _run({"lr": 0.2})
    out = write_routes.api_param_study(get_db(), {"ids": [a, b]})

    assert [p["key"] for p in out["varying"]] == ["lr"]
    assert out["unknown_ids"] == []


def test_route_accepts_id_prefixes(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    a = _run({"lr": 0.1})
    b = _run({"lr": 0.2})
    out = write_routes.api_param_study(get_db(), {"ids": [a[:6], b[:6]]})
    assert [p["key"] for p in out["varying"]] == ["lr"]


def test_route_reports_unknown_ids_rather_than_dropping_them(tmp_project):
    """An analysis quietly computed over fewer runs than were selected would
    misreport what varies."""
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    a = _run({"lr": 0.1})
    out = write_routes.api_param_study(get_db(), {"ids": [a, "nope123"]})
    assert out["unknown_ids"] == ["nope123"]
    assert out["n_runs"] == 1


def test_route_errors_on_an_empty_or_unknown_set(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    conn = get_db()
    assert "error" in write_routes.api_param_study(conn, {"ids": []})
    assert "error" in write_routes.api_param_study(conn, {"ids": ["nope"]})
    assert "error" in write_routes.api_param_study(conn, {})


def test_route_dedupes_repeated_ids(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    a = _run({"lr": 0.1})
    out = write_routes.api_param_study(get_db(), {"ids": [a, a, a[:6]]})
    assert out["n_runs"] == 1


def test_route_returns_duplicates_when_asked(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    a = _run({"lr": 0.1})
    b = _run({"lr": 0.1})
    conn = get_db()

    assert "duplicates" not in write_routes.api_param_study(conn, {"ids": [a, b]})
    out = write_routes.api_param_study(conn, {"ids": [a, b], "duplicates": True})
    assert len(out["duplicates"]) == 1


@pytest.mark.parametrize("bad", ["notalist", 42, None, {"a": 1}])
def test_route_tolerates_a_malformed_ids_field(tmp_project, bad):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    out = write_routes.api_param_study(get_db(), {"ids": bad})
    assert "error" in out


# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------

def _scored(params, metrics, status="done", script="train.py"):
    """A finished run with params and a metric series."""
    from exptrack.core import Experiment

    exp = Experiment(script=script, params=params)
    for key, points in metrics.items():
        for step, value in points:
            exp.log_metric(key, value, step=step)
    if status == "failed":
        exp.fail("boom")
    else:
        exp.finish()
    return exp.id


def test_matrix_columns_are_the_varying_params_only(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import build_matrix

    a = _scored({"lr": 0.1, "bs": 32}, {"acc": [(1, 0.7)]})
    b = _scored({"lr": 0.2, "bs": 32}, {"acc": [(1, 0.9)]})
    m = build_matrix(get_db(), [a, b])

    assert [c["key"] for c in m["varying"]] == ["lr"]
    assert [c["key"] for c in m["constant"]] == ["bs"]
    for row in m["rows"]:
        assert set(row["params"]) <= {"lr"}, "rows carry only varying columns"


def test_matrix_marks_the_best_row(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import build_matrix

    a = _scored({"lr": 0.1}, {"acc": [(1, 0.70)]})
    b = _scored({"lr": 0.2}, {"acc": [(1, 0.93)]})
    conn = get_db()
    pm.set_project_primary_metric("acc")
    assert build_matrix(conn, [a, b])["best_row_id"] == b


def test_matrix_best_respects_a_minimized_metric(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import build_matrix

    a = _scored({"lr": 0.1}, {"val_loss": [(1, 0.9)]})
    b = _scored({"lr": 0.2}, {"val_loss": [(1, 0.2)]})
    conn = get_db()
    pm.set_project_primary_metric("val_loss")
    m = build_matrix(conn, [a, b])
    assert m["goal"] == "min"
    assert m["best_row_id"] == b


def test_matrix_rank_by_best_differs_from_final(tmp_project):
    """A run that peaked then regressed ranks differently on the two bases,
    which is why both are on every row."""
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import build_matrix

    peaked = _scored({"lr": 0.1}, {"acc": [(1, 0.99), (2, 0.50)]})
    steady = _scored({"lr": 0.2}, {"acc": [(1, 0.60), (2, 0.60)]})
    conn = get_db()
    pm.set_project_primary_metric("acc")

    assert build_matrix(conn, [peaked, steady], rank_by="final")["best_row_id"] == steady
    assert build_matrix(conn, [peaked, steady], rank_by="best")["best_row_id"] == peaked


def test_running_runs_are_hidden_by_default_and_counted(tmp_project):
    """Their metrics are still moving, so a rank against them doesn't
    reproduce — but the exclusion is stated, never silent."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.param_study import build_matrix

    done = _scored({"lr": 0.1}, {"acc": [(1, 0.7)]})
    live = Experiment(script="train.py", params={"lr": 0.2})
    conn = get_db()

    m = build_matrix(conn, [done, live.id])
    assert [r["id"] for r in m["rows"]] == [done]
    assert m["excluded"]["running"] == 1

    m2 = build_matrix(conn, [done, live.id], include_running=True)
    assert len(m2["rows"]) == 2


def test_failed_runs_are_shown_by_default(tmp_project):
    """A config that failed is a result of the search; hiding it invites
    re-running the thing that already broke."""
    from exptrack.core import get_db
    from exptrack.core.param_study import build_matrix

    ok = _scored({"lr": 0.1}, {"acc": [(1, 0.7)]})
    bad = _scored({"lr": 999}, {}, status="failed")
    conn = get_db()

    m = build_matrix(conn, [ok, bad])
    assert {r["id"] for r in m["rows"]} == {ok, bad}
    assert "failed" not in m["excluded"]

    m2 = build_matrix(conn, [ok, bad], include_failed=False)
    assert [r["id"] for r in m2["rows"]] == [ok]
    assert m2["excluded"]["failed"] == 1


def test_a_run_without_the_metric_is_kept_but_never_best(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import build_matrix

    scored = _scored({"lr": 0.1}, {"acc": [(1, 0.7)]})
    silent = _scored({"lr": 0.2}, {})
    conn = get_db()
    pm.set_project_primary_metric("acc")

    m = build_matrix(conn, [scored, silent])
    assert {r["id"] for r in m["rows"]} == {scored, silent}
    assert m["best_row_id"] == scored
    row = next(r for r in m["rows"] if r["id"] == silent)
    assert row["primary"]["missing"] is True


def test_matrix_rows_state_which_params_are_missing(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import build_matrix

    a = _scored({"lr": 0.1}, {"acc": [(1, 0.7)]})
    b = _scored({"lr": 0.1, "dropout": 0.5}, {"acc": [(1, 0.8)]})
    m = build_matrix(get_db(), [a, b])

    row_a = next(r for r in m["rows"] if r["id"] == a)
    assert "dropout" in row_a["missing"]
    assert "dropout" not in row_a["params"]


def test_matrix_flags_duplicate_configs_on_the_row(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import build_matrix

    a = _scored({"lr": 0.1}, {"acc": [(1, 0.7)]})
    b = _scored({"lr": 0.1}, {"acc": [(1, 0.8)]})
    m = build_matrix(get_db(), [a, b])

    groups = {r["id"]: r["dup_group"] for r in m["rows"]}
    assert groups[a] is not None and groups[a] == groups[b]
    assert len(m["duplicates"]) == 1


def test_trashed_runs_are_excluded_and_counted(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.db import trash_experiment
    from exptrack.core.param_study import build_matrix

    a = _scored({"lr": 0.1}, {"acc": [(1, 0.7)]})
    b = _scored({"lr": 0.2}, {"acc": [(1, 0.8)]})
    conn = get_db()
    trash_experiment(conn, b)
    conn.commit()

    m = build_matrix(conn, [a, b])
    assert [r["id"] for r in m["rows"]] == [a]
    assert m["excluded"]["trashed_or_missing"] == 1
    assert m["n_selected"] == 2


def test_matrix_route_defaults(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    ok = _scored({"lr": 0.1}, {"acc": [(1, 0.7)]})
    bad = _scored({"lr": 0.2}, {}, status="failed")
    out = write_routes.api_param_matrix(get_db(), {"ids": [ok, bad]})

    assert out["rank_by"] == "final"
    assert len(out["rows"]) == 2, "failed shown by default"
    assert out["unknown_ids"] == []


def test_matrix_route_rejects_an_unknown_rank_basis(tmp_project):
    """An unrecognised rank_by must not silently rank on something else."""
    from exptrack.core import get_db
    from exptrack.dashboard.routes import write_routes

    exp_id = _scored({"lr": 0.1}, {"acc": [(1, 0.7)]})
    out = write_routes.api_param_matrix(
        get_db(), {"ids": [exp_id], "rank_by": "wobble"})
    assert out["rank_by"] == "final"


def test_matrix_of_an_empty_set(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import build_matrix

    m = build_matrix(get_db(), [])
    assert m["rows"] == [] and m["best_row_id"] is None


# ---------------------------------------------------------------------------
# Three-dimensional duplicate classification
# ---------------------------------------------------------------------------

def _run_with_code(params, source, tmp_path, metrics=None):
    """A run whose script has known content, so its code fingerprint is real."""
    from exptrack.core import Experiment

    script = tmp_path / "train.py"
    script.write_text(source)
    exp = Experiment(script=str(script), params=params)
    for key, value in (metrics or {}).items():
        exp.log_metric(key, value, step=1)
    exp.finish()
    return exp.id


def test_identical_runs_are_classified_identical(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import classify_duplicates

    a = _run_with_code({"lr": 0.1}, "print('v1')\n", tmp_project)
    b = _run_with_code({"lr": 0.1}, "print('v1')\n", tmp_project)
    groups = classify_duplicates(get_db(), [a, b])

    assert len(groups) == 1
    assert groups[0]["code"] == "same"
    assert groups[0]["kind"] == "identical"


def test_same_params_different_code_is_not_a_plain_duplicate(tmp_project):
    """The change-one-line loop working correctly — reporting it as waste
    would be actively wrong."""
    from exptrack.core import get_db
    from exptrack.core.param_study import classify_duplicates

    a = _run_with_code({"lr": 0.1}, "print('v1')\n", tmp_project)
    b = _run_with_code({"lr": 0.1}, "print('v2 — fixed the bug')\n", tmp_project)
    groups = classify_duplicates(get_db(), [a, b])

    assert groups[0]["code"] == "differs"
    assert groups[0]["kind"] == "code_differs"


def test_unknown_code_never_reads_as_matching_code(tmp_project):
    """A run that captured no source is not a run whose source matched."""
    from exptrack.core import get_db
    from exptrack.core.param_study import classify_duplicates

    a = _run_with_code({"lr": 0.1}, "print('v1')\n", tmp_project)
    # Same script path as `a` so the *code* dimension is what is under test (a
    # different script name would correctly be reported as script_differs
    # before the code ladder is consulted), but with the file gone so `b`
    # captures no source at all.
    (tmp_project / "train.py").unlink()
    b = _run({"lr": 0.1}, script=str(tmp_project / "train.py"))
    groups = classify_duplicates(get_db(), [a, b])

    assert groups[0]["code"] == "unknown"
    assert groups[0]["kind"] == "params_only"


def test_two_models_sharing_params_are_not_called_a_rerun(tmp_project):
    """model_a.py --lr 0.01 and model_b.py --lr 0.01 are two models, not a
    repeat: the duplicate verdict must say the script differs before it says
    anything about code or data."""
    from exptrack.core import get_db
    from exptrack.core.param_study import classify_duplicates

    a = _run({"lr": 0.1}, script="model_a.py")
    b = _run({"lr": 0.1}, script="model_b.py")
    groups = classify_duplicates(get_db(), [a, b])

    assert groups[0]["script"] == "differs"
    assert groups[0]["kind"] == "script_differs"


def test_a_scriptless_run_is_not_a_duplicate_of_every_script(tmp_project):
    """find_equivalent_runs dropped its script filter when the run had no
    script, so a script-less run matched every script in the project."""
    from exptrack.core import get_db
    from exptrack.core.param_study import find_equivalent_runs

    _run({"lr": 0.1}, script="model_a.py")
    scriptless = _run({"lr": 0.1}, script="")
    hits = find_equivalent_runs(get_db(), scriptless, {"lr": 0.1}, script="")

    assert hits == []


def test_demonstrable_difference_beats_a_missing_third_member(tmp_project):
    """UNKNOWN outranks SAME but not DIFFERS: two members that provably
    differ differ, whatever a third failed to record."""
    from exptrack.core.param_study import _agreement

    assert _agreement(["x", "x", None]) == "unknown"
    assert _agreement(["x", "y", None]) == "differs"
    assert _agreement(["x", "x"]) == "same"
    assert _agreement([None, None]) == "absent", "nobody recorded it at all"


def test_absent_dataset_does_not_block_an_identical_verdict(tmp_project):
    """A run may genuinely read no data files, so "neither recorded a dataset"
    is a complete answer — but every run executes code, so "neither captured
    source" is missing evidence. The asymmetry is the point: without it, a
    project whose scripts take no data path would never see the one verdict
    the feature exists to deliver."""
    from exptrack.core.param_study import _duplicate_kind

    assert _duplicate_kind("same", "absent") == "identical"
    assert _duplicate_kind("absent", "absent") == "params_only"
    assert _duplicate_kind("same", "unknown") == "params_only"


def test_dataset_change_is_reported_when_code_matches(tmp_project):
    from exptrack.core.param_study import _duplicate_kind, dataset_fingerprint

    # The ladder itself, independent of capture: code known-same plus data
    # known-different is the finding that silently invalidates a comparison.
    assert _duplicate_kind("same", "differs") == "dataset_differs"
    assert _duplicate_kind("same", "same") == "identical"
    assert _duplicate_kind("differs", "same") == "code_differs"
    assert _duplicate_kind("unknown", "same") == "params_only"
    assert dataset_fingerprint({}) is None


def test_dataset_fingerprint_reads_the_manifest(tmp_project):
    from exptrack.core.param_study import DATASET_PARAM, dataset_fingerprint

    a = dataset_fingerprint({DATASET_PARAM: {"data": {"hash": "abc", "size": 10}}})
    b = dataset_fingerprint({DATASET_PARAM: {"data": {"hash": "abc", "size": 10}}})
    c = dataset_fingerprint({DATASET_PARAM: {"data": {"hash": "zzz", "size": 10}}})
    assert a == b and a != c


def test_subgroups_split_a_mixed_group(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import classify_duplicates

    a = _run_with_code({"lr": 0.1}, "print('v1')\n", tmp_project)
    b = _run_with_code({"lr": 0.1}, "print('v1')\n", tmp_project)
    c = _run_with_code({"lr": 0.1}, "print('v2')\n", tmp_project)
    groups = classify_duplicates(get_db(), [a, b, c])

    assert groups[0]["n"] == 3
    assert groups[0]["kind"] == "code_differs"
    sizes = sorted(len(s["exp_ids"]) for s in groups[0]["subgroups"])
    assert sizes == [1, 2], "the two sharing code group together"


def test_matrix_row_carries_the_duplicate_kind(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import build_matrix

    a = _run_with_code({"lr": 0.1}, "print('v1')\n", tmp_project)
    b = _run_with_code({"lr": 0.1}, "print('v1')\n", tmp_project)
    m = build_matrix(get_db(), [a, b])

    kinds = {r["id"]: r["dup_kind"] for r in m["rows"]}
    assert kinds[a] == kinds[b] == "identical"


# ---------------------------------------------------------------------------
# The post-capture notice
# ---------------------------------------------------------------------------

def test_finish_warns_when_the_config_was_already_run(tmp_project, capsys):
    from exptrack.core import Experiment

    Experiment(script="train.py", params={"lr": 0.1}).finish()
    capsys.readouterr()
    Experiment(script="train.py", params={"lr": 0.1}).finish()
    err = capsys.readouterr().err
    assert "already run" in err


def test_finish_is_silent_for_a_new_config(tmp_project, capsys):
    from exptrack.core import Experiment

    Experiment(script="train.py", params={"lr": 0.1}).finish()
    capsys.readouterr()
    Experiment(script="train.py", params={"lr": 0.9}).finish()
    assert "already run" not in capsys.readouterr().err


def test_the_notice_can_be_switched_off(tmp_project, capsys):
    from exptrack import config
    from exptrack.core import Experiment

    Experiment(script="train.py", params={"lr": 0.1}).finish()
    conf = config.load()
    conf["warn_duplicate_runs"] = False
    config.save(conf)
    config.reload()
    capsys.readouterr()
    Experiment(script="train.py", params={"lr": 0.1}).finish()
    assert "already run" not in capsys.readouterr().err


def test_a_different_script_with_the_same_params_is_not_a_repeat(tmp_project, capsys):
    from exptrack.core import Experiment

    Experiment(script="train.py", params={"lr": 0.1}).finish()
    capsys.readouterr()
    Experiment(script="eval.py", params={"lr": 0.1}).finish()
    assert "already run" not in capsys.readouterr().err


def test_the_notice_never_breaks_a_finish(tmp_project, monkeypatch, capsys):
    """It sits on the finish path of every run; an advisory must not be able
    to take one down."""
    from exptrack.core import Experiment, param_study

    Experiment(script="train.py", params={"lr": 0.1}).finish()

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(param_study, "find_equivalent_runs", boom)
    exp = Experiment(script="train.py", params={"lr": 0.1})
    exp.finish()
    assert exp.status == "done"


def test_a_failed_run_is_not_checked(tmp_project, capsys):
    """The check runs only on a clean finish — a crash is not a repeat worth
    reporting, and fail() has its own path."""
    from exptrack.core import Experiment

    Experiment(script="train.py", params={"lr": 0.1}).finish()
    capsys.readouterr()
    exp = Experiment(script="train.py", params={"lr": 0.1})
    exp.fail("boom")
    assert "already run" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Parameter effects (descriptive summaries)
# ---------------------------------------------------------------------------

def test_effects_summarize_each_value(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1}, {"acc": [(1, 0.60)]}),
           _scored({"lr": 0.1}, {"acc": [(1, 0.80)]}),
           _scored({"lr": 0.9}, {"acc": [(1, 0.30)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = parameter_effects(conn, ids)

    lr = next(p for p in out["params"] if p["key"] == "lr")
    by_value = {str(v["value"]): v for v in lr["values"]}
    assert by_value["0.1"]["count"] == 2
    assert by_value["0.1"]["best"] == 0.80
    assert by_value["0.1"]["median"] == 0.70
    assert by_value["0.9"]["best"] == 0.30
    assert out["metric"]["key"] == "acc"
    assert out["n_scored"] == 3


def test_effects_best_follows_the_goal(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1}, {"val_loss": [(1, 0.9)]}),
           _scored({"lr": 0.1}, {"val_loss": [(1, 0.2)]}),
           _scored({"lr": 0.9}, {"val_loss": [(1, 0.5)]})]
    conn = get_db()
    pm.set_project_primary_metric("val_loss")
    out = parameter_effects(conn, ids)

    lr = next(p for p in out["params"] if p["key"] == "lr")
    best = next(v for v in lr["values"] if str(v["value"]) == "0.1")["best"]
    assert best == 0.2, "for a minimized metric, best is the lowest"


def test_perfectly_confounded_params_are_named_not_charted(tmp_project):
    """If two params moved together on every run, the data cannot separate
    them — labelling one's chart "lr vs acc" would read as an answer."""
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1, "warmup": 10}, {"acc": [(1, 0.6)]}),
           _scored({"lr": 0.9, "warmup": 99}, {"acc": [(1, 0.9)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = parameter_effects(conn, ids)

    lr = next(p for p in out["params"] if p["key"] == "lr")
    warmup = next(p for p in out["params"] if p["key"] == "warmup")
    assert lr["aliased_with"] == ["warmup"]
    assert warmup["aliased_with"] == ["lr"]


def test_independently_varied_params_are_not_flagged(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1, "bs": 32}, {"acc": [(1, 0.6)]}),
           _scored({"lr": 0.1, "bs": 64}, {"acc": [(1, 0.7)]}),
           _scored({"lr": 0.9, "bs": 32}, {"acc": [(1, 0.8)]}),
           _scored({"lr": 0.9, "bs": 64}, {"acc": [(1, 0.9)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = parameter_effects(conn, ids)

    for p in out["params"]:
        assert p["aliased_with"] == [], p["key"]


def test_one_run_per_value_is_flagged(tmp_project):
    """"Best" and "median" of a single run are that run; presenting them as a
    summary implies a distribution that was never measured."""
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1, "bs": 1}, {"acc": [(1, 0.6)]}),
           _scored({"lr": 0.9, "bs": 2}, {"acc": [(1, 0.9)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = parameter_effects(conn, ids)
    assert all(p["single_run_per_value"] for p in out["params"])


def test_repeated_values_are_not_flagged_as_single_run(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1}, {"acc": [(1, 0.6)]}),
           _scored({"lr": 0.1}, {"acc": [(1, 0.7)]}),
           _scored({"lr": 0.9}, {"acc": [(1, 0.9)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = parameter_effects(conn, ids)
    lr = next(p for p in out["params"] if p["key"] == "lr")
    assert lr["single_run_per_value"] is False


def test_unscored_runs_are_counted_but_not_summarized(tmp_project):
    """A run with no value for the metric is still a run that tried the value."""
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1}, {"acc": [(1, 0.6)]}),
           _scored({"lr": 0.1}, {}),
           _scored({"lr": 0.9}, {"acc": [(1, 0.9)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = parameter_effects(conn, ids)

    lr = next(p for p in out["params"] if p["key"] == "lr")
    v = next(v for v in lr["values"] if str(v["value"]) == "0.1")
    assert v["count"] == 2, "both runs tried this value"
    assert v["n_scored"] == 1, "only one produced a number"
    assert v["median"] == 0.6


def test_effects_points_carry_the_group_when_asked(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1, "opt": "adam"}, {"acc": [(1, 0.6)]}),
           _scored({"lr": 0.9, "opt": "sgd"}, {"acc": [(1, 0.9)]}),
           _scored({"lr": 0.1, "opt": "sgd"}, {"acc": [(1, 0.7)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = parameter_effects(conn, ids, group_by="opt")

    lr = next(p for p in out["params"] if p["key"] == "lr")
    assert {pt["group"] for pt in lr["points"]} == {"adam", "sgd"}
    assert out["group_by"] == "opt"
    # The picker is built from `groupable`, so the selected key has to be in it
    # or the control has no option to mark — choosing a key coloured the points
    # and then snapped the dropdown back to "—", which reads as the setting not
    # having taken. (The assertion here used to be `"opt" not in
    # out["groupable"]`, comparing a string against a list of dicts: always
    # true, so it never checked anything.)
    keys = [g["key"] for g in out["groupable"]]
    assert "opt" in keys, "the picker must be able to show its own value"
    assert "lr" in keys
    assert "_script" in keys, "script is always groupable"


def test_an_unknown_group_by_is_ignored_not_applied(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1}, {"acc": [(1, 0.6)]}),
           _scored({"lr": 0.9}, {"acc": [(1, 0.9)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = parameter_effects(conn, ids, group_by="nope")
    assert out["group_by"] == ""


def test_numeric_points_expose_a_numeric_x(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1, "opt": "adam"}, {"acc": [(1, 0.6)]}),
           _scored({"lr": 0.9, "opt": "sgd"}, {"acc": [(1, 0.9)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = parameter_effects(conn, ids)

    lr = next(p for p in out["params"] if p["key"] == "lr")
    opt = next(p for p in out["params"] if p["key"] == "opt")
    assert all(pt["numeric"] for pt in lr["points"])
    assert not any(pt["numeric"] for pt in opt["points"])


def test_effects_values_are_ordered_numerically(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 10}, {"acc": [(1, 0.6)]}),
           _scored({"lr": 2}, {"acc": [(1, 0.7)]}),
           _scored({"lr": 100}, {"acc": [(1, 0.8)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = parameter_effects(conn, ids)
    lr = next(p for p in out["params"] if p["key"] == "lr")
    assert [v["value"] for v in lr["values"]] == [2, 10, 100]


def test_effects_route(tmp_project):
    from exptrack.core import get_db
    from exptrack.core import primary_metric as pm
    from exptrack.dashboard.routes import write_routes

    ids = [_scored({"lr": 0.1}, {"acc": [(1, 0.6)]}),
           _scored({"lr": 0.9}, {"acc": [(1, 0.9)]})]
    conn = get_db()
    pm.set_project_primary_metric("acc")
    out = write_routes.api_param_effects(conn, {"ids": ids})

    assert out["metric"]["key"] == "acc"
    assert [p["key"] for p in out["params"]] == ["lr"]
    assert "error" in write_routes.api_param_effects(conn, {"ids": []})


def test_effects_with_no_primary_metric_says_so(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.param_study import parameter_effects

    ids = [_scored({"lr": 0.1}, {}), _scored({"lr": 0.9}, {})]
    out = parameter_effects(get_db(), ids)
    assert out["metric"]["key"] == ""
    assert out["n_scored"] == 0
