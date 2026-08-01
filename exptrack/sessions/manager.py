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
from ..core.utils import debug_log
from . import _shared

# Shared state/constants/helpers used by the class + build_tree, plus the
# back-compat re-export surface: historically every session helper lived in
# this module and callers import them straight from here (incl.
# core/queries.py's `_node_lineage_labels`), so keep that intact after the
# split. (noqa: F401 — the names not used in this file are deliberately
# re-exported.)
from ._shared import (  # noqa: F401  (re-exported)
    _ELIDED_MARKER,
    _NODE_CELLS_MAX_BYTES,
    _NODE_IMAGES_MAX,
    _NODE_SETUP_MAX_BYTES,
    _collect_descendants,
    _count_cells,
    _count_node_images,
    _detach_experiments,
    _group_run_into_session_study,
    _image_paths_for_nodes,
    _is_elided,
    _nearest_live_checkpoint,
    _new_id,
    _node_images,
    _node_lineage_labels,
    _resolve_node_diff,
    _session_study_name,
    _store_node_diff,
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
        # Kept so start() can tell a replay of this session from a request to
        # start a different one, without re-reading the row it wrote.
        self.session_name: str | None = None
        self._current_node_id: str | None = None
        self._last_checkpoint_id: str | None = None
        # Mirror of the current node's cell_source / cell_outputs — avoids a
        # SELECT per cell. Refreshed whenever _current_node_id changes via
        # _switch_to_node(). The two blobs stay segment-aligned (one output
        # per recorded cell).
        self._current_cell_source: str = ""
        self._current_cell_outputs: str = ""
        # Cursor into the current node's recorded cells while a Run-All replays
        # them, and the index of the cell most recently recorded. Together these
        # make re-running a node's cells refresh what's stored instead of
        # appending a second copy of the same code. Reset on every node switch
        # (see _switch_to_node) because a Run-All re-enters the node from the
        # top. None = not replaying / nothing recorded yet.
        self._replay_idx: int | None = None
        self._last_cell_idx: int | None = None
        # The same pair for the *setup* store (`%%setup` cells), which is its
        # own blob and so needs its own cursors: without them the setup store
        # deduped only against its last segment, so a Run-All over a node with
        # two or more setup cells appended a fresh copy of every one on every
        # pass — doubling the blob until the byte cap began evicting real
        # content, and replaying each duplicate as its own timeline event on
        # materialize.
        self._setup_replay_idx: int | None = None
        self._last_setup_idx: int | None = None
        # One-shot guard for `branch("X")` reusing an existing label. We can't
        # tell at branch() time whether this is a Run-All re-run (merge) or a
        # new idea reusing the name (fork) — the code hasn't run yet. So we arm
        # this and let the next recorded cell decide by comparing first-cell
        # source. See record_cell()/branch().
        self._pending_collision: dict[str, Any] | None = None
        # One-shot guard for auto-linking the notebook's run to this session.
        self._auto_linked_run_id: str | None = None
        # True when the last start() re-adopted an existing session (kernel
        # restart) rather than creating one — the magic reports which happened.
        self.reattached: bool = False
        # One-shot guard so a session removed in another process is reported
        # once, not on every recorded cell.
        self._liveness_warned: bool = False

    # ── cell capture ────────────────────────────────────────────────────────

    # Shared constant re-exposed as a class attr for back-compat.
    _CELL_SEPARATOR = _shared._CELL_SEPARATOR

    @staticmethod
    def _is_session_cell(source: str) -> bool:
        """True if the *entire* cell should be skipped from recording.

        - Cell magics `%%scratch` / `%%setup` at the top: own the whole cell,
          skip entirely (scratch is never recorded; setup goes to the node's
          own demoted store).
        - Cells that are nothing but `%exptrack` line magics (plus blanks
          and comments): nothing to record.

        Cells with `%exptrack` on the first line followed by real code are
        NOT session cells — the magic lines are stripped and the remainder
        is recorded. That covers the natural pattern of putting the magic
        at the top of a working cell.

        **`%%pin` is not a session cell.** A pinned cell is real code whose
        result the user thought worth keeping, and it was already tracked in the
        experiment's cell lineage — excluding it from the node meant the one cell
        most worth carrying was the one a materialized run didn't replay.
        """
        if not source:
            return True
        for ln in source.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("%%scratch") or s.startswith("%%setup"):
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
        version only contains the user's actual code — plus a leading `%%pin`
        line, whose body *is* recorded (see `_is_session_cell`). `%%scratch` /
        `%%setup` cells are handled elsewhere."""
        kept = [ln for ln in source.splitlines()
                if not ln.strip().startswith("%exptrack")
                and not ln.strip().startswith("%%pin")]
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

    # How far ahead of the replay cursor a Run-All may look for the segment it
    # is re-running. A single inserted or edited cell mid-node shifts every
    # later cell by one, and an exact-index-only cursor would never realign —
    # the rest of the pass appended a second copy of every remaining cell, and
    # every later pass did it again. A small bounded window realigns after such
    # an edit while keeping the match local enough that a genuinely new cell
    # that merely resembles a much later one is still recorded as new.
    _REPLAY_LOOKAHEAD = 8

    @classmethod
    def _match_segment(cls, parts: list[str], recorded: str,
                       last_idx: int | None,
                       replay_idx: int | None) -> int | None:
        """Index of the already-recorded segment this execution repeats, else
        None. Shared by the tracked-cell and `%%setup` stores, which each keep
        their own cursor pair over their own blob.

        Two ways an execution can be a repeat rather than new work:

        - It re-runs the segment recorded most recently (`last_idx`) — the user
          hit Ctrl-Enter twice.
        - It matches at or just after the replay cursor (`replay_idx`) — a
          Run-All is stepping through the store's existing segments in their
          original order, possibly skipping one the user deleted or edited.

        Anything else is genuinely new and gets appended.
        """
        target = recorded.strip()
        if last_idx is not None and 0 <= last_idx < len(parts) \
                and parts[last_idx].strip() == target:
            return last_idx
        if replay_idx is None:
            return None
        start = max(0, replay_idx)
        for idx in range(start, min(len(parts), start + cls._REPLAY_LOOKAHEAD)):
            if _is_elided(parts[idx]):
                continue
            if parts[idx].strip() == target:
                return idx
        return None

    @classmethod
    def _initial_replay_idx(cls, blob: str) -> int:
        """Where to arm a replay cursor when entering a node.

        Index 0, unless the store tripped its byte cap and starts with the
        elision placeholder — a cursor parked on that marker can never match an
        incoming cell, so one cap trip used to defeat replay dedup permanently
        and the node re-appended its whole contents on every later pass.
        """
        if not blob:
            return 0
        first = blob.split(cls._CELL_SEPARATOR)[0]
        return 1 if _is_elided(first) else 0

    @classmethod
    def _record_segment(cls, src_blob: str, out_blob: str, recorded: str,
                        out_str: str, cap: int, last_idx: int | None,
                        replay_idx: int | None):
        """Append or refresh one (source, output) segment in a SEP-joined pair.

        Returns ``(new_src, new_out, last_idx, replay_idx)`` with the cursors
        already advanced. ``new_src`` is None when there is nothing to persist (a
        repeat whose output is unchanged too) — the cursors still move, since a
        Run-All whose outputs are identical must stay recognized past its first
        segment.

        The one implementation of the segment rules, used by both stores: keeps
        the two blobs aligned (one output per source), refreshes a repeat in
        place rather than appending a copy, and elides oldest segments in pairs
        once over `cap`. `record_cell` used to carry its own inline copy of all
        of that, so the byte-budget arithmetic and the elision sentinel existed
        twice, 140 lines apart, with the tracked-cell and setup stores free to
        drift apart on exactly the duplication bugs this logic exists to prevent.
        """
        sep = cls._CELL_SEPARATOR
        src_parts = src_blob.split(sep) if src_blob else []
        out_parts = out_blob.split(sep) if out_blob else []
        # Older DBs / partial writes may leave a shorter outputs blob.
        while len(out_parts) < len(src_parts):
            out_parts.append("")

        idx = cls._match_segment(src_parts, recorded, last_idx, replay_idx)
        if idx is not None:
            # A repeat: cursors advance whether or not the output changed.
            if not out_str or out_parts[idx] == out_str:
                return None, None, idx, idx + 1
            out_parts[idx] = out_str
            return sep.join(src_parts), sep.join(out_parts), idx, idx + 1

        src_parts.append(recorded)
        out_parts.append(out_str)
        sep_len = len(sep)
        total = sum(len(p) for p in src_parts) + sep_len * (len(src_parts) - 1)
        if total > cap:
            while len(src_parts) > 1 and total > cap:
                total -= len(src_parts.pop(0)) + sep_len
                out_parts.pop(0)
            src_parts.insert(0, _ELIDED_MARKER)
            out_parts.insert(0, "")
        # New work means we've diverged from whatever was recorded before, so
        # any in-progress replay is over.
        return sep.join(src_parts), sep.join(out_parts), len(src_parts) - 1, None

    def record_setup_cell(self, source: str, output: str | None = None) -> None:
        """Append a `%%setup` cell to the current node's *demoted* setup store.

        Setup cells are recorded but secondary: kept off the tracked-cell
        lineage and git-diff bookkeeping, stored in their own byte-budgeted
        columns so a big prep block can't evict real recorded cells. Used so the
        provenance of a `df` built under a branch survives a promote without a
        rerun or a giant diff. Replay recognition is the same as for tracked
        cells, against this store's own cursors."""
        if not self.session_id or not source or not self._current_node_id:
            return
        recorded = self._strip_setup_magic(source)
        if not recorded:
            return
        # Same collision arbitration tracked cells get: `branch("X")` on a reused
        # label defers the merge-or-fork decision to the first cell that runs
        # under it, and that first cell may well be a `%%setup` block.
        self._resolve_branch_collision(recorded)
        if self._write_setup_segment(recorded, output or ""):
            return
        # The node was trashed out from under us (dashboard / CLI in another
        # process). Re-anchor and write the cell where it can still be kept.
        if self._recover_current_node():
            self._write_setup_segment(recorded, output or "")

    def _write_setup_segment(self, recorded: str, out_str: str) -> bool:
        """Write one setup segment onto the current node. False if the node row
        is gone or trashed (the caller re-anchors and retries)."""
        row = self._get_node(self._current_node_id, "setup_source, setup_outputs")
        if row is None:
            return False
        new_src, new_out, self._last_setup_idx, self._setup_replay_idx = \
            self._record_segment(
                row["setup_source"] if row["setup_source"] else "",
                row["setup_outputs"] if row["setup_outputs"] else "",
                recorded, out_str, _NODE_SETUP_MAX_BYTES,
                self._last_setup_idx, self._setup_replay_idx)
        if new_src is None:
            return True
        conn = get_db()
        cur = conn.execute(
            "UPDATE session_nodes SET setup_source=?, setup_outputs=? "
            "WHERE id=? AND deleted_at IS NULL",
            (new_src, new_out or None, self._current_node_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def record_cell(self, source: str, output: str | None = None) -> None:
        """Record a cell's source (and its output) on the *current* node.

        `cell_source` and `cell_outputs` are kept segment-aligned: each
        recorded cell contributes one source segment and one output segment
        (the trailing-expression repr, or "" when the cell produced none).
        Cells are written live so the dashboard shows what ran — and what it
        produced — under the active branch/checkpoint immediately. Session
        magics are skipped.

        **Re-running a cell refreshes it in place rather than appending a
        second copy.** That covers a back-to-back re-execution *and* a Run-All
        replaying the whole node (see `_match_segment`); without the replay
        cursor every Run-All doubled the node's stored cells until the byte cap
        started evicting the real content.
        """
        if not self.session_id or not source or not self._current_node_id:
            return
        if self._is_session_cell(source):
            return
        recorded = self._strip_session_magics(source)
        if not recorded:
            return
        self._resolve_branch_collision(recorded)
        if self._write_cell_segment(recorded, output or ""):
            return
        # Rowcount 0 means the node row is gone or trashed — another process
        # (the dashboard's node delete, `exptrack session rm-node`) mutated the
        # tree while this kernel kept recording. Re-anchor to a live node and
        # write the cell there rather than dropping it silently.
        if self._recover_current_node():
            self._write_cell_segment(recorded, output or "")

    def _write_cell_segment(self, recorded: str, out_str: str) -> bool:
        """Write one recorded cell onto the current node. Returns False if the
        node row is gone or trashed (the caller re-anchors and retries).

        The liveness check rides the UPDATE's own ``deleted_at IS NULL`` filter,
        so the common path costs nothing extra — no SELECT per recorded cell.
        """
        new_blob, new_out, self._last_cell_idx, self._replay_idx = \
            self._record_segment(
                self._current_cell_source, self._current_cell_outputs,
                recorded, out_str, _NODE_CELLS_MAX_BYTES,
                self._last_cell_idx, self._replay_idx)
        if new_blob is None:
            return True     # same code, same result — nothing to write
        conn = get_db()
        cur = conn.execute(
            "UPDATE session_nodes SET cell_source=?, cell_outputs=? "
            "WHERE id=? AND deleted_at IS NULL",
            (new_blob, new_out or None, self._current_node_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return False
        self._current_cell_source = new_blob
        self._current_cell_outputs = new_out
        return True

    # ── cross-process liveness ──────────────────────────────────────────────

    def _session_is_live(self) -> bool:
        """True if this session's row is still active and not trashed.

        The dashboard and the CLI can end, trash or purge a session while a
        kernel is still recording into it. One indexed lookup, called on
        structural operations only (checkpoint / branch / recovery) — never per
        recorded cell, which rides its UPDATE's own filter instead.
        """
        if not self.session_id:
            return False
        row = get_db().execute(
            "SELECT status FROM sessions WHERE id=? AND deleted_at IS NULL",
            (self.session_id,),
        ).fetchone()
        return bool(row) and row["status"] == "active"

    def _warn_session_gone(self) -> None:
        """Say once that the session went away under this kernel."""
        if getattr(self, "_liveness_warned", False):
            return
        self._liveness_warned = True
        print("[exptrack] this session was ended, trashed or removed elsewhere "
              "— session recording is paused. Restore it (or run "
              "'%exptrack session start \"<name>\"' again) to resume.",
              file=sys.stderr)

    def _ensure_live_anchor(self) -> bool:
        """Verify the session and the node a structural op will hang off are
        still live, re-anchoring if only the node is gone.

        Two indexed lookups at most, and only on `checkpoint()` / `branch()` —
        the per-cell paths ride their UPDATE's `deleted_at IS NULL` filter.
        """
        if not self._session_is_live():
            self._warn_session_gone()
            return False
        self._liveness_warned = False
        conn = get_db()
        # A trashed checkpoint anchor would otherwise be handed to the next
        # branch() as a parent, hanging a live node under a dead one.
        if self._last_checkpoint_id and not conn.execute(
                "SELECT 1 FROM session_nodes WHERE id=? AND deleted_at IS NULL",
                (self._last_checkpoint_id,)).fetchone():
            self._last_checkpoint_id = None
        anchor = self._current_node_id
        if anchor and conn.execute(
                "SELECT 1 FROM session_nodes WHERE id=? AND deleted_at IS NULL",
                (anchor,)).fetchone():
            if not self._last_checkpoint_id:
                self._last_checkpoint_id = _nearest_live_checkpoint(conn, anchor)
            return True
        return self._recover_current_node()

    def _recover_current_node(self) -> bool:
        """Re-anchor after the current node disappeared under us.

        Falls back to the live checkpoint anchor, else the session root — always
        through `_switch_to_node`, so the cached blobs and both replay cursors
        describe the node we actually landed on. Returns False (and pauses
        recording) when the whole session is gone.
        """
        if not self._session_is_live():
            self._warn_session_gone()
            return False
        conn = get_db()
        from .lifecycle import _session_root_id
        candidates = [self._last_checkpoint_id, _session_root_id(conn, self.session_id)]
        for nid in candidates:
            if not nid:
                continue
            row = conn.execute(
                "SELECT id FROM session_nodes WHERE id=? AND deleted_at IS NULL",
                (nid,),
            ).fetchone()
            if row:
                if self._current_node_id != nid:
                    print(f"[exptrack] the active session node was removed "
                          f"elsewhere — recording continues on {nid[:8]}.",
                          file=sys.stderr)
                self._switch_to_node(nid)
                self._last_checkpoint_id = _nearest_live_checkpoint(conn, nid)
                return True
        self._warn_session_gone()
        return False

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
        """Set _current_node_id and refresh the cached cell_source/outputs.

        Arms both replay cursors at their store's first cell: entering a node is
        exactly when a Run-All would start re-executing its cells from the top,
        so this is what lets `record_cell` / `record_setup_cell` recognize the
        replay and refresh in place instead of appending duplicates.

        **Every path that changes the current node must go through here.**
        Assigning `_current_node_id` directly leaves the cached blobs and both
        cursors describing the *previous* node, so the next recorded cell is
        written with the old node's cells prepended onto the new node — which is
        exactly how a deleted branch's code used to reappear on the checkpoint
        the deletion fell back to.
        """
        self._current_node_id = node_id
        row = self._get_node(node_id, "cell_source, cell_outputs, setup_source") \
            if node_id else None
        self._current_cell_source = (row["cell_source"]
                                     if row and row["cell_source"] else "")
        self._current_cell_outputs = (row["cell_outputs"]
                                      if row and row["cell_outputs"] else "")
        setup_src = row["setup_source"] if row and row["setup_source"] else ""
        # Arm past the elision placeholder when a store tripped its byte cap —
        # a cursor on the marker can never match, which killed dedup for good.
        self._replay_idx = self._initial_replay_idx(self._current_cell_source)
        self._last_cell_idx = None
        self._setup_replay_idx = self._initial_replay_idx(setup_src)
        self._last_setup_idx = None
        # A collision guard is armed for one specific node, so moving off that
        # node retires it. Clearing it here rather than at each call site is what
        # makes the "every path goes through here" invariant above cover all of
        # the per-node state; branch() re-arms it *after* switching.
        self._pending_collision = None

    def _get_node(self, node_id: str, cols: str = "*"):
        """Single-row id lookup — used in a few places."""
        return get_db().execute(
            f"SELECT {cols} FROM session_nodes WHERE id=?", (node_id,),
        ).fetchone()

    def _refresh_branch_diff(self) -> None:
        """Re-snapshot the current branch node's diff against its checkpoint.

        Called on **structural transitions only** — a new checkpoint, switching
        branches, a promote, or session end — i.e. the moments the user finishes
        with a branch. This used to run on every recorded cell (throttled to
        2 s, which interactive cells almost always exceed), so each cell paid for
        two or three `git` subprocesses plus a rewrite of the node's whole diff
        blob, overwhelmingly to store a byte-identical diff: exploration happens
        in cells, and cells are not in the working tree.

        The tradeoff is explicit — a working-tree edit made mid-branch lands on
        the node at the next transition rather than instantly. Nothing is lost,
        since every path that reads a branch's diff (promote, materialize,
        finalize, session end) passes through one of these transitions first.
        """
        if not self.session_id or not self._current_node_id:
            return
        try:
            row = self._get_node(self._current_node_id, "node_type, parent_id")
            if not row or row["node_type"] != "branch":
                return
            head = _git("rev-parse", "--short", "HEAD")
            diff = self._compute_diff_vs_checkpoint(row["parent_id"], head)
            conn = get_db()
            conn.execute(
                "UPDATE session_nodes SET git_diff=? WHERE id=?",
                (_store_node_diff(conn, diff), self._current_node_id),
            )
            conn.commit()
        except Exception as e:
            debug_log(f"could not refresh branch diff: {e}")

    def _find_ancestor_checkpoint(self, label: str) -> str | None:
        """Id of a live checkpoint with this label on the current node's
        ancestor path, or None.

        This is what makes a Run-All idempotent. Re-running the notebook
        re-executes `%exptrack checkpoint "base"` while the current node is
        still the branch from the previous pass, so the checkpoint was created
        *under that branch* — and the following `branch` under it — growing a
        fresh duplicate spine on every Run-All (each with its own cells and diff
        blob). Re-declaring a checkpoint that is already an ancestor means "the
        notebook is replaying from the top", so we return to it instead.

        The walk starts at the **current node itself**, not its parent, so
        re-declaring the checkpoint you are already standing on resolves here
        like any other replay. Starting at the parent made that case structurally
        invisible, and `checkpoint()` carried a special-cased early return to
        cover it — which returned the id without re-arming the replay cursors (so
        every cell of the node was appended again on each Run-All) and without
        updating `_last_checkpoint_id`.
        """
        conn = get_db()
        pid = self._current_node_id
        seen: set[str] = set()
        while pid and pid not in seen:
            seen.add(pid)
            row = conn.execute(
                "SELECT id, parent_id, node_type, label FROM session_nodes "
                "WHERE id=? AND deleted_at IS NULL", (pid,),
            ).fetchone()
            if not row:
                return None
            if row["node_type"] == "checkpoint" and row["label"] == label:
                return row["id"]
            pid = row["parent_id"]
        return None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def _find_reattachable_session(self, name: str, notebook: str) -> str | None:
        """Id of the newest live session this kernel should re-adopt, or None.

        A kernel restart (or a `%load_ext` in a fresh process) leaves the
        `SessionManager` singleton empty while the session's rows are still in
        the database, marked `active`. Re-running the notebook's first magic
        then INSERTed a *second* session with the same name, so a restart —
        routine in notebook work — silently forked the tree and split the
        session's checkpoints across two entries no view ever joins.

        Only an **active, non-trashed** session with the same name qualifies,
        newest first. The notebook must match too, but leniently: a session
        recorded without a detected notebook name (or a magic run before
        detection works) must not block re-adoption of the obvious candidate.
        """
        rows = get_db().execute(
            "SELECT id, notebook FROM sessions "
            "WHERE name=? AND status='active' AND deleted_at IS NULL "
            "ORDER BY created_at DESC",
            (name,),
        ).fetchall()
        want = (notebook or "").strip()
        for r in rows:
            have = (r["notebook"] or "").strip()
            if not want or not have or want == have:
                return r["id"]
        return None

    def start(self, name: str, notebook: str = "", *, new: bool = False) -> str:
        """Create a session and write its root node. Returns the session id, or
        `""` when a *differently named* session is already active.

        With no live session in *this* process, an existing active session of
        the same name is **re-adopted** rather than duplicated (see
        `_find_reattachable_session`) — that is what makes a session survive a
        kernel restart. `self.reattached` records which happened so callers can
        say so. Pass ``new=True`` to force a fresh session regardless.

        Re-declaring the **same** session returns to its root, because that is
        what re-executing the notebook's first magic means: it is replaying from
        the top (the same reasoning `_find_ancestor_checkpoint` applies to a
        re-declared checkpoint). Doing nothing left the current node wherever the
        previous pass ended, so the pre-checkpoint cells — imports, data loading
        — were recorded onto that node instead of the root, appending a copy on
        every pass while the root's own copies sat untouched.

        A **different** name while a session is live is a mistake rather than a
        replay, and returning `""` is how every caller learns that: the rule
        belongs here, next to the rewind it guards, not in the one magic that
        happens to call this today.
        """
        from .lifecycle import _session_root_id
        self.reattached = False
        if self.session_id:
            if name and self.session_name and name != self.session_name:
                return ""
            root = _session_root_id(get_db(), self.session_id)
            if root:
                self._switch_to_node(root)
                self._last_checkpoint_id = root
            return self.session_id

        if not new:
            existing = self._find_reattachable_session(name, notebook)
            if existing:
                root = _session_root_id(get_db(), existing)
                if root:
                    self.session_id = existing
                    self.session_name = name
                    self._liveness_warned = False
                    self._auto_linked_run_id = None
                    # Rewind to the root, exactly as a same-session re-declare
                    # does: a restarted kernel re-runs the notebook from the top,
                    # so the cells that follow belong to the root until the next
                    # checkpoint magic — and the replay cursors armed here are
                    # what keep them from being appended a second time.
                    self._switch_to_node(root)
                    self._last_checkpoint_id = root
                    self.reattached = True
                    return existing

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
        self.session_name = name
        self._switch_to_node(root_id)
        self._last_checkpoint_id = root_id
        return sid

    def end(self) -> None:
        """Mark session ended; mark trailing open branches as abandoned."""
        if not self.session_id:
            return
        # Ending the session is the last chance to capture the open branch's
        # working-tree state.
        self._refresh_branch_diff()
        # Mark any branch with no live child as abandoned, and flip the session
        # to 'ended'. Shared with the dashboard's end-session route so the two
        # can't drift (see end_session_rows).
        from .lifecycle import end_session_rows
        end_session_rows(get_db(), self.session_id)
        self.session_id = None
        self.session_name = None
        self._current_node_id = None
        self._last_checkpoint_id = None
        self._current_cell_source = ""
        self._current_cell_outputs = ""
        self._replay_idx = None
        self._last_cell_idx = None
        self._setup_replay_idx = None
        self._last_setup_idx = None
        self._pending_collision = None
        self._auto_linked_run_id = None
        self.reattached = False
        self._liveness_warned = False

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
        checkpoint with the same label (idempotent re-runs).

        A label already present as a child of the current node, *or anywhere on
        its ancestor path including the current node itself*, resolves to that
        node — which is what keeps a Run-All from rebuilding the whole spine
        underneath itself (see `_find_ancestor_checkpoint`). Every one of those
        cases lands on the single `_switch_to_node` below, so the replay cursors
        and `_last_checkpoint_id` are re-armed no matter which way it resolved.
        """
        if not self.session_id:
            return None
        # One indexed check per structural op: the session (and the node we are
        # about to hang this checkpoint off) may have been ended, trashed or
        # purged from the dashboard/CLI since the last magic ran.
        if not self._ensure_live_anchor():
            return None
        # Leaving a branch — freeze its diff before we move off it. A no-op when
        # the current node isn't a branch, which includes the re-declare case.
        self._refresh_branch_diff()
        parent_id = self._current_node_id or self._last_checkpoint_id
        existing = (self._find_child_by_label(parent_id, label, ("checkpoint",))
                    or self._find_ancestor_checkpoint(label))
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
             _store_node_diff(conn, diff), commit or None, self._next_seq(), now),
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
        if not self.session_id:
            return None
        if not self._ensure_live_anchor():
            return None
        if not self._last_checkpoint_id:
            return None
        # Moving off whatever branch we were on — freeze its diff first.
        self._refresh_branch_diff()
        existing = self._find_child_by_label(
            self._last_checkpoint_id, label, ("branch", "abandoned"))
        if existing:
            self._reactivate_branch(existing)
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

    @staticmethod
    def _reactivate_branch(node_id: str) -> None:
        """A branch re-entered by name becomes live again if it was abandoned.

        The `WHERE node_type='abandoned'` makes this a no-op for a node that is
        already live (or is a checkpoint), so no caller needs to read the row
        first — which is what both callers used to do, in two copies.
        """
        conn = get_db()
        conn.execute(
            "UPDATE session_nodes SET node_type='branch' "
            "WHERE id=? AND node_type='abandoned'",
            (node_id,),
        )
        conn.commit()

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
             _store_node_diff(conn, diff), commit or None, self._next_seq(), now),
        )
        conn.commit()
        return nid

    def _find_sibling_by_first_cell(self, parent_id: str,
                                    recorded: str) -> str | None:
        """A live sibling under `parent_id` whose first recorded cell is
        `recorded`, else None.

        This is what makes the collision fork idempotent. `_find_child_by_label`
        only ever resolves the *unsuffixed* label, so a second Run-All of an
        edited branch re-collided with the original node, compared against the
        original's first cell again, and forked yet another suffix — `A (2)`,
        `A (3)`, `A (4)`, one per pass, each with its own cells and diff blob:
        precisely the duplicate growth the Run-All handling exists to prevent.
        Recognizing the fork a previous pass already created merges into it.

        Identity is the **first recorded cell**, not the label: matching on a
        `"{label} ("` prefix instead looked reasonable and was defeated by the
        very thing the fork notice invites the user to do — rename the fork.
        A renamed (or promoted-to-checkpoint) fork stopped being findable and got
        re-forked on the next pass, so the label heuristic re-created the bug it
        was written to fix. Content matching is rename-proof and promote-proof,
        which is also why no `node_type` filter is applied.

        Only reached from the rare collision path, so reading the siblings'
        `cell_source` is not on any hot path.
        """
        target = recorded.strip()
        if not target:
            return None
        rows = get_db().execute(
            "SELECT id, cell_source FROM session_nodes "
            "WHERE session_id=? AND parent_id=? AND deleted_at IS NULL "
            "ORDER BY seq",
            (self.session_id, parent_id),
        ).fetchall()
        for r in rows:
            first = (r["cell_source"] or "").split(self._CELL_SEPARATOR)[0]
            if first.strip() == target:
                return r["id"]
        return None

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
        # A previous Run-All of this same edited branch already forked a node —
        # return to it rather than forking another.
        existing_fork = self._find_sibling_by_first_cell(pc["parent_id"], recorded)
        if existing_fork:
            self._reactivate_branch(existing_fork)
            self._switch_to_node(existing_fork)
            return
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
        # Promoting is a "capture this branch's state" moment, so make sure the
        # node's diff reflects the working tree as of now.
        self._refresh_branch_diff()
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
        # A trashed run is gone from every list, so its `→ exp` badge would link
        # to something the user can't open — the node stays visible, the badge
        # doesn't. Matches materialize's own already-filtered lookup.
        "LEFT JOIN experiments e ON e.session_node_id = n.id "
        "  AND e.deleted_at IS NULL "
        "WHERE n.session_id=? AND n.deleted_at IS NULL ORDER BY n.seq",
        (session_id,),
    ).fetchall()

    # Build node dict and child lists. Node diffs are stored content-addressed
    # (siblings off one checkpoint usually share a working tree, so they share
    # a blob), so each is resolved back to text here — memoized, since that
    # sharing means one body would otherwise be re-read once per node.
    diff_cache: dict[str, str] = {}
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
            "git_diff": _resolve_node_diff(conn, r["git_diff"], diff_cache),
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
