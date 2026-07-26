"""Tests for exptrack/core/experiment.py — Experiment class lifecycle."""
from __future__ import annotations

import json

import pytest


class CommitCountingProxy:
    """Wraps a sqlite3 connection, counting commit() calls and delegating the
    rest, so tests can assert how many commits a batched write performed."""

    def __init__(self, real):
        self._real = real
        self.commits = 0

    def commit(self):
        self.commits += 1
        return self._real.commit()

    def __getattr__(self, name):
        return getattr(self._real, name)


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


def test_name_is_auto_flag(tmp_project):
    """Auto-generated names set name_is_auto=1; an explicit name sets it to 0."""
    from exptrack.core import Experiment, get_db

    auto = Experiment(script="train.py")
    explicit = Experiment(script="train.py", name="my-best-run")
    conn = get_db()
    a = conn.execute("SELECT name_is_auto FROM experiments WHERE id=?", (auto.id,)).fetchone()
    e = conn.execute("SELECT name_is_auto FROM experiments WHERE id=?", (explicit.id,)).fetchone()
    assert a["name_is_auto"] == 1
    assert e["name_is_auto"] == 0
    auto.finish()
    explicit.finish()


def test_internal_rename_keeps_auto_flag(tmp_project):
    """Internal auto-rename (argparse/notebook capture) keeps name_is_auto=1."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.naming import make_run_name

    exp = Experiment(script="train.py")
    exp._rename(make_run_name("train.py", {"lr": 0.01}))
    conn = get_db()
    row = conn.execute("SELECT name_is_auto FROM experiments WHERE id=?", (exp.id,)).fetchone()
    assert row["name_is_auto"] == 1
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


def test_internal_param_no_overwrite_warning(tmp_project, capsys):
    """Internal bookkeeping params (_var/, _code_change/, _cells_ran) must not
    print the 'param overwritten' warning when re-logged with a new value,
    but a real user param still warns."""
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")
    capsys.readouterr()  # clear

    exp.log_params({"_var/df": "DataFrame(shape=(3, 2))"})
    exp.log_params({"_var/df": "DataFrame(shape=(4, 2))"})
    exp.log_params({"_code_change/cell_1": "+ a"})
    exp.log_params({"_code_change/cell_1": "+ b"})
    exp.log_params({"_cells_ran": "[1]"})
    exp.log_params({"_cells_ran": "[1, 2]"})
    err = capsys.readouterr().err
    assert "overwritten" not in err

    # A real hyperparameter still warns on overwrite.
    exp.log_params({"lr": 0.01})
    exp.log_params({"lr": 0.02})
    err = capsys.readouterr().err
    assert "param 'lr' overwritten" in err

    exp.finish()


def test_batched_writes_single_commit(tmp_project, monkeypatch):
    """batched_writes defers commits and writes everything once on exit."""
    import exptrack.core.experiment as expmod
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    conn = get_db()

    proxy = CommitCountingProxy(conn)
    monkeypatch.setattr(expmod, "get_db", lambda: proxy)

    with exp.batched_writes():
        exp.log_event(event_type="cell_exec", key="cell_1", value={"a": 1})
        exp.log_event(event_type="var_set", key="x", value="1")
        exp.log_params({"_var/x": "1"})
        assert proxy.commits == 0  # nothing committed mid-batch
    assert proxy.commits == 1  # exactly one commit on exit

    monkeypatch.undo()

    rows = conn.execute(
        "SELECT COUNT(*) AS c FROM timeline WHERE exp_id=?", (exp.id,)
    ).fetchone()
    assert rows["c"] == 2
    p = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key=?", (exp.id, "_var/x")
    ).fetchone()
    assert p is not None

    exp.finish()


def test_batched_writes_defers_tags_and_notes(tmp_project, monkeypatch):
    """add_tag/remove_tag/set_note/add_note honor batched_writes (one commit)."""
    import exptrack.core.experiment as expmod
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    conn = get_db()

    proxy = CommitCountingProxy(conn)
    monkeypatch.setattr(expmod, "get_db", lambda: proxy)

    with exp.batched_writes():
        exp.add_tag("baseline")
        exp.add_tag("v2")
        exp.remove_tag("baseline")
        exp.set_note("first")
        exp.add_note("second")
        assert proxy.commits == 0  # nothing committed mid-batch
    assert proxy.commits == 1  # exactly one commit on exit

    monkeypatch.undo()

    row = conn.execute(
        "SELECT tags, notes FROM experiments WHERE id=?", (exp.id,)
    ).fetchone()
    import json as _json
    assert _json.loads(row["tags"]) == ["v2"]
    assert row["notes"] == "first\nsecond"

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


def test_fail_captures_traceback(tmp_project):
    """fail(traceback=...) stores the full traceback as _error_traceback and
    surfaces it as the detail `error` key (not in the params table)."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import get_experiment_detail

    tb = 'Traceback (most recent call last):\n  File "t.py", line 3\nIndexError: x'
    exp = Experiment(script="train.py")
    exp.fail("IndexError: x", traceback=tb)

    conn = get_db()
    row = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key='_error_traceback'",
        (exp.id,),
    ).fetchone()
    assert json.loads(row["value"]) == tb

    detail = get_experiment_detail(conn, exp.id)
    assert detail["error"] == tb
    assert "_error_traceback" not in detail["params"]


def test_context_manager_captures_traceback(tmp_project):
    """A `with Experiment(...)` block that raises captures the full traceback,
    not just the message — so the context-manager path matches the wrapper."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import get_experiment_detail

    try:
        with Experiment(script="train.py") as exp:
            raise ValueError("boom in a with-block")
    except ValueError:
        pass

    conn = get_db()
    detail = get_experiment_detail(conn, exp.id)
    assert detail["status"] == "failed"
    assert "ValueError: boom in a with-block" in detail["error"]
    assert "test_experiment.py" in detail["error"]


def test_fail_traceback_capped(tmp_project):
    """A pathologically large traceback is truncated before storage."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.experiment import _MAX_TRACEBACK_CHARS

    exp = Experiment(script="train.py")
    exp.fail("boom", traceback="x" * (_MAX_TRACEBACK_CHARS + 5000))

    conn = get_db()
    row = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key='_error_traceback'",
        (exp.id,),
    ).fetchone()
    stored = json.loads(row["value"])
    assert stored.startswith("…(truncated)")
    assert len(stored) <= _MAX_TRACEBACK_CHARS + len("…(truncated)\n")


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
    with pytest.raises(ValueError, match="boom"), Experiment(script="train.py") as exp:
        eid = exp.id
        raise ValueError("boom")

    conn = get_db()
    row = conn.execute(
        "SELECT status FROM experiments WHERE id=?", (eid,)
    ).fetchone()
    assert row["status"] == "failed"
