"""
exptrack/sessions/_shared.py — shared state, constants, and cross-cutting
helpers for the session subsystem (manager / lifecycle / materialize).

Holds the module-level current-session singleton plus the small helpers that
more than one of those modules needs (experiment detach, per-node image
bookkeeping, session-study grouping, descendant collection, lineage labels).
Kept dependency-free of manager/lifecycle/materialize so those can all import
it without a cycle.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..core.git import _git as git_run
from ..core.utils import debug_log

_NODE_CELLS_MAX_BYTES = 256 * 1024  # soft cap on per-node cell_source size
_NODE_SETUP_MAX_BYTES = 256 * 1024  # separate soft cap for %%setup prep blocks
_BRANCH_DIFF_THROTTLE_S = 2.0  # min seconds between branch git_diff refreshes
_NODE_IMAGES_MAX = 30  # cap on plot paths tracked per node (most-recent kept)

# One SEP-joined blob holds a node's recorded cells (and, in parallel, their
# outputs). Defined here as the single source of truth so manager/lifecycle/
# materialize all split/join on the same separator; SessionManager re-exposes
# it as the class attribute `SessionManager._CELL_SEPARATOR` for back-compat
# (core/queries.py and tests reference it by that name).
_CELL_SEPARATOR = "\n\n# ── cell ──\n\n"

# The live SessionManager singleton. Read via get_current_session() and set via
# set_current_session() — never `from ._shared import _current_session`, which
# would freeze the None binding at import time.
_current_session: Any | None = None


def get_current_session():
    return _current_session


def set_current_session(sm) -> None:
    global _current_session
    _current_session = sm


def _new_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def _unix_to_iso(ts) -> str | None:
    """Convert a unix timestamp (float/None) to a UTC ISO string, or None.

    UTC ISO strings sort chronologically, so callers can string-compare them
    against `metrics.ts` etc. Returns None for missing/unparseable input."""
    if ts is None:
        return None
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


_git = git_run  # local alias for terseness inside this module


def _detach_experiments(conn, node_ids: list[str]) -> None:
    """Clear `session_node_id` on any experiments linked to these nodes.

    The invariant across every node-removal path (soft delete, hard purge,
    empty-trash) is "touch a node id → detach its experiments first" so runs
    are never left pointing at a vanished node. Centralizing it here keeps
    that contract in one place."""
    if not node_ids:
        return
    placeholders = ",".join("?" * len(node_ids))
    conn.execute(
        f"UPDATE experiments SET session_node_id=NULL "
        f"WHERE session_node_id IN ({placeholders})",
        node_ids,
    )


def _node_images(images_json: str | None) -> list[dict[str, Any]]:
    """Parse a node's `images` JSON into render-ready dicts: {label, url, path}.

    `url` is the path relative to the project root (served by the dashboard's
    /api/file/ route); it's None when the file lives outside the project and
    therefore can't be served. `path` (absolute) is kept for tooltips."""
    if not images_json:
        return []
    try:
        raw = json.loads(images_json)
    except Exception:
        return []
    from ..core.queries import _rel_path  # absolute → project-relative
    out: list[dict[str, Any]] = []
    for im in raw:
        if not isinstance(im, dict) or not im.get("path"):
            continue
        # `_rel_path` returns a project-relative path (or the original if it
        # can't convert / lives outside root). A leftover absolute path or a
        # "../" prefix means the file isn't under the project, so it can't be
        # served by /api/file/ — surface url=None for those.
        rel = _rel_path(im["path"])
        url = (rel.replace(os.sep, "/")
               if rel and not os.path.isabs(rel) and not rel.startswith("..")
               else None)
        out.append({"label": im.get("label"), "url": url, "path": im["path"]})
    return out


def _image_paths_for_nodes(conn, node_ids: list[str]) -> list[str]:
    """Return the distinct plot file paths attached across these nodes (parsed
    from each node's `images` JSON, deduped, order-stable). Single source of
    the parse-and-iterate for both counting and trashing image files."""
    if not node_ids:
        return []
    placeholders = ",".join("?" * len(node_ids))
    rows = conn.execute(
        f"SELECT images FROM session_nodes WHERE id IN ({placeholders})", node_ids,
    ).fetchall()
    seen: set[str] = set()
    paths: list[str] = []
    for r in rows:
        if not r["images"]:
            continue
        try:
            arr = json.loads(r["images"])
        except Exception:
            continue
        for im in arr:
            p = im.get("path") if isinstance(im, dict) else None
            if p and p not in seen:
                seen.add(p)
                paths.append(p)
    return paths


