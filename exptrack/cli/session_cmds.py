"""
exptrack/cli/session_cmds.py — Session Trees CLI subcommands.

    exptrack sessions                  list sessions
    exptrack session show <id|name>    render tree as ASCII
    exptrack session nodes <id|name>   list nodes flat
    exptrack session rm <id>           delete session (preserves linked exps)
    exptrack session rm-node <node>    soft-delete a node + subtree (to Trash)
    exptrack session restore-node <n>  restore a trashed node + subtree
    exptrack session purge-node <n>    permanently delete a trashed node (no undo)
    exptrack session empty-trash <id>  permanently delete all trashed nodes
    exptrack session trash <id>        list a session's trashed nodes
    exptrack session rename-node <n> "label"  rename a node's label
    exptrack session note <node_id> "..."  annotate a node
"""
from __future__ import annotations

import sys
from datetime import datetime

from ..core.db import get_db
from ..sessions.manager import build_tree
from ..sessions.tree import find_session, list_sessions, render_ascii
from .formatting import C, DIM, G, R, RST, Y, bold, col, dim


def cmd_sessions(args):
    """List all sessions."""
    rows = list_sessions()
    if not rows:
        print(dim("(no sessions)"))
        return
    for r in rows:
        ts = ""
        if r.get("created_at"):
            try:
                ts = datetime.fromtimestamp(r["created_at"]).strftime("%m/%d %H:%M")
            except Exception:
                pass
        status = r.get("status") or "active"
        status_col = G if status == "ended" else Y
        line = (f"{r['id'][:8]}  {bold(r['name']):40}  "
                f"{col(status, status_col)}  {dim(ts)}  "
                f"checkpoints={r.get('checkpoints', 0)}  "
                f"promoted={r.get('promoted', 0)}")
        print(line)


def cmd_session_show(args):
    """Render a session tree."""
    s = find_session(args.id_or_name)
    if not s:
        print(col(f"session not found: {args.id_or_name}", R), file=sys.stderr)
        sys.exit(1)
    tree = build_tree(s["id"])
    print(render_ascii(tree))


def cmd_session_nodes(args):
    """List all nodes in a session (flat, for scripting)."""
    s = find_session(args.id_or_name)
    if not s:
        print(col(f"session not found: {args.id_or_name}", R), file=sys.stderr)
        sys.exit(1)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, parent_id, node_type, label, seq, created_at "
        "FROM session_nodes WHERE session_id=? ORDER BY seq",
        (s["id"],),
    ).fetchall()
    for r in rows:
        ts = ""
        if r["created_at"]:
            try:
                ts = datetime.fromtimestamp(r["created_at"]).strftime("%m/%d %H:%M")
            except Exception:
                pass
        print(f"{r['id'][:8]}  seq={r['seq']:>3}  {r['node_type']:10}  "
              f"{r['label']:40}  {dim(ts)}")


def cmd_session_rm(args):
    """Delete a session and its nodes. Linked experiments are preserved
    (their session_node_id is cleared)."""
    s = find_session(args.id_or_name)
    if not s:
        print(col(f"session not found: {args.id_or_name}", R), file=sys.stderr)
        sys.exit(1)
    from ..sessions.manager import delete_session
    delete_session(s["id"])
    print(col(f"deleted session {s['id'][:8]} ({s['name']})", G))


