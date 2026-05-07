"""
exptrack/cli/session_cmds.py — Session Trees CLI subcommands.

    exptrack sessions                  list sessions
    exptrack session show <id|name>    render tree as ASCII
    exptrack session nodes <id|name>   list nodes flat
    exptrack session rm <id>           delete session (preserves linked exps)
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
    elif sub == "note":
        cmd_session_note(args)
    else:
        print("usage: exptrack session {show|nodes|rm|note} <id> [...]",
              file=sys.stderr)
        sys.exit(2)
