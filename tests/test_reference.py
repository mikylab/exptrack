"""Tests for exptrack/core/reference.py — the run everything is measured against.

The properties worth guarding are the ones that make a fixed baseline different
from the chronological one: it never falls through to an implicit substitute,
it always says where it was set, and a broken reference is reported rather than
looking like no reference at all.
"""
from __future__ import annotations


def _run(params=None, metrics=None, script="train.py"):
    from exptrack.core import Experiment

    exp = Experiment(script=script, params=params or {})
    for k, v in (metrics or {}).items():
        exp.log_metric(k, v)
    exp.finish()
    return exp.id


def _set_study(conn, study, exp_id):
    """Study membership without depending on an Experiment helper's name."""
    import json
    conn.execute("UPDATE experiments SET studies=? WHERE id=?",
                 (json.dumps([study]), exp_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def test_no_reference_resolves_to_nothing(tmp_project):
    """An unset reference is *no* reference — never a substituted one."""
    from exptrack.core import get_db
    from exptrack.core.reference import resolve

    _run({"lr": 0.1}, {"val_acc": 0.9})
    assert resolve(get_db()) is None


def test_project_reference_resolves_and_names_its_source(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.reference import resolve, set_reference

    exp_id = _run({"lr": 0.1}, {"val_acc": 0.9})
    conn = get_db()
    set_reference(conn, exp_id)
    ref = resolve(conn)

    assert ref["id"] == exp_id
    assert ref["source"] == "project"
    assert ref["stale"] is None


def test_study_reference_wins_over_the_project_one(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.reference import resolve, set_reference

    project_ref = _run({"lr": 0.1}, {"val_acc": 0.9})
    study_ref = _run({"lr": 0.2}, {"val_acc": 0.8})
    conn = get_db()
    set_reference(conn, project_ref)
    set_reference(conn, study_ref, study="sweep-a")

    assert resolve(conn)["id"] == project_ref
    got = resolve(conn, studies=["sweep-a"])
    assert got["id"] == study_ref
    assert got["source"] == "study" and got["study"] == "sweep-a"


def test_a_study_without_its_own_reference_falls_to_the_project(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.reference import resolve, set_reference

    project_ref = _run({"lr": 0.1}, {"val_acc": 0.9})
    conn = get_db()
    set_reference(conn, project_ref)

    got = resolve(conn, studies=["unrelated"])
    assert got["id"] == project_ref and got["source"] == "project"


def test_the_ladder_stops_at_the_project_level(tmp_project):
    """No implicit chain: it never continues on to "the best run so far"."""
    from exptrack.core import get_db
    from exptrack.core.reference import resolve

    _run({"lr": 0.1}, {"val_acc": 0.99})
    _run({"lr": 0.2}, {"val_acc": 0.5})
    assert resolve(get_db(), studies=["anything"]) is None


# ---------------------------------------------------------------------------
# Broken references are reported, not hidden
# ---------------------------------------------------------------------------

def test_a_deleted_reference_is_reported_as_missing(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.db import delete_experiment
    from exptrack.core.reference import STALE_MISSING, resolve, set_reference

    exp_id = _run({"lr": 0.1}, {"val_acc": 0.9})
    conn = get_db()
    set_reference(conn, exp_id)
    delete_experiment(conn, exp_id)

    ref = resolve(conn)
    assert ref is not None and ref["stale"] == STALE_MISSING
    # The id and the level still come back, so the message can name both.
    assert ref["id"] == exp_id and ref["source"] == "project"


def test_a_trashed_reference_is_distinguished_from_a_deleted_one(tmp_project):
    """Trashed is restorable; deleted is not. Different fixes, so different
    states rather than one 'unavailable'."""
    from exptrack.core import get_db
    from exptrack.core.db import trash_experiment
    from exptrack.core.reference import STALE_TRASHED, resolve, set_reference

    exp_id = _run({"lr": 0.1}, {"val_acc": 0.9})
    conn = get_db()
    set_reference(conn, exp_id)
    trash_experiment(conn, exp_id)

    assert resolve(conn)["stale"] == STALE_TRASHED


# ---------------------------------------------------------------------------
# Setting
# ---------------------------------------------------------------------------

def test_setting_an_unknown_run_is_refused(tmp_project):
    """A typo'd id would otherwise be stored and surface later as a stale
    reference — a worse way to learn about it."""
    from exptrack.core import get_db
    from exptrack.core.reference import resolve, set_reference

    assert "error" in set_reference(get_db(), "nope-not-a-run")
    assert resolve(get_db()) is None


def test_setting_a_trashed_run_is_refused(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.db import trash_experiment
    from exptrack.core.reference import set_reference

    exp_id = _run({"lr": 0.1}, {"val_acc": 0.9})
    conn = get_db()
    trash_experiment(conn, exp_id)
    assert "error" in set_reference(conn, exp_id)


def test_clearing_one_level_leaves_the_other(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.reference import resolve, set_reference

    project_ref = _run({"lr": 0.1}, {"val_acc": 0.9})
    study_ref = _run({"lr": 0.2}, {"val_acc": 0.8})
    conn = get_db()
    set_reference(conn, project_ref)
    set_reference(conn, study_ref, study="sweep-a")

    set_reference(conn, "", study="sweep-a")
    assert resolve(conn, studies=["sweep-a"])["id"] == project_ref
    assert resolve(conn)["id"] == project_ref


def test_all_configured_lists_every_level(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.reference import all_configured, set_reference

    project_ref = _run({"lr": 0.1}, {"val_acc": 0.9})
    study_ref = _run({"lr": 0.2}, {"val_acc": 0.8})
    conn = get_db()
    set_reference(conn, project_ref)
    set_reference(conn, study_ref, study="sweep-a")

    out = all_configured(conn)
    assert out["project"]["id"] == project_ref
    assert [(s["study"], s["id"]) for s in out["studies"]] == [("sweep-a", study_ref)]


# ---------------------------------------------------------------------------
# The delta, and its separation from lineage
# ---------------------------------------------------------------------------

def test_delta_is_against_the_reference_not_the_previous_run(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.reference import delta_vs_reference, set_reference

    first = _run({"lr": 0.1}, {"val_acc": 0.5})
    _run({"lr": 0.2}, {"val_acc": 0.6})           # the chronological previous
    latest = _run({"lr": 0.3}, {"val_acc": 0.7})
    conn = get_db()
    set_reference(conn, first)

    d = delta_vs_reference(conn, latest)
    assert d["reference"]["id"] == first
    assert [c["key"] for c in d["param_changes"]] == ["lr"]
    # Decoded, not the raw stored JSON — diff_runs reports values, not storage.
    assert d["param_changes"][0]["from"] == 0.1


def test_setting_a_reference_does_not_touch_the_chronological_baseline(tmp_project):
    """variant_of is lineage, the reference is a target. Pinning one must not
    silently rewrite every run's "what changed since last time"."""
    from exptrack.core import get_db
    from exptrack.core.queries import get_previous_run
    from exptrack.core.reference import set_reference

    first = _run({"lr": 0.1}, {"val_acc": 0.5})
    second = _run({"lr": 0.2}, {"val_acc": 0.6})
    third = _run({"lr": 0.3}, {"val_acc": 0.7})
    conn = get_db()

    before = get_previous_run(conn, third)["id"]
    set_reference(conn, first)
    assert get_previous_run(conn, third)["id"] == before == second


def test_the_reference_run_reports_itself_rather_than_a_self_diff(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.reference import delta_vs_reference, set_reference

    exp_id = _run({"lr": 0.1}, {"val_acc": 0.9})
    conn = get_db()
    set_reference(conn, exp_id)

    d = delta_vs_reference(conn, exp_id)
    assert d["is_reference"] is True
    assert "param_changes" not in d


def test_delta_reports_a_stale_reference_without_diffing(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.db import trash_experiment
    from exptrack.core.reference import delta_vs_reference, set_reference

    ref_id = _run({"lr": 0.1}, {"val_acc": 0.9})
    other = _run({"lr": 0.2}, {"val_acc": 0.8})
    conn = get_db()
    set_reference(conn, ref_id)
    trash_experiment(conn, ref_id)

    d = delta_vs_reference(conn, other)
    assert d["reference"]["stale"] == "trashed"
    assert "param_changes" not in d


def test_a_runs_study_reference_applies_to_its_delta(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.reference import delta_vs_reference, set_reference

    project_ref = _run({"lr": 0.1}, {"val_acc": 0.9})
    study_ref = _run({"lr": 0.2}, {"val_acc": 0.8})
    subject = _run({"lr": 0.3}, {"val_acc": 0.7})
    conn = get_db()
    set_reference(conn, project_ref)
    set_reference(conn, study_ref, study="sweep-a")
    _set_study(conn, "sweep-a", subject)

    d = delta_vs_reference(conn, subject)
    assert d["reference"]["id"] == study_ref
    assert d["reference"]["source"] == "study"


def test_detail_payload_carries_the_reference(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.queries import get_experiment_detail
    from exptrack.core.reference import set_reference

    ref_id = _run({"lr": 0.1}, {"val_acc": 0.9})
    other = _run({"lr": 0.2}, {"val_acc": 0.8})
    conn = get_db()
    set_reference(conn, ref_id)

    detail = get_experiment_detail(conn, other)
    assert detail["reference"]["id"] == ref_id
    assert detail["reference"]["source"] == "project"
