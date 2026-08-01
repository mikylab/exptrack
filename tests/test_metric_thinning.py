"""Write-time metric thinning (``metric_keep_every`` / ``thin_every``).

The rule being pinned here: thinning keeps 1 of every N **logged points**, per
metric key, and always keeps a key's first point. It must not look at the *step
value*, which is what it used to do — see ``test_thinning_survives_a_logging_``
``cadence_coprime_with_keep_every`` for the failure that caused.
"""

import json

import pytest

from exptrack.core.experiment import Experiment


def _set_keep_every(tmp_project, n):
    from exptrack import config as cfg

    p = tmp_project / ".exptrack" / "config.json"
    conf = json.loads(p.read_text())
    conf["metric_keep_every"] = n
    p.write_text(json.dumps(conf))
    cfg._cache = None       # force a reload on the next cfg.load()
    return conf


def _points(_conn, exp_id, key="loss"):
    # Fetch the connection fresh rather than holding the fixture's: clearing the
    # config cache above can make get_db() re-resolve and close the old handle.
    from exptrack.core.db import get_db

    return get_db().execute(
        "SELECT step FROM metrics WHERE exp_id=? AND key=? ORDER BY rowid",
        (exp_id, key),
    ).fetchall()


def test_keep_every_1_stores_every_point(tmp_project, db_conn):
    _set_keep_every(tmp_project, 1)
    exp = Experiment(name="all")
    for i in range(20):
        exp.log_metric("loss", float(i), step=i)
    exp.finish()
    assert len(_points(db_conn, exp.id)) == 20


def test_keep_every_counts_points_not_steps(tmp_project, db_conn):
    """Every 5th *logged point*, starting with the first."""
    _set_keep_every(tmp_project, 5)
    exp = Experiment(name="thin")
    for i in range(20):
        exp.log_metric("loss", float(i), step=i)
    exp.finish()
    assert [r["step"] for r in _points(db_conn, exp.id)] == [0, 5, 10, 15]


def test_thinning_survives_a_logging_cadence_coprime_with_keep_every(tmp_project, db_conn):
    """The regression that made a run look like it recorded no metrics at all.

    Logging every 5th step (``if (i+1) % 5 == 0``) with ``keep_every=999`` used
    to be evaluated as ``step % 999 == 0``. The two are coprime, so not one of
    the steps 5, 10, 15 … ever satisfied it and the run stored *zero* points —
    a setting that reads as "thin this" acting as "discard everything".
    """
    _set_keep_every(tmp_project, 999)
    exp = Experiment(name="coprime")
    for i in range(200):
        if (i + 1) % 5 == 0:
            exp.log_metric("loss", 1.0 / (i + 1), step=i + 1)
    exp.finish()
    rows = _points(db_conn, exp.id)
    # 40 points logged, so 1 of every 999 is exactly one — the first. Never zero.
    assert [r["step"] for r in rows] == [5]


def test_a_keys_first_point_is_always_kept(tmp_project, db_conn):
    """Whatever the factor, a key that logged anything has at least one point."""
    _set_keep_every(tmp_project, 10_000)
    exp = Experiment(name="first")
    for i in range(50):
        exp.log_metric("loss", float(i), step=i * 7)
    exp.finish()
    assert [r["step"] for r in _points(db_conn, exp.id)] == [0]


def test_step_none_is_thinned_like_any_other_point(tmp_project, db_conn):
    """A step-less series is counted, not exempted.

    The old gate returned True for ``step is None`` because it had no step to
    take a modulo of — so ``log_metric(k, v)`` in a loop ignored the setting
    entirely. Counting points makes the setting mean the same thing either way.
    """
    _set_keep_every(tmp_project, 4)
    exp = Experiment(name="nostep")
    for i in range(12):
        exp.log_metric("loss", float(i))
    exp.finish()
    assert len(_points(db_conn, exp.id)) == 3


def test_each_key_is_thinned_on_its_own_count(tmp_project, db_conn):
    """A key logged on only some calls still keeps every Nth of *its* points."""
    _set_keep_every(tmp_project, 3)
    exp = Experiment(name="perkey")
    for i in range(9):
        exp.log_metrics({"loss": float(i)}, step=i)
        if i % 3 == 0:
            exp.log_metric("acc", float(i), step=i)
    exp.finish()
    assert len(_points(db_conn, exp.id, "loss")) == 3     # 9 logged → every 3rd
    assert len(_points(db_conn, exp.id, "acc")) == 1      # 3 logged → the first


def test_log_metrics_thins_all_keys_in_a_dict_together(tmp_project, db_conn):
    _set_keep_every(tmp_project, 2)
    exp = Experiment(name="dict")
    for i in range(10):
        exp.log_metrics({"loss": float(i), "acc": float(i) / 10}, step=i)
    exp.finish()
    assert [r["step"] for r in _points(db_conn, exp.id, "loss")] == [0, 2, 4, 6, 8]
    assert [r["step"] for r in _points(db_conn, exp.id, "acc")] == [0, 2, 4, 6, 8]


def test_thin_every_argument_overrides_config(tmp_project, db_conn):
    _set_keep_every(tmp_project, 1)
    exp = Experiment(name="arg", thin_every=4)
    for i in range(16):
        exp.log_metric("loss", float(i), step=i)
    exp.finish()
    assert len(_points(db_conn, exp.id)) == 4


def test_thinning_prints_one_notice_per_run(tmp_project, db_conn, capsys):
    """Dropping data silently is what made this undiagnosable from the UI."""
    _set_keep_every(tmp_project, 5)
    exp = Experiment(name="notice")
    for i in range(20):
        exp.log_metric("loss", float(i), step=i)
    exp.finish()
    err = capsys.readouterr().err
    assert err.count("metric thinning is on") == 1
    assert "keep_every=5" in err


def test_no_notice_at_the_default(tmp_project, db_conn, capsys):
    _set_keep_every(tmp_project, 1)
    exp = Experiment(name="quiet")
    for i in range(20):
        exp.log_metric("loss", float(i), step=i)
    exp.finish()
    assert "metric thinning" not in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["", None, "abc", 0, -3, 1e999])
def test_an_unusable_keep_every_degrades_to_keeping_everything(tmp_project, db_conn, bad):
    """A hand-edited config must never be the reason a run records nothing."""
    _set_keep_every(tmp_project, bad)
    exp = Experiment(name=f"bad{bad!r}")
    for i in range(6):
        exp.log_metric("loss", float(i), step=i)
    exp.finish()
    assert len(_points(db_conn, exp.id)) == 6


def test_a_resumed_run_thins_without_an_initialized_counter(tmp_project, db_conn):
    """``resume`` builds the instance via ``object.__new__``, skipping __init__."""
    _set_keep_every(tmp_project, 2)
    exp = Experiment(name="resumeme")
    exp.log_metric("loss", 0.0, step=0)
    exp.finish()

    again = Experiment.resume(exp.id)
    for i in range(1, 9):
        again.log_metric("loss", float(i), step=i)
    again.finish()
    # The resumed run counts its own points from zero: 8 logged → every 2nd.
    assert len(_points(db_conn, exp.id)) == 1 + 4
