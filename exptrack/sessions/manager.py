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
_NODE_SETUP_MAX_BYTES = 256 * 1024  # separate soft cap for %%setup prep blocks
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
        # One-shot guard for auto-linking the notebook's run to this session.
        self._auto_linked_run_id: str | None = None

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
            if (s.startswith("%%scratch") or s.startswith("%%pin")
                    or s.startswith("%%setup")):
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

    @staticmethod
    def _strip_setup_magic(source: str) -> str:
        """Drop the leading `%%setup` line from a setup cell so the recorded
        version only carries the user's prep code."""
        lines = source.splitlines()
        out: list[str] = []
        dropped = False
        for ln in lines:
            if not dropped and ln.strip().startswith("%%setup"):
                dropped = True
                continue
            out.append(ln)
        return "\n".join(out).strip()

    @classmethod
    def _append_cell_segment(cls, src_blob: str, out_blob: str, recorded: str,
                             out_str: str, cap: int):
        """Append one (source, output) segment to a SEP-joined pair of blobs.

        Returns (new_src, new_out) or None when nothing changed (an immediate
        re-run of the same cell whose output is unchanged). Keeps the two blobs
        segment-aligned and elides oldest segments together once over `cap`.
        Shared by the setup store; record_cell keeps its own inline copy because
        it interleaves git-diff/collision bookkeeping."""
        src_parts = src_blob.split(cls._CELL_SEPARATOR) if src_blob else []
        out_parts = out_blob.split(cls._CELL_SEPARATOR) if out_blob else []
        while len(out_parts) < len(src_parts):
            out_parts.append("")
        if src_parts and src_parts[-1].strip() == recorded.strip():
            if out_str and out_parts and out_parts[-1] != out_str:
                out_parts[-1] = out_str
            else:
                return None
        else:
            src_parts.append(recorded)
            out_parts.append(out_str)
            sep_len = len(cls._CELL_SEPARATOR)
            total = sum(len(p) for p in src_parts) + sep_len * (len(src_parts) - 1)
            if total > cap:
                while len(src_parts) > 1 and total > cap:
                    total -= len(src_parts.pop(0)) + sep_len
                    out_parts.pop(0)
                src_parts.insert(0, "# … earlier cells elided to bound memory …")
                out_parts.insert(0, "")
        return (cls._CELL_SEPARATOR.join(src_parts),
                cls._CELL_SEPARATOR.join(out_parts))

    def record_setup_cell(self, source: str, output: str | None = None) -> None:
        """Append a `%%setup` cell to the current node's *demoted* setup store.

        Setup cells are recorded but secondary: kept off the tracked-cell
        lineage and git-diff bookkeeping, stored in their own byte-budgeted
        columns so a big prep block can't evict real recorded cells. Used so the
        provenance of a `df` built under a branch survives a promote without a
        rerun or a giant diff."""
        if not self.session_id or not source or not self._current_node_id:
            return
        recorded = self._strip_setup_magic(source)
        if not recorded:
            return
        row = self._get_node(self._current_node_id, "setup_source, setup_outputs")
        src_blob = row["setup_source"] if row and row["setup_source"] else ""
        out_blob = row["setup_outputs"] if row and row["setup_outputs"] else ""
        res = self._append_cell_segment(
            src_blob, out_blob, recorded, output or "", _NODE_SETUP_MAX_BYTES)
        if res is None:
            return
        new_src, new_out = res
        conn = get_db()
        conn.execute(
            "UPDATE session_nodes SET setup_source=?, setup_outputs=? WHERE id=?",
            (new_src, new_out or None, self._current_node_id),
        )
        conn.commit()

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
        self._auto_linked_run_id = None

    def autolink_run(self, exp_id: str) -> None:
        """Group a notebook's auto-created run under the current node, once.

        Without this a session's run floats as a separate, unconnected
        experiment. Called by the notebook hook on each real cell; idempotent
        (the `_auto_linked_run_id` guard skips repeat work) and never overrides
        an explicit `promote` — the guarded UPDATE only fills a NULL link."""
        if not exp_id or self._auto_linked_run_id == exp_id:
            return
        if not self.session_id or not self._current_node_id:
            return
        conn = get_db()
        conn.execute(
            "UPDATE experiments SET session_node_id=? "
            "WHERE id=? AND session_node_id IS NULL",
            (self._current_node_id, exp_id),
        )
        conn.commit()
        self._auto_linked_run_id = exp_id

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


