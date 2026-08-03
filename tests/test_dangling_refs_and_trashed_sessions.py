"""Tests for the smaller orphan/consistency issues from the audit.

1. ``resolve_git_diff`` failed open: a dangling ``[ref:sha256:…]`` pointer
   returned the marker itself, so every consumer rendered that literal string
   as though it were the diff body (and counted it as a diff line).
2. A soft-deleted session stayed reachable through an experiment's back-link
   while being hidden from every live list, with nothing marking it as trashed
   and live-only actions still offered on it. Its trashed nodes were also
   listed in the Trash under a session that was itself in the Trash.
3. ``_send_to_os_trash`` wrote the XDG ``.trashinfo`` record *after* moving the
   file, so a failed write left a file in Trash/files that no file manager can
   restore.
"""
from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# 1. Dangling diff refs report unavailable, never render as content
# ---------------------------------------------------------------------------

def test_dangling_diff_ref_resolves_to_sentinel(tmp_project, db_conn):
    from exptrack.core.db import DIFF_UNAVAILABLE, resolve_git_diff, store_git_diff

    conn = db_conn
    ref = store_git_diff(conn, "diff --git a/x b/x\n+body\n")
    conn.commit()
    assert resolve_git_diff(conn, ref) == "diff --git a/x b/x\n+body\n"

    conn.execute("DELETE FROM git_diffs")
    conn.commit()

    resolved = resolve_git_diff(conn, ref)
    assert resolved == DIFF_UNAVAILABLE
    assert not resolved.startswith("[ref:"), "must not hand back the raw pointer"


def test_empty_and_inline_diffs_are_unaffected(tmp_project, db_conn):
    """Only a *dangling* ref changes: no diff stays "", inline text passes through."""
    from exptrack.core.db import resolve_git_diff

    assert resolve_git_diff(db_conn, None) == ""
    assert resolve_git_diff(db_conn, "") == ""
    assert resolve_git_diff(db_conn, "diff --git a/x b/x\n") == "diff --git a/x b/x\n"
    assert resolve_git_diff(db_conn, "[compacted — 2 KB stripped]") \
        == "[compacted — 2 KB stripped]"


def test_sentinel_diff_is_not_counted_as_a_diff_line(tmp_project, db_conn):
    """diff_lines must be 0 for a sentinel — it previously reported 1."""
    from exptrack.core.db import get_db, store_git_diff
    from exptrack.core.experiment import Experiment
    from exptrack.core.queries import get_experiment_detail

    exp = Experiment(name="dangling", script="train.py")
    conn = get_db()
    ref = store_git_diff(conn, "diff --git a/x b/x\n+body\n")
    conn.execute("UPDATE experiments SET git_diff=? WHERE id=?", (ref, exp.id))
    conn.commit()
    exp.finish()

    conn = get_db()
    conn.execute("DELETE FROM git_diffs")
    conn.commit()

    detail = get_experiment_detail(conn, exp.id)
    assert detail["git_diff"] == "[diff-unavailable]"
    assert detail["diff_lines"] == 0


@pytest.mark.parametrize("diff,expected", [
    ("", False),
    ("diff --git a/x b/x", False),
    ("[capture-failed]", True),
    ("[diff-unavailable]", True),
    ("[compacted — 2 KB stripped — 1 file(s)]", True),
])
def test_is_diff_sentinel(diff, expected):
    from exptrack.core.db import is_diff_sentinel
    assert is_diff_sentinel(diff) is expected


def test_cli_diff_says_unavailable_not_clean_tree(tmp_project, capsys):
    """`exptrack diff` must not imply a clean tree for a dangling ref."""
    from types import SimpleNamespace

    from exptrack.cli.inspect_cmds import cmd_diff
    from exptrack.core.db import get_db, store_git_diff
    from exptrack.core.experiment import Experiment

    exp = Experiment(name="dangling", script="train.py")
    conn = get_db()
    ref = store_git_diff(conn, "diff --git a/x b/x\n+body\n")
    conn.execute("UPDATE experiments SET git_diff=? WHERE id=?", (ref, exp.id))
    conn.commit()
    exp.finish()
    conn = get_db()
    conn.execute("DELETE FROM git_diffs")
    conn.commit()

    cmd_diff(SimpleNamespace(id=exp.id))

    out = capsys.readouterr().out
    assert "no longer available" in out
    assert "[ref:sha256:" not in out, "raw pointer must never be printed as a diff"
    assert "No uncommitted changes" not in out, "must not read as a clean tree"


