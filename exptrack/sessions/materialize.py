"""
exptrack/sessions/materialize.py — turn session nodes into standalone
experiments (materialize / link) and the metric/lineage helpers they need.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

from ..core.db import get_db
from ._shared import (
    _CELL_SEPARATOR,
    _detach_experiments,
    _group_run_into_session_study,
    _node_images,
    _node_lineage_labels,
    _unix_to_iso,
)


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
    srow = conn.execute(
        "SELECT session_id FROM session_nodes WHERE id=?", (node_id,),
    ).fetchone()
    _detach_experiments(conn, [node_id])
    conn.execute(
        "UPDATE experiments SET session_node_id=? WHERE id=?",
        (node_id, erow["id"]),
    )
    if srow:
        _group_run_into_session_study(conn, erow["id"], srow["session_id"])
    conn.commit()
    return {"ok": True, "linked": erow["id"]}


def materialize_experiment(node_id: str) -> dict[str, Any]:
    """Create a standalone experiment from a session node's captured data and
    link it (sets experiments.session_node_id).

    This is the dashboard equivalent of `%exptrack promote` for a node that has
    no live notebook run behind it: it turns an exploratory branch/checkpoint
    into a first-class experiment by copying the node's name (label), git
    commit/diff, branch, and note, and replaying the node's **whole ancestor
    chain** of cells (root → … → node) as `cell_exec` timeline events — so the
    run carries the upstream setup code (imports, data prep, helper defs) it
    depends on and is self-contained / re-runnable, not just the node's own
    fragment. Refuses the root and trashed nodes, and refuses a node that
    already has a linked run (returns the existing id)."""
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
    created_at = _unix_to_iso(row["created_at"]) or now
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

    # Replay cells as cell_exec timeline events (source + output) so the
    # materialized run is browsable AND re-runnable on its own — not just a
    # metadata stub. We replay the node's whole ANCESTOR CHAIN (root → … →
    # node), not only the node's own cells: a branch cell like
    # `run_pipeline(data, threshold)` needs the upstream cells that defined
    # `run_pipeline`/`data` to make sense, so a self-contained experiment must
    # carry them. %%setup prep cells of each ancestor are replayed (as muted
    # `setup` events) right before that ancestor's code.
    #
    # Each cell's FULL source is also written to the content-addressed
    # `cell_lineage` table and the event's `cell_hash` set to point at it, so the
    # Timeline's "view source" button appears and can show + copy the whole cell
    # — otherwise only the first-line preview survives the promotion and the
    # session code isn't really transitioned over (you can't retrace/rerun it).
    from ..capture.cell_lineage import cell_hash as _cell_hash
    SEP = _CELL_SEPARATOR
    seq = 0
    cell_pos = 0
    setup_pos = 0
    # tuple shape: (exp_id, seq, event_type, cell_hash, cell_pos, key, value, ts)
    events: list[tuple] = []
    lineage_rows: list[tuple] = []  # (cell_hash, notebook, source, parent_hash, created_at)
    notebook = (row["sess_name"] or "session")

    def _split(blob):
        return blob.split(SEP) if blob else []

    for anc in _node_ancestor_chain(conn, node_id):
        setup_cells = _split(anc["setup_source"])
        setup_outs = _split(anc["setup_outputs"])
        for i, c in enumerate(setup_cells):
            setup_pos += 1
            # Setup cells render their full source inline (no view-source
            # button), so they don't need a cell_lineage row.
            events.append(
                (exp_id, seq, "setup", None, None, f"setup_{setup_pos}",
                 json.dumps({"source_preview": c,
                             "output_preview": (setup_outs[i] if i < len(setup_outs) else "").strip()}),
                 now))
            seq += 1
        cells = _split(anc["cell_source"])
        outs = _split(anc["cell_outputs"])
        for i, c in enumerate(cells):
            ch = _cell_hash(c) if c.strip() else None
            if ch:
                lineage_rows.append((ch, notebook, c, None, now))
            cell_pos += 1
            events.append(
                (exp_id, seq, "cell_exec", ch, cell_pos, f"cell_{cell_pos}",
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

    # Attribute the session's metrics to this node by execution window. A
    # notebook session has ONE live auto-run that all `metric()` calls log into
    # (steps/ts but no node tag), so a materialized branch otherwise has the
    # code but not its own accuracy/loss. We copy the live run's metrics whose
    # timestamp falls in [this node's created_at, the next node's created_at) —
    # i.e. the metrics logged while this branch's cells were running — so each
    # graduated experiment is self-contained for comparison too.
    _copy_node_window_metrics(conn, row, exp_id)

    # Group the new run under the session's study so it stays with its siblings
    # (and survives the session being deleted).
    _group_run_into_session_study(conn, exp_id, row["session_id"])
    conn.commit()
    return {"ok": True, "id": exp_id, "name": name}


def _copy_node_window_metrics(conn, node_row, new_exp_id: str) -> int:
    """Copy the session's live-run metrics that were logged while this node's
    cells ran (ts in [node.created_at, next node's created_at)) onto the newly
    materialized run. Best-effort, returns the number copied.

    Notebook sessions log every `metric()` into one auto-created run; this
    re-attributes those points to the branch/checkpoint they belong to so a
    graduated experiment carries its own metrics, not just its code."""
    try:
        lower = float(node_row["created_at"])
    except (TypeError, ValueError):
        return 0
    session_id = node_row["session_id"]
    nxt = conn.execute(
        "SELECT MIN(created_at) AS c FROM session_nodes "
        "WHERE session_id=? AND deleted_at IS NULL AND created_at > ?",
        (session_id, lower),
    ).fetchone()
    lower_iso = _unix_to_iso(lower)
    upper_iso = _unix_to_iso(nxt["c"]) if nxt else None
    # Pull from every run linked to this session (the live auto-run), except the
    # run we're building. Window-filter on the ISO ts (UTC ISO sorts chronologically).
    rows = conn.execute(
        "SELECT m.key, m.value, m.step, m.ts, m.source FROM metrics m "
        "JOIN experiments e ON e.id = m.exp_id "
        "JOIN session_nodes n ON n.id = e.session_node_id "
        "WHERE n.session_id=? AND e.deleted_at IS NULL AND e.id != ? "
        "AND m.ts >= ? AND (? IS NULL OR m.ts < ?)",
        (session_id, new_exp_id, lower_iso, upper_iso, upper_iso),
    ).fetchall()
    if not rows:
        return 0
    conn.executemany(
        "INSERT INTO metrics (exp_id, key, value, step, ts, source) "
        "VALUES (?,?,?,?,?,?)",
        [(new_exp_id, r["key"], r["value"], r["step"], r["ts"],
          r["source"] or "auto") for r in rows],
    )
    return len(rows)


def _node_ancestor_chain(conn, node_id: str) -> list:
    """Return the node rows from root → … → node (inclusive, oldest first).

    A materialized experiment must be *self-contained* — runnable on its own.
    A branch cell like ``threshold = 0.7; run_pipeline(data, threshold)`` is
    meaningless without the ancestor cells that defined ``run_pipeline`` and
    ``data`` (typically on the session root / an upstream checkpoint). So
    materialization replays the whole ancestor chain's code, not just the
    node's own cells. Trashed ancestors are skipped."""
    # Fetch the node's whole (live) session in one query, then walk parent_id
    # pointers in memory — avoids a SELECT per hop (which `finalize` would
    # multiply across every materialized node).
    by_id = {
        r["id"]: r
        for r in conn.execute(
            "SELECT id, parent_id, node_type, label, setup_source, setup_outputs, "
            "cell_source, cell_outputs FROM session_nodes "
            "WHERE session_id = (SELECT session_id FROM session_nodes WHERE id=?) "
            "AND deleted_at IS NULL",
            (node_id,),
        ).fetchall()
    }
    chain: list = []
    seen: set[str] = set()
    cur = node_id
    while cur and cur not in seen and cur in by_id:
        seen.add(cur)
        r = by_id[cur]
        chain.append(r)
        cur = r["parent_id"]
    chain.reverse()
    return chain
