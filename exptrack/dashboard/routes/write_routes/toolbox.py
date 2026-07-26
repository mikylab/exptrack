"""
exptrack/dashboard/routes/write_routes/toolbox.py

Todos and saved commands, stored as config lists.
"""
from __future__ import annotations

from ._shared import body_str


def _config_list_add(list_key: str, id_prefix: str, body: dict,
                     required_field: str, extra_fields: dict) -> dict:
    """Generic add to a config-stored list (todos, commands)."""
    import hashlib
    import time

    from exptrack import config as cfg
    conf = cfg.load()
    items = conf.get(list_key, [])
    value = body_str(body, required_field)
    if not value:
        return {"error": f"empty {required_field}"}
    item = {
        "id": id_prefix + hashlib.sha256(
            (value + str(time.time())).encode()).hexdigest()[:8],
        required_field: value,
        "tags": body.get("tags", []),
        "study": body.get("study", ""),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        **extra_fields,
    }
    items.append(item)
    conf[list_key] = items
    cfg.save(conf)
    return {"ok": True, list_key.rstrip("s"): item}


def _config_list_update(list_key: str, body: dict,
                        allowed_fields: list) -> dict:
    """Generic update of an item in a config-stored list."""
    import time

    from exptrack import config as cfg
    conf = cfg.load()
    items = conf.get(list_key, [])
    item = next((i for i in items if i["id"] == body.get("id", "")), None)
    if not item:
        return {"error": "not found"}
    for field in allowed_fields:
        if field in body:
            item[field] = body[field]
    item["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    cfg.save(conf)
    return {"ok": True}


def _config_list_delete(list_key: str, body: dict) -> dict:
    """Generic delete from a config-stored list."""
    from exptrack import config as cfg
    conf = cfg.load()
    rid = body.get("id", "")
    conf[list_key] = [i for i in conf.get(list_key, []) if i["id"] != rid]
    cfg.save(conf)
    return {"ok": True}


def api_add_todo(body: dict) -> dict:
    due = body_str(body, "due") if body.get("due") else ""
    return _config_list_add("todos", "t_", body, "text",
                            {"done": False, "due": due})


def api_update_todo(body: dict) -> dict:
    if "done" in body:
        body["done"] = bool(body["done"])
    return _config_list_update("todos", body,
                               ["done", "text", "tags", "study", "due"])


def api_delete_todo(body: dict) -> dict:
    return _config_list_delete("todos", body)


def api_add_command(body: dict) -> dict:
    cmd_text = body_str(body, "command")
    label = body_str(body, "label") or (
        cmd_text.split()[0] if cmd_text else "")
    return _config_list_add("commands", "c_", body, "command",
                            {"label": label})


def api_update_command(body: dict) -> dict:
    return _config_list_update("commands", body,
                               ["label", "command", "tags", "study", "values"])


def api_delete_command(body: dict) -> dict:
    return _config_list_delete("commands", body)


def api_reorder_commands(body: dict) -> dict:
    """Reorder saved commands by id. Body: {ids: [c_..., ...]}. Items not
    listed in `ids` keep their relative order at the end (so a missing id
    after a race can't drop a command)."""
    from exptrack import config as cfg
    new_ids = body.get("ids") or []
    if not isinstance(new_ids, list):
        return {"error": "ids must be a list"}
    conf = cfg.load()
    items = conf.get("commands", [])
    by_id = {c.get("id"): c for c in items}
    seen = set()
    ordered = []
    for cid in new_ids:
        c = by_id.get(cid)
        if c is not None and cid not in seen:
            ordered.append(c)
            seen.add(cid)
    # Append any commands not mentioned (defensive: don't drop them)
    for c in items:
        if c.get("id") not in seen:
            ordered.append(c)
    conf["commands"] = ordered
    cfg.save(conf)
    return {"ok": True}