def test_export_diff_refuses_a_dangling_ref(tmp_project, db_conn):
    from exptrack.core.db import get_db, store_git_diff
    from exptrack.core.experiment import Experiment
    from exptrack.dashboard.routes.write_routes import api_export_diff

    exp = Experiment(name="dangling", script="train.py")
    conn = get_db()
    ref = store_git_diff(conn, "diff --git a/x b/x\n+body\n")
    conn.execute("UPDATE experiments SET git_diff=? WHERE id=?", (ref, exp.id))
    conn.commit()
    exp.finish()
    conn = get_db()
    conn.execute("DELETE FROM git_diffs")
    conn.commit()

    res = api_export_diff(conn, exp.id)
    assert res.get("unavailable") is True
    assert "markdown" not in res


def test_compaction_skips_a_dangling_ref(tmp_project, db_conn):
    """Compacting must not replace a sentinel with a '[compacted 17 B]' marker."""
    from exptrack.core.db import get_db, store_git_diff
    from exptrack.core.experiment import Experiment
    from exptrack.core.storage import compact_git_diffs

    exp = Experiment(name="dangling", script="train.py")
    conn = get_db()
    ref = store_git_diff(conn, "diff --git a/x b/x\n+body\n")
    conn.execute("UPDATE experiments SET git_diff=? WHERE id=?", (ref, exp.id))
    conn.commit()
    exp.finish()
    conn = get_db()
    conn.execute("DELETE FROM git_diffs")
    conn.commit()

    st = compact_git_diffs(conn, [exp.id])

    assert (st["bytes"], st["runs"]) == (0, 0)
    stored = conn.execute("SELECT git_diff FROM experiments WHERE id=?",
                          (exp.id,)).fetchone()[0]
    assert stored == ref, "the pointer is left as-is, not overwritten"


# ---------------------------------------------------------------------------
# 2. A trashed session is marked as such everywhere it's still reachable
# ---------------------------------------------------------------------------

def _session_with_node_and_run(conn):
    """A session + node + a live experiment linked to that node."""
    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment

    exp = Experiment(name="promoted", script="train.py")
    exp.finish()
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (id,name,notebook,status,created_at) "
        "VALUES ('s1','my sess','nb.ipynb','active',1.0)")
    conn.execute(
        "INSERT INTO session_nodes "
        "(id,session_id,parent_id,node_type,label,seq,created_at) "
        "VALUES ('n0','s1',NULL,'root','root',0,1.0)")
    conn.execute(
        "INSERT INTO session_nodes "
        "(id,session_id,parent_id,node_type,label,cell_source,seq,created_at) "
        "VALUES ('n1','s1','n0','branch','try 0.7','x = 1',1,2.0)")
    conn.execute("UPDATE experiments SET session_node_id='n1' WHERE id=?", (exp.id,))
    conn.commit()
    return exp.id, conn


def test_session_origin_flags_a_trashed_session(tmp_project, db_conn):
    """The back-link banner must know the session is in the Trash."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_experiment_detail
    from exptrack.sessions.lifecycle import delete_session

    exp_id, conn = _session_with_node_and_run(db_conn)

    origin = get_experiment_detail(conn, exp_id)["session_origin"]
    assert origin["session_deleted"] is False

    delete_session("s1")  # soft delete
    conn = get_db()
    origin = get_experiment_detail(conn, exp_id)["session_origin"]
    assert origin is not None, "the run and node are still live — keep the banner"
    assert origin["session_deleted"] is True
    assert origin["session_name"] == "my sess"


def test_build_tree_marks_a_trashed_session(tmp_project, db_conn):
    """The tree payload says `deleted` so the view can't look live."""
    from exptrack.sessions.lifecycle import delete_session, restore_session
    from exptrack.sessions.manager import build_tree

    _session_with_node_and_run(db_conn)

    assert build_tree("s1")["session"]["session_deleted"] is False
    delete_session("s1")
    tree = build_tree("s1")
    assert tree, "a trashed session must still be inspectable"
    assert tree["session"]["session_deleted"] is True
    restore_session("s1")
    assert build_tree("s1")["session"]["session_deleted"] is False


