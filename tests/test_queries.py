"""Tests for exptrack/core/queries.py — shared query functions."""


def test_find_experiment_by_prefix(tmp_project, sample_experiment):
    """find_experiment returns experiment by prefix match."""
    from exptrack.core import get_db
    from exptrack.core.queries import find_experiment

    conn = get_db()
    result = find_experiment(conn, sample_experiment.id[:6])
    assert result is not None
    assert result["id"] == sample_experiment.id


def test_find_experiment_not_found(tmp_project):
    """find_experiment returns None for non-existent ID."""
    from exptrack.core import get_db
    from exptrack.core.queries import find_experiment

    conn = get_db()
    result = find_experiment(conn, "nonexistent")
    assert result is None


def test_get_experiment_detail(tmp_project, sample_experiment):
    """get_experiment_detail returns full experiment with params and metrics."""
    from exptrack.core import get_db
    from exptrack.core.queries import get_experiment_detail

    conn = get_db()
    detail = get_experiment_detail(conn, sample_experiment.id[:6])

    assert detail is not None
    assert detail["id"] == sample_experiment.id
    assert detail["status"] == "done"
    assert detail["params"]["lr"] == 0.01
    assert detail["params"]["epochs"] == 10
    assert len(detail["metrics"]) == 2  # loss and acc
    assert any(m["key"] == "loss" for m in detail["metrics"])
    assert any(m["key"] == "acc" for m in detail["metrics"])


def test_list_experiments(tmp_project, sample_experiment):
    """list_experiments returns recent experiments with metrics."""
    from exptrack.core import get_db
    from exptrack.core.queries import list_experiments

    conn = get_db()
    results = list_experiments(conn, limit=10)

    assert len(results) >= 1
    assert results[0]["id"] == sample_experiment.id


def test_list_experiments_status_filter(tmp_project):
    """list_experiments filters by status."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import list_experiments

    # Create one done and one failed
    e1 = Experiment(script="a.py")
    e1.finish()
    e2 = Experiment(script="b.py")
    e2.fail("crash")

    conn = get_db()
    done = list_experiments(conn, status="done")
    failed = list_experiments(conn, status="failed")

    assert all(e["status"] == "done" for e in done)
    assert all(e["status"] == "failed" for e in failed)


def test_get_latest_metrics(tmp_project, sample_experiment):
    """get_latest_metrics returns the last value for each metric key."""
    from exptrack.core import get_db
    from exptrack.core.queries import get_latest_metrics

    conn = get_db()
    metrics = get_latest_metrics(conn, sample_experiment.id)

    assert "loss" in metrics
    assert metrics["loss"] == 0.3  # step 2 value
    assert "acc" in metrics
    assert metrics["acc"] == 0.85
