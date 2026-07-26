"""
exptrack/dashboard/routes/write_routes/params.py

Param rows: add, edit, rename, delete (manual params only).
"""
from __future__ import annotations

import json

from exptrack.core.queries import find_experiment

from ._shared import body_str


def _parse_param_value(value):
    """Try to JSON-decode (so users can type numbers/bools/lists), fall back to string."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return s
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return s


def api_add_param(conn, exp_id: str, body: dict) -> dict:
    """Add a new manual param. Refuses to overwrite an existing param of any
    source — to change an existing value, double-click to edit; to replace an
    auto param, pick a different key."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body_str(body, "key")
    if not key:
        return {"error": "provide key"}
    if key.startswith("_"):
        return {"error": "keys starting with '_' are reserved"}
    value = _parse_param_value(body.get("value", ""))
    row = conn.execute(
        "SELECT COALESCE(source, 'auto') as source FROM params WHERE exp_id=? AND key=?",
        (exp["id"], key)
    ).fetchone()
    if row:
        if row["source"] == "auto":
            return {"error": f"param '{key}' was auto-captured and is read-only — pick a different key"}
        return {"error": f"param '{key}' already exists — double-click to edit it"}
    conn.execute(
        "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
        (exp["id"], key, json.dumps(value), "manual")
    )
    conn.commit()
    return {"ok": True, "key": key, "value": value}


def api_edit_param(conn, exp_id: str, body: dict) -> dict:
    """Update the value of an existing manual param."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body_str(body, "key")
    if not key:
        return {"error": "provide key"}
    row = conn.execute(
        "SELECT COALESCE(source, 'auto') as source FROM params WHERE exp_id=? AND key=?",
        (exp["id"], key)
    ).fetchone()
    if not row:
        return {"error": f"param '{key}' not found"}
    if row["source"] == "auto":
        return {"error": f"param '{key}' is auto-captured and cannot be edited"}
    value = _parse_param_value(body.get("value", ""))
    conn.execute(
        "UPDATE params SET value=? WHERE exp_id=? AND key=?",
        (json.dumps(value), exp["id"], key)
    )
    conn.commit()
    return {"ok": True, "key": key, "value": value}


def api_delete_param(conn, exp_id: str, body: dict) -> dict:
    """Delete a manual param. Auto-captured params cannot be deleted."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body_str(body, "key")
    if not key:
        return {"error": "provide key"}
    row = conn.execute(
        "SELECT COALESCE(source, 'auto') as source FROM params WHERE exp_id=? AND key=?",
        (exp["id"], key)
    ).fetchone()
    if not row:
        return {"error": f"param '{key}' not found"}
    if row["source"] == "auto":
        return {"error": f"param '{key}' is auto-captured and cannot be deleted"}
    conn.execute(
        "DELETE FROM params WHERE exp_id=? AND key=?",
        (exp["id"], key)
    )
    conn.commit()
    return {"ok": True}


def api_rename_param(conn, exp_id: str, body: dict) -> dict:
    """Rename a manual param key."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    old_key = body_str(body, "old_key")
    new_key = body_str(body, "new_key")
    if not old_key or not new_key:
        return {"error": "provide old_key and new_key"}
    if old_key == new_key:
        return {"ok": True, "old_key": old_key, "new_key": new_key}
    if new_key.startswith("_"):
        return {"error": "keys starting with '_' are reserved"}
    row = conn.execute(
        "SELECT COALESCE(source, 'auto') as source FROM params WHERE exp_id=? AND key=?",
        (exp["id"], old_key)
    ).fetchone()
    if not row:
        return {"error": f"param '{old_key}' not found"}
    if row["source"] == "auto":
        return {"error": f"param '{old_key}' is auto-captured and cannot be renamed"}
    collision = conn.execute(
        "SELECT 1 FROM params WHERE exp_id=? AND key=?",
        (exp["id"], new_key)
    ).fetchone()
    if collision:
        return {"error": f"param '{new_key}' already exists"}
    conn.execute(
        "UPDATE params SET key=? WHERE exp_id=? AND key=?",
        (new_key, exp["id"], old_key)
    )
    conn.commit()
    return {"ok": True, "old_key": old_key, "new_key": new_key}