def link_experiment(node_id: str, exp_id: str) -> dict[str, Any]:
    """Link (promote) an experiment to a live session node — the dashboard
    equivalent of `%exptrack promote`.

    A blank `exp_id` unlinks whatever experiment currently points at the node.
    Linking is 1:1: any other run on the node is detached first (`_detach_experiments`)
    so its `→ exp` badge is unambiguous. Only the `experiments.session_node_id`
    pointer is touched — the experiment row is never modified or deleted.
    Returns {ok, linked} (the resolved full id, or None on unlink) or
    {ok: False, error}."""
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM session_nodes WHERE id=? AND deleted_at IS NULL",
        (node_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "node not found"}
    exp_id = (exp_id or "").strip()
    if not exp_id:
        _detach_experiments(conn, [node_id])
        conn.commit()
        return {"ok": True, "linked": None}
    erow = conn.execute(
        "SELECT id FROM experiments WHERE id LIKE ? AND deleted_at IS NULL",
        (exp_id + "%",),
    ).fetchone()
    if not erow:
        return {"ok": False, "error": "experiment not found"}
    _detach_experiments(conn, [node_id])
    conn.execute(
        "UPDATE experiments SET session_node_id=? WHERE id=?",
        (node_id, erow["id"]),
    )
    conn.commit()
    return {"ok": True, "linked": erow["id"]}


