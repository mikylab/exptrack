"""
exptrack/sessions/manager.py — Session and node lifecycle management.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from ..core.db import get_db
from ..core.git import _git as git_run, git_diff as _git_diff

_NODE_CELLS_MAX_BYTES = 256 * 1024  # soft cap on per-node cell_source size
_BRANCH_DIFF_THROTTLE_S = 2.0  # min seconds between branch git_diff refreshes
_NODE_IMAGES_MAX = 30  # cap on plot paths tracked per node (most-recent kept)

_current_session: SessionManager | None = None


def get_current_session() -> SessionManager | None:
    return _current_session


def set_current_session(sm: SessionManager | None) -> None:
    global _current_session
    _current_session = sm


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


_git = git_run  # local alias for terseness inside this module


class SessionManager:
    """Track an exploratory session as a tree of checkpoints/branches."""

    def __init__(self):
        self.session_id: str | None = None
        self._current_node_id: str | None = None
        self._last_checkpoint_id: str | None = None
        # Mirror of the current node's cell_source / cell_outputs — avoids a
        # SELECT per cell. Refreshed whenever _current_node_id changes via
        # _switch_to_node(). The two blobs stay segment-aligned (one output
        # per recorded cell).
        self._current_cell_source: str = ""
        self._current_cell_outputs: str = ""
        self._last_branch_diff_refresh: float = 0.0
        # One-shot guard for `branch("X")` reusing an existing label. We can't
        # tell at branch() time whether this is a Run-All re-run (merge) or a
        # new idea reusing the name (fork) — the code hasn't run yet. So we arm
        # this and let the next recorded cell decide by comparing first-cell
        # source. See record_cell()/branch().
        self._pending_collision: dict[str, Any] | None = None

    # ── cell capture ────────────────────────────────────────────────────────

    _CELL_SEPARATOR = "\n\n# ── cell ──\n\n"

    @staticmethod
    def _is_session_cell(source: str) -> bool:
        """True if the *entire* cell should be skipped from recording.

        - Cell magics `%%scratch` / `%%pin` at the top: own the whole cell,
          skip entirely (the magic handles it separately).
        - Cells that are nothing but `%exptrack` line magics (plus blanks
          and comments): nothing to record.

        Cells with `%exptrack` on the first line followed by real code are
        NOT session cells — the magic lines are stripped and the remainder
        is recorded. That covers the natural pattern of putting the magic
        at the top of a working cell.
        """
        if not source:
            return True
        for ln in source.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("%%scratch") or s.startswith("%%pin"):
                return True
            break
        for ln in source.splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("%exptrack"):
                continue
            return False
        return True

    @staticmethod
    def _strip_session_magics(source: str) -> str:
        """Remove any %exptrack ... lines from a cell's source so the recorded
        version only contains the user's actual code. Cell magics (%%scratch
        / %%pin) get the whole cell handled elsewhere."""
        kept = [ln for ln in source.splitlines()
                if not ln.strip().startswith("%exptrack")]
        while kept and not kept[0].strip():
            kept.pop(0)
        while kept and not kept[-1].strip():
            kept.pop()
        return "\n".join(kept)

    def record_cell(self, source: str, output: str | None = None) -> None:
        """Append a cell's source (and its output) to the *current* node.

        `cell_source` and `cell_outputs` are kept segment-aligned: each
        recorded cell contributes one source segment and one output segment
        (the trailing-expression repr, or "" when the cell produced none).
        Cells are written live so the dashboard shows what ran — and what it
        produced — under the active branch/checkpoint immediately. Session
        magics are skipped. Re-running the same cell back-to-back is deduped,
        but its output is refreshed so the latest result is shown.
        """
        if not self.session_id or not source or not self._current_node_id:
            return
        if self._is_session_cell(source):
            return
        recorded = self._strip_session_magics(source)
        if not recorded:
            return
        self._resolve_branch_collision(recorded)
        out_str = output or ""
        src_parts = (self._current_cell_source.split(self._CELL_SEPARATOR)
                     if self._current_cell_source else [])
        out_parts = (self._current_cell_outputs.split(self._CELL_SEPARATOR)
                     if self._current_cell_outputs else [])
        # Keep the outputs list the same length as the sources list (older
        # DBs / partial writes may have a shorter outputs blob).
        while len(out_parts) < len(src_parts):
            out_parts.append("")

        if src_parts and src_parts[-1].strip() == recorded.strip():
            # Immediate re-run of the same cell — don't duplicate the source,
            # but refresh its output so a fresh result is reflected.
            if out_str and out_parts and out_parts[-1] != out_str:
                out_parts[-1] = out_str
            else:
                return  # nothing changed
        else:
            src_parts.append(recorded)
            out_parts.append(out_str)
            # Drop oldest cells (source + output together) if over the cap.
            # Track the running byte total instead of re-joining each iteration.
            sep_len = len(self._CELL_SEPARATOR)
            total = sum(len(p) for p in src_parts) + sep_len * (len(src_parts) - 1)
            if total > _NODE_CELLS_MAX_BYTES:
                while len(src_parts) > 1 and total > _NODE_CELLS_MAX_BYTES:
                    total -= len(src_parts.pop(0)) + sep_len
                    out_parts.pop(0)
                src_parts.insert(0, "# … earlier cells elided to bound memory …")
                out_parts.insert(0, "")

        new_blob = self._CELL_SEPARATOR.join(src_parts)
        new_out = self._CELL_SEPARATOR.join(out_parts)
        conn = get_db()
        conn.execute(
            "UPDATE session_nodes SET cell_source=?, cell_outputs=? WHERE id=?",
            (new_blob, new_out or None, self._current_node_id),
        )
        self._current_cell_source = new_blob
        self._current_cell_outputs = new_out
        # Throttle the per-cell git diff refresh: 2-3 subprocesses on every
        # cell run is too aggressive for big repos. _BRANCH_DIFF_THROTTLE_S
        # caps it without losing freshness — the next non-throttled cell or
        # any explicit checkpoint still re-snapshots.
        now = time.time()
        if now - self._last_branch_diff_refresh >= _BRANCH_DIFF_THROTTLE_S:
            row = self._get_node(self._current_node_id, "node_type, parent_id")
            if row and row["node_type"] == "branch":
                head = _git("rev-parse", "--short", "HEAD")
                diff = self._compute_diff_vs_checkpoint(row["parent_id"], head)
                conn.execute(
                    "UPDATE session_nodes SET git_diff=? WHERE id=?",
                    (diff or None, self._current_node_id),
                )
                self._last_branch_diff_refresh = now
        conn.commit()

    def record_image(self, path: str, label: str | None = None) -> None:
        """Attach a saved plot to the current node *by reference* (no copy).

        Called from the matplotlib savefig patch whenever a figure is written
        while a session node is active. Stores the absolute path (+ optional
        figure title) in the node's `images` JSON, deduped by path (re-saving
        the same file refreshes its label/timestamp instead of duplicating),
        capped at the _NODE_IMAGES_MAX most-recent entries. Any failure is
        swallowed with a warning so it never breaks the user's savefig call."""
        if not self.session_id or not self._current_node_id or not path:
            return
        try:
            abs_path = str(Path(path).resolve())
            conn = get_db()
            row = self._get_node(self._current_node_id, "images")
            try:
                imgs = json.loads(row["images"]) if row and row["images"] else []
            except Exception:
                imgs = []
            imgs = [im for im in imgs
                    if isinstance(im, dict) and im.get("path") != abs_path]
            imgs.append({"path": abs_path,
                         "label": (label or "").strip() or None,
                         "ts": time.time()})
            if len(imgs) > _NODE_IMAGES_MAX:
                imgs = imgs[-_NODE_IMAGES_MAX:]
            conn.execute("UPDATE session_nodes SET images=? WHERE id=?",
                         (json.dumps(imgs), self._current_node_id))
            conn.commit()
        except Exception as e:
            print(f"[exptrack] session image capture warning: {e}", file=sys.stderr)

    def _switch_to_node(self, node_id: str) -> None:
        """Set _current_node_id and refresh the cached cell_source/outputs."""
        self._current_node_id = node_id
        row = self._get_node(node_id, "cell_source, cell_outputs")
        self._current_cell_source = (row["cell_source"]
                                     if row and row["cell_source"] else "")
        self._current_cell_outputs = (row["cell_outputs"]
                                      if row and row["cell_outputs"] else "")

    def _get_node(self, node_id: str, cols: str = "*"):
        """Single-row id lookup — used in a few places."""
        return get_db().execute(
            f"SELECT {cols} FROM session_nodes WHERE id=?", (node_id,),
        ).fetchone()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self, name: str, notebook: str = "") -> str:
        """Create a new session and write the root node. Returns session_id."""
        if self.session_id:
            return self.session_id
        sid = _new_id()
        now = time.time()
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        commit = _git("rev-parse", "--short", "HEAD")
        conn = get_db()
        conn.execute(
            "INSERT INTO sessions (id, name, notebook, status, git_branch, "
            "git_commit, created_at) VALUES (?, ?, ?, 'active', ?, ?, ?)",
            (sid, name, notebook or None, branch or None, commit or None, now),
        )
        # Write root node
        root_id = _new_id()
        conn.execute(
            "INSERT INTO session_nodes (id, session_id, parent_id, node_type, "
            "label, seq, created_at, git_commit) VALUES (?, ?, NULL, 'root', ?, 0, ?, ?)",
            (root_id, sid, name, now, commit or None),
        )
        conn.commit()
        self.session_id = sid
        self._switch_to_node(root_id)
        self._last_checkpoint_id = root_id
        return sid

    def end(self) -> None:
        """Mark session ended; mark trailing open branches as abandoned."""
        if not self.session_id:
            return
        conn = get_db()
        # Mark any branch nodes whose deepest child is themselves (no checkpoint
        # follows) as abandoned. A branch is "open" if no descendant is a
        # checkpoint. Simpler heuristic: any branch with no child node at all.
        rows = conn.execute(
            "SELECT id FROM session_nodes WHERE session_id=? AND node_type='branch' "
            "AND id NOT IN (SELECT parent_id FROM session_nodes "
            "WHERE session_id=? AND parent_id IS NOT NULL)",
            (self.session_id, self.session_id),
        ).fetchall()
        for r in rows:
            conn.execute(
                "UPDATE session_nodes SET node_type='abandoned' WHERE id=?",
                (r["id"],),
            )
        conn.execute(
            "UPDATE sessions SET status='ended', ended_at=? WHERE id=?",
            (time.time(), self.session_id),
        )
        conn.commit()
        self.session_id = None
        self._current_node_id = None
        self._last_checkpoint_id = None
        self._current_cell_source = ""
        self._current_cell_outputs = ""
        self._pending_collision = None

    # ── nodes ────────────────────────────────────────────────────────────────

    def _next_seq(self) -> int:
        conn = get_db()
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 AS n FROM session_nodes WHERE session_id=?",
            (self.session_id,),
        ).fetchone()
        return int(row["n"])

    def _find_child_by_label(self, parent_id: str, label: str,
                              types: tuple[str, ...]) -> str | None:
        """Return id of an existing live child node with this label/parent/type,
        or None. Trashed nodes are skipped — restore via the dashboard or
        `session restore-node` to reuse one."""
        placeholders = ",".join("?" * len(types))
        row = get_db().execute(
            f"SELECT id FROM session_nodes WHERE session_id=? AND parent_id=? "
            f"AND label=? AND node_type IN ({placeholders}) "
            f"AND deleted_at IS NULL "
            f"ORDER BY seq DESC LIMIT 1",
            (self.session_id, parent_id, label, *types),
        ).fetchone()
        return row["id"] if row else None

    def checkpoint(self, label: str) -> str | None:
        """Add a checkpoint under the current node, or reuse an existing
        checkpoint with the same label (idempotent re-runs)."""
        self._pending_collision = None
        if not self.session_id:
            return None
        if self._current_node_id:
            row = self._get_node(self._current_node_id, "node_type, label")
            if row and row["node_type"] == "checkpoint" and row["label"] == label:
                return self._current_node_id
        parent_id = self._current_node_id or self._last_checkpoint_id
        existing = self._find_child_by_label(parent_id, label, ("checkpoint",))
        if existing:
            self._switch_to_node(existing)
            self._last_checkpoint_id = existing
            return existing

        conn = get_db()
        nid = _new_id()
        now = time.time()
        commit = _git("rev-parse", "--short", "HEAD")
        prev_commit = None
        if self._last_checkpoint_id:
            row = self._get_node(self._last_checkpoint_id, "git_commit")
            if row:
                prev_commit = row["git_commit"]
        if prev_commit and commit and prev_commit != commit:
            diff = _git_diff(prev_commit, commit)
        else:
            diff = _git_diff("HEAD")
        conn.execute(
            "INSERT INTO session_nodes (id, session_id, parent_id, node_type, "
            "label, git_diff, git_commit, seq, created_at) "
            "VALUES (?, ?, ?, 'checkpoint', ?, ?, ?, ?, ?)",
            (nid, self.session_id, parent_id, label,
             diff or None, commit or None, self._next_seq(), now),
        )
        conn.commit()
        self._switch_to_node(nid)
        self._last_checkpoint_id = nid
        return nid

    def branch(self, label: str) -> str | None:
        """Add a branch under the most recent checkpoint, or reuse an existing
        branch with the same label (idempotent re-runs). Reactivates an
        abandoned branch if one exists with this label.

        When the label collides with an existing branch, we can't yet know if
        this is a harmless re-run or a new exploration reusing the name (the
        cells haven't run). We switch to the existing node and arm
        `_pending_collision`; the next recorded cell forks to a suffixed node
        if its first cell differs from the existing node's. See record_cell()."""
        self._pending_collision = None
        if not self.session_id or not self._last_checkpoint_id:
            return None
        existing = self._find_child_by_label(
            self._last_checkpoint_id, label, ("branch", "abandoned"))
        if existing:
            row = self._get_node(existing, "node_type")
            if row and row["node_type"] == "abandoned":
                conn = get_db()
                conn.execute(
                    "UPDATE session_nodes SET node_type='branch' WHERE id=?",
                    (existing,),
                )
                conn.commit()
            self._switch_to_node(existing)
            first = (self._current_cell_source.split(self._CELL_SEPARATOR)[0]
                     if self._current_cell_source else "")
            self._pending_collision = {
                "existing_id": existing,
                "label": label,
                "parent_id": self._last_checkpoint_id,
                "baseline_first": first,
            }
            return existing

        nid = self._create_branch_node(self._last_checkpoint_id, label)
        self._switch_to_node(nid)
        return nid

    def _create_branch_node(self, checkpoint_id: str, label: str) -> str:
        """Insert a fresh branch node under `checkpoint_id`, capturing its diff
        vs that checkpoint. Returns the new node id. Shared by branch() and the
        collision-fork path so node creation lives in one place."""
        conn = get_db()
        nid = _new_id()
        now = time.time()
        commit = _git("rev-parse", "--short", "HEAD")
        diff = self._compute_diff_vs_checkpoint(checkpoint_id, commit)
        conn.execute(
            "INSERT INTO session_nodes (id, session_id, parent_id, node_type, "
            "label, git_diff, git_commit, seq, created_at) "
            "VALUES (?, ?, ?, 'branch', ?, ?, ?, ?, ?)",
            (nid, self.session_id, checkpoint_id, label,
             diff or None, commit or None, self._next_seq(), now),
        )
        conn.commit()
        return nid

    def _unique_branch_label(self, parent_id: str, label: str) -> str:
        """Return `label (2)`, `label (3)`, … — the first suffix not already
        taken by a live child of `parent_id`."""
        n = 2
        while self._find_child_by_label(
                parent_id, f"{label} ({n})", ("branch", "abandoned", "checkpoint")):
            n += 1
        return f"{label} ({n})"

    def _resolve_branch_collision(self, recorded: str) -> None:
        """Decide a pending branch-label collision using the first recorded cell.

        Armed by branch() when a label was reused. If the incoming cell's source
        matches the existing node's first cell, it's a Run-All re-run — keep
        merging into the existing node (no-op here). If it differs, this is a
        new idea reusing the name: fork a fresh suffixed branch, switch to it,
        and warn so the user can rename it."""
        pc = self._pending_collision
        if not pc or self._current_node_id != pc["existing_id"]:
            return
        self._pending_collision = None
        baseline = (pc["baseline_first"] or "").strip()
        if not baseline or baseline == recorded.strip():
            return  # first cell / identical re-run — merge as before
        new_label = self._unique_branch_label(pc["parent_id"], pc["label"])
        nid = self._create_branch_node(pc["parent_id"], new_label)
        self._switch_to_node(nid)
        print(
            f"[exptrack] branch {pc['label']!r} already had different code under "
            f"this checkpoint — recording under {new_label!r} ({nid[:8]}) instead. "
            f"Rename it in the dashboard (double-click the node label) if you like.",
            file=sys.stderr,
        )

    def _compute_diff_vs_checkpoint(self, checkpoint_id: str | None,
                                    head_commit: str | None) -> str:
        """Diff from parent checkpoint's commit to current working tree."""
        prev_commit = None
        if checkpoint_id:
            row = self._get_node(checkpoint_id, "git_commit")
            if row:
                prev_commit = row["git_commit"]
        if prev_commit and head_commit and prev_commit != head_commit:
            committed = _git_diff(prev_commit, head_commit) or ""
            working = _git_diff("HEAD") or ""
            return (committed + ("\n" + working if working else "")).strip()
        if prev_commit:
            return _git_diff(prev_commit) or ""
        return _git_diff("HEAD") or ""

    def mark_abandoned(self, node_id: str) -> None:
        conn = get_db()
        conn.execute(
            "UPDATE session_nodes SET node_type='abandoned' WHERE id=?",
            (node_id,),
        )
        conn.commit()

    def promote(self, label: str, exp_id: str) -> None:
        """Link an experiment to the current session node."""
        if not self.session_id or not self._current_node_id:
            return
        conn = get_db()
        conn.execute(
            "UPDATE experiments SET session_node_id=? WHERE id=?",
            (self._current_node_id, exp_id),
        )
        conn.commit()
        if label:
            self.append_to_current_note(f"promoted: {label}")

    def append_to_current_note(self, text: str) -> None:
        """Append a line to the current node's `note` field. Used by promote
        and by external integrations (e.g. %%pin) that want to leave a trail
        on the active checkpoint without reaching into internals."""
        if not self.session_id or not self._current_node_id or not text:
            return
        conn = get_db()
        row = conn.execute(
            "SELECT note FROM session_nodes WHERE id=?",
            (self._current_node_id,),
        ).fetchone()
        existing = row["note"] if row and row["note"] else ""
        new_note = existing + ("\n" if existing else "") + text
        conn.execute(
            "UPDATE session_nodes SET note=? WHERE id=?",
            (new_note, self._current_node_id),
        )
        conn.commit()

    def annotate(self, node_id: str, text: str) -> None:
        if not node_id:
            return
        conn = get_db()
        conn.execute(
            "UPDATE session_nodes SET note=? WHERE id=?", (text, node_id),
        )
        conn.commit()

    # ── reads ────────────────────────────────────────────────────────────────

    def get_tree(self, session_id: str | None = None) -> dict[str, Any]:
        sid = session_id or self.session_id
        if not sid:
            return {}
        return build_tree(sid)


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


