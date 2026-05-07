"""
exptrack/sessions/manager.py — Session and node lifecycle management.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from ..core.db import get_db
from ..core.git import _git as git_run

_NODE_CELLS_MAX_BYTES = 256 * 1024  # soft cap on per-node cell_source size
_BRANCH_DIFF_THROTTLE_S = 2.0  # min seconds between branch git_diff refreshes

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
        # Mirror of the current node's cell_source — avoids a SELECT per cell.
        # Refreshed whenever _current_node_id changes via _switch_to_node().
        self._current_cell_source: str = ""
        self._last_branch_diff_refresh: float = 0.0

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

    def record_cell(self, source: str) -> None:
        """Append a cell's source to the *current* node's cell_source field.

        Cells are written live so the dashboard shows what's running under
        the active branch/checkpoint immediately. Session magics are skipped.
        Repeated runs of the same cell (immediate re-execution) are deduped.
        """
        if not self.session_id or not source or not self._current_node_id:
            return
        if self._is_session_cell(source):
            return
        recorded = self._strip_session_magics(source)
        if not recorded:
            return
        existing = self._current_cell_source
        last = existing.rsplit(self._CELL_SEPARATOR, 1)[-1] if existing else ""
        if last.strip() == recorded.strip():
            return
        new_blob = (existing + (self._CELL_SEPARATOR if existing else "") + recorded)
        if len(new_blob) > _NODE_CELLS_MAX_BYTES:
            new_blob = ("# … earlier cells elided to bound memory …"
                        + self._CELL_SEPARATOR
                        + new_blob[-_NODE_CELLS_MAX_BYTES:])
        conn = get_db()
        conn.execute(
            "UPDATE session_nodes SET cell_source=? WHERE id=?",
            (new_blob, self._current_node_id),
        )
        self._current_cell_source = new_blob
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

    def _switch_to_node(self, node_id: str) -> None:
        """Set _current_node_id and refresh the cached cell_source."""
        self._current_node_id = node_id
        row = self._get_node(node_id, "cell_source")
        self._current_cell_source = (row["cell_source"]
                                     if row and row["cell_source"] else "")

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
        """Return id of an existing child node with this label/parent/type,
        or None. Caller passes the full type tuple it wants to consider."""
        placeholders = ",".join("?" * len(types))
        row = get_db().execute(
            f"SELECT id FROM session_nodes WHERE session_id=? AND parent_id=? "
            f"AND label=? AND node_type IN ({placeholders}) "
            f"ORDER BY seq DESC LIMIT 1",
            (self.session_id, parent_id, label, *types),
        ).fetchone()
        return row["id"] if row else None

    def checkpoint(self, label: str) -> str | None:
        """Add a checkpoint under the current node, or reuse an existing
        checkpoint with the same label (idempotent re-runs)."""
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
            diff = _git("diff", prev_commit, commit)
        else:
            diff = _git("diff", "HEAD")
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
        abandoned branch if one exists with this label."""
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
            return existing

        conn = get_db()
        nid = _new_id()
        now = time.time()
        commit = _git("rev-parse", "--short", "HEAD")
        diff = self._compute_diff_vs_checkpoint(self._last_checkpoint_id, commit)
        conn.execute(
            "INSERT INTO session_nodes (id, session_id, parent_id, node_type, "
            "label, git_diff, git_commit, seq, created_at) "
            "VALUES (?, ?, ?, 'branch', ?, ?, ?, ?, ?)",
            (nid, self.session_id, self._last_checkpoint_id, label,
             diff or None, commit or None, self._next_seq(), now),
        )
        conn.commit()
        self._switch_to_node(nid)
        return nid

    def _compute_diff_vs_checkpoint(self, checkpoint_id: str | None,
                                    head_commit: str | None) -> str:
        """Diff from parent checkpoint's commit to current working tree."""
        prev_commit = None
        if checkpoint_id:
            row = self._get_node(checkpoint_id, "git_commit")
            if row:
                prev_commit = row["git_commit"]
        if prev_commit and head_commit and prev_commit != head_commit:
            committed = _git("diff", prev_commit, head_commit) or ""
            working = _git("diff", "HEAD") or ""
            return (committed + ("\n" + working if working else "")).strip()
        if prev_commit:
            return _git("diff", prev_commit) or ""
        return _git("diff", "HEAD") or ""

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
        "WHERE n.session_id=? ORDER BY n.seq",
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
