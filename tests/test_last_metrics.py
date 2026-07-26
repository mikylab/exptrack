"""Tests for the shared last_metrics() query.

The old SQL (`GROUP BY key HAVING MAX(COALESCE(step,0))`) dropped step-less
metrics entirely (HAVING treats the MAX as a boolean filter → 0 → group gone)
and returned an arbitrary row's value for stepped metrics. These lock in the
correct latest-value-per-key behavior.
"""
from __future__ import annotations


def _exp(conn, exp_id):
    conn.execute(
        "INSERT INTO experiments (id, name, created_at, updated_at) "
        "VALUES (?,'n','2026-01-01','2026-01-01')", (exp_id,))


def _log(conn, exp_id, key, value, step=None, ts="2026-01-01T00:00:00"):
    conn.execute(
        "INSERT INTO metrics (exp_id, key, value, step, ts) VALUES (?,?,?,?,?)",
        (exp_id, key, value, step, ts),
    )


def test_stepless_metrics_kept(db_conn):
    from exptrack.core.queries import last_metrics

    _exp(db_conn, "e1")
    _log(db_conn, "e1", "loss", 0.5, ts="2026-01-01T00:00:01")
    _log(db_conn, "e1", "loss", 0.3, ts="2026-01-01T00:00:02")
    db_conn.commit()

    assert last_metrics(db_conn, "e1") == {"loss": 0.3}


def test_stepped_out_of_order(db_conn):
    from exptrack.core.queries import last_metrics

    _exp(db_conn, "e2")
    _log(db_conn, "e2", "acc", 0.9, step=10)
    _log(db_conn, "e2", "acc", 0.7, step=5)
    db_conn.commit()

    # Highest step wins regardless of insert order.
    assert last_metrics(db_conn, "e2") == {"acc": 0.9}


def test_mixed_keys_and_step_modes(db_conn):
    from exptrack.core.queries import last_metrics

    _exp(db_conn, "e3")
    _log(db_conn, "e3", "acc", 0.6, step=1)
    _log(db_conn, "e3", "acc", 0.8, step=2)
    _log(db_conn, "e3", "loss", 1.0, ts="2026-01-01T00:00:01")
    _log(db_conn, "e3", "loss", 0.4, ts="2026-01-01T00:00:02")
    db_conn.commit()

    assert last_metrics(db_conn, "e3") == {"acc": 0.8, "loss": 0.4}


def test_experiment_last_metrics_stepless(tmp_project):
    """Experiment.last_metrics() (which now delegates) keeps step-less metrics."""
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")
    exp.log_metric("loss", 0.5)   # no step
    exp.log_metric("loss", 0.3)   # no step
    assert exp.last_metrics() == {"loss": 0.3}
