"""
exptrack/dashboard/routes/write_routes/sessions.py

Session Trees mutations: session lifecycle plus per-node operations.
"""
from __future__ import annotations


def api_session_note_node(conn, session_id: str, body: dict) -> dict:
    """Annotate a session node by id."""
    node_id = body.get("node_id", "")
    text = body.get("text", "")
    if not node_id:
        return {"error": "missing node_id"}
    row = conn.execute(
        "SELECT id, session_id FROM session_nodes WHERE id=? AND session_id=?",
        (node_id, session_id),
    ).fetchone()
    if not row:
        return {"error": "not found"}
    conn.execute("UPDATE session_nodes SET note=? WHERE id=?", (text, node_id))
    conn.commit()
    return {"ok": True}


def api_session_delete(conn, session_id: str, body: dict) -> dict:
    """Move a session to the Trash (default) or purge it permanently.

    Soft delete (`permanent` falsy) is fully recoverable via the Trash; nodes
    and linked experiments are untouched. `permanent: true` hard-deletes the
    session and its nodes (linked experiments preserved, session_node_id
    cleared)."""
    from exptrack.sessions.manager import delete_session
    permanent = bool(body.get("permanent"))
    if not delete_session(session_id, permanent=permanent):
        return {"error": "not found"}
    return {"ok": True, "permanent": permanent}


def api_session_restore(conn, session_id: str, body: dict) -> dict:
    """Restore a soft-deleted session from the Trash."""
    from exptrack.sessions.manager import restore_session
    if not restore_session(session_id):
        return {"error": "not found"}
    return {"ok": True}


def api_session_purge(conn, session_id: str, body: dict) -> dict:
    """Permanently remove a trashed session (refuses a non-trashed session)."""
    from exptrack.sessions.manager import purge_session
    if not purge_session(session_id):
        return {"error": "not in trash"}
    return {"ok": True}


def api_session_finalize(conn, session_id: str, body: dict) -> dict:
    """Graduate a session: materialize the chosen un-promoted nodes into
    standalone experiments, group every linked run under the session's study,
    then (by default) move the session to the Trash.

    Body: {node_ids?: [..], study?: str, soft_delete?: bool}. When `node_ids`
    is omitted, all recommended (un-promoted, code-bearing) nodes are used."""
    from exptrack.sessions.manager import finalize_session
    node_ids = body.get("node_ids")
    if node_ids is not None and not isinstance(node_ids, list):
        return {"error": "node_ids must be a list"}
    res = finalize_session(
        session_id,
        node_ids=node_ids,
        study=body.get("study"),
        soft_delete=bool(body.get("soft_delete", True)),
    )
    if not res.get("ok"):
        return {"error": res.get("error", "finalize failed")}
    return res


def _validate_session_node(conn, session_id: str, body: dict):
    """Pull `node_id` from the body and confirm it belongs to this session.
    Returns (node_id, None) on success or (None, error_dict) to return."""
    node_id = body.get("node_id", "")
    if not node_id:
        return None, {"error": "missing node_id"}
    row = conn.execute(
        "SELECT id FROM session_nodes WHERE id=? AND session_id=?",
        (node_id, session_id),
    ).fetchone()
    if not row:
        return None, {"error": "not found"}
    return node_id, None


def api_session_delete_node(conn, session_id: str, body: dict) -> dict:
    """Cascade-delete a single node (and descendants). Refuses to delete the
    session root. Linked experiments are preserved (session_node_id cleared)."""
    node_id, err = _validate_session_node(conn, session_id, body)
    if err:
        return err
    from exptrack.sessions.manager import delete_node
    r = delete_node(node_id)
    if not r.get("ok"):
        return {"error": r.get("error", "delete failed")}
    return {"ok": True, "nodes": r["nodes"], "experiments": r["experiments"]}


def api_session_preview_delete_node(conn, session_id: str, body: dict) -> dict:
    """Preview a node cascade-delete: counts of nodes and linked experiments."""
    node_id, err = _validate_session_node(conn, session_id, body)
    if err:
        return err
    from exptrack.sessions.manager import preview_node_delete
    return preview_node_delete(node_id) or {"error": "not found"}