def delete_session(session_id: str) -> bool:
    """Delete a session and all its nodes. Linked experiments are preserved
    with their session_node_id cleared. Returns True if a session was deleted."""
    conn = get_db()
    row = conn.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not row:
        return False
    conn.execute(
        "UPDATE experiments SET session_node_id=NULL "
        "WHERE session_node_id IN (SELECT id FROM session_nodes WHERE session_id=?)",
        (session_id,),
    )
    conn.execute("DELETE FROM session_nodes WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    return True


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
    mgr = _current_session
    if mgr and mgr.session_id == row["session_id"]:
        deleted = set(ids)
        if mgr._current_node_id in deleted:
            mgr._current_node_id = mgr._last_checkpoint_id \
                if mgr._last_checkpoint_id not in deleted else None
        if mgr._last_checkpoint_id in deleted:
            mgr._last_checkpoint_id = None

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


def list_trashed_nodes(session_id: str) -> list[dict[str, Any]]:
    """Return the session's trashed nodes (most recently deleted first).
    Used by the dashboard Trash panel and the CLI."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, parent_id, node_type, label, seq, created_at, deleted_at, "
        "       length(cell_source) AS cell_bytes "
        "FROM session_nodes WHERE session_id=? AND deleted_at IS NOT NULL "
        "ORDER BY deleted_at DESC, seq",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def build_tree(session_id: str) -> dict[str, Any]:
    """Reconstruct a session's tree as a nested dict.

    Handles missing parents by attaching orphans to the root.
    Shape:
      { "session": {...}, "root": { "node": {...}, "children": [...] } }
    """
    conn = get_db()
    s_row = conn.execute(
        "SELECT * FROM sessions WHERE id=?", (session_id,),
    ).fetchone()
    if not s_row:
        return {}
    nodes = conn.execute(
        "SELECT n.*, e.id AS exp_id, e.name AS exp_name "
        "FROM session_nodes n "
        "LEFT JOIN experiments e ON e.session_node_id = n.id "
        "WHERE n.session_id=? AND n.deleted_at IS NULL ORDER BY n.seq",
        (session_id,),
    ).fetchall()

    # Build node dict and child lists
    by_id: dict[str, dict] = {}
    for r in nodes:
        by_id[r["id"]] = {
            "id": r["id"],
            "parent_id": r["parent_id"],
            "node_type": r["node_type"],
            "label": r["label"],
            "note": r["note"],
            "cell_source": r["cell_source"],
            "cell_outputs": r["cell_outputs"],
            "images": _node_images(r["images"]),
            "git_diff": r["git_diff"],
            "git_commit": r["git_commit"],
            "seq": r["seq"],
            "created_at": r["created_at"],
            "exp_id": r["exp_id"],
            "exp_name": r["exp_name"],
            "children": [],
        }

    root = None
    orphans: list[dict] = []
    for n in by_id.values():
        pid = n["parent_id"]
        if pid is None:
            if root is None:
                root = n
            else:
                # Multiple roots — attach extras to the first root
                orphans.append(n)
        elif pid in by_id:
            by_id[pid]["children"].append(n)
        else:
            orphans.append(n)
    if root is None and by_id:
        # No root node found — synthesize one
        root = {
            "id": "_synth_root",
            "parent_id": None,
            "node_type": "root",
            "label": s_row["name"],
            "note": None,
            "cell_source": None,
            "cell_outputs": None,
            "images": [],
            "git_diff": None,
            "git_commit": None,
            "seq": -1,
            "created_at": s_row["created_at"],
            "exp_id": None,
            "exp_name": None,
            "children": [n for n in by_id.values() if n["parent_id"] is None],
        }
    if root is not None:
        root["children"].extend(orphans)

    return {
        "session": {
            "id": s_row["id"],
            "name": s_row["name"],
            "notebook": s_row["notebook"],
            "status": s_row["status"],
            "git_branch": s_row["git_branch"],
            "git_commit": s_row["git_commit"],
            "created_at": s_row["created_at"],
            "ended_at": s_row["ended_at"],
        },
        "root": root or {},
    }
