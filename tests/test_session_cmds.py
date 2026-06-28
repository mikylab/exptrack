"""CLI-level tests for `exptrack session ...` subcommands (session_cmds.py).

These exercise the command functions directly (as the dispatch in main.py
would call them) with a `SimpleNamespace` args object, complementing the
Python-API coverage in test_session_trees.py. Confirmation prompts are skipped
via `yes=True` so the destructive paths run non-interactively.
"""
from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest


def _capture_output(func, *args):
    """Run *func* capturing stdout+stderr; returns ``(stdout, stderr)``."""
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = out_buf = io.StringIO()
    sys.stderr = err_buf = io.StringIO()
    try:
        func(*args)
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
    return out_buf.getvalue(), err_buf.getvalue()


@pytest.fixture()
def session_tree(tmp_project):
    """A started session with root → checkpoint → branch, one cell on the branch.

    Returns ``(session_id, root_id, checkpoint_id, branch_id)``.
    """
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sid = sm.start("explore", notebook="nb.ipynb")
    cp = sm.checkpoint("after preprocess")
    br = sm.branch("try threshold 0.7")
    sm.record_cell("x = 1\n", "1")

    conn = get_db()
    root = conn.execute(
        "SELECT id FROM session_nodes WHERE session_id=? AND node_type='root'",
        (sid,),
    ).fetchone()
    return sid, root["id"], cp, br


# ---------------------------------------------------------------------------
# sessions (list) / show / nodes
# ---------------------------------------------------------------------------

def test_cmd_sessions_lists_session(session_tree):
    from exptrack.cli.session_cmds import cmd_sessions

    sid = session_tree[0]
    out, _ = _capture_output(cmd_sessions, SimpleNamespace())
    assert sid[:8] in out
    assert "explore" in out


def test_cmd_sessions_empty(tmp_project):
    from exptrack.cli.session_cmds import cmd_sessions

    out, _ = _capture_output(cmd_sessions, SimpleNamespace())
    assert "no sessions" in out


def test_cmd_session_show(session_tree):
    from exptrack.cli.session_cmds import cmd_session_show

    sid = session_tree[0]
    out, _ = _capture_output(cmd_session_show, SimpleNamespace(id_or_name=sid))
    # tree renders the checkpoint + branch labels
    assert "after preprocess" in out
    assert "try threshold 0.7" in out


def test_cmd_session_show_not_found(tmp_project):
    from exptrack.cli.session_cmds import cmd_session_show

    with pytest.raises(SystemExit):
        _capture_output(cmd_session_show, SimpleNamespace(id_or_name="nope"))


def test_cmd_session_nodes(session_tree):
    from exptrack.cli.session_cmds import cmd_session_nodes

    sid, root_id, cp, br = session_tree
    out, _ = _capture_output(cmd_session_nodes, SimpleNamespace(id_or_name=sid))
    # root + checkpoint + branch all listed by id prefix
    for nid in (root_id, cp, br):
        assert nid[:8] in out


def test_cmd_session_nodes_not_found(tmp_project):
    from exptrack.cli.session_cmds import cmd_session_nodes

    with pytest.raises(SystemExit):
        _capture_output(cmd_session_nodes, SimpleNamespace(id_or_name="missing"))


# ---------------------------------------------------------------------------
# rm (whole session)
# ---------------------------------------------------------------------------

def test_cmd_session_rm(session_tree):
    from exptrack.cli.session_cmds import (
        cmd_session_rm, cmd_session_restore, cmd_session_purge)
    from exptrack.core.db import get_db

    sid = session_tree[0]
    # Default rm = soft-delete (Trash), recoverable.
    out, _ = _capture_output(
        cmd_session_rm, SimpleNamespace(id_or_name=sid, permanent=False))
    assert "moved session" in out and "Trash" in out
    conn = get_db()
    row = conn.execute(
        "SELECT deleted_at FROM sessions WHERE id=?", (sid,)).fetchone()
    assert row is not None and row["deleted_at"] is not None

    # restore brings it back.
    out, _ = _capture_output(
        cmd_session_restore, SimpleNamespace(id_or_name=sid))
    assert "restored session" in out
    row = conn.execute(
        "SELECT deleted_at FROM sessions WHERE id=?", (sid,)).fetchone()
    assert row["deleted_at"] is None

    # purge requires a trashed session; trash then purge removes it.
    _capture_output(cmd_session_rm, SimpleNamespace(id_or_name=sid, permanent=False))
    out, _ = _capture_output(
        cmd_session_purge, SimpleNamespace(id_or_name=sid, yes=True))
    assert "permanently deleted" in out
    assert conn.execute(
        "SELECT id FROM sessions WHERE id=?", (sid,)).fetchone() is None


