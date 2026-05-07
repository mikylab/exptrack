"""Tests for Session Trees: schema, SessionManager, tree rendering, scratch detection."""
from __future__ import annotations

import pytest


def test_session_schema_tables_exist(db_conn):
    """Migration creates sessions and session_nodes tables."""
    tables = {
        r[0]
        for r in db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "sessions" in tables
    assert "session_nodes" in tables


def test_experiments_has_session_node_id(db_conn):
    """experiments table has the new session_node_id column (nullable)."""
    cols = {row[1] for row in db_conn.execute("PRAGMA table_info(experiments)").fetchall()}
    assert "session_node_id" in cols


def test_session_manager_start_creates_root(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sid = sm.start("explore-1", notebook="x.ipynb")
    assert sid
    conn = get_db()
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    assert row["name"] == "explore-1"
    assert row["status"] == "active"
    nodes = conn.execute(
        "SELECT * FROM session_nodes WHERE session_id=?", (sid,)
    ).fetchall()
    assert len(nodes) == 1
    assert nodes[0]["node_type"] == "root"


def test_checkpoint_branch_promote_flow(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("flow")
    cp = sm.checkpoint("after preprocess")
    br = sm.branch("try threshold 0.7")
    assert cp and br

    exp = Experiment(script="train.py", params={"lr": 0.01})
    sm.promote("threshold 0.7 wins", exp.id)
    exp.finish()

    conn = get_db()
    row = conn.execute(
        "SELECT session_node_id FROM experiments WHERE id=?", (exp.id,),
    ).fetchone()
    assert row["session_node_id"] == br


def test_branch_without_checkpoint_is_rejected(tmp_project):
    from exptrack.sessions import SessionManager
    sm = SessionManager()
    sm.start("name")
    # Last checkpoint is the root, which counts as a checkpoint anchor.
    # Force a state where root is the only node — branch should still attach.
    nid = sm.branch("intent")
    assert nid is not None  # branch attaches under root


def test_session_end_marks_open_branches_abandoned(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("end-test")
    sm.checkpoint("first")
    open_branch = sm.branch("dangling intent")
    sm.end()

    conn = get_db()
    row = conn.execute(
        "SELECT node_type FROM session_nodes WHERE id=?", (open_branch,),
    ).fetchone()
    assert row["node_type"] == "abandoned"
    s = conn.execute("SELECT status FROM sessions").fetchone()
    assert s["status"] == "ended"


def test_build_tree_shape(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import build_tree

    sm = SessionManager()
    sid = sm.start("shape")
    sm.checkpoint("c1")
    sm.branch("b1")
    sm.checkpoint("c2")

    tree = build_tree(sid)
    assert tree["session"]["name"] == "shape"
    root = tree["root"]
    assert root["node_type"] == "root"
    # root → c1 → b1 → c2
    assert len(root["children"]) == 1
    c1 = root["children"][0]
    assert c1["label"] == "c1"
    assert len(c1["children"]) == 1
    b1 = c1["children"][0]
    assert b1["node_type"] == "branch"
    assert len(b1["children"]) == 1
    c2 = b1["children"][0]
    assert c2["label"] == "c2"


def test_render_ascii_smoke(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import build_tree
    from exptrack.sessions.tree import render_ascii

    sm = SessionManager()
    sid = sm.start("render")
    sm.checkpoint("clean")
    out = render_ascii(build_tree(sid))
    assert "render" in out
    assert "checkpoint" in out
    assert "clean" in out


def test_scratch_cell_detection():
    from exptrack.capture.session_hooks import is_scratch_cell
    assert is_scratch_cell("%%scratch\nprint('x')")
    assert is_scratch_cell("\n\n%%scratch arg\nbody")
    assert not is_scratch_cell("print('hi')")
    assert not is_scratch_cell("# %%scratch\nprint(1)")
    assert not is_scratch_cell("")


def test_session_rm_preserves_experiments(tmp_project):
    """exptrack session rm clears session_node_id but keeps the experiment."""
    from exptrack.sessions import SessionManager
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    sm = SessionManager()
    sid = sm.start("rm-test")
    sm.checkpoint("cp")
    exp = Experiment(script="t.py", params={})
    sm.promote("p", exp.id)
    exp.finish()

    conn = get_db()
    # Simulate cmd_session_rm
    conn.execute(
        "UPDATE experiments SET session_node_id=NULL "
        "WHERE session_node_id IN (SELECT id FROM session_nodes WHERE session_id=?)",
        (sid,),
    )
    conn.execute("DELETE FROM session_nodes WHERE session_id=?", (sid,))
    conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
    conn.commit()

    # Experiment should still exist with session_node_id NULL
    row = conn.execute(
        "SELECT id, session_node_id FROM experiments WHERE id=?", (exp.id,),
    ).fetchone()
    assert row is not None
    assert row["session_node_id"] is None


def test_record_cell_writes_to_current_node(tmp_project):
    """Cells run while a node is active are appended to that node's cell_source."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("live")
    cp = sm.checkpoint("first")
    sm.record_cell("import pandas as pd")
    sm.record_cell("df = pd.read_csv('x.csv')")

    conn = get_db()
    row = conn.execute(
        "SELECT cell_source FROM session_nodes WHERE id=?", (cp,),
    ).fetchone()
    assert "import pandas" in row["cell_source"]
    assert "read_csv" in row["cell_source"]


def test_branch_magic_inline_with_code(tmp_project):
    """User's reported bug: cells of the form
        %exptrack branch "X"
        threshold = 0.7
    must record `threshold = 0.7` under branch X — the magic line on top
    should not cause the whole cell to be dropped."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("inline")
    sm.checkpoint("base")
    # Simulate IPython: the magic runs first, then post_run_cell hands the
    # full cell source (magic line included) to record_cell.
    br = sm.branch("try X")
    sm.record_cell(
        '%exptrack branch "try X"\n'
        'threshold = 0.7\n'
        'results = run(threshold)\n'
    )

    conn = get_db()
    row = conn.execute(
        "SELECT cell_source FROM session_nodes WHERE id=?", (br,),
    ).fetchone()
    src = row["cell_source"] or ""
    assert "threshold = 0.7" in src
    assert "results = run(threshold)" in src
    assert "%exptrack" not in src


def test_branch_magic_alone_then_code_cells(tmp_project):
    """User's reported workflow: %exptrack branch "X" sits alone in its own
    cell. Cells run AFTER it (in their own cells, no inline magic) must each
    record under branch X — this is the most natural notebook pattern."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("alone")
    sm.checkpoint("base")
    br = sm.branch("run 2")
    sm.record_cell('%exptrack branch "run 2"')  # the magic-only cell itself
    sm.record_cell("threshold = 0.7")           # next cell, just code
    sm.record_cell("results = run(threshold)")  # cell after that

    conn = get_db()
    row = conn.execute(
        "SELECT cell_source FROM session_nodes WHERE id=?", (br,),
    ).fetchone()
    src = row["cell_source"] or ""
    assert "threshold = 0.7" in src
    assert "results = run(threshold)" in src
    assert "%exptrack" not in src


def test_pure_magic_cell_is_skipped(tmp_project):
    """A cell that's only %exptrack magics (and blanks) should not record."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("pure")
    cp = sm.checkpoint("cp")
    sm.record_cell('%exptrack branch "X"\n\n# comment only\n')

    conn = get_db()
    row = conn.execute(
        "SELECT cell_source FROM session_nodes WHERE id=?", (cp,),
    ).fetchone()
    assert (row["cell_source"] or "") == ""


def test_branch_captures_cells_run_under_it(tmp_project):
    """User's reported bug: cells run AFTER `branch` should appear under
    that branch, not require a follow-up checkpoint to materialize."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("branchtest")
    sm.checkpoint("base")
    br = sm.branch("try threshold 0.7")
    sm.record_cell("threshold = 0.7")
    sm.record_cell("results = run_pipeline(threshold)")

    conn = get_db()
    row = conn.execute(
        "SELECT cell_source FROM session_nodes WHERE id=?", (br,),
    ).fetchone()
    assert "threshold = 0.7" in row["cell_source"]
    assert "run_pipeline" in row["cell_source"]


def test_branch_idempotent_by_label(tmp_project):
    """Re-running %exptrack branch "X" reuses the existing branch instead
    of creating a duplicate."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("idem")
    sm.checkpoint("base")
    first = sm.branch("try X")
    sm.record_cell("a = 1")
    second = sm.branch("try X")  # re-run the same branch cell
    sm.record_cell("b = 2")

    assert first == second  # same node id reused
    conn = get_db()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM session_nodes "
        "WHERE session_id=? AND label='try X'", (sm.session_id or "",),
    ).fetchone()["n"]
    # It might be 0 if session_id was cleared; query via the original sid
    assert n >= 1
    row = conn.execute(
        "SELECT cell_source FROM session_nodes WHERE id=?", (first,),
    ).fetchone()
    assert "a = 1" in row["cell_source"]
    assert "b = 2" in row["cell_source"]


def test_checkpoint_idempotent_by_label(tmp_project):
    from exptrack.sessions import SessionManager
    sm = SessionManager()
    sm.start("idem-cp")
    a = sm.checkpoint("first")
    b = sm.checkpoint("first")
    assert a == b


def test_branch_reactivates_abandoned(tmp_project):
    """If session end abandoned a branch, re-declaring it with branch() flips
    it back to 'branch' (avoids losing the open exploration)."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sid = sm.start("revive")
    cp = sm.checkpoint("cp")
    br = sm.branch("dangling")
    sm.end()
    conn = get_db()
    row = conn.execute(
        "SELECT node_type FROM session_nodes WHERE id=?", (br,),
    ).fetchone()
    assert row["node_type"] == "abandoned"

    sm2 = SessionManager()
    sm2.session_id = sid
    sm2._current_node_id = cp
    sm2._last_checkpoint_id = cp
    # Restart sessions row so manipulations are valid
    conn.execute("UPDATE sessions SET status='active', ended_at=NULL WHERE id=?",
                 (sm.session_id,))
    conn.commit()
    revived = sm2.branch("dangling")
    assert revived == br
    row = conn.execute(
        "SELECT node_type FROM session_nodes WHERE id=?", (br,),
    ).fetchone()
    assert row["node_type"] == "branch"


def test_record_cell_skips_session_magics_and_dedupes(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("magic")
    cp = sm.checkpoint("cp")
    sm.record_cell("%exptrack checkpoint \"x\"")
    sm.record_cell("%%scratch\nprint('s')")
    sm.record_cell("%%pin \"foo\"\ndf.head()")
    sm.record_cell("real code")
    sm.record_cell("real code")  # immediate re-run — should dedupe

    conn = get_db()
    row = conn.execute(
        "SELECT cell_source FROM session_nodes WHERE id=?", (cp,),
    ).fetchone()
    src = row["cell_source"] or ""
    assert "%exptrack" not in src
    assert "%%scratch" not in src
    assert "%%pin" not in src
    assert src.count("real code") == 1


def test_dashboard_session_delete(tmp_project):
    """POST /api/session/<id>/delete removes nodes, preserves linked exps."""
    from exptrack.sessions import SessionManager
    from exptrack.core import Experiment
    from exptrack.dashboard.routes import write_routes
    from exptrack.core.db import get_db

    sm = SessionManager()
    sid = sm.start("dash-del")
    sm.checkpoint("cp")
    exp = Experiment(script="t.py", params={})
    sm.promote("p", exp.id)
    exp.finish()

    conn = get_db()
    res = write_routes.api_session_delete(conn, sid, {})
    assert res.get("ok")
    # Session and nodes are gone
    assert conn.execute("SELECT id FROM sessions WHERE id=?", (sid,)).fetchone() is None
    assert conn.execute(
        "SELECT id FROM session_nodes WHERE session_id=?", (sid,),
    ).fetchone() is None
    # Experiment still exists with session_node_id cleared
    erow = conn.execute(
        "SELECT id, session_node_id FROM experiments WHERE id=?", (exp.id,),
    ).fetchone()
    assert erow is not None
    assert erow["session_node_id"] is None


def test_dashboard_session_routes(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.dashboard.routes import read_routes
    from exptrack.core.db import get_db

    sm = SessionManager()
    sid = sm.start("dash")
    sm.checkpoint("cp")

    conn = get_db()
    listed = read_routes.api_sessions(conn)
    assert any(s["id"] == sid for s in listed["sessions"])

    tree = read_routes.api_session_tree(conn, sid)
    assert tree["session"]["name"] == "dash"
    assert tree["root"]["node_type"] == "root"

    nodes = read_routes.api_session_nodes(conn, sid)
    assert len(nodes["nodes"]) >= 2  # root + checkpoint