def promote_to_checkpoint(node_id: str) -> dict[str, Any]:
    """Convert a branch (or abandoned branch) node into a checkpoint.

    The branch's current `git_diff` — which is refreshed live as cells run — is
    simply frozen in place (checkpoints don't refresh their diff). Returns
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


def materialize_experiment(node_id: str) -> dict[str, Any]:
    """Create a standalone experiment from a session node's captured data and
    link it (sets experiments.session_node_id).

    This is the dashboard equivalent of `%exptrack promote` for a node that has
    no live notebook run behind it: it turns an exploratory branch/checkpoint
    into a first-class experiment by copying the node's name (label), git
    commit/diff, branch, and note, and replaying its recorded cells as
    `cell_exec` timeline events so the run's Timeline shows the code + output.
    Refuses the root and trashed nodes, and refuses a node that already has a
    linked run (returns the existing id)."""
    conn = get_db()
    row = conn.execute(
        "SELECT n.*, s.git_branch AS sess_branch, s.name AS sess_name "
        "FROM session_nodes n LEFT JOIN sessions s ON s.id = n.session_id "
        "WHERE n.id=? AND n.deleted_at IS NULL",
        (node_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "node not found"}
    if row["node_type"] == "root":
        return {"ok": False, "error": "cannot promote the session root"}
    existing = conn.execute(
        "SELECT id FROM experiments WHERE session_node_id=? AND deleted_at IS NULL",
        (node_id,),
    ).fetchone()
    if existing:
        return {"ok": False, "id": existing["id"],
                "error": "node already linked to experiment " + existing["id"][:8]}

    import platform
    import socket
    from datetime import datetime, timezone

    from ..config import load as load_config
    from ..core.db import store_git_diff

    exp_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    # Backdate created_at to when the node ran (it's a unix float) so the run
    # sorts with the work it came from; updated_at stays "now".
    created_at = now
    if row["created_at"]:
        try:
            created_at = datetime.fromtimestamp(
                float(row["created_at"]), timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            pass
    name = (row["label"] or "").strip() or f"{row['sess_name'] or 'session'} node"
    # Dedup the git diff by hash like the canonical save path does, so a node's
    # diff doesn't get a second inline copy in the experiments row.
    git_diff = row["git_diff"]
    if git_diff:
        try:
            git_diff = store_git_diff(conn, git_diff)
        except Exception:
            pass  # fall back to storing inline

    # Lineage breadcrumb: walk the parent chain back to root so the materialized
    # run records where in the tree it came from (checkpoint → branch path),
    # which is otherwise lost once it's a standalone experiment.
    lineage = _node_lineage_labels(conn, node_id)
    note_parts = []
    if lineage:
        kind = row["node_type"] or "node"
        note_parts.append(f"From session '{row['sess_name'] or 'session'}' "
                          f"({kind}): {' → '.join(lineage)}")
    if row["note"]:
        note_parts.append(row["note"])
    notes = "\n\n".join(note_parts) or None

    conn.execute(
        "INSERT INTO experiments (id, project, name, status, created_at, updated_at, "
        "git_branch, git_commit, git_diff, hostname, python_ver, notes, tags, studies, "
        "session_node_id, name_is_auto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (exp_id, load_config().get("project", ""), name, "done", created_at, now,
         row["sess_branch"], row["git_commit"], git_diff,
         socket.gethostname(), platform.python_version(),
         notes, "[]", "[]", node_id, 0),
    )

    # Replay the node's cells as cell_exec timeline events (source + output) so
    # the materialized run is browsable on its own, not just a metadata stub.
    # %%setup prep cells are replayed first as muted `setup` events so the code
    # that built referenced vars/frames stays with the run.
    #
    # Each cell's FULL source is also written to the content-addressed
    # `cell_lineage` table and the event's `cell_hash` set to point at it, so the
    # Timeline's "view source" button appears and can show + copy the whole cell
    # — otherwise only the first-line preview survives the promotion and the
    # session code isn't really transitioned over (you can't retrace/rerun it).
    from ..capture.cell_lineage import cell_hash as _cell_hash
    seq = 0
    # tuple shape: (exp_id, seq, event_type, cell_hash, cell_pos, key, value, ts)
    events: list[tuple] = []
    lineage_rows: list[tuple] = []  # (cell_hash, notebook, source, parent_hash, created_at)
    notebook = (row["sess_name"] or "session")
    setup_src = row["setup_source"] or ""
    setup_cells = (setup_src.split(SessionManager._CELL_SEPARATOR)
                   if setup_src else [])
    setup_outs = ((row["setup_outputs"] or "").split(SessionManager._CELL_SEPARATOR)
                  if row["setup_outputs"] else [])
    for i, c in enumerate(setup_cells):
        # Setup cells render their full source inline (no view-source button), so
        # they don't need a cell_lineage row — store_preview carries the source.
        events.append(
            (exp_id, seq, "setup", None, None, f"setup_{i + 1}",
             json.dumps({"source_preview": c,
                         "output_preview": (setup_outs[i] if i < len(setup_outs) else "").strip()}),
             now))
        seq += 1

    src = row["cell_source"] or ""
    cells = src.split(SessionManager._CELL_SEPARATOR) if src else []
    outs = ((row["cell_outputs"] or "").split(SessionManager._CELL_SEPARATOR)
            if row["cell_outputs"] else [])
    for i, c in enumerate(cells):
        ch = _cell_hash(c) if c.strip() else None
        if ch:
            lineage_rows.append((ch, notebook, c, None, now))
        events.append(
            (exp_id, seq, "cell_exec", ch, i + 1, f"cell_{i + 1}",
             json.dumps({"source_preview": c,
                         "output_preview": (outs[i] if i < len(outs) else "").strip()}),
             now))
        seq += 1
    if lineage_rows:
        # Content-addressed: cell_hash is the PK, so OR IGNORE dedups a cell that
        # already exists from a live capture or another promoted node.
        conn.executemany(
            "INSERT OR IGNORE INTO cell_lineage "
            "(cell_hash, notebook, source, parent_hash, created_at) VALUES (?,?,?,?,?)",
            lineage_rows,
        )
    conn.executemany(
        "INSERT INTO timeline (exp_id, seq, event_type, cell_hash, cell_pos, key, value, ts) "
        "VALUES (?,?,?,?,?,?,?,?)",
        events,
    )

    # Register the node's by-reference plots as artifacts so they show up in the
    # materialized run's Images tab / artifacts (capture is by reference — no
    # copy, matching the rest of exptrack).
    imgs = _node_images(row["images"])
    if imgs:
        from ..core.hashing import file_hash
        art_rows = []
        for im in imgs:
            p = im.get("path")
            if not p:
                continue
            try:
                content_hash, size_bytes = file_hash(p)
            except Exception:
                content_hash, size_bytes = "", 0
            label = im.get("label") or os.path.basename(p)
            art_rows.append((exp_id, label, p, content_hash, size_bytes, None, now))
        if art_rows:
            conn.executemany(
                "INSERT INTO artifacts (exp_id, label, path, content_hash, "
                "size_bytes, timeline_seq, created_at) VALUES (?,?,?,?,?,?,?)",
                art_rows,
            )

    conn.commit()
    return {"ok": True, "id": exp_id, "name": name}


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
    caller / UI; here we just return the flat, session-annotated list."""
    conn = conn or get_db()
    rows = conn.execute(
        "SELECT n.id, n.session_id, n.parent_id, n.node_type, n.label, n.seq, "
        "       n.created_at, n.deleted_at, length(n.cell_source) AS cell_bytes, "
        "       s.name AS session_name, s.status AS session_status "
        "FROM session_nodes n JOIN sessions s ON s.id = n.session_id "
        "WHERE n.deleted_at IS NOT NULL "
        "ORDER BY n.deleted_at DESC, n.seq",
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
            "setup_source": r["setup_source"],
            "setup_outputs": r["setup_outputs"],
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
            "setup_source": None,
            "setup_outputs": None,
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

    # Attach an id-bearing lineage (root → … → parent, excluding the node itself
    # and the synthetic/root node) to every node so the dashboard can render a
    # clickable breadcrumb in the node detail — rides the existing payload.
    for n in by_id.values():
        chain: list[dict] = []
        seen2: set[str] = set()
        cur = n["parent_id"]
        while cur and cur in by_id and cur not in seen2:
            seen2.add(cur)
            p = by_id[cur]
            if p["node_type"] != "root":
                chain.append({"id": p["id"], "label": p["label"],
                              "node_type": p["node_type"]})
            cur = p["parent_id"]
        chain.reverse()
        n["lineage"] = chain

    # Per-session outcome summary: the experiments this session produced plus
    # node-type counts, surfaced in the tree header so "what did this session
    # give me?" is answerable at a glance. Read-only aggregate.
    exp_rows = conn.execute(
        "SELECT e.id, e.name, e.status, e.created_at "
        "FROM experiments e JOIN session_nodes n ON n.id = e.session_node_id "
        "WHERE n.session_id=? AND n.deleted_at IS NULL AND e.deleted_at IS NULL "
        "ORDER BY e.created_at DESC",
        (session_id,),
    ).fetchall()
    type_counts = {"checkpoint": 0, "branch": 0, "abandoned": 0}
    for n in by_id.values():
        t = n["node_type"]
        if t in type_counts:
            type_counts[t] += 1
    outcomes = {
        "experiments": [
            {"id": r["id"], "name": r["name"], "status": r["status"]}
            for r in exp_rows
        ],
        "checkpoints": type_counts["checkpoint"],
        "branches": type_counts["branch"],
        "abandoned": type_counts["abandoned"],
    }

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
            "outcomes": outcomes,
        },
        "root": root or {},
    }