def api_session_restore_node(conn, session_id: str, body: dict) -> dict:
    """Restore a soft-deleted session node and its trashed subtree."""
    node_id, err = _validate_session_node(conn, session_id, body)
    if err:
        return err
    from exptrack.sessions.manager import restore_node
    r = restore_node(node_id)
    if not r.get("ok"):
        return {"error": r.get("error", "restore failed")}
    return {"ok": True, "nodes": r["nodes"]}


def api_session_rename_node(conn, session_id: str, body: dict) -> dict:
    """Rename a session node's label."""
    node_id, err = _validate_session_node(conn, session_id, body)
    if err:
        return err
    from exptrack.sessions.manager import rename_node
    r = rename_node(node_id, body.get("label", ""))
    if not r.get("ok"):
        return {"error": r.get("error", "rename failed")}
    return {"ok": True, "label": r["label"]}


def api_session_promote_to_checkpoint(conn, session_id: str, body: dict) -> dict:
    """Promote a branch node to a checkpoint (freezing its current diff)."""
    node_id, err = _validate_session_node(conn, session_id, body)
    if err:
        return err
    from exptrack.sessions.manager import promote_to_checkpoint
    r = promote_to_checkpoint(node_id)
    if not r.get("ok"):
        return {"error": r.get("error", "promote failed")}
    return {"ok": True, "node_type": r.get("node_type")}


def api_session_link_experiment(conn, session_id: str, body: dict) -> dict:
    """Link (promote) an experiment to a session node — the dashboard equivalent
    of `%exptrack promote`. Pass an empty `exp_id` to unlink. Delegates the
    1:1-linking logic to `manager.link_experiment`."""
    node_id, err = _validate_session_node(conn, session_id, body)
    if err:
        return err
    from exptrack.sessions.manager import link_experiment
    r = link_experiment(node_id, body.get("exp_id") or "")
    if not r.get("ok"):
        return {"error": r.get("error", "link failed")}
    return {"ok": True, "linked": r.get("linked")}


def api_session_materialize_experiment(conn, session_id: str, body: dict) -> dict:
    """Create a standalone experiment from a node's captured data and link it."""
    node_id, err = _validate_session_node(conn, session_id, body)
    if err:
        return err
    from exptrack.sessions.manager import materialize_experiment
    r = materialize_experiment(node_id)
    if not r.get("ok"):
        return {"error": r.get("error", "could not create experiment"),
                "id": r.get("id")}
    return {"ok": True, "id": r.get("id"), "name": r.get("name")}


def api_session_purge_node(conn, session_id: str, body: dict) -> dict:
    """Permanently delete a trashed node and its subtree (no undo)."""
    node_id, err = _validate_session_node(conn, session_id, body)
    if err:
        return err
    from exptrack.sessions.manager import purge_node
    r = purge_node(node_id)
    if not r.get("ok"):
        return {"error": r.get("error", "purge failed")}
    return {"ok": True, "nodes": r["nodes"], "images": r.get("images", {})}


def api_session_empty_trash(conn, session_id: str, body: dict) -> dict:
    """Permanently delete every trashed node in the session (no undo)."""
    row = conn.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not row:
        return {"error": "not found"}
    from exptrack.sessions.manager import empty_trash
    r = empty_trash(session_id)
    return {"ok": True, "nodes": r["nodes"], "images": r.get("images", {})}


def api_session_end(conn, session_id: str, body: dict) -> dict:
    """Mark a session as ended (and abandon any open branches)."""
    import time
    row = conn.execute("SELECT id, status FROM sessions WHERE id=?",
                       (session_id,)).fetchone()
    if not row:
        return {"error": "not found"}
    conn.execute(
        "UPDATE session_nodes SET node_type='abandoned' "
        "WHERE session_id=? AND node_type='branch' "
        "AND id NOT IN (SELECT parent_id FROM session_nodes "
        "  WHERE session_id=? AND parent_id IS NOT NULL)",
        (session_id, session_id),
    )
    conn.execute("UPDATE sessions SET status='ended', ended_at=? WHERE id=?",
                 (time.time(), session_id))
    conn.commit()
    return {"ok": True}
