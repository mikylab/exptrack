"""Metric writes are committed on a time window, not once per call.

A commit is an fsync, and metrics are the one thing written in a tight loop —
100k iterations logging 5 metrics each spent ~96% of its time in commit (151s,
against 8s once batched). `Experiment._commit_metrics` coalesces commits into
at most one per `metric_commit_interval_ms`.

The window is bounded by *time* specifically so the dashboard stays live:
uncommitted rows are invisible to the dashboard's separate connection, so a
count-based batch would stall a slow run's chart for however long N iterations
take. These tests pin both halves — the batching, and everything that has to
flush it.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys


def _rows(tmp_project) -> int:
    """Count metric rows over a SEPARATE connection — the point is what another
    process (the dashboard) can actually see, not what this one has buffered."""
    conn = sqlite3.connect(tmp_project / ".exptrack" / "experiments.db")
    try:
        return conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    finally:
        conn.close()


def _set_interval(tmp_project, ms):
    from exptrack import config as cfg
    p = tmp_project / ".exptrack" / "config.json"
    conf = json.loads(p.read_text())
    conf["metric_commit_interval_ms"] = ms
    p.write_text(json.dumps(conf))
    cfg._cache = None


def test_writes_are_batched_within_the_window(tmp_project):
    """A burst inside one window commits far fewer times than it logs."""
    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 10_000)   # one long window
    exp = Experiment(name="burst")
    for i in range(200):
        exp.log_metric("loss", float(i), step=i)

    # The first write always commits (see test_first_write_lands_immediately);
    # every later one in the window is buffered rather than fsync'd.
    assert _rows(tmp_project) == 1, "metrics committed per call — batching is not active"
    exp.finish()
    assert _rows(tmp_project) == 200, "finish() must flush the pending window"


def test_zero_interval_commits_every_call(tmp_project):
    """`metric_commit_interval_ms: 0` restores the old commit-per-call behaviour."""
    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 0)
    exp = Experiment(name="unbatched")
    exp.log_metric("loss", 1.0, step=1)
    assert _rows(tmp_project) == 1
    exp.log_metrics({"a": 1.0, "b": 2.0}, step=2)
    assert _rows(tmp_project) == 3
    exp.finish()


def test_first_write_lands_immediately(tmp_project):
    """The first metric of a run always commits, however long the window is.

    Starting the window at run creation instead would defer it until the
    *second* write — so a run logging once per epoch would show its chart
    permanently one epoch behind, which is the opposite of the liveness this
    scheme is supposed to preserve.
    """
    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 10_000)
    exp = Experiment(name="firstpoint")
    exp.log_metric("loss", 1.0, step=1)
    assert _rows(tmp_project) == 1
    exp.finish()


def test_slow_logger_is_never_a_point_behind(tmp_project):
    """A run logging less often than the window commits every point as it goes,
    so the dashboard is never showing stale numbers for a live run."""
    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 1)      # 1ms: every call is past the window
    exp = Experiment(name="slow")
    import time
    for i in range(4):
        exp.log_metric("epoch_loss", float(i), step=i)
        time.sleep(0.005)
        assert _rows(tmp_project) == i + 1, f"point {i} not visible to a reader"
    exp.finish()


def test_fail_flushes(tmp_project):
    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 10_000)
    exp = Experiment(name="crashed")
    for i in range(10):
        exp.log_metric("loss", float(i), step=i)
    exp.fail("boom")
    assert _rows(tmp_project) == 10


def test_context_manager_exit_flushes(tmp_project):
    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 10_000)
    with Experiment(name="ctx") as exp:
        for i in range(10):
            exp.log_metric("loss", float(i), step=i)
    assert _rows(tmp_project) == 10


def test_other_writes_flush_pending_metrics(tmp_project):
    """Any other logging call commits the shared connection, which lands the
    pending metrics too — worth pinning, since it's why a run that logs a param
    mid-loop can't strand points."""
    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 10_000)
    exp = Experiment(name="mixed")
    for i in range(5):
        exp.log_metric("loss", float(i), step=i)
    assert _rows(tmp_project) == 1      # first landed, 4 buffered
    exp.log_param("note_key", "v")
    assert _rows(tmp_project) == 5
    exp.finish()


def test_starting_another_run_with_metrics_pending(tmp_project):
    """A pending window leaves an implicit transaction open on the shared
    connection; creating the next run does `BEGIN IMMEDIATE`, which fails with
    "cannot start a transaction within a transaction" unless it flushes first."""
    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 10_000)
    a = Experiment(name="first")
    for i in range(5):
        a.log_metric("loss", float(i), step=i)

    b = Experiment(name="second")      # must not raise
    assert _rows(tmp_project) == 5, "creating a run must land the previous run's metrics"
    a.finish()
    b.finish()