def _count_node_images(conn, node_ids: list[str]) -> int:
    """Count distinct plot files attached across these nodes."""
    return len(_image_paths_for_nodes(conn, node_ids))


def _trash_node_images(conn, node_ids: list[str]) -> dict[str, int]:
    """Move by-reference plot files attached to these nodes to the OS Trash
    (recoverable; never `rm -rf`). Returns {os_trash, local_trash, missing,
    failed}. Used only by the permanent-removal paths (purge / empty-trash) —
    soft delete leaves files in place so Restore still works."""
    counts = {"os_trash": 0, "local_trash": 0, "missing": 0, "failed": 0}
    from ..core.db import _trash_or_local
    for p in _image_paths_for_nodes(conn, node_ids):
        try:
            res = _trash_or_local(Path(p), label="plot")
        except Exception:
            res = "failed"
        counts[res] = counts.get(res, 0) + 1
    return counts


def _session_study_name(conn, session_id: str) -> str | None:
    """The study a session's runs are grouped under — its name (or a short id
    fallback). Single source so autolink / materialize / finalize agree."""
    row = conn.execute(
        "SELECT name FROM sessions WHERE id=?", (session_id,),
    ).fetchone()
    if not row:
        return None
    name = (row["name"] or "").strip()
    return name or f"session {session_id[:8]}"


def _group_run_into_session_study(conn, exp_id: str, session_id: str) -> None:
    """Add an experiment to its session's study (best-effort, no commit).

    The grouping is what survives session deletion: once a run carries the
    study, it stays grouped in the dashboard/table even after the session and
    its node links are gone."""
    if not exp_id or not session_id:
        return
    study = _session_study_name(conn, session_id)
    if not study:
        return
    try:
        from ..core.queries import add_to_study
        add_to_study(conn, exp_id, study)
    except Exception as e:
        debug_log(f"could not group run {exp_id[:8]} into session study: {e}")


def _collect_descendants(conn, node_id: str, *,
                          include_trashed: bool = False) -> list[str]:
    """Return [node_id, ...descendants] in delete order (children before parents).

    Walks session_nodes.parent_id via BFS within the node's session. By
    default, trashed (soft-deleted) nodes are skipped so a delete pass on a
    live subtree doesn't also re-touch already-trashed descendants. Pass
    `include_trashed=True` to walk through trashed nodes — used by restore,
    which needs to bring back the entire previously-deleted subtree.
    """
    children_by_parent: dict[str, list[str]] = {}
    sid_row = conn.execute(
        "SELECT session_id FROM session_nodes WHERE id=?", (node_id,),
    ).fetchone()
    if not sid_row:
        return []
    q = "SELECT id, parent_id FROM session_nodes WHERE session_id=?"
    if not include_trashed:
        q += " AND deleted_at IS NULL"
    rows = conn.execute(q, (sid_row["session_id"],)).fetchall()
    for r in rows:
        children_by_parent.setdefault(r["parent_id"], []).append(r["id"])
    out: list[str] = []
    stack = [node_id]
    while stack:
        nid = stack.pop()
        out.append(nid)
        stack.extend(children_by_parent.get(nid, []))
    out.reverse()  # children before parents
    return out


def _node_lineage_labels(conn, node_id: str) -> list[str]:
    """Walk a node's parent chain to the root and return the ordered list of
    labels (root → … → node), skipping the synthetic root and empty labels.
    Used to give a materialized experiment a breadcrumb of where it sits in the
    session tree."""
    labels: list[str] = []
    seen: set[str] = set()
    cur = node_id
    while cur and cur not in seen:
        seen.add(cur)
        r = conn.execute(
            "SELECT label, node_type, parent_id FROM session_nodes WHERE id=?",
            (cur,),
        ).fetchone()
        if not r:
            break
        if r["node_type"] != "root" and (r["label"] or "").strip():
            labels.append(r["label"].strip())
        cur = r["parent_id"]
    labels.reverse()
    return labels
