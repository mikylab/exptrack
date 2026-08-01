"""Tests for explicit baseline linking (`_variant_of`).

Chronology is the wrong baseline for the commonest notebook loop: re-run one
notebook with a different model and "the previous run of this script" is
whatever happened to run last, not the run you mean to compare against.
Declaring a target overrides the chronological pick everywhere the delta is
computed.
"""
from __future__ import annotations


def _mk(script="train.py", **kw):
    from exptrack.core import Experiment
    exp = Experiment(script=script, **kw)
    exp.finish()
    return exp


def test_chronological_baseline_by_default(tmp_project):
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_previous_run

    first = _mk()
    second = _mk()
    third = _mk()

    assert get_previous_run(get_db(), third.id)["id"] == second.id
    assert get_previous_run(get_db(), second.id)["id"] == first.id


def test_declared_target_overrides_chronology(tmp_project):
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_previous_run, set_variant_of

    first = _mk()
    _mk()                       # the run that merely happened to be last
    third = _mk()

    conn = get_db()
    assert set_variant_of(conn, third.id, first.id)["ok"]

    prev = get_previous_run(conn, third.id)
    assert prev["id"] == first.id
    assert prev["explicit"] is True


def test_what_changed_card_honors_the_link(tmp_project):
    """find_previous_by_script backs the Overview card and must agree with the
    vs-previous strip, or the two surfaces name different baselines."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import find_previous_by_script, set_variant_of

    first = _mk()
    _mk()
    third = _mk()

    conn = get_db()
    set_variant_of(conn, third.id, first.id)

    prev = find_previous_by_script(conn, third.id)
    assert prev["id"] == first.id
    assert prev["explicit"] is True
    # Still carries what the card renders.
    assert "params" in prev and "metrics" in prev


def test_trashed_target_falls_back_to_chronology(tmp_project):
    """A stale link must degrade to the old behaviour, never leave the run with
    no comparison at all."""
    from exptrack.core.db import get_db, trash_experiment
    from exptrack.core.queries import get_previous_run, set_variant_of

    first = _mk()
    second = _mk()
    third = _mk()

    conn = get_db()
    set_variant_of(conn, third.id, first.id)
    trash_experiment(conn, first.id)
    conn.commit()

    prev = get_previous_run(conn, third.id)
    assert prev["id"] == second.id
    assert not prev.get("explicit")


def test_running_target_is_not_used_as_baseline(tmp_project):
    """A run still in flight has moving metrics — the same rule the
    chronological baseline already applies."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_previous_run, set_variant_of

    first = _mk()
    live = Experiment(script="train.py")      # deliberately not finished
    third = _mk()

    conn = get_db()
    set_variant_of(conn, third.id, live.id)

    assert get_previous_run(conn, third.id)["id"] == first.id


def test_clearing_the_link_restores_chronology(tmp_project):
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_previous_run, get_variant_of, set_variant_of

    first = _mk()
    second = _mk()
    third = _mk()

    conn = get_db()
    set_variant_of(conn, third.id, first.id)
    assert set_variant_of(conn, third.id, "")["ok"]

    assert get_variant_of(conn, third.id) is None
    assert get_previous_run(conn, third.id)["id"] == second.id


def test_relinking_replaces_rather_than_conflicts(tmp_project):
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_variant_of, set_variant_of

    first, second, third = _mk(), _mk(), _mk()
    conn = get_db()
    set_variant_of(conn, third.id, first.id)
    set_variant_of(conn, third.id, second.id)

    assert get_variant_of(conn, third.id) == second.id


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_self_link_refused(tmp_project):
    from exptrack.core.db import get_db
    from exptrack.core.queries import set_variant_of

    exp = _mk()
    assert "error" in set_variant_of(get_db(), exp.id, exp.id)


def test_unknown_target_refused(tmp_project):
    from exptrack.core.db import get_db
    from exptrack.core.queries import set_variant_of

    exp = _mk()
    assert "error" in set_variant_of(get_db(), exp.id, "nosuchrun")


def test_one_step_cycle_refused(tmp_project):
    """If A is a variant of B, B cannot be a variant of A — neither would then
    have a stable baseline."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import set_variant_of

    a, b = _mk(), _mk()
    conn = get_db()
    set_variant_of(conn, a.id, b.id)
    assert "error" in set_variant_of(conn, b.id, a.id)


def test_link_is_internal_and_stays_out_of_user_params(tmp_project):
    """The `_` prefix is what keeps it out of run naming, the params table and
    the What-changed diff."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import VARIANT_OF_KEY, set_variant_of

    assert VARIANT_OF_KEY.startswith("_")
    a, b = _mk(), _mk()
    set_variant_of(get_db(), b.id, a.id)
    detail_params = get_db().execute(
        "SELECT key FROM params WHERE exp_id=? AND key NOT LIKE '\\_%' ESCAPE '\\'",
        (b.id,),
    ).fetchall()
    assert all(r["key"] != VARIANT_OF_KEY for r in detail_params)


def test_route_wires_through(tmp_project):
    from exptrack.core.db import get_db
    from exptrack.dashboard.routes import write_routes

    a, b = _mk(), _mk()
    conn = get_db()
    res = write_routes.api_set_variant_of(conn, b.id, {"variant_of": a.id})
    assert res["ok"] and res["variant_of"] == a.id
    # A JSON number/None body must not blow up the route (body_str contract).
    assert write_routes.api_set_variant_of(conn, b.id, {"variant_of": None})["ok"]
