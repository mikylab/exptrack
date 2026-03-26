"""Tests for exptrack/core/experiment.py — Experiment class lifecycle."""
from __future__ import annotations

import json
import math

import pytest


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

def test_create_writes_to_db(tmp_project):
    """Creating an Experiment inserts a row into the experiments table."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM experiments WHERE id=?", (exp.id,)
    ).fetchone()

    assert row is not None, "Experiment row not found in DB"
    assert row["status"] == "running"
    assert row["name"] == exp.name
    assert row["id"] == exp.id

    exp.finish()


def test_create_with_initial_params(tmp_project):
    """Experiment created with initial params stores them in the DB."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py", params={"lr": 0.01, "epochs": 10})
    conn = get_db()
    rows = conn.execute(
        "SELECT key, value FROM params WHERE exp_id=?", (exp.id,)
    ).fetchall()
    params = {r["key"]: json.loads(r["value"]) for r in rows}

    assert params.get("lr") == 0.01
    assert params.get("epochs") == 10

    exp.finish()


# ---------------------------------------------------------------------------
# Params
# ---------------------------------------------------------------------------

def test_log_param(tmp_project):
    """log_param stores a single parameter."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    exp.log_param("lr", 0.01)

    conn = get_db()
    row = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key=?", (exp.id, "lr")
    ).fetchone()

    assert row is not None
    assert json.loads(row["value"]) == 0.01

    exp.finish()


def test_log_params_batch(tmp_project):
    """log_params stores multiple parameters at once."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    exp.log_params({"lr": 0.01, "batch_size": 32, "epochs": 10})

    conn = get_db()
    rows = conn.execute(
        "SELECT key, value FROM params WHERE exp_id=? ORDER BY key", (exp.id,)
    ).fetchall()
    params = {r["key"]: json.loads(r["value"]) for r in rows}

    assert params["lr"] == 0.01
    assert params["batch_size"] == 32
    assert params["epochs"] == 10

    exp.finish()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_log_metric_with_step(tmp_project):
    """log_metric stores metric values with step numbers."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    exp.log_metric("loss", 0.5, step=1)
    exp.log_metric("loss", 0.3, step=2)
    exp.log_metric("loss", 0.1, step=3)

    conn = get_db()
    rows = conn.execute(
        "SELECT value, step FROM metrics WHERE exp_id=? AND key='loss' ORDER BY step",
        (exp.id,),
    ).fetchall()

    assert len(rows) == 3
    assert rows[0]["value"] == 0.5
    assert rows[1]["value"] == 0.3
    assert rows[2]["value"] == 0.1

    exp.finish()


def test_log_metric_skips_non_finite(tmp_project):
    """log_metric silently skips NaN / Inf / -Inf values."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    exp.log_metric("loss", 0.5, step=1)
    exp.log_metric("loss", float("nan"), step=2)
    exp.log_metric("loss", float("inf"), step=3)
    exp.log_metric("loss", float("-inf"), step=4)
    exp.log_metric("loss", 0.1, step=5)

    conn = get_db()
    rows = conn.execute(
        "SELECT value, step FROM metrics WHERE exp_id=? AND key='loss' ORDER BY step",
        (exp.id,),
    ).fetchall()

    # Only the two finite values should have been stored
    assert len(rows) == 2
    assert rows[0]["step"] == 1
    assert rows[1]["step"] == 5

    exp.finish()


def test_log_metrics_batch(tmp_project):
    """log_metrics inserts multiple metrics in one call."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    exp.log_metrics({"loss": 0.5, "acc": 0.9}, step=1)

    conn = get_db()
    rows = conn.execute(
        "SELECT key, value FROM metrics WHERE exp_id=? ORDER BY key", (exp.id,)
    ).fetchall()
    by_key = {r["key"]: r["value"] for r in rows}

    assert by_key["acc"] == 0.9
    assert by_key["loss"] == 0.5

    exp.finish()


def test_log_metrics_filters_non_finite(tmp_project):
    """log_metrics skips non-finite values while keeping finite ones."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    exp.log_metrics(
        {"loss": float("nan"), "acc": 0.9, "f1": float("inf")}, step=1
    )

    conn = get_db()
    rows = conn.execute(
        "SELECT key, value FROM metrics WHERE exp_id=? ORDER BY key", (exp.id,)
    ).fetchall()

    assert len(rows) == 1
    assert rows[0]["key"] == "acc"
    assert rows[0]["value"] == 0.9

    exp.finish()


# ---------------------------------------------------------------------------
# Lifecycle: finish / fail
# ---------------------------------------------------------------------------

def test_finish_sets_done(tmp_project):
    """finish() sets status='done' and records duration_s."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    exp.finish()

    assert exp.status == "done"
    assert exp.duration_s is not None
    assert exp.duration_s >= 0

    conn = get_db()
    row = conn.execute(
        "SELECT status, duration_s FROM experiments WHERE id=?", (exp.id,)
    ).fetchone()
    assert row["status"] == "done"
    assert row["duration_s"] is not None


def test_fail_sets_failed(tmp_project):
    """fail() sets status='failed' and logs error as a param."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    exp.fail("OOM error")

    assert exp.status == "failed"

    conn = get_db()
    row = conn.execute(
        "SELECT status FROM experiments WHERE id=?", (exp.id,)
    ).fetchone()
    assert row["status"] == "failed"

    param = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key='error'", (exp.id,)
    ).fetchone()
    assert json.loads(param["value"]) == "OOM error"


def test_finish_twice_raises(tmp_project):
    """Calling finish() twice raises RuntimeError."""
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")
    exp.finish()

    with pytest.raises(RuntimeError, match="already finished"):
        exp.finish()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

def test_context_manager_finish(tmp_project):
    """Context manager calls finish() on normal exit."""
    from exptrack.core import Experiment, get_db

    with Experiment(script="train.py") as exp:
        exp.log_metric("loss", 0.1)
        eid = exp.id

    conn = get_db()
    row = conn.execute(
        "SELECT status FROM experiments WHERE id=?", (eid,)
    ).fetchone()
    assert row["status"] == "done"


def test_context_manager_fail_on_exception(tmp_project):
    """Context manager calls fail() when an exception is raised inside."""
    from exptrack.core import Experiment, get_db

    eid = None
    with pytest.raises(ValueError, match="boom"):
        with Experiment(script="train.py") as exp:
            eid = exp.id
            raise ValueError("boom")

    conn = get_db()
    row = conn.execute(
        "SELECT status FROM experiments WHERE id=?", (eid,)
    ).fetchone()
    assert row["status"] == "failed"
