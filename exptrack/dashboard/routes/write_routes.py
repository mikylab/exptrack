"""
exptrack/dashboard/routes/write_routes.py — Mutation API endpoints

POST endpoints for notes, tags, rename, delete, finish, artifacts, groups.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ...core.queries import find_experiment, update_experiment_tags, remove_tag_global


def api_add_note(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id, "id, notes")
    if not exp:
        return {"error": "not found"}
    text = body.get("note", "").strip()
    if not text:
        return {"error": "empty note"}
    existing = exp["notes"] or ""
    new_notes = (existing + "\n" + text).strip() if existing else text
    conn.execute(
        "UPDATE experiments SET notes=?, updated_at=? WHERE id=?",
        (new_notes, datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    conn.commit()
    return {"ok": True, "notes": new_notes}


def api_add_tag(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id, "id, tags")
    if not exp:
        return {"error": "not found"}
    tag = body.get("tag", "").strip()
    if not tag:
        return {"error": "empty tag"}
    tags = json.loads(exp["tags"] or "[]")
    if tag not in tags:
        tags.append(tag)
    update_experiment_tags(conn, exp["id"], tags)
    conn.commit()
    return {"ok": True, "tags": tags}


def api_rename(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id, "id, name")
    if not exp:
        return {"error": "not found"}
    new_name = body.get("name", "").strip()
    if not new_name:
        return {"error": "empty name"}
    old_name = exp["name"]
    conn.execute(
        "UPDATE experiments SET name=?, updated_at=? WHERE id=?",
        (new_name, datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    from ...core.db import rename_output_folder
    rename_output_folder(conn, exp["id"], old_name, new_name)
    conn.commit()
    return {"ok": True, "name": new_name}


def api_delete(conn, exp_id: str) -> dict:
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    from ...core.db import delete_experiment
    delete_experiment(conn, exp["id"])
    conn.commit()
    return {"ok": True}


def api_finish(conn, exp_id: str) -> dict:
    exp = conn.execute(
        "SELECT id, status, created_at FROM experiments WHERE id LIKE ?",
        (exp_id + "%",)
    ).fetchone()
    if not exp:
        return {"error": "not found"}
    if exp["status"] == "done":
        return {"ok": True, "status": "done", "message": "already done"}
    now = datetime.now(timezone.utc).isoformat()
    duration = (datetime.fromisoformat(now) -
                datetime.fromisoformat(exp["created_at"])).total_seconds()
    conn.execute("""
        UPDATE experiments SET status='done', updated_at=?, duration_s=? WHERE id=?
    """, (now, duration, exp["id"]))
    conn.commit()
    return {"ok": True, "status": "done", "duration_s": duration}


def api_add_artifact(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    label = body.get("label", "").strip()
    path = body.get("path", "").strip()
    if not label and not path:
        return {"error": "provide label or path"}
    if not label:
        label = Path(path).name
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO artifacts (exp_id, label, path, created_at) VALUES (?,?,?,?)",
        (exp["id"], label, path, ts)
    )
    conn.commit()
    return {"ok": True, "label": label, "path": path}


def api_delete_tag(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id, "id, tags")
    if not exp:
        return {"error": "not found"}
    tag = body.get("tag", "").strip()
    if not tag:
        return {"error": "empty tag"}
    tags = json.loads(exp["tags"] or "[]")
    tags = [t for t in tags if t != tag]
    update_experiment_tags(conn, exp["id"], tags)
    conn.commit()
    return {"ok": True, "tags": tags}


def api_edit_tag(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id, "id, tags")
    if not exp:
        return {"error": "not found"}
    old_tag = body.get("old_tag", "").strip()
    new_tag = body.get("new_tag", "").strip()
    if not old_tag or not new_tag:
        return {"error": "provide old_tag and new_tag"}
    tags = json.loads(exp["tags"] or "[]")
    tags = [new_tag if t == old_tag else t for t in tags]
    update_experiment_tags(conn, exp["id"], tags)
    conn.commit()
    return {"ok": True, "tags": tags}


def api_edit_notes(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    notes = body.get("notes", "")
    conn.execute(
        "UPDATE experiments SET notes=?, updated_at=? WHERE id=?",
        (notes, datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    conn.commit()
    return {"ok": True, "notes": notes}


def api_delete_artifact(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    label = body.get("label", "")
    path = body.get("path", "")
    if not label and not path:
        return {"error": "provide label or path"}
    if label and path:
        conn.execute(
            "DELETE FROM artifacts WHERE exp_id=? AND label=? AND path=?",
            (exp["id"], label, path)
        )
    elif label:
        conn.execute(
            "DELETE FROM artifacts WHERE exp_id=? AND label=?",
            (exp["id"], label)
        )
    else:
        conn.execute(
            "DELETE FROM artifacts WHERE exp_id=? AND path=?",
            (exp["id"], path)
        )
    conn.commit()
    return {"ok": True}


def api_edit_artifact(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    old_label = body.get("old_label", "")
    old_path = body.get("old_path", "")
    new_label = body.get("new_label", "")
    new_path = body.get("new_path", "")
    if not old_label and not old_path:
        return {"error": "provide old_label or old_path"}
    if old_label and old_path:
        conn.execute(
            "UPDATE artifacts SET label=?, path=? WHERE exp_id=? AND label=? AND path=?",
            (new_label or old_label, new_path or old_path, exp["id"], old_label, old_path)
        )
    elif old_label:
        conn.execute(
            "UPDATE artifacts SET label=?, path=? WHERE exp_id=? AND label=?",
            (new_label or old_label, new_path or old_path, exp["id"], old_label)
        )
    else:
        conn.execute(
            "UPDATE artifacts SET label=?, path=? WHERE exp_id=? AND path=?",
            (new_label or old_label, new_path or old_path, exp["id"], old_path)
        )
    conn.commit()
    return {"ok": True}


def api_bulk_delete(conn, body: dict) -> dict:
    ids = body.get("ids", [])
    if not ids:
        return {"error": "no ids provided"}
    from ...core.db import delete_experiment
    deleted = 0
    for eid in ids:
        exp = find_experiment(conn, eid)
        if exp:
            delete_experiment(conn, exp["id"])
            deleted += 1
    conn.commit()
    return {"ok": True, "deleted": deleted}


def api_bulk_export(conn, body: dict) -> list:
    from .read_routes import api_export
    ids = body.get("ids", [])
    fmt = body.get("format", "json")
    if not ids:
        return [{"error": "no ids provided"}]
    results = []
    for eid in ids:
        data = api_export(conn, eid, {"format": fmt})
        if not data.get("error"):
            results.append(data)
    return results


def api_delete_tag_global(conn, body: dict) -> dict:
    tag = body.get("tag", "").strip()
    if not tag:
        return {"error": "empty tag"}
    count = remove_tag_global(conn, tag)
    conn.commit()
    return {"ok": True, "deleted_from": count}


def api_set_timezone(body: dict) -> dict:
    from ...config import load, save
    tz = body.get("timezone", "").strip()
    valid = {
        "", "UTC", "America/New_York", "America/Chicago", "America/Denver",
        "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Europe/Paris",
        "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata", "Australia/Sydney",
    }
    if tz not in valid:
        return {"error": "invalid timezone"}
    conf = load()
    conf["timezone"] = tz
    save(conf)
    return {"ok": True, "timezone": tz}


# ── Group management ─────────────────────────────────────────────────────────

def api_create_group(conn, body: dict) -> dict:
    """Create a new group by adding group/ tag to specified experiments."""
    name = body.get("name", "").strip()
    exp_ids = body.get("experiment_ids", [])
    if not name:
        return {"error": "empty group name"}
    from ...core.queries import add_to_group
    added = 0
    for eid in exp_ids:
        tags = add_to_group(conn, eid, name)
        if tags:
            added += 1
    conn.commit()
    return {"ok": True, "name": name, "added": added}


def api_add_to_group(conn, body: dict) -> dict:
    """Add an experiment to an existing group."""
    name = body.get("group", "").strip()
    exp_id = body.get("experiment_id", "").strip()
    if not name or not exp_id:
        return {"error": "provide group and experiment_id"}
    from ...core.queries import add_to_group
    tags = add_to_group(conn, exp_id, name)
    conn.commit()
    return {"ok": True, "tags": tags}


def api_remove_from_group(conn, body: dict) -> dict:
    """Remove an experiment from a group."""
    name = body.get("group", "").strip()
    exp_id = body.get("experiment_id", "").strip()
    if not name or not exp_id:
        return {"error": "provide group and experiment_id"}
    from ...core.queries import remove_from_group
    tags = remove_from_group(conn, exp_id, name)
    conn.commit()
    return {"ok": True, "tags": tags}


def api_delete_group(conn, body: dict) -> dict:
    """Delete a group (remove group/ tag from all experiments)."""
    name = body.get("name", "").strip()
    if not name:
        return {"error": "empty group name"}
    tag = f"group/{name}"
    count = remove_tag_global(conn, tag)
    conn.commit()
    return {"ok": True, "deleted_from": count}
