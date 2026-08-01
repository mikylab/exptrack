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
_NODE_IMAGES_MAX = 30  # cap on plot paths tracked per node (most-recent kept)

# One SEP-joined blob holds a node's recorded cells (and, in parallel, their
# outputs). Defined here as the single source of truth so manager/lifecycle/
# materialize all split/join on the same separator; SessionManager re-exposes
# it as the class attribute `SessionManager._CELL_SEPARATOR` for back-compat
# (core/queries.py and tests reference it by that name).
_CELL_SEPARATOR = "\n\n# ── cell ──\n\n"

# Placeholder written in place of the oldest segments once a node's cell store
# trips its byte cap. It is bookkeeping, not code: it must never be counted as a
# recorded cell (finalize's "ran code?" test, the dashboard's cell counts) and
# must never be the segment a replay cursor is armed on — a cursor sitting on it
# can never match an incoming cell, which used to poison replay dedup for the
# rest of the session once a node tripped the cap.
_ELIDED_MARKER = "# … earlier cells elided to bound memory …"


def _is_elided(segment: str | None) -> bool:
    """True if a stored segment is the cap-trip elision placeholder."""
    return (segment or "").strip() == _ELIDED_MARKER


def _count_cells(blob: str | None) -> int:
    """Number of *real* recorded cells in a SEP-joined blob (0 when empty).

    Skips blank segments and the elision placeholder, so a node that tripped the
    byte cap doesn't report a phantom extra cell."""
    if not blob:
        return 0
    return sum(1 for c in blob.split(_CELL_SEPARATOR)
               if c.strip() and not _is_elided(c))

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


def _store_node_diff(conn, diff_text: str | None) -> str | None:
    """Prepare a diff for storage in ``session_nodes.git_diff``.

    Session diffs get the same two protections experiment diffs have always
    had, and for the same reasons. They are **capped** at ``max_git_diff_kb``
    (a node captured whatever `git diff` produced, uncapped, so one large
    working tree could write megabytes per node), and they are **stored
    content-addressed** in `git_diffs` — sibling branches off one checkpoint
    share a working tree, so their diffs are usually byte-identical and were
    being stored once per node.

    Returns the ``[ref:sha256:…]`` marker, or the text itself when it is a
    status sentinel (``[capture-failed]`` etc. — a marker, not a body) or when
    the blob write fails. Does not commit; the caller's transaction owns it.
    """
    if not diff_text:
        return None
    from ..core.db import is_diff_sentinel, store_git_diff
    if is_diff_sentinel(diff_text):
        return diff_text
    from ..config import load as load_config
    try:
        cap = max(0, int(load_config().get("max_git_diff_kb", 256))) * 1024
    except (TypeError, ValueError):
        cap = 256 * 1024
    if cap and len(diff_text) > cap:
        diff_text = (diff_text[:cap]
                     + "\n\n[truncated — exceeded max_git_diff_kb limit]")
    try:
        return store_git_diff(conn, diff_text)
    except Exception as e:
        debug_log(f"could not store session node diff by reference: {e}")
        return diff_text


def _resolve_node_diff(conn, raw_diff: str | None, cache: dict | None = None) -> str | None:
    """Resolve a node's stored ``git_diff`` (a ref marker, inline text, or a
    sentinel) into displayable text.

    `cache` memoizes by raw value: sibling nodes routinely share one blob, so
    rendering a tree would otherwise re-read the same body once per node.
    """
    if not raw_diff:
        return raw_diff
    if cache is not None and raw_diff in cache:
        return cache[raw_diff]
    from ..core.db import resolve_git_diff
    resolved = resolve_git_diff(conn, raw_diff)
    if cache is not None:
        cache[raw_diff] = resolved
    return resolved


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


def _nearest_live_checkpoint(conn, node_id: str | None) -> str | None:
    """Walk up from `node_id` to the nearest live checkpoint (or root), or None.

    The checkpoint anchor is where the next `branch()` attaches, so it has to be
    a checkpoint/root — falling back to "whatever node is current" pointed it at
    a *branch* after a delete, and the following branch was created as a child of
    a branch, quietly flattening the tree's meaning. Starts at `node_id` itself,
    which is the right answer when the current node already is a checkpoint."""
    seen: set[str] = set()
    cur = node_id
    while cur and cur not in seen:
        seen.add(cur)
        r = conn.execute(
            "SELECT id, parent_id, node_type FROM session_nodes "
            "WHERE id=? AND deleted_at IS NULL",
            (cur,),
        ).fetchone()
        if not r:
            return None
        if r["node_type"] in ("checkpoint", "root"):
            return r["id"]
        cur = r["parent_id"]
    return None


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
