"""
exptrack/dashboard/routes/write_routes/metrics.py

Metric and result rows: log, edit, rename, delete.
"""
from __future__ import annotations

from datetime import datetime, timezone

from exptrack.core.queries import find_experiment

from ._shared import body_str


def api_log_result(conn, exp_id: str, body: dict) -> dict:
    """Log a manual result. Routes to metrics table with source='manual'."""
    body = dict(body)
    body.setdefault("source", "manual")
    return api_log_metric(conn, exp_id, body)


def api_log_metric(conn, exp_id: str, body: dict) -> dict:
    """Log a metric value. All dashboard-logged values go to the metrics table.

    Accepts optional step. If step is omitted or empty, auto-increments from
    the highest existing step for that key.
    """
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body_str(body, "key")
    value = body_str(body, "value")
    if not key or not value:
        return {"error": "provide key and value"}
    try:
        num_val = float(value)
    except ValueError:
        return {"error": "value must be a number"}

    ts = datetime.now(timezone.utc).isoformat()

    # Use explicit step if provided, otherwise auto-increment
    step_raw = body.get("step", "")
    if step_raw is not None and str(step_raw).strip() != "":
        try:
            step = int(step_raw)
        except (ValueError, TypeError):
            return {"error": "step must be an integer"}
    else:
        row = conn.execute(
            "SELECT MAX(COALESCE(step, -1)) as max_step, COUNT(*) as cnt FROM metrics WHERE exp_id=? AND key=?",
            (exp["id"], key)
        ).fetchone()
        max_step = row["max_step"] if row and row["max_step"] is not None else -1
        cnt = row["cnt"] if row else 0
        # Use whichever is higher: max explicit step + 1, or total point count
        # This handles auto metrics with NULL steps (count-based) and explicit steps
        step = max(max_step + 1, cnt)

    source = body.get("source", "manual")

    # Never allow a manual metric to overwrite an auto-captured point at the same step
    if source == "manual":
        auto_row = conn.execute(
            "SELECT 1 FROM metrics WHERE exp_id=? AND key=? AND step=? AND (source IS NULL OR source != 'manual') LIMIT 1",
            (exp["id"], key, step)
        ).fetchone()
        if auto_row:
            # Find the next available step after all existing data
            max_row = conn.execute(
                "SELECT MAX(COALESCE(step, -1)) as ms, COUNT(*) as cnt FROM metrics WHERE exp_id=? AND key=?",
                (exp["id"], key)
            ).fetchone()
            next_step = max(max_row["ms"] + 1, max_row["cnt"]) if max_row else step + 1
            return {"error": f"step {step} already has auto data — try step {next_step} or higher"}

    conn.execute(
        "INSERT INTO metrics (exp_id, key, value, step, ts, source) VALUES (?,?,?,?,?,?)",
        (exp["id"], key, num_val, step, ts, source)
    )
    conn.commit()
    return {"ok": True, "key": key, "value": num_val, "step": step}


def api_delete_result(conn, exp_id: str, body: dict) -> dict:
    """Delete a manually logged result."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body_str(body, "key")
    if not key:
        return {"error": "provide key"}

    # Delete from metrics table (unified storage)
    conn.execute(
        "DELETE FROM metrics WHERE exp_id=? AND key=? AND source='manual'",
        (exp["id"], key)
    )
    # Also clean up any legacy _result:* param entries
    conn.execute(
        "DELETE FROM params WHERE exp_id=? AND key=?",
        (exp["id"], f"_result:{key}")
    )
    conn.commit()
    return {"ok": True}


def api_edit_result(conn, exp_id: str, body: dict) -> dict:
    """Edit a manually logged result value."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body_str(body, "key")
    value = body_str(body, "value")
    if not key or not value:
        return {"error": "provide key and value"}
    try:
        num_val = float(value)
    except ValueError:
        return {"error": "value must be a number"}

    ts = datetime.now(timezone.utc).isoformat()
    # Delete old manual entry and insert new one
    conn.execute(
        "DELETE FROM metrics WHERE exp_id=? AND key=? AND source='manual'",
        (exp["id"], key)
    )
    conn.execute(
        "INSERT INTO metrics (exp_id, key, value, step, ts, source) "
        "VALUES (?,?,?,0,?,?)",
        (exp["id"], key, num_val, ts, "manual")
    )
    # Clean up any legacy _result:* param
    conn.execute(
        "DELETE FROM params WHERE exp_id=? AND key=?",
        (exp["id"], f"_result:{key}")
    )
    conn.commit()
    return {"ok": True, "key": key, "value": num_val}


def api_delete_metric(conn, exp_id: str, body: dict) -> dict:
    """Delete metric data points. Supports deleting last step, a specific step, or all.

    body.mode: "last" (default) | "step" | "all"
    body.key: metric key (required)
    body.step: step number (required when mode="step")
    """
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body_str(body, "key")
    if not key:
        return {"error": "provide key"}

    mode = body.get("mode", "last")

    if mode == "all":
        conn.execute(
            "DELETE FROM metrics WHERE exp_id=? AND key=?",
            (exp["id"], key)
        )
    elif mode == "step":
        step = body.get("step")
        if step is None:
            return {"error": "provide step number"}
        conn.execute(
            "DELETE FROM metrics WHERE exp_id=? AND key=? AND step=?",
            (exp["id"], key, int(step))
        )
    else:
        # Delete just the last (highest step) entry
        conn.execute("""
            DELETE FROM metrics WHERE id = (
                SELECT id FROM metrics WHERE exp_id=? AND key=?
                ORDER BY COALESCE(step, 0) DESC, id DESC LIMIT 1
            )
        """, (exp["id"], key))

    conn.commit()
    remaining = conn.execute(
        "SELECT COUNT(*) as n FROM metrics WHERE exp_id=? AND key=?",
        (exp["id"], key)
    ).fetchone()["n"]
    return {"ok": True, "remaining": remaining}


def api_rename_metric(conn, exp_id: str, body: dict) -> dict:
    """Rename a metric key (e.g. 'loss' -> 'train/loss')."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    old_key = body_str(body, "old_key")
    new_key = body_str(body, "new_key")
    if not old_key or not new_key:
        return {"error": "provide old_key and new_key"}
    if old_key == new_key:
        return {"ok": True}
    # Check old key exists
    count = conn.execute(
        "SELECT COUNT(*) as n FROM metrics WHERE exp_id=? AND key=?",
        (exp["id"], old_key)
    ).fetchone()["n"]
    if not count:
        return {"error": f"metric '{old_key}' not found"}
    conn.execute(
        "UPDATE metrics SET key=? WHERE exp_id=? AND key=?",
        (new_key, exp["id"], old_key)
    )
    conn.commit()
    return {"ok": True, "old_key": old_key, "new_key": new_key}