def test_a_collected_run_cannot_strand_its_pending_window(tmp_project):
    """`_live_runs` holds weak references, so a run dropped without finish()
    vanished from it with its window still open: the rows sat in the shared
    connection's implicit transaction unreachable by every flush, and the next
    Experiment()'s BEGIN IMMEDIATE then died on "cannot start a transaction
    within a transaction" — whose rollback destroyed those points and raised
    into the user's script. `db.flush_pending` asks the connection instead of a
    registry, so a collected run's rows still land."""
    import gc

    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 60_000)

    def train():
        exp = Experiment(name="dropped")
        for i in range(10):
            exp.log_metric("loss", float(i), step=i)
        return exp.id           # exp goes out of scope with 9 points buffered

    train()
    gc.collect()

    Experiment(name="after").finish()   # must not raise
    assert _rows(tmp_project) == 10, "the collected run's pending window was lost"


def test_close_db_lands_a_pending_window_instead_of_rolling_it_back(tmp_project):
    """close_db() closed the connection without committing, so any rows still
    inside the coalescing window were silently rolled back."""
    from exptrack.core.db import close_db
    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 60_000)
    exp = Experiment(name="pending")
    for i in range(5):
        exp.log_metric("loss", float(i), step=i)
    assert _rows(tmp_project) == 1          # first landed, 4 buffered
    close_db(sweep=False, checkpoint=False)
    assert _rows(tmp_project) == 5


def test_a_thinned_stretch_still_flushes_an_earlier_kept_point(tmp_project):
    """A thinned-away point stores nothing, but an earlier kept point may be
    sitting uncommitted — with keep_every=1000 the next call that would flush it
    is a thousand iterations away. The tick must not cost a get_db() per dropped
    point, so it checks the window on instance state first."""
    import json

    from exptrack import config as cfg
    from exptrack.core.experiment import Experiment

    p = tmp_project / ".exptrack" / "config.json"
    conf = json.loads(p.read_text())
    conf["metric_commit_interval_ms"] = 0      # every flush lands immediately
    conf["metric_keep_every"] = 50
    p.write_text(json.dumps(conf))
    cfg._cache = None

    exp = Experiment(name="thinned")
    for i in range(120):
        exp.log_metric("loss", float(i), step=i)
    # 1 of every 50 points kept, and all of them visible to another connection.
    assert _rows(tmp_project) == 3
    exp.finish()


def test_batched_writes_still_owns_its_commit(tmp_project):
    """Inside batched_writes() the block commits, not the metric window."""
    from exptrack.core.experiment import Experiment

    _set_interval(tmp_project, 0)      # would otherwise commit every call
    exp = Experiment(name="batched")
    with exp.batched_writes():
        for i in range(10):
            exp.log_metric("loss", float(i), step=i)
        assert _rows(tmp_project) == 0, "batched_writes must defer metric commits"
    assert _rows(tmp_project) == 10
    exp.finish()


def test_interpreter_exit_flushes_unfinished_run(tmp_project):
    """A script that just ends — no finish(), no context manager — still keeps
    its last points, via the atexit hook. Only a hard kill can lose them."""
    script = tmp_project / "run.py"
    script.write_text(
        "from exptrack.core.experiment import Experiment\n"
        "exp = Experiment(name='no-finish')\n"
        "for i in range(20):\n"
        "    exp.log_metric('loss', float(i), step=i)\n"
    )
    _set_interval(tmp_project, 10_000)
    r = subprocess.run([sys.executable, str(script)], cwd=tmp_project,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert _rows(tmp_project) == 20, "atexit flush lost the run's metrics"


def test_session_node_index_is_partial(db_conn):
    """`session_node_id` is NULL for every metric written outside a notebook
    session — i.e. all of them for a script user — and the only query it serves
    probes a real node id. Indexing the NULLs was ~10% of the database (5.1 MB
    of 54 MB on a 100k-iteration run) for nothing.
    """
    sql = db_conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' "
        "AND name='idx_metrics_session_node'").fetchone()
    assert sql is not None, "index missing"
    assert "session_node_id IS NOT NULL" in sql[0], (
        "index is no longer partial — it will store one entry per metric row")


def test_session_node_lookup_still_uses_the_index(db_conn):
    """A partial index only helps if the query it exists for still hits it."""
    plan = db_conn.execute(
        "EXPLAIN QUERY PLAN SELECT key, value FROM metrics WHERE session_node_id=?",
        ("node1",)).fetchall()
    assert any("idx_metrics_session_node" in str(tuple(r)) for r in plan), \
        f"node-tagged metric lookup no longer uses the index: {[tuple(r) for r in plan]}"
