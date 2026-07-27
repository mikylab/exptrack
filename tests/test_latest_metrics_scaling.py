"""Guards for the experiment-list metric queries.

`get_latest_metrics*` used to find each key's last point with a *correlated*
subquery (`WHERE COALESCE(step,0) = (SELECT MAX(...) WHERE m2.exp_id=m.exp_id
AND m2.key=m.key)`), plus a second correlated subquery for the distinct-source
count. Both re-scan a whole (exp_id, key) group once per row *in* that group,
so the cost grows with the square of points-per-metric. A project with ~70 runs
x 5 keys x 2k points (680k rows — an ordinary size for real training runs) hung
`/api/experiments` indefinitely, leaving the dashboard showing its headline
stats above a permanently empty table.

The scaling test measures SQLite VM opcodes rather than wall-clock, so it is
deterministic and can't flake on a busy machine.
"""
from __future__ import annotations


def _exp(conn, exp_id):
    conn.execute(
        "INSERT INTO experiments (id, name, created_at, updated_at) "
        "VALUES (?,'n','2026-01-01','2026-01-01')", (exp_id,))


def _series(conn, exp_id, key, n, source="auto"):
    conn.executemany(
        "INSERT INTO metrics (exp_id, key, value, step, ts, source) VALUES (?,?,?,?,?,?)",
        [(exp_id, key, float(s), s, f"2026-01-01T00:00:{s % 60:02d}", source)
         for s in range(n)],
    )


def _opcodes(conn, fn):
    """Count SQLite VM steps executed by `fn` — a machine-independent proxy for
    how much work the query plan actually does."""
    count = 0

    def tick():
        nonlocal count
        count += 1
        return 0

    conn.set_progress_handler(tick, 1)
    try:
        fn()
    finally:
        conn.set_progress_handler(None, 1)
    return count


def test_latest_metrics_scales_linearly_with_points(db_conn):
    """Doubling the points per metric must not quadruple the work.

    Under the old correlated-subquery plan this ratio was ~4x (quadratic); the
    windowed plan is ~2x. The 3.0 threshold sits between the two, so a
    regression to a per-row rescan fails here regardless of hardware.
    """
    from exptrack.core.queries import get_latest_metrics_with_source_batch

    _exp(db_conn, "small")
    _exp(db_conn, "big")
    _series(db_conn, "small", "loss", 400)
    _series(db_conn, "big", "loss", 800)
    db_conn.commit()

    small = _opcodes(db_conn, lambda: get_latest_metrics_with_source_batch(db_conn, ["small"]))
    big = _opcodes(db_conn, lambda: get_latest_metrics_with_source_batch(db_conn, ["big"]))

    assert small > 0 and big > 0
    assert big < small * 3.0, (
        f"work grew {big / small:.1f}x for 2x the data — the per-row rescan is back"
    )


def test_latest_value_wins_per_key(db_conn):
    from exptrack.core.queries import get_latest_metrics

    _exp(db_conn, "e1")
    _series(db_conn, "e1", "loss", 50)
    _series(db_conn, "e1", "acc", 10)
    db_conn.commit()

    assert get_latest_metrics(db_conn, "e1") == {"loss": 49.0, "acc": 9.0}


def test_stepless_metrics_use_insert_order(db_conn):
    """Every step is NULL for the common `log_metric(k, v)` case, so the tie is
    broken by ts then rowid — the genuinely last-logged point."""
    from exptrack.core.queries import get_latest_metrics

    _exp(db_conn, "e2")
    for v in (0.9, 0.5, 0.7):
        db_conn.execute(
            "INSERT INTO metrics (exp_id, key, value, step, ts) "
            "VALUES ('e2','loss',?,NULL,'2026-01-01T00:00:00')", (v,))
    db_conn.commit()

    assert get_latest_metrics(db_conn, "e2") == {"loss": 0.7}


def test_mixed_sources_flagged(db_conn):
    from exptrack.core.queries import get_latest_metrics_with_source

    _exp(db_conn, "e3")
    _series(db_conn, "e3", "loss", 5, source="auto")
    db_conn.execute(
        "INSERT INTO metrics (exp_id, key, value, step, ts, source) "
        "VALUES ('e3','loss',0.1,99,'2026-01-01T00:00:00','manual')")
    _series(db_conn, "e3", "acc", 5, source="auto")
    db_conn.commit()

    out = get_latest_metrics_with_source(db_conn, "e3")
    assert out["loss"]["source"] == "mixed"
    assert out["loss"]["value"] == 0.1
    assert out["acc"]["source"] == "auto"


def test_batch_matches_single(db_conn):
    """The batched form is what the experiment list uses; it must agree with
    the per-experiment form it replaced."""
    from exptrack.core.queries import (
        get_latest_metrics_with_source,
        get_latest_metrics_with_source_batch,
    )

    for eid in ("a", "b", "c"):
        _exp(db_conn, eid)
    _series(db_conn, "a", "loss", 20)
    _series(db_conn, "b", "loss", 5, source="pipeline")
    _series(db_conn, "b", "acc", 7)
    db_conn.commit()   # "c" logs nothing

    batch = get_latest_metrics_with_source_batch(db_conn, ["a", "b", "c"])
    assert batch == {eid: get_latest_metrics_with_source(db_conn, eid)
                     for eid in ("a", "b", "c")}
    assert batch["c"] == {}


def test_empty_batch_is_empty(db_conn):
    from exptrack.core.queries import get_latest_metrics_with_source_batch

    assert get_latest_metrics_with_source_batch(db_conn, []) == {}
