"""Tests for Experiment.resume() — reopening a finished run to continue it.

Every resume path (Experiment.resume, `exptrack run --resume`, `run-start
--resume`) went through this method, which crashed with AttributeError because
instances built via object.__new__ never had _defer_commit set. These tests
lock the behavior in.
"""
from __future__ import annotations

import pytest


def _make_finished(script="train.py", **params):
    from exptrack.core import Experiment
    exp = Experiment(script=script, params=params or None)
    exp.log_metric("loss", 0.5, step=1)
    exp.finish()
    return exp


def test_resume_by_id(tmp_project):
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    exp = _make_finished(lr=0.01)
    resumed = Experiment.resume(exp.id)
    assert resumed.id == exp.id

    status = get_db().execute(
        "SELECT status FROM experiments WHERE id=?", (exp.id,)
    ).fetchone()[0]
    assert status == "running"


def test_resume_logs_timeline_event(tmp_project):
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    exp = _make_finished()
    prev_max = get_db().execute(
        "SELECT COALESCE(MAX(seq), 0) FROM timeline WHERE exp_id=?", (exp.id,)
    ).fetchone()[0]

    Experiment.resume(exp.id)

    row = get_db().execute(
        "SELECT seq FROM timeline WHERE exp_id=? AND event_type='resume' "
        "ORDER BY seq DESC LIMIT 1", (exp.id,)
    ).fetchone()
    assert row is not None
    assert row[0] > prev_max


def test_resume_by_prefix(tmp_project):
    from exptrack.core import Experiment

    exp = _make_finished()
    resumed = Experiment.resume(exp.id[:6])
    assert resumed.id == exp.id


def test_resume_unknown_raises(tmp_project):
    from exptrack.core import Experiment

    with pytest.raises(ValueError):
        Experiment.resume("does-not-exist")


def test_resume_then_log_and_finish(tmp_project):
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    exp = _make_finished(lr=0.01)
    resumed = Experiment.resume(exp.id)

    resumed.log_metric("loss", 0.2, step=2)
    resumed.log_params({"extra": 7})
    resumed.log_event("observational")
    resumed.finish()

    conn = get_db()
    # Metrics aggregate onto the same exp_id
    n_loss = conn.execute(
        "SELECT COUNT(*) FROM metrics WHERE exp_id=? AND key='loss'", (exp.id,)
    ).fetchone()[0]
    assert n_loss == 2

    row = conn.execute(
        "SELECT status, duration_s FROM experiments WHERE id=?", (exp.id,)
    ).fetchone()
    assert row["status"] == "done"
    assert row["duration_s"] is not None


def test_resume_batched_writes(tmp_project):
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    exp = _make_finished()
    resumed = Experiment.resume(exp.id)

    with resumed.batched_writes():
        resumed.log_params({"a": 1, "b": 2})

    conn = get_db()
    vals = {
        r["key"]: r["value"] for r in conn.execute(
            "SELECT key, value FROM params WHERE exp_id=? AND key IN ('a','b')",
            (exp.id,)
        ).fetchall()
    }
    assert vals == {"a": "1", "b": "2"}