def cmd_session_rm_node(args):
    """Cascade-delete a single node and its descendants by id prefix.
    Refuses to delete the session root."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, label, node_type FROM session_nodes WHERE id LIKE ? LIMIT 1",
        (args.node_id + "%",),
    ).fetchone()
    if not row:
        print(col(f"node not found: {args.node_id}", R), file=sys.stderr)
        sys.exit(1)
    from ..sessions.manager import delete_node, preview_node_delete
    preview = preview_node_delete(row["id"])
    if not preview:
        print(col(f"node not found: {args.node_id}", R), file=sys.stderr)
        sys.exit(1)
    if preview.get("is_root"):
        print(col("cannot delete session root — use `exptrack session rm` instead", R),
              file=sys.stderr)
        sys.exit(1)
    label = preview.get("label") or "(unlabeled)"
    summary = (f"{preview['node_type']} \"{label}\" "
               f"({preview['nodes']} node{'s' if preview['nodes'] != 1 else ''}, "
               f"{preview['experiments']} linked exp"
               f"{'s' if preview['experiments'] != 1 else ''} preserved)")
    if not getattr(args, "yes", False):
        print(f"About to delete {summary}.")
        resp = input("Continue? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print(col("aborted", Y))
            return
    r = delete_node(row["id"])
    if not r.get("ok"):
        print(col(f"error: {r.get('error', 'unknown')}", R), file=sys.stderr)
        sys.exit(1)
    print(col(f"deleted {summary}", G))


def cmd_session_restore_node(args):
    """Restore a soft-deleted node (and its trashed subtree) by id prefix."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, label, node_type, deleted_at FROM session_nodes "
        "WHERE id LIKE ? LIMIT 1",
        (args.node_id + "%",),
    ).fetchone()
    if not row:
        print(col(f"node not found: {args.node_id}", R), file=sys.stderr)
        sys.exit(1)
    if row["deleted_at"] is None:
        print(col(f"node {row['id'][:8]} is not in the trash", Y), file=sys.stderr)
        sys.exit(1)
    from ..sessions.manager import restore_node
    r = restore_node(row["id"])
    if not r.get("ok"):
        print(col(f"error: {r.get('error', 'unknown')}", R), file=sys.stderr)
        sys.exit(1)
    label = row["label"] or "(unlabeled)"
    print(col(f"restored {row['node_type']} \"{label}\" ({r['nodes']} node"
              f"{'s' if r['nodes'] != 1 else ''})", G))


def cmd_session_purge_node(args):
    """Permanently delete a trashed node and its subtree by id prefix."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, label, node_type, deleted_at FROM session_nodes "
        "WHERE id LIKE ? LIMIT 1",
        (args.node_id + "%",),
    ).fetchone()
    if not row:
        print(col(f"node not found: {args.node_id}", R), file=sys.stderr)
        sys.exit(1)
    if row["deleted_at"] is None:
        print(col(f"node {row['id'][:8]} is not in the trash — "
                  f"use `session rm-node` to trash it first", Y), file=sys.stderr)
        sys.exit(1)
    label = row["label"] or "(unlabeled)"
    if not getattr(args, "yes", False):
        print(f"Permanently delete {row['node_type']} \"{label}\" and its trashed "
              f"subtree? This cannot be undone.")
        resp = input("Continue? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print(col("aborted", Y))
            return
    from ..sessions.manager import purge_node
    r = purge_node(row["id"])
    if not r.get("ok"):
        print(col(f"error: {r.get('error', 'unknown')}", R), file=sys.stderr)
        sys.exit(1)
    print(col(f"permanently deleted {r['nodes']} node"
              f"{'s' if r['nodes'] != 1 else ''}", G))


def cmd_session_empty_trash(args):
    """Permanently delete every trashed node in a session."""
    s = find_session(args.id_or_name)
    if not s:
        print(col(f"session not found: {args.id_or_name}", R), file=sys.stderr)
        sys.exit(1)
    from ..sessions.manager import empty_trash, list_trashed_nodes
    n = len(list_trashed_nodes(s["id"]))
    if not n:
        print(dim("(trash is already empty)"))
        return
    if not getattr(args, "yes", False):
        print(f"Permanently delete all {n} trashed node{'s' if n != 1 else ''} "
              f"in session {s['id'][:8]}? This cannot be undone.")
        resp = input("Continue? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print(col("aborted", Y))
            return
    r = empty_trash(s["id"])
    print(col(f"emptied trash — removed {r['nodes']} node"
              f"{'s' if r['nodes'] != 1 else ''}", G))


def cmd_session_trash(args):
    """List a session's trashed nodes (the per-session Trash view)."""
    s = find_session(args.id_or_name)
    if not s:
        print(col(f"session not found: {args.id_or_name}", R), file=sys.stderr)
        sys.exit(1)
    from ..sessions.manager import list_trashed_nodes
    rows = list_trashed_nodes(s["id"])
    if not rows:
        print(dim("(trash is empty)"))
        return
    for r in rows:
        ts = ""
        if r.get("deleted_at"):
            try:
                ts = datetime.fromtimestamp(r["deleted_at"]).strftime("%m/%d %H:%M")
            except Exception:
                pass
        print(f"{r['id'][:8]}  {r['node_type']:10}  {r['label']:40}  "
              f"{dim('deleted ' + ts)}")