def test_cmd_session_rm_permanent(session_tree):
    from exptrack.cli.session_cmds import cmd_session_rm
    from exptrack.core.db import get_db

    sid = session_tree[0]
    out, _ = _capture_output(
        cmd_session_rm, SimpleNamespace(id_or_name=sid, permanent=True))
    assert "permanently deleted session" in out
    conn = get_db()
    assert conn.execute(
        "SELECT id FROM sessions WHERE id=?", (sid,)).fetchone() is None


def test_cmd_session_rm_not_found(tmp_project):
    from exptrack.cli.session_cmds import cmd_session_rm

    with pytest.raises(SystemExit):
        _capture_output(cmd_session_rm, SimpleNamespace(id_or_name="nope"))


# ---------------------------------------------------------------------------
# rm-node / restore-node / purge-node
# ---------------------------------------------------------------------------

def test_cmd_session_rm_node_soft_deletes(session_tree):
    from exptrack.cli.session_cmds import cmd_session_rm_node
    from exptrack.core.db import get_db

    sid, root_id, cp, br = session_tree
    out, _ = _capture_output(
        cmd_session_rm_node, SimpleNamespace(node_id=br[:8], yes=True)
    )
    assert "deleted" in out
    conn = get_db()
    row = conn.execute(
        "SELECT deleted_at FROM session_nodes WHERE id=?", (br,)
    ).fetchone()
    assert row["deleted_at"] is not None


def test_cmd_session_rm_node_refuses_root(session_tree):
    from exptrack.cli.session_cmds import cmd_session_rm_node

    root_id = session_tree[1]
    with pytest.raises(SystemExit):
        _capture_output(
            cmd_session_rm_node, SimpleNamespace(node_id=root_id[:8], yes=True)
        )


def test_cmd_session_rm_node_not_found(tmp_project):
    from exptrack.cli.session_cmds import cmd_session_rm_node

    with pytest.raises(SystemExit):
        _capture_output(
            cmd_session_rm_node, SimpleNamespace(node_id="zzzz", yes=True)
        )


def test_cmd_session_restore_node(session_tree):
    from exptrack.cli.session_cmds import cmd_session_rm_node, cmd_session_restore_node
    from exptrack.core.db import get_db

    br = session_tree[3]
    _capture_output(cmd_session_rm_node, SimpleNamespace(node_id=br[:8], yes=True))
    out, _ = _capture_output(
        cmd_session_restore_node, SimpleNamespace(node_id=br[:8])
    )
    assert "restored" in out
    conn = get_db()
    row = conn.execute(
        "SELECT deleted_at FROM session_nodes WHERE id=?", (br,)
    ).fetchone()
    assert row["deleted_at"] is None


def test_cmd_session_restore_node_not_trashed(session_tree):
    from exptrack.cli.session_cmds import cmd_session_restore_node

    br = session_tree[3]
    with pytest.raises(SystemExit):
        _capture_output(
            cmd_session_restore_node, SimpleNamespace(node_id=br[:8])
        )


def test_cmd_session_purge_node(session_tree):
    from exptrack.cli.session_cmds import cmd_session_rm_node, cmd_session_purge_node
    from exptrack.core.db import get_db

    br = session_tree[3]
    _capture_output(cmd_session_rm_node, SimpleNamespace(node_id=br[:8], yes=True))
    out, _ = _capture_output(
        cmd_session_purge_node, SimpleNamespace(node_id=br[:8], yes=True)
    )
    assert "permanently deleted" in out
    conn = get_db()
    row = conn.execute("SELECT id FROM session_nodes WHERE id=?", (br,)).fetchone()
    assert row is None


def test_cmd_session_purge_node_refuses_live(session_tree):
    """A node that isn't trashed yet can't be purged."""
    from exptrack.cli.session_cmds import cmd_session_purge_node

    br = session_tree[3]
    with pytest.raises(SystemExit):
        _capture_output(
            cmd_session_purge_node, SimpleNamespace(node_id=br[:8], yes=True)
        )


# ---------------------------------------------------------------------------
# trash / empty-trash
# ---------------------------------------------------------------------------

