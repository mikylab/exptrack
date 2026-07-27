"""
exptrack/sessions/lifecycle.py — session- and node-level lifecycle: soft/hard
delete, restore, purge, trash listing, rename, promote-to-checkpoint, and
finalize.
"""
from __future__ import annotations

import time
from typing import Any

from ..core.db import get_db
from ._shared import (
    _CELL_SEPARATOR,
    _collect_descendants,
    _count_node_images,
    _detach_experiments,
    _node_lineage_labels,
    _session_study_name,
    _trash_node_images,
    get_current_session,
)
from .materialize import materialize_experiment


def delete_session(session_id: str, *, permanent: bool = False) -> bool:
    """Soft-delete (Trash) a session, or permanently purge it.

    Default (``permanent=False``) sets ``sessions.deleted_at`` so the session
    drops out of the live list but is fully recoverable via
    :func:`restore_session` — nodes and linked experiments are left untouched.

    ``permanent=True`` hard-deletes the session and all its nodes; linked
    experiments are preserved with their ``session_node_id`` cleared (the
    session study, if any, keeps them grouped). Returns True if a session was
    found."""
    conn = get_db()
    row = conn.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not row:
        return False
    if not permanent:
        conn.execute(
            "UPDATE sessions SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
            (time.time(), session_id),
        )
        conn.commit()
        return True
    conn.execute(
        "UPDATE experiments SET session_node_id=NULL "
        "WHERE session_node_id IN (SELECT id FROM session_nodes WHERE session_id=?)",
        (session_id,),
    )
    conn.execute("DELETE FROM session_nodes WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    return True


def restore_session(session_id: str) -> bool:
    """Undo a soft-delete: clear ``sessions.deleted_at``. Returns True if a
    trashed session was restored."""
    conn = get_db()
    cur = conn.execute(
        "UPDATE sessions SET deleted_at=NULL "
        "WHERE id=? AND deleted_at IS NOT NULL",
        (session_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def purge_session(session_id: str) -> bool:
    """Permanently remove a *trashed* session (hard delete). Refuses a session
    that isn't already in the Trash, so true removal is always a deliberate
    trash → purge two-step (matching node purge / experiment delete)."""
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM sessions WHERE id=? AND deleted_at IS NOT NULL",
        (session_id,),
    ).fetchone()
    if not row:
        return False
    return delete_session(session_id, permanent=True)


def list_trashed_sessions(conn=None) -> list[dict[str, Any]]:
    """Every soft-deleted session, most recently trashed first, with the node /
    promoted-run counts the unified Trash view shows. Backs the Sessions section
    of the global Trash."""
    conn = conn or get_db()
    rows = conn.execute(
        "SELECT s.id, s.name, s.status, s.created_at, s.deleted_at, "
        "  COUNT(DISTINCT n.id) AS nodes, "
        "  COUNT(DISTINCT e.id) AS promoted "
        "FROM sessions s "
        "LEFT JOIN session_nodes n ON n.session_id = s.id AND n.deleted_at IS NULL "
        "LEFT JOIN experiments e ON e.session_node_id = n.id AND e.deleted_at IS NULL "
        "WHERE s.deleted_at IS NOT NULL "
        "GROUP BY s.id "
        "ORDER BY s.deleted_at DESC",
    ).fetchall()
    return [dict(r) for r in rows]


def finalize_session_preview(session_id: str) -> dict[str, Any]:
    """Describe what `finalize_session` would graduate, for an interactive
    confirm UI.

    Returns each non-root, non-trashed node with its lineage, cell count, and
    whether it's *already* promoted to an experiment (`linked_exp`) or still
    un-promoted (`recommended` to materialize). The dashboard shows these as a
    checklist so the user can pick which exploratory nodes become standalone
    experiments before the session is archived."""
    conn = get_db()
    s = conn.execute(
        "SELECT id, name, status FROM sessions "
        "WHERE id=? AND deleted_at IS NULL",
        (session_id,),
    ).fetchone()
    if not s:
        return {"ok": False, "error": "session not found"}
    sep = _CELL_SEPARATOR
    rows = conn.execute(
        "SELECT id, node_type, label, cell_source "
        "FROM session_nodes "
        "WHERE session_id=? AND deleted_at IS NULL AND node_type!='root' "
        "ORDER BY seq",
        (session_id,),
    ).fetchall()
    # One pass to map each node → its linked run (avoids a SELECT per node).
    linked_by_node = {
        r["session_node_id"]: r["id"]
        for r in conn.execute(
            "SELECT e.id, e.session_node_id FROM experiments e "
            "JOIN session_nodes n ON n.id = e.session_node_id "
            "WHERE n.session_id=? AND e.deleted_at IS NULL",
            (session_id,),
        ).fetchall()
    }
    nodes: list[dict[str, Any]] = []
    for r in rows:
        linked_exp = linked_by_node.get(r["id"])
        src = r["cell_source"] or ""
        cell_count = len([c for c in src.split(sep) if c.strip()]) if src else 0
        nodes.append({
            "id": r["id"],
            "label": r["label"] or "",
            "node_type": r["node_type"],
            "lineage": _node_lineage_labels(conn, r["id"]),
            "linked_exp": linked_exp,
            "cell_count": cell_count,
            # Recommend materializing an un-promoted node that actually ran code.
            "recommended": linked_exp is None and cell_count > 0,
        })
    return {
        "ok": True,
        "session": {"id": s["id"], "name": s["name"], "status": s["status"]},
        "study": _session_study_name(conn, session_id),
        "nodes": nodes,
        "linked_count": sum(1 for n in nodes if n["linked_exp"]),
        "recommended_count": sum(1 for n in nodes if n["recommended"]),
    }


def finalize_session(session_id: str, node_ids: list[str] | None = None, *,
                     study: str | None = None,
                     soft_delete: bool = True) -> dict[str, Any]:
    """Graduate a session into self-contained, grouped experiments.

    For each selected un-promoted node (``node_ids``; defaults to every
    recommended node from :func:`finalize_session_preview`) a standalone
    experiment is materialized (full code, %%setup, plots — see
    :func:`materialize_experiment`). Every experiment linked to the session —
    the freshly materialized ones *and* any already-promoted runs — is added to
    a study named after the session (override with ``study``) so they stay
    grouped permanently. When ``soft_delete`` is true the session is then moved
    to the Trash (recoverable). Returns a summary dict."""
    conn = get_db()
    s = conn.execute(
        "SELECT id, name FROM sessions WHERE id=? AND deleted_at IS NULL",
        (session_id,),
    ).fetchone()
    if not s:
        return {"ok": False, "error": "session not found"}
    study_name = (study or "").strip() or _session_study_name(conn, session_id)

    # Resolve which nodes to materialize. Default = the recommended set:
    # un-promoted, non-root nodes that actually ran code (matches the
    # `recommended` flag in finalize_session_preview, without rebuilding it).
    if node_ids is None:
        sep = _CELL_SEPARATOR
        node_ids = [
            r["id"] for r in conn.execute(
                "SELECT n.id, n.cell_source FROM session_nodes n "
                "WHERE n.session_id=? AND n.deleted_at IS NULL "
                "AND n.node_type!='root' AND NOT EXISTS ("
                "  SELECT 1 FROM experiments e "
                "  WHERE e.session_node_id=n.id AND e.deleted_at IS NULL)",
                (session_id,),
            ).fetchall()
            if any(c.strip() for c in (r["cell_source"] or "").split(sep))
        ]

    else:
        # Caller-supplied ids: keep only nodes that actually belong to this
        # session. A stray id from another session would otherwise be
        # materialized here and filed under this session's study.
        own = {r["id"] for r in conn.execute(
            "SELECT id FROM session_nodes WHERE session_id=? AND deleted_at IS NULL",
            (session_id,),
        ).fetchall()}
        node_ids = [nid for nid in node_ids if nid in own]

    materialized: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for nid in node_ids:
        res = materialize_experiment(nid)
        if res.get("ok"):
            materialized.append({"node_id": nid, "exp_id": res["id"],
                                 "name": res.get("name", "")})
        elif res.get("id"):
            # Already linked — not an error, just nothing to do.
            continue
        else:
            errors.append({"node_id": nid, "error": res.get("error", "failed")})

    # Group *every* experiment tied to this session under the study (idempotent),
    # covering already-promoted runs and any just materialized above.
    exp_ids = [r["id"] for r in conn.execute(
        "SELECT e.id FROM experiments e "
        "JOIN session_nodes n ON n.id = e.session_node_id "
        "WHERE n.session_id=? AND e.deleted_at IS NULL",
        (session_id,),
    ).fetchall()]
    grouped = 0
    if study_name:
        from ..core.queries import add_to_study
        for eid in exp_ids:
            try:
                add_to_study(conn, eid, study_name)
                grouped += 1
            except Exception:
                pass
    conn.commit()

    deleted = False
    if soft_delete:
        deleted = delete_session(session_id)

    return {
        "ok": True,
        "study": study_name,
        "materialized": materialized,
        "errors": errors,
        "grouped": grouped,
        "deleted": deleted,
    }


def _session_root_id(conn, session_id: str) -> str | None:
    """The session's live root node id, or None."""
    row = conn.execute(
        "SELECT id FROM session_nodes WHERE session_id=? AND parent_id IS NULL "
        "AND deleted_at IS NULL ORDER BY seq LIMIT 1",
        (session_id,),
    ).fetchone()
    return row["id"] if row else None


def preview_node_delete(node_id: str) -> dict[str, Any]:
    """Count what `delete_node(node_id)` would remove. Returns
    {nodes, descendants, experiments, label, node_type} or {} if not found."""
    conn = get_db()
    row = conn.execute(
        "SELECT label, node_type, parent_id FROM session_nodes WHERE id=?",
        (node_id,),
    ).fetchone()
    if not row:
        return {}
    ids = _collect_descendants(conn, node_id)
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    exp_count = conn.execute(
        f"SELECT COUNT(*) AS c FROM experiments WHERE session_node_id IN ({placeholders})",
        ids,
    ).fetchone()["c"]
    return {
        "label": row["label"],
        "node_type": row["node_type"],
        "is_root": row["parent_id"] is None,
        "nodes": len(ids),
        "descendants": len(ids) - 1,
        "experiments": exp_count,
        "images": _count_node_images(conn, ids),
    }


def delete_node(node_id: str) -> dict[str, Any]:
    """Soft-delete (Trash) a session node and all live descendants. Refuses
    to delete the session's root. Linked experiments are preserved with their
    session_node_id cleared. Returns {ok, nodes, experiments} or
    {ok: False, error: ...}.

    The rows stay in `session_nodes` with `deleted_at` set; `build_tree` and
    the magic-side lookups filter them out, but `list_trashed_nodes` /
    `restore_node` can bring them back unchanged (cell_source, git_diff,
    note all preserved). Use `delete_session` for hard removal.

    Also clears the session manager's _current_node_id / _last_checkpoint_id
    if either points at a trashed node, so subsequent magics don't dangle.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT parent_id, session_id FROM session_nodes WHERE id=? "
        "AND deleted_at IS NULL",
        (node_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "node not found"}
    if row["parent_id"] is None:
        return {"ok": False, "error": "cannot delete session root — delete the session instead"}
    ids = _collect_descendants(conn, node_id)
    placeholders = ",".join("?" * len(ids))
    exp_count = conn.execute(
        f"SELECT COUNT(*) AS c FROM experiments WHERE session_node_id IN ({placeholders})",
        ids,
    ).fetchone()["c"]
    _detach_experiments(conn, ids)
    conn.execute(
        f"UPDATE session_nodes SET deleted_at=? WHERE id IN ({placeholders})",
        [time.time(), *ids],
    )
    conn.commit()

    # Defensive: if the live SessionManager was pointing at any trashed node,
    # detach it so further checkpoint()/branch() calls don't crash.
    mgr = get_current_session()
    if mgr and mgr.session_id == row["session_id"]:
        deleted = set(ids)
        if mgr._last_checkpoint_id in deleted:
            mgr._last_checkpoint_id = None
        if mgr._current_node_id in deleted:
            # Fall back to the live checkpoint anchor, else the session root —
            # never to None, which would make the next checkpoint() insert a
            # parentless node and give the session a second root.
            mgr._current_node_id = mgr._last_checkpoint_id or _session_root_id(
                conn, row["session_id"])
        if mgr._last_checkpoint_id is None:
            mgr._last_checkpoint_id = mgr._current_node_id

    return {"ok": True, "nodes": len(ids), "experiments": exp_count}


def restore_node(node_id: str) -> dict[str, Any]:
    """Restore a soft-deleted node and all its (also-trashed) descendants.

    If the node's parent is itself trashed, the parent is restored too — a
    restored child without a live ancestor would render as an orphan. We
    walk up `parent_id` and clear `deleted_at` on every trashed ancestor
    until we hit either a live row or the root.

    Returns {ok, nodes} (count of rows restored) or {ok: False, error: ...}.
    Linked experiments are not re-attached — delete cleared their
    session_node_id, and we don't know which run was the "right" one.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT parent_id, session_id, deleted_at FROM session_nodes WHERE id=?",
        (node_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "node not found"}
    if row["deleted_at"] is None:
        return {"ok": False, "error": "node is not trashed"}

    # Collect the subtree (descendants are walked through trashed rows since
    # restore is symmetric with delete).
    ids = _collect_descendants(conn, node_id, include_trashed=True)

    # Walk parents upward, restoring any that are also trashed. Stops at the
    # first live row (or the root with parent_id=NULL).
    extra: list[str] = []
    pid = row["parent_id"]
    while pid:
        prow = conn.execute(
            "SELECT id, parent_id, deleted_at FROM session_nodes WHERE id=?",
            (pid,),
        ).fetchone()
        if not prow or prow["deleted_at"] is None:
            break
        extra.append(prow["id"])
        pid = prow["parent_id"]

    all_ids = ids + extra
    placeholders = ",".join("?" * len(all_ids))
    conn.execute(
        f"UPDATE session_nodes SET deleted_at=NULL WHERE id IN ({placeholders})",
        all_ids,
    )
    conn.commit()
    return {"ok": True, "nodes": len(all_ids)}


def purge_node(node_id: str) -> dict[str, Any]:
    """Permanently delete a *trashed* node and its trashed subtree from the DB.

    This is the hard counterpart to `delete_node` (soft delete). It refuses
    anything that isn't already in the trash, so the only way to truly remove
    a node is the deliberate two-step trash → purge. Linked experiments were
    already detached by `delete_node`, but we defensively re-clear any that
    still point at the purged ids. Returns {ok, nodes} or {ok: False, error}.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT deleted_at FROM session_nodes WHERE id=?", (node_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "node not found"}
    if row["deleted_at"] is None:
        return {"ok": False, "error": "node is not trashed — move it to trash first"}
    ids = _collect_descendants(conn, node_id, include_trashed=True)
    placeholders = ",".join("?" * len(ids))
    _detach_experiments(conn, ids)
    images = _trash_node_images(conn, ids)
    conn.execute(
        f"DELETE FROM session_nodes WHERE id IN ({placeholders})", ids,
    )
    conn.commit()
    return {"ok": True, "nodes": len(ids), "images": images}


def empty_trash(session_id: str) -> dict[str, Any]:
    """Permanently delete every trashed node in a session. Returns {ok, nodes}.

    Live nodes are untouched. Linked experiments on the trashed rows were
    already detached by `delete_node`; re-cleared here defensively."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id FROM session_nodes WHERE session_id=? AND deleted_at IS NOT NULL",
        (session_id,),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if not ids:
        return {"ok": True, "nodes": 0, "images": {}}
    placeholders = ",".join("?" * len(ids))
    _detach_experiments(conn, ids)
    images = _trash_node_images(conn, ids)
    conn.execute(
        f"DELETE FROM session_nodes WHERE id IN ({placeholders})", ids,
    )
    conn.commit()
    return {"ok": True, "nodes": len(ids), "images": images}


def rename_node(node_id: str, label: str) -> dict[str, Any]:
    """Rename a live session node's label. Returns {ok, label} or {ok: False,
    error}. Used to fix up auto-suffixed forks (`try 0.7 (2)`) and any other
    relabeling. Trashed nodes are not renamable — restore first."""
    label = (label or "").strip()
    if not label:
        return {"ok": False, "error": "label cannot be empty"}
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM session_nodes WHERE id=? AND deleted_at IS NULL",
        (node_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "node not found"}
    conn.execute("UPDATE session_nodes SET label=? WHERE id=?", (label, node_id))
    conn.commit()
    return {"ok": True, "label": label}


def promote_to_checkpoint(node_id: str) -> dict[str, Any]:
    """Convert a branch (or abandoned branch) node into a checkpoint.

    The branch's current `git_diff` — last refreshed when the live session left
    it — is simply frozen in place (checkpoints don't refresh their diff). Returns
    {ok, node_type} or {ok: False, error}. Keeps the live SessionManager's
    checkpoint anchor pointed at the newest checkpoint so later branches attach
    under it."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, session_id, node_type FROM session_nodes "
        "WHERE id=? AND deleted_at IS NULL",
        (node_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "node not found"}
    if row["node_type"] == "checkpoint":
        return {"ok": True, "node_type": "checkpoint"}
    if row["node_type"] not in ("branch", "abandoned"):
        return {"ok": False, "error": "only branches can be promoted to checkpoints"}
    conn.execute(
        "UPDATE session_nodes SET node_type='checkpoint' WHERE id=?", (node_id,),
    )
    conn.commit()
    sm = get_current_session()
    if sm is not None and sm.session_id == row["session_id"]:
        sm._last_checkpoint_id = node_id
    return {"ok": True, "node_type": "checkpoint"}


def list_trashed_nodes(session_id: str) -> list[dict[str, Any]]:
    """Return the session's trashed nodes (most recently deleted first).
    Used by the per-session CLI (`exptrack session trash`)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, parent_id, node_type, label, seq, created_at, deleted_at, "
        "       length(cell_source) AS cell_bytes "
        "FROM session_nodes WHERE session_id=? AND deleted_at IS NOT NULL "
        "ORDER BY deleted_at DESC, seq",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_all_trashed_nodes(conn=None) -> list[dict[str, Any]]:
    """Return every trashed session node across all sessions, each annotated
    with its owning session's id/name/status, most recently deleted first.

    Backs the unified Trash view (the global Trash now shows trashed session
    nodes alongside trashed experiments). Grouping by session happens in the
    caller / UI; here we just return the flat, session-annotated list.

    ``session_deleted`` flags a node whose *session* is itself in the Trash.
    Such a node still belongs in the list (it can be purged), but restoring it
    alone has no visible effect — the session is hidden from every live list —
    so the UI marks the group and points at the session's own Restore."""
    conn = conn or get_db()
    rows = conn.execute(
        "SELECT n.id, n.session_id, n.parent_id, n.node_type, n.label, n.seq, "
        "       n.created_at, n.deleted_at, length(n.cell_source) AS cell_bytes, "
        "       s.name AS session_name, s.status AS session_status, "
        "       s.deleted_at IS NOT NULL AS session_deleted "
        "FROM session_nodes n JOIN sessions s ON s.id = n.session_id "
        "WHERE n.deleted_at IS NOT NULL "
        "ORDER BY n.deleted_at DESC, n.seq",
    ).fetchall()
    return [dict(r) for r in rows]
