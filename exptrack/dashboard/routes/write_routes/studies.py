"""
exptrack/dashboard/routes/write_routes/studies.py

Studies and global tag operations, including the config-side rename
propagation both share.
"""
from __future__ import annotations

import json

from exptrack.core.queries import remove_tag_global

from ._shared import body_str


def _propagate_tag_change_to_config(old_tag: str, new_tag: str = ""):
    """Rename or remove a tag from todos and commands in config.json.

    If new_tag is empty, removes old_tag. Otherwise renames it.
    """
    from exptrack import config as cfg
    conf = cfg.load()
    changed = False
    for list_key in ("todos", "commands"):
        for item in conf.get(list_key, []):
            tags = item.get("tags", [])
            if old_tag in tags:
                tags.remove(old_tag)
                if new_tag and new_tag not in tags:
                    tags.append(new_tag)
                item["tags"] = tags
                changed = True
    if changed:
        cfg.save(conf)


def _propagate_study_change_to_config(old_study: str, new_study: str = ""):
    """Rename or remove a study from todos and commands in config.json."""
    from exptrack import config as cfg
    conf = cfg.load()
    changed = False
    for list_key in ("todos", "commands"):
        for item in conf.get(list_key, []):
            if item.get("study") == old_study:
                item["study"] = new_study
                changed = True
    if changed:
        cfg.save(conf)


def api_propagate_tag_rename(body: dict) -> dict:
    """Propagate a tag rename to todos/commands in config."""
    old = body_str(body, "old_tag")
    new = body_str(body, "new_tag")
    if not old:
        return {"error": "missing old_tag"}
    _propagate_tag_change_to_config(old, new)
    return {"ok": True}


def api_propagate_study_rename(body: dict) -> dict:
    """Propagate a study rename to todos/commands in config."""
    old = body_str(body, "old_study")
    new = body_str(body, "new_study")
    if not old:
        return {"error": "missing old_study"}
    _propagate_study_change_to_config(old, new)
    return {"ok": True}


def api_delete_tag_global(conn, body: dict) -> dict:
    tag = body_str(body, "tag")
    if not tag:
        return {"error": "empty tag"}
    count = remove_tag_global(conn, tag)
    conn.commit()
    _propagate_tag_change_to_config(tag)
    return {"ok": True, "deleted_from": count}


def api_create_study(conn, body: dict) -> dict:
    """Create a new study, optionally adding specified experiments to it."""
    name = body_str(body, "name")
    exp_ids = body.get("experiment_ids", [])
    if not name:
        return {"error": "empty study name"}
    from exptrack.core.queries import add_to_study
    added = 0
    for eid in exp_ids:
        studies = add_to_study(conn, eid, name)
        if studies is not None:
            added += 1
    conn.commit()
    return {"ok": True, "name": name, "added": added}


def api_add_to_study(conn, body: dict) -> dict:
    """Add an experiment to a study."""
    name = body_str(body, "study")
    exp_id = body_str(body, "experiment_id")
    if not name or not exp_id:
        return {"error": "provide study and experiment_id"}
    from exptrack.core.queries import add_to_study
    studies = add_to_study(conn, exp_id, name)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_remove_from_study(conn, body: dict) -> dict:
    """Remove an experiment from a study."""
    name = body_str(body, "study")
    exp_id = body_str(body, "experiment_id")
    if not name or not exp_id:
        return {"error": "provide study and experiment_id"}
    from exptrack.core.queries import remove_from_study
    studies = remove_from_study(conn, exp_id, name)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_delete_study(conn, body: dict) -> dict:
    """Delete a study from all experiments."""
    name = body_str(body, "name")
    if not name:
        return {"error": "empty study name"}
    from exptrack.core.queries import remove_study_global
    count = remove_study_global(conn, name)
    conn.commit()
    _propagate_study_change_to_config(name)
    return {"ok": True, "deleted_from": count}


def api_add_study(conn, exp_id: str, body: dict) -> dict:
    """Add a single study to an experiment (inline editing)."""
    from exptrack.core.queries import find_experiment, update_experiment_studies
    exp = find_experiment(conn, exp_id, "id, studies")
    if not exp:
        return {"error": "not found"}
    study = body_str(body, "study")
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
    from exptrack.core.queries import find_experiment, update_experiment_studies
    exp = find_experiment(conn, exp_id, "id, studies")
    if not exp:
        return {"error": "not found"}
    study = body_str(body, "study")
    if not study:
        return {"error": "empty study"}
    studies = json.loads(exp["studies"] or "[]")
    studies = [s for s in studies if s != study]
    update_experiment_studies(conn, exp["id"], studies)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_all_studies(conn) -> dict:
    """Get all studies with usage counts."""
    from exptrack.core.queries import get_all_studies
    return {"studies": get_all_studies(conn)}


def api_bulk_add_to_study(conn, body: dict) -> dict:
    """Add multiple experiments to a study."""
    name = body_str(body, "study")
    ids = body.get("ids", [])
    if not name:
        return {"error": "empty study name"}
    if not ids:
        return {"error": "no ids provided"}
    from exptrack.core.queries import add_to_study
    added = 0
    for eid in ids:
        studies = add_to_study(conn, eid, name)
        if studies is not None:
            added += 1
    conn.commit()
    return {"ok": True, "study": name, "added": added}