def test_cmd_session_trash_lists_trashed(session_tree):
    from exptrack.cli.session_cmds import cmd_session_rm_node, cmd_session_trash

    sid, root_id, cp, br = session_tree
    _capture_output(cmd_session_rm_node, SimpleNamespace(node_id=br[:8], yes=True))
    out, _ = _capture_output(cmd_session_trash, SimpleNamespace(id_or_name=sid))
    assert br[:8] in out


def test_cmd_session_trash_empty(session_tree):
    from exptrack.cli.session_cmds import cmd_session_trash

    sid = session_tree[0]
    out, _ = _capture_output(cmd_session_trash, SimpleNamespace(id_or_name=sid))
    assert "trash is empty" in out


def test_cmd_session_empty_trash(session_tree):
    from exptrack.cli.session_cmds import cmd_session_rm_node, cmd_session_empty_trash
    from exptrack.sessions.manager import list_trashed_nodes

    sid, root_id, cp, br = session_tree
    _capture_output(cmd_session_rm_node, SimpleNamespace(node_id=br[:8], yes=True))
    out, _ = _capture_output(
        cmd_session_empty_trash, SimpleNamespace(id_or_name=sid, yes=True)
    )
    assert "emptied trash" in out
    assert list_trashed_nodes(sid) == []


def test_cmd_session_empty_trash_already_empty(session_tree):
    from exptrack.cli.session_cmds import cmd_session_empty_trash

    sid = session_tree[0]
    out, _ = _capture_output(
        cmd_session_empty_trash, SimpleNamespace(id_or_name=sid, yes=True)
    )
    assert "already empty" in out


# ---------------------------------------------------------------------------
# rename-node / promote-checkpoint / note
# ---------------------------------------------------------------------------

def test_cmd_session_rename_node(session_tree):
    from exptrack.cli.session_cmds import cmd_session_rename_node
    from exptrack.core.db import get_db

    br = session_tree[3]
    out, _ = _capture_output(
        cmd_session_rename_node,
        SimpleNamespace(node_id=br[:8], label="renamed branch"),
    )
    assert "renamed" in out
    conn = get_db()
    row = conn.execute("SELECT label FROM session_nodes WHERE id=?", (br,)).fetchone()
    assert row["label"] == "renamed branch"


def test_cmd_session_rename_node_not_found(tmp_project):
    from exptrack.cli.session_cmds import cmd_session_rename_node

    with pytest.raises(SystemExit):
        _capture_output(
            cmd_session_rename_node,
            SimpleNamespace(node_id="zzzz", label="x"),
        )


def test_cmd_session_promote_checkpoint(session_tree):
    from exptrack.cli.session_cmds import cmd_session_promote_checkpoint
    from exptrack.core.db import get_db

    br = session_tree[3]
    out, _ = _capture_output(
        cmd_session_promote_checkpoint, SimpleNamespace(node_id=br[:8])
    )
    assert "promoted" in out
    conn = get_db()
    row = conn.execute(
        "SELECT node_type FROM session_nodes WHERE id=?", (br,)
    ).fetchone()
    assert row["node_type"] == "checkpoint"


def test_cmd_session_promote_checkpoint_not_found(tmp_project):
    from exptrack.cli.session_cmds import cmd_session_promote_checkpoint

    with pytest.raises(SystemExit):
        _capture_output(
            cmd_session_promote_checkpoint, SimpleNamespace(node_id="zzzz")
        )


def test_cmd_session_note(session_tree):
    from exptrack.cli.session_cmds import cmd_session_note
    from exptrack.core.db import get_db

    br = session_tree[3]
    out, _ = _capture_output(
        cmd_session_note, SimpleNamespace(node_id=br[:8], text="a useful note")
    )
    assert "noted" in out
    conn = get_db()
    row = conn.execute("SELECT note FROM session_nodes WHERE id=?", (br,)).fetchone()
    assert row["note"] == "a useful note"


def test_cmd_session_note_not_found(tmp_project):
    from exptrack.cli.session_cmds import cmd_session_note

    with pytest.raises(SystemExit):
        _capture_output(
            cmd_session_note, SimpleNamespace(node_id="zzzz", text="x")
        )


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def test_cmd_session_dispatch_unknown_sub(tmp_project):
    from exptrack.cli.session_cmds import cmd_session

    with pytest.raises(SystemExit):
        _capture_output(cmd_session, SimpleNamespace(session_sub="bogus"))


def test_cmd_session_dispatch_routes_to_show(session_tree):
    from exptrack.cli.session_cmds import cmd_session

    sid = session_tree[0]
    out, _ = _capture_output(
        cmd_session, SimpleNamespace(session_sub="show", id_or_name=sid)
    )
    assert "after preprocess" in out