def test_trashed_node_group_flags_a_trashed_session(tmp_project, db_conn):
    """A node group inside a trashed session is marked in the unified Trash."""
    from exptrack.core.db import get_db
    from exptrack.core.trash import list_unified_trash
    from exptrack.sessions.lifecycle import delete_node, delete_session

    _session_with_node_and_run(db_conn)
    delete_node("n1")

    payload = list_unified_trash(get_db())
    group = next(g for g in payload["sessions"] if g["session"]["id"] == "s1")
    assert group["session"]["session_deleted"] is False

    delete_session("s1")
    payload = list_unified_trash(get_db())
    group = next(g for g in payload["sessions"] if g["session"]["id"] == "s1")
    assert group["session"]["session_deleted"] is True, \
        "otherwise Restore on this node appears to do nothing"
    # And the session shows up in its own section, so the two are cross-referable.
    assert "s1" in {s["id"] for s in payload["trashed_sessions"]}


def test_list_all_trashed_nodes_exposes_session_deleted(tmp_project, db_conn):
    from exptrack.sessions.lifecycle import delete_node, delete_session
    from exptrack.sessions.manager import list_all_trashed_nodes

    _session_with_node_and_run(db_conn)
    delete_node("n1")
    delete_session("s1")

    rows = list_all_trashed_nodes()
    row = next(r for r in rows if r["id"] == "n1")
    assert row["session_deleted"] == 1
    assert row["session_name"] == "my sess"


# ---------------------------------------------------------------------------
# 3. XDG trash writes its info record before moving the file
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"),
                    reason="XDG trash path is Linux-only")
def test_xdg_trash_writes_info_record_with_the_file(tmp_project, tmp_path, monkeypatch):
    from exptrack.core.db import _send_to_os_trash

    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    victim = tmp_project / "model.pt"
    victim.write_bytes(b"weights")

    assert _send_to_os_trash(victim) is True

    files = list((xdg / "Trash" / "files").iterdir())
    infos = list((xdg / "Trash" / "info").iterdir())
    assert len(files) == 1 and len(infos) == 1
    assert files[0].name == "model.pt"
    assert infos[0].name == "model.pt.trashinfo"
    body = infos[0].read_text()
    assert "[Trash Info]" in body and "DeletionDate=" in body
    assert str(victim) in body.replace("%2F", "/")


@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"),
                    reason="XDG trash path is Linux-only")
def test_xdg_trash_never_leaves_a_file_without_its_info(tmp_project, tmp_path, monkeypatch):
    """If the move fails, no orphaned info record is left pointing at nothing.

    The mirror case (a file in Trash/files with no info record — unrestorable by
    any file manager) is prevented by writing the record first.
    """
    import shutil

    from exptrack.core import db as core_db

    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    victim = tmp_project / "model.pt"
    victim.write_bytes(b"weights")

    def boom(*a, **k):
        raise OSError("cross-device move failed")
    monkeypatch.setattr(shutil, "move", boom)

    assert core_db._send_to_os_trash(victim) is False  # caller falls back to local

    assert list((xdg / "Trash" / "info").iterdir()) == [], "no dangling info record"
    assert victim.exists(), "the original is left in place for the fallback"


@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"),
                    reason="XDG trash path is Linux-only")
def test_xdg_trash_name_collisions_stay_paired(tmp_project, tmp_path, monkeypatch):
    """Trashing the same filename twice keeps each file paired with its own info."""
    from exptrack.core.db import _send_to_os_trash

    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))

    for body in (b"first", b"second"):
        victim = tmp_project / "model.pt"
        victim.write_bytes(body)
        assert _send_to_os_trash(victim) is True

    files = {p.name for p in (xdg / "Trash" / "files").iterdir()}
    infos = {p.name for p in (xdg / "Trash" / "info").iterdir()}
    assert len(files) == 2
    # Every file has exactly the matching <name>.trashinfo record.
    assert infos == {f + ".trashinfo" for f in files}


@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"),
                    reason="XDG trash path is Linux-only")
def test_info_record_is_private(tmp_project, tmp_path, monkeypatch):
    """The record holds an absolute path; keep it 0600 like the token file."""
    import stat

    from exptrack.core.db import _send_to_os_trash

    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    victim = tmp_project / "model.pt"
    victim.write_bytes(b"weights")
    _send_to_os_trash(victim)

    info = next((xdg / "Trash" / "info").iterdir())
    assert stat.S_IMODE(os.stat(info).st_mode) == 0o600
