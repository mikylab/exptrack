"""`get_metrics_series` downsamples in SQL, not in Python.

It used to SELECT every point for the experiment and build a dict per row
before throwing ~99% of them away. One 100k-iteration run logging 5 metrics is
500k rows, so producing 2500 chart points cost ~6s — on the endpoint the detail
view polls every 5 seconds while a run is live, so the poll could not keep up
with itself.

These pin the properties a chart actually depends on: a bounded number of
points, the true first/last point, the true extremes, and chronological order.
"""
from __future__ import annotations


def _exp(conn, exp_id):
    conn.execute(
        "INSERT INTO experiments (id, name, created_at, updated_at) "
        "VALUES (?,'n','2026-01-01','2026-01-01')", (exp_id,))


def _series(conn, exp_id, key, values, stepless=False):
    conn.executemany(
        "INSERT INTO metrics (exp_id, key, value, step, ts) VALUES (?,?,?,?,?)",
        [(exp_id, key, float(v), None if stepless else i,
          f"2026-01-01T00:00:{i % 60:02d}") for i, v in enumerate(values)],
    )


def test_short_series_returned_whole_and_unchanged(db_conn):
    from exptrack.core.queries import get_metrics_series

    _exp(db_conn, "e1")
    _series(db_conn, "e1", "loss", [3.0, 1.0, 2.0])
    db_conn.commit()

    out = get_metrics_series(db_conn, "e1", max_points=500)
    assert [p["value"] for p in out["loss"]] == [3.0, 1.0, 2.0]
    assert [p["step"] for p in out["loss"]] == [0, 1, 2]


def test_long_series_is_bounded(db_conn):
    from exptrack.core.queries import get_metrics_series

    _exp(db_conn, "e2")
    _series(db_conn, "e2", "loss", range(50_000))
    db_conn.commit()

    out = get_metrics_series(db_conn, "e2", max_points=500)
    assert 0 < len(out["loss"]) <= 500


def test_endpoints_and_extremes_are_exact(db_conn):
    """A spike must survive downsampling — that is the whole point of min/max
    bucketing over every-Nth sampling — and the final value read off the chart
    has to be the run's actual last value."""
    from exptrack.core.queries import get_metrics_series

    _exp(db_conn, "e3")
    vals = [1.0] * 20_000
    vals[0] = 5.0            # first
    vals[7_777] = -99.0      # a lone trough mid-run
    vals[12_345] = 99.0      # a lone spike mid-run
    vals[-1] = 7.0           # last
    _series(db_conn, "e3", "loss", vals)
    db_conn.commit()

    pts = get_metrics_series(db_conn, "e3", max_points=500)["loss"]
    assert pts[0]["value"] == 5.0 and pts[0]["step"] == 0
    assert pts[-1]["value"] == 7.0 and pts[-1]["step"] == 19_999
    assert min(p["value"] for p in pts) == -99.0, "trough lost in downsampling"
    assert max(p["value"] for p in pts) == 99.0, "spike lost in downsampling"
    # And the spike keeps its own x position, not its bucket's.
    assert next(p["step"] for p in pts if p["value"] == 99.0) == 12_345


def test_points_are_chronological(db_conn):
    from exptrack.core.queries import get_metrics_series

    _exp(db_conn, "e4")
    _series(db_conn, "e4", "loss", [(i * 7919) % 1000 for i in range(20_000)])
    db_conn.commit()

    pts = get_metrics_series(db_conn, "e4", max_points=500)["loss"]
    steps = [p["step"] for p in pts]
    assert steps == sorted(steps)


def test_flat_series_does_not_blow_up(db_conn):
    """Every point ties for both min and max of its bucket. Selecting on
    `value = MIN(value)` would return the entire series here; ranking within
    the bucket is what bounds it."""
    from exptrack.core.queries import get_metrics_series

    _exp(db_conn, "e5")
    _series(db_conn, "e5", "loss", [1.0] * 20_000)
    db_conn.commit()

    pts = get_metrics_series(db_conn, "e5", max_points=500)["loss"]
    assert len(pts) <= 500


def test_stepless_series_is_bucketed_by_insert_order(db_conn):
    """`log_metric(k, v)` leaves every step NULL. Bucketing on step alone would
    collapse the whole run into one bucket and return two points."""
    from exptrack.core.queries import get_metrics_series

    _exp(db_conn, "e6")
    _series(db_conn, "e6", "loss", range(20_000), stepless=True)
    db_conn.commit()

    pts = get_metrics_series(db_conn, "e6", max_points=500)["loss"]
    assert len(pts) > 100, "step-less series collapsed to a handful of points"
    assert len(pts) <= 500
    assert pts[0]["value"] == 0.0
    assert pts[-1]["value"] == 19_999.0


def test_keys_are_independent(db_conn):
    from exptrack.core.queries import get_metrics_series

    _exp(db_conn, "e7")
    _series(db_conn, "e7", "big", range(5_000))
    _series(db_conn, "e7", "small", [1.0, 2.0])
    db_conn.commit()

    out = get_metrics_series(db_conn, "e7", max_points=100)
    assert len(out["big"]) <= 100
    assert [p["value"] for p in out["small"]] == [1.0, 2.0]


def test_tiny_max_points_does_not_divide_by_zero(db_conn):
    from exptrack.core.queries import get_metrics_series

    _exp(db_conn, "e8")
    _series(db_conn, "e8", "loss", range(100))
    db_conn.commit()

    for mp in (0, 1, 2, 3, 4):
        pts = get_metrics_series(db_conn, "e8", max_points=mp)["loss"]
        assert len(pts) >= 1


def test_no_metrics_is_empty(db_conn):
    from exptrack.core.queries import get_metrics_series

    _exp(db_conn, "e9")
    db_conn.commit()
    assert get_metrics_series(db_conn, "e9") == {}
