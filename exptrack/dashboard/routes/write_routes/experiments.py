"""
exptrack/dashboard/routes/write_routes/experiments.py

Per-experiment mutations: notes, tags, rename, delete/restore,
artifacts, stage, params-adjacent extras, and manual creation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from exptrack.core.queries import find_experiment, update_experiment_tags

from ._shared import body_str


def api_add_note(conn, exp_id: str, body: dict) -> dict:
    from exptrack.core.queries import append_note
    text = body_str(body, "note")
    if not text:
        return {"error": "empty note"}
    result = append_note(conn, exp_id, text)
    if result.get("error"):
        return result
    conn.commit()
    return result


def api_add_tag(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id, "id, tags")
    if not exp:
        return {"error": "not found"}
    tag = body_str(body, "tag")
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
    new_name = body_str(body, "name")
    if not new_name:
        return {"error": "empty name"}
    old_name = exp["name"]
    # A deliberate rename clears the auto-named flag so the run stops being
    # nudged as "needs naming".
    conn.execute(
        "UPDATE experiments SET name=?, name_is_auto=0, updated_at=? WHERE id=?",
        (new_name, datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    from exptrack.core.db import rename_output_folder
    rename_output_folder(conn, exp["id"], old_name, new_name)
    conn.commit()
    return {"ok": True, "name": new_name}


def api_delete(conn, exp_id: str) -> dict:
    """Soft-delete (move to Trash). Use /delete-permanent for the destructive path."""
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    from exptrack.core.db import trash_experiment
    moved = trash_experiment(conn, exp["id"])
    conn.commit()
    return {"ok": True, "trashed": moved}


def api_restore(conn, exp_id: str) -> dict:
    """Restore a trashed experiment."""
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    from exptrack.core.db import restore_experiment
    restored = restore_experiment(conn, exp["id"])
    conn.commit()
    return {"ok": True, "restored": restored}


def api_delete_permanent(conn, exp_id: str, body: dict) -> dict:
    """Permanently delete an experiment. With delete_files=True, files on disk
    are moved to the OS Trash (recoverable in Finder/Files) with a local
    ``.exptrack/trash/`` fallback — never unlinked outright.
    """
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    delete_files = bool(body.get("delete_files", False))
    from exptrack.core.db import checkpoint_truncate, delete_experiment
    from exptrack.core.storage import free_space
    # Measured either side of the commit: SQLite moves deleted pages to the
    # file's free list rather than shrinking the file, so without reporting
    # this the UI can only say "deleted" while the database stays the same
    # size on disk — which reads as the delete having done nothing.
    free_before = free_space(conn)["bytes"]
    file_stats = delete_experiment(conn, exp["id"], delete_files=delete_files)
    conn.commit()
    freed = max(0, free_space(conn)["bytes"] - free_before)
    # A delete pushes every rewritten page through the WAL, and the
    # per-request checkpoint is PASSIVE (it must never wait on a live run), so
    # without this the WAL is left sitting at the size of what was deleted.
    checkpoint_truncate(conn)
    return {"ok": True, "deleted_files": delete_files, "file_stats": file_stats,
            "freed_bytes": freed}


def api_finish(conn, exp_id: str) -> dict:
    from exptrack.core.queries import finish_experiment
    result = finish_experiment(conn, exp_id)
    if result.get("error"):
        return result
    conn.commit()
    return result


def api_add_artifact(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    label = body_str(body, "label")
    path = body_str(body, "path")
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
    tag = body_str(body, "tag")
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
    old_tag = body_str(body, "old_tag")
    new_tag = body_str(body, "new_tag")
    if not old_tag or not new_tag:
        return {"error": "provide old_tag and new_tag"}
    tags = json.loads(exp["tags"] or "[]")
    tags = [new_tag if t == old_tag else t for t in tags]
    update_experiment_tags(conn, exp["id"], tags)
    conn.commit()
    return {"ok": True, "tags": tags}


def api_edit_notes(conn, exp_id: str, body: dict) -> dict:
    from exptrack.core.queries import replace_notes
    notes = body.get("notes", "")
    result = replace_notes(conn, exp_id, notes)
    if result.get("error"):
        return result
    conn.commit()
    return result


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


def api_set_stage(conn, exp_id: str, body: dict) -> dict:
    """Set stage number and optional stage_name for an experiment."""
    from exptrack.core.queries import update_experiment_stage
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    stage = body.get("stage")
    stage_name = body.get("stage_name", "")
    if stage is None and not stage_name:
        return {"error": "provide stage or stage_name"}
    if stage is not None:
        try:
            stage = int(stage)
        except (ValueError, TypeError):
            return {"error": "stage must be an integer"}
    update_experiment_stage(conn, exp["id"], stage, stage_name or None)
    conn.commit()
    return {"ok": True, "stage": stage, "stage_name": stage_name}
_CONFUSION_PARAM_KEY = "_confusion_matrices"


def api_save_confusion(conn, exp_id: str, body: dict) -> dict:
    """Replace the persisted list of confusion matrices for an experiment.

    Stored as a single JSON-encoded manual param so it round-trips with
    the rest of the experiment record (export, copy-to-study, etc.) and
    is hidden from the regular params table by the dashboard's `_`-prefix
    filter.
    """
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    matrices = body.get("matrices")
    if not isinstance(matrices, list):
        return {"error": "matrices must be a list"}
    payload = json.dumps({"matrices": matrices})
    conn.execute(
        "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?) "
        "ON CONFLICT(exp_id, key) DO UPDATE SET value=excluded.value, source=excluded.source",
        (exp["id"], _CONFUSION_PARAM_KEY, payload, "manual"),
    )
    conn.commit()
    return {"ok": True, "count": len(matrices)}


def api_edit_script(conn, exp_id: str, body: dict) -> dict:
    """Edit the script/notebook path for an experiment."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    script = body_str(body, "script")
    conn.execute(
        "UPDATE experiments SET script=?, updated_at=? WHERE id=?",
        (script or None, datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    conn.commit()
    return {"ok": True, "script": script}


def api_edit_command(conn, exp_id: str, body: dict) -> dict:
    """Edit the reproduce command for an experiment."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    command = body_str(body, "command")
    conn.execute(
        "UPDATE experiments SET command=?, updated_at=? WHERE id=?",
        (command or None, datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    conn.commit()
    return {"ok": True, "command": command}


def api_create_experiment(conn, body: dict) -> dict:
    """Create a manual experiment entry."""
    import uuid
    name = body_str(body, "name")
    if not name:
        return {"error": "name is required"}

    exp_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    created_at = body_str(body, "created_at") or now
    status = body_str(body, "status", "done")
    if status not in ("done", "failed", "running"):
        status = "done"

    script = body_str(body, "script") or None
    command = body_str(body, "command") or None
    notes = body_str(body, "notes") or None
    tags = body.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tags_json = json.dumps(tags) if tags else "[]"

    from exptrack.config import load as load_config
    conf = load_config()
    project = conf.get("project", "")

    conn.execute(
        """INSERT INTO experiments
           (id, project, name, status, created_at, updated_at,
            script, command, hostname, python_ver, notes, tags, studies)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (exp_id, project, name, status, created_at, now,
         script, command, None, None, notes, tags_json, "[]")
    )

    # Insert params (marked as manual since they come from the create-modal form)
    params = body.get("params", {})
    if isinstance(params, dict):
        for k, v in params.items():
            conn.execute(
                "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
                (exp_id, k, json.dumps(v), "manual")
            )

    # Insert metrics
    metrics = body.get("metrics", {})
    if isinstance(metrics, dict):
        for k, v in metrics.items():
            try:
                num_val = float(v)
            except (ValueError, TypeError):
                continue
            conn.execute(
                "INSERT INTO metrics (exp_id, key, value, step, ts, source) VALUES (?,?,?,0,?,?)",
                (exp_id, k, num_val, now, "manual")
            )

    conn.commit()
    return {"ok": True, "id": exp_id}


def api_log_path(conn, exp_id: str, body: dict) -> dict:
    """Manage log paths for an experiment (add/edit/delete).

    Stored in experiments.log_paths as a JSON array of strings.
    """
    exp = find_experiment(conn, exp_id, "id, log_paths")
    if not exp:
        return {"error": "not found"}
    action = body.get("action", "")
    paths = json.loads(exp["log_paths"] or "[]")

    if action == "add":
        path = body_str(body, "path")
        if not path:
            return {"error": "empty path"}
        if path not in paths:
            paths.append(path)
    elif action == "delete":
        index = body.get("index", -1)
        if 0 <= index < len(paths):
            paths.pop(index)
    elif action == "edit":
        index = body.get("index", -1)
        path = body_str(body, "path")
        if 0 <= index < len(paths) and path:
            paths[index] = path
    else:
        return {"error": "invalid action"}

    conn.execute(
        "UPDATE experiments SET log_paths=?, updated_at=? WHERE id=?",
        (json.dumps(paths), datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    conn.commit()
    return {"ok": True, "paths": paths}


def api_image_path(conn, exp_id: str, body: dict) -> dict:
    """Manage image paths for an experiment (add/edit/delete).

    Stored in experiments.image_paths as a JSON array of strings.
    """
    exp = find_experiment(conn, exp_id, "id, image_paths")
    if not exp:
        return {"error": "not found"}
    action = body.get("action", "")
    paths = json.loads(exp["image_paths"] or "[]")

    if action == "add":
        path = body_str(body, "path")
        if not path:
            return {"error": "empty path"}
        if path not in paths:
            paths.append(path)
    elif action == "delete":
        index = body.get("index", -1)
        if 0 <= index < len(paths):
            paths.pop(index)
    elif action == "edit":
        index = body.get("index", -1)
        path = body_str(body, "path")
        if 0 <= index < len(paths) and path:
            paths[index] = path
    else:
        return {"error": "invalid action"}

    conn.execute(
        "UPDATE experiments SET image_paths=?, updated_at=? WHERE id=?",
        (json.dumps(paths), datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    conn.commit()
    return {"ok": True, "paths": paths}
