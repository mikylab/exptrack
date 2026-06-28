"""Unified trash aggregation across the two soft-delete domains.

exptrack soft-deletes two unrelated kinds of thing:

  * **experiments** — `experiments.deleted_at` (see `core/db.py`:
    `trash_experiment` / `restore_experiment` / `delete_experiment`)
  * **session nodes** — `session_nodes.deleted_at` (see `sessions/manager.py`:
    `delete_node` / `restore_node` / `purge_node` / `empty_trash`)

The two schemas are genuinely different (one experiment fans out into
metrics/params/artifacts/timeline; a node is one row in a tree subtree), so the
per-kind soft-delete/restore/purge logic rightly lives in its own domain module.
What they *share* is the destructive-file primitive (`_trash_or_local` /
`_send_to_os_trash` in `core/db.py`, used by both) and — now — a single place
that answers "what is in the trash?" so the dashboard can show one unified Trash
view with an Experiments section and a Session-nodes section.

This module is that single place: `list_unified_trash()` and
`count_unified_trash()`. Restore/purge stay as the per-kind functions the
dashboard routes already call.
"""

from __future__ import annotations

import json as _json
from typing import Any


def count_unified_trash(conn) -> dict[str, int]:
    """Return {experiments, nodes, total} counts of everything in the trash.

    Cheap COUNT(*)s over both tables — used for the Trash badge so it reflects
    trashed experiments *and* trashed session nodes."""
    experiments = conn.execute(
        "SELECT COUNT(*) AS n FROM experiments WHERE deleted_at IS NOT NULL"
    ).fetchone()["n"]
    try:
        nodes = conn.execute(
            "SELECT COUNT(*) AS n FROM session_nodes WHERE deleted_at IS NOT NULL"
        ).fetchone()["n"]
    except Exception:
        # session_nodes may not exist on a pre-Session-Trees DB.
        nodes = 0
    try:
        sessions = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE deleted_at IS NOT NULL"
        ).fetchone()["n"]
    except Exception:
        sessions = 0
    return {"experiments": experiments, "nodes": nodes, "sessions": sessions,
            "total": experiments + nodes + sessions}


def _count_by_exp(conn, table: str, exp_ids: list[str]) -> dict[str, int]:
    """One grouped COUNT over *table* for all *exp_ids* (avoids a query per row)."""
    if not exp_ids:
        return {}
    ph = ",".join("?" * len(exp_ids))
    rows = conn.execute(
        f"SELECT exp_id, COUNT(*) AS n FROM {table} "
        f"WHERE exp_id IN ({ph}) GROUP BY exp_id", exp_ids
    ).fetchall()
    return {r["exp_id"]: r["n"] for r in rows}


def _trashed_experiments(conn) -> list[dict[str, Any]]:
    """Trashed experiments with the quick scope info the Trash view shows."""
    from .db import list_trashed_experiments

    trashed = list_trashed_experiments(conn)
    ids = [r["id"] for r in trashed]
    metrics_counts = _count_by_exp(conn, "metrics", ids)
    artifact_counts = _count_by_exp(conn, "artifacts", ids)
    out: list[dict[str, Any]] = []
    for r in trashed:
        eid = r["id"]
        try:
            tags = _json.loads(r["tags"] or "[]")
        except (ValueError, TypeError):
            tags = []
        try:
            studies = _json.loads(r["studies"] or "[]")
        except (ValueError, TypeError):
            studies = []
        n_metrics = metrics_counts.get(eid, 0)
        n_artifacts = artifact_counts.get(eid, 0)
        out.append({
            "id": eid,
            "name": r["name"] or "",
            "status": r["status"],
            "created_at": r["created_at"],
            "deleted_at": r["deleted_at"],
            "git_branch": r["git_branch"],
            "git_commit": r["git_commit"],
            "output_dir": r["output_dir"] or "",
            "tags": tags,
            "studies": studies,
            "metrics_count": n_metrics,
            "artifacts_count": n_artifacts,
        })
    return out


def _trashed_node_groups(conn) -> list[dict[str, Any]]:
    """Trashed session nodes grouped by their owning session, newest-deleted
    session first. Each group is {session: {id, name, status}, nodes: [...]}."""
    try:
        from ..sessions.manager import list_all_trashed_nodes
        nodes = list_all_trashed_nodes(conn)
    except Exception:
        return []
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for n in nodes:
        sid = n["session_id"]
        if sid not in groups:
            groups[sid] = {
                "session": {
                    "id": sid,
                    "name": n.get("session_name") or "",
                    "status": n.get("session_status") or "",
                },
                "nodes": [],
            }
            order.append(sid)
        groups[sid]["nodes"].append({
            "id": n["id"],
            "session_id": sid,
            "parent_id": n["parent_id"],
            "node_type": n["node_type"],
            "label": n["label"],
            "seq": n["seq"],
            "created_at": n["created_at"],
            "deleted_at": n["deleted_at"],
            "cell_bytes": n["cell_bytes"] or 0,
        })
    return [groups[sid] for sid in order]


def _trashed_whole_sessions(conn) -> list[dict[str, Any]]:
    """Soft-deleted *whole* sessions (distinct from trashed individual nodes).
    Restoring one brings the entire session back; purging hard-deletes it."""
    try:
        from ..sessions.manager import list_trashed_sessions
        return list_trashed_sessions(conn)
    except Exception:
        return []


def list_unified_trash(conn) -> dict[str, Any]:
    """Everything in the trash, shaped for the dashboard's unified Trash view:

        {
          "experiments":     [ {id, name, status, deleted_at, metrics_count, ...} ],
          "sessions":        [ {session: {id, name, status}, nodes: [...]} ],
          "trashed_sessions":[ {id, name, status, nodes, promoted, deleted_at} ],
          "counts":          {experiments, nodes, sessions, total},
        }

    Note the two session-shaped keys: ``sessions`` groups individually-trashed
    *nodes* by their (live) owning session, while ``trashed_sessions`` lists
    whole sessions that were themselves moved to the Trash."""
    return {
        "experiments": _trashed_experiments(conn),
        "sessions": _trashed_node_groups(conn),
        "trashed_sessions": _trashed_whole_sessions(conn),
        "counts": count_unified_trash(conn),
    }
