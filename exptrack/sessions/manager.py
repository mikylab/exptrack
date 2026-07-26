"""
exptrack/sessions/manager.py — SessionManager (the live session/tree recorder)
and tree reconstruction (build_tree).

The session subsystem is split across sibling modules; this module also
re-exports the lifecycle/materialize/shared helpers so long-standing imports
of the form ``from exptrack.sessions.manager import X`` keep working.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from ..core.db import get_db
from ..core.git import _git as git_run
from ..core.git import git_diff as _git_diff
from . import _shared

# Shared state/constants/helpers used by the class + build_tree, plus the
# back-compat re-export surface: historically every session helper lived in
# this module and callers import them straight from here (incl.
# core/queries.py's `_node_lineage_labels`), so keep that intact after the
# split. (noqa: F401 — the names not used in this file are deliberately
# re-exported.)
from ._shared import (  # noqa: F401  (re-exported)
    _BRANCH_DIFF_THROTTLE_S,
    _NODE_CELLS_MAX_BYTES,
    _NODE_IMAGES_MAX,
    _NODE_SETUP_MAX_BYTES,
    _collect_descendants,
    _count_node_images,
    _detach_experiments,
    _group_run_into_session_study,
    _image_paths_for_nodes,
    _new_id,
    _node_images,
    _node_lineage_labels,
    _session_study_name,
    _trash_node_images,
    _unix_to_iso,
    get_current_session,
    set_current_session,
)
from .lifecycle import (  # noqa: F401  (re-exported)
    delete_node,
    delete_session,
    empty_trash,
    finalize_session,
    finalize_session_preview,
    list_all_trashed_nodes,
    list_trashed_nodes,
    list_trashed_sessions,
    preview_node_delete,
    promote_to_checkpoint,
    purge_node,
    purge_session,
    rename_node,
    restore_node,
    restore_session,
)
from .materialize import (  # noqa: F401  (re-exported)
    link_experiment,
    materialize_experiment,
)

_git = git_run  # local alias for terseness inside this module

# Re-exported for back-compat: callers (and SessionManager below) reference
# `manager._CELL_SEPARATOR`. Bound via the module rather than imported by
# name so the class attr of the same name isn't read as a redefinition.
_CELL_SEPARATOR = _shared._CELL_SEPARATOR


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

    # Shared constant re-exposed as a class attr for back-compat.
    _CELL_SEPARATOR = _shared._CELL_SEPARATOR

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
        # Group the run under a study named after the session, so the runs from
        # one session stay grouped even after the session itself is deleted
        # (the session_node_id link is cleared on purge, but the study persists).
        _group_run_into_session_study(conn, exp_id, self.session_id)
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
        _group_run_into_session_study(conn, exp_id, self.session_id)
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
            # build_tree deliberately loads a trashed session (inspecting one
            # before restoring is legitimate, and the experiment back-link
            # navigates here), so the payload must say it's in the Trash —
            # otherwise the view is indistinguishable from a live session and
            # offers live-only actions on it.
            "session_deleted": s_row["deleted_at"] is not None,
            "outcomes": outcomes,
        },
        "root": root or {},
    }
