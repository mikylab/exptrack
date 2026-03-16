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
    from ...core.queries import append_note
    text = body.get("note", "").strip()
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
    from ...core.queries import finish_experiment
    result = finish_experiment(conn, exp_id)
    if result.get("error"):
        return result
    conn.commit()
    return result


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
    from ...core.queries import replace_notes
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


def api_bulk_export(conn, body: dict) -> dict | list:
    from ...core.queries import (get_batch_export_data, format_export_csv,
                                 format_export_markdown)
    ids = body.get("ids", [])
    fmt = body.get("format", "json")
    if not ids:
        return {"error": "no ids provided"}
    batch = get_batch_export_data(conn, exp_ids=ids)
    if not batch:
        return {"error": "no experiments found"}
    if fmt in ("csv", "tsv"):
        delimiter = "\t" if fmt == "tsv" else ","
        return {"format": fmt, "content": format_export_csv(batch, delimiter=delimiter)}
    elif fmt == "markdown":
        md_parts = [format_export_markdown(d) for d in batch]
        return {"format": "markdown", "content": "\n\n---\n\n".join(md_parts)}
    else:
        return batch


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


# ── Study management ─────────────────────────────────────────────────────────

def api_create_study(conn, body: dict) -> dict:
    """Create a new study, optionally adding specified experiments to it."""
    name = body.get("name", "").strip()
    exp_ids = body.get("experiment_ids", [])
    if not name:
        return {"error": "empty study name"}
    from ...core.queries import add_to_study
    added = 0
    for eid in exp_ids:
        studies = add_to_study(conn, eid, name)
        if studies is not None:
            added += 1
    conn.commit()
    return {"ok": True, "name": name, "added": added}


def api_add_to_study(conn, body: dict) -> dict:
    """Add an experiment to a study."""
    name = body.get("study", "").strip()
    exp_id = body.get("experiment_id", "").strip()
    if not name or not exp_id:
        return {"error": "provide study and experiment_id"}
    from ...core.queries import add_to_study
    studies = add_to_study(conn, exp_id, name)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_remove_from_study(conn, body: dict) -> dict:
    """Remove an experiment from a study."""
    name = body.get("study", "").strip()
    exp_id = body.get("experiment_id", "").strip()
    if not name or not exp_id:
        return {"error": "provide study and experiment_id"}
    from ...core.queries import remove_from_study
    studies = remove_from_study(conn, exp_id, name)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_delete_study(conn, body: dict) -> dict:
    """Delete a study from all experiments."""
    name = body.get("name", "").strip()
    if not name:
        return {"error": "empty study name"}
    from ...core.queries import remove_study_global
    count = remove_study_global(conn, name)
    conn.commit()
    return {"ok": True, "deleted_from": count}


def api_add_study(conn, exp_id: str, body: dict) -> dict:
    """Add a single study to an experiment (inline editing)."""
    from ...core.queries import find_experiment, update_experiment_studies
    exp = find_experiment(conn, exp_id, "id, studies")
    if not exp:
        return {"error": "not found"}
    study = body.get("study", "").strip()
    if not study:
        return {"error": "empty study"}
    studies = json.loads(exp["studies"] or "[]")
    if study not in studies:
        studies.append(study)
    update_experiment_studies(conn, exp["id"], studies)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_delete_exp_study(conn, exp_id: str, body: dict) -> dict:
    """Remove a single study from an experiment (inline editing)."""
    from ...core.queries import find_experiment, update_experiment_studies
    exp = find_experiment(conn, exp_id, "id, studies")
    if not exp:
        return {"error": "not found"}
    study = body.get("study", "").strip()
    if not study:
        return {"error": "empty study"}
    studies = json.loads(exp["studies"] or "[]")
    studies = [s for s in studies if s != study]
    update_experiment_studies(conn, exp["id"], studies)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_all_studies(conn) -> dict:
    """Get all studies with usage counts."""
    from ...core.queries import get_all_studies
    return {"studies": get_all_studies(conn)}


def api_bulk_add_to_study(conn, body: dict) -> dict:
    """Add multiple experiments to a study."""
    name = body.get("study", "").strip()
    ids = body.get("ids", [])
    if not name:
        return {"error": "empty study name"}
    if not ids:
        return {"error": "no ids provided"}
    from ...core.queries import add_to_study
    added = 0
    for eid in ids:
        studies = add_to_study(conn, eid, name)
        if studies is not None:
            added += 1
    conn.commit()
    return {"ok": True, "study": name, "added": added}


def api_set_stage(conn, exp_id: str, body: dict) -> dict:
    """Set stage number and optional stage_name for an experiment."""
    from ...core.queries import update_experiment_stage
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


def api_manage_result_types(body: dict) -> dict:
    """Add/remove result types from project config."""
    from ...config import load, save, reload
    conf = load()
    default_types = ["accuracy", "loss", "auroc", "f1", "precision", "recall",
                     "mse", "mae", "r2", "perplexity", "bleu"]
    types = list(conf.get("result_types", default_types))

    action = body.get("action", "")
    if action == "add":
        name = body.get("name", "").strip().lower()
        if not name:
            return {"error": "empty name"}
        if name not in types:
            types.append(name)
    elif action == "remove":
        index = body.get("index", -1)
        if 0 <= index < len(types):
            types.pop(index)
    else:
        return {"error": "invalid action"}

    conf["result_types"] = types
    save(conf)
    reload()
    return {"ok": True, "types": types}


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
    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body.get("key", "").strip()
    value = body.get("value", "").strip()
    if not key or not value:
        return {"error": "provide key and value"}
    try:
        num_val = float(value)
    except ValueError:
        return {"error": "value must be a number"}

    from datetime import datetime, timezone
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
            "SELECT MAX(COALESCE(step, -1)) as max_step FROM metrics WHERE exp_id=? AND key=?",
            (exp["id"], key)
        ).fetchone()
        step = (row["max_step"] + 1) if row and row["max_step"] is not None else 0

    source = body.get("source", "manual")
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
    key = body.get("key", "").strip()
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
    key = body.get("key", "").strip()
    value = body.get("value", "").strip()
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
        "VALUES (?,?,?,NULL,?,?)",
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
    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body.get("key", "").strip()
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
        path = body.get("path", "").strip()
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
        path = body.get("path", "").strip()
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
        path = body.get("path", "").strip()
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
        path = body.get("path", "").strip()
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