def cmd_session_rename_node(args):
    """Rename a node's label by id prefix."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, label FROM session_nodes WHERE id LIKE ? AND deleted_at IS NULL "
        "LIMIT 1",
        (args.node_id + "%",),
    ).fetchone()
    if not row:
        print(col(f"node not found: {args.node_id}", R), file=sys.stderr)
        sys.exit(1)
    from ..sessions.manager import rename_node
    r = rename_node(row["id"], args.label)
    if not r.get("ok"):
        print(col(f"error: {r.get('error', 'unknown')}", R), file=sys.stderr)
        sys.exit(1)
    print(col(f"renamed {row['id'][:8]}: \"{row['label'] or ''}\" → "
              f"\"{r['label']}\"", G))


def cmd_session_promote_checkpoint(args):
    """Promote a branch node to a checkpoint by id prefix."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, label, node_type FROM session_nodes "
        "WHERE id LIKE ? AND deleted_at IS NULL LIMIT 1",
        (args.node_id + "%",),
    ).fetchone()
    if not row:
        print(col(f"node not found: {args.node_id}", R), file=sys.stderr)
        sys.exit(1)
    from ..sessions.manager import promote_to_checkpoint
    r = promote_to_checkpoint(row["id"])
    if not r.get("ok"):
        print(col(f"error: {r.get('error', 'unknown')}", R), file=sys.stderr)
        sys.exit(1)
    print(col(f"promoted {row['id'][:8]} \"{row['label'] or ''}\" "
              f"({row['node_type']} → checkpoint)", G))


def cmd_session_note(args):
    """Annotate a node by id (prefix match)."""
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM session_nodes WHERE id LIKE ? LIMIT 1",
        (args.node_id + "%",),
    ).fetchone()
    if not row:
        print(col(f"node not found: {args.node_id}", R), file=sys.stderr)
        sys.exit(1)
    conn.execute("UPDATE session_nodes SET note=? WHERE id=?", (args.text, row["id"]))
    conn.commit()
    print(col(f"noted {row['id'][:8]}", G))


def cmd_session(args):
    """Dispatch for `exptrack session <subcommand>`."""
    sub = getattr(args, "session_sub", None)
    if sub == "show":
        cmd_session_show(args)
    elif sub == "nodes":
        cmd_session_nodes(args)
    elif sub == "rm":
        cmd_session_rm(args)
    elif sub == "rm-node":
        cmd_session_rm_node(args)
    elif sub == "restore-node":
        cmd_session_restore_node(args)
    elif sub == "purge-node":
        cmd_session_purge_node(args)
    elif sub == "empty-trash":
        cmd_session_empty_trash(args)
    elif sub == "trash":
        cmd_session_trash(args)
    elif sub == "rename-node":
        cmd_session_rename_node(args)
    elif sub == "promote-checkpoint":
        cmd_session_promote_checkpoint(args)
    elif sub == "note":
        cmd_session_note(args)
    else:
        print("usage: exptrack session "
              "{show|nodes|rm|rm-node|restore-node|purge-node|empty-trash|"
              "trash|rename-node|promote-checkpoint|note} <id> [...]",
              file=sys.stderr)
        sys.exit(2)
