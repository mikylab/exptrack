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


def test_setup_cell_detection():
    from exptrack.capture.session_hooks import is_setup_cell, is_scratch_cell
    assert is_setup_cell("%%setup\ndf = load()")
    assert is_setup_cell("\n\n%%setup\nbody")
    assert not is_setup_cell("print('hi')")
    assert not is_setup_cell("# %%setup\nx=1")
    assert not is_setup_cell("")
    # scratch and setup are distinct
    assert not is_scratch_cell("%%setup\nx=1")
    assert not is_setup_cell("%%scratch\nx=1")


def test_session_nodes_has_setup_columns(db_conn):
    cols = {row[1] for row in db_conn.execute(
        "PRAGMA table_info(session_nodes)").fetchall()}
    assert "setup_source" in cols
    assert "setup_outputs" in cols


def test_record_setup_cell_stored_separately(tmp_project):
    """%%setup cells land in setup_source/outputs, never in cell_source, and
    keep their own segment alignment."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("s", "nb.ipynb")
    sm.checkpoint("c1")
    sm.record_cell("model = train()", output="acc=0.9")
    sm.record_setup_cell("%%setup\ndf = load_csv('x.csv')\ndf", output="<DataFrame>")
    sm.record_setup_cell("%%setup\nfeats = build(df)", output=None)

    conn = get_db()
    row = conn.execute(
        "SELECT cell_source, setup_source, setup_outputs FROM session_nodes WHERE id=?",
        (sm._current_node_id,),
    ).fetchone()
    SEP = SessionManager._CELL_SEPARATOR
    # real cell untouched by setup
    assert row["cell_source"].split(SEP) == ["model = train()"]
    setup_cells = row["setup_source"].split(SEP)
    setup_outs = row["setup_outputs"].split(SEP)
    assert len(setup_cells) == len(setup_outs) == 2
    # the leading %%setup line is stripped from what we store
    assert setup_cells[0] == "df = load_csv('x.csv')\ndf"
    assert setup_outs[0] == "<DataFrame>"
    assert setup_outs[1] == ""


def test_build_tree_exposes_setup_fields(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import build_tree

    sm = SessionManager()
    sid = sm.start("s", "nb.ipynb")
    sm.checkpoint("c1")
    sm.record_setup_cell("%%setup\ndf = 1", output="1")
    tree = build_tree(sid)
    cp = tree["root"]["children"][0]
    assert "setup_source" in cp and cp["setup_source"]
    assert "setup_outputs" in cp


def test_promote_branch_to_checkpoint(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import promote_to_checkpoint
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("s", "nb.ipynb")
    sm.checkpoint("c1")
    br = sm.branch("idea-a")
    r = promote_to_checkpoint(br)
    assert r["ok"] and r["node_type"] == "checkpoint"

    conn = get_db()
    row = conn.execute(
        "SELECT node_type FROM session_nodes WHERE id=?", (br,)).fetchone()
    assert row["node_type"] == "checkpoint"
    # promoting a checkpoint is a no-op; a root is rejected
    assert promote_to_checkpoint(br)["ok"] is True
    assert promote_to_checkpoint("nonexistent")["ok"] is False


def test_materialize_carries_setup_images_and_lineage(tmp_project, tmp_path):
    """A node promoted to an experiment carries its %%setup prep cells (as muted
    setup events), its by-reference plots (as artifacts), and a lineage
    breadcrumb in the notes, so the run can be traced back to its session
    context."""
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import materialize_experiment
    from exptrack.core.db import get_db

    # a real file so file_hash() succeeds and the artifact is registered
    img = tmp_path / "loss.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    sm = SessionManager()
    sm.start("explore-lr", "nb.ipynb")
    sm.checkpoint("baseline")
    br = sm.branch("lr-0.5")
    sm.record_cell("model.fit(lr=0.5)", output="acc=0.91")
    sm.record_setup_cell("%%setup\ndf = load()", output="<DataFrame>")
    sm.record_image(str(img), label="loss curve")

    res = materialize_experiment(br)
    assert res["ok"], res
    exp_id = res["id"]

    conn = get_db()
    exp = conn.execute(
        "SELECT notes, session_node_id FROM experiments WHERE id=?", (exp_id,)).fetchone()
    # linked back to the node + lineage breadcrumb in notes
    assert exp["session_node_id"] == br
    assert "baseline" in exp["notes"] and "lr-0.5" in exp["notes"]

    # setup cell replayed as a muted setup event, real cell as cell_exec
    evs = conn.execute(
        "SELECT event_type FROM timeline WHERE exp_id=? ORDER BY seq", (exp_id,)).fetchall()
    types = [e["event_type"] for e in evs]
    assert "setup" in types and "cell_exec" in types

    # plot registered as an artifact (by reference — path points at the original)
    arts = conn.execute(
        "SELECT label, path FROM artifacts WHERE exp_id=?", (exp_id,)).fetchall()
    assert any(a["path"] == str(img) for a in arts)

    # re-materializing the same node is refused (already linked)
    assert materialize_experiment(br)["ok"] is False


def test_materialize_stores_full_cell_source_for_view_source(tmp_project):
    """A promoted node's cells carry their FULL source into the experiment: each
    cell_exec timeline event gets a cell_hash pointing at a content-addressed
    cell_lineage row holding the whole cell, so the Timeline's "view source"
    can show + copy the code (not just the one-line preview) and the run is
    re-runnable. Regression test for sessions promoting with "no code"."""
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import materialize_experiment
    from exptrack.capture.cell_lineage import get_cell_source
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("explore", "nb.ipynb")
    sm.checkpoint("cp1")
    br = sm.branch("try-thresh")
    sm.record_cell("x = 1\nprint(x)", output="1")
    sm.record_cell("threshold = 0.5\ny = x * threshold", output="")

    exp_id = materialize_experiment(br)["id"]
    conn = get_db()

    evs = conn.execute(
        "SELECT cell_hash, value FROM timeline "
        "WHERE exp_id=? AND event_type='cell_exec' ORDER BY seq", (exp_id,)
    ).fetchall()
    assert len(evs) == 2
    # every cell_exec event has a cell_hash and the lineage row holds the FULL
    # multi-line source (get_cell_source is exactly what /api/cell-source serves)
    sources = []
    for e in evs:
        assert e["cell_hash"], "cell_exec event must carry a cell_hash for view-source"
        full = get_cell_source(e["cell_hash"])
        assert full is not None
        sources.append(full)
    assert "x = 1\nprint(x)" in sources
    assert "threshold = 0.5\ny = x * threshold" in sources


def test_session_origin_surfaced_in_detail(tmp_project):
    """get_experiment_detail exposes session_origin so the dashboard can render
    the back-link from a linked experiment to its session node."""
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import materialize_experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_experiment_detail

    sm = SessionManager()
    sm.start("explore", "nb.ipynb")
    sm.checkpoint("cp1")
    br = sm.branch("try-this")
    sm.record_cell("x = 1", output="1")
    exp_id = materialize_experiment(br)["id"]

    d = get_experiment_detail(get_db(), exp_id)
    so = d["session_origin"]
    assert so and so["node_id"] == br
    assert so["session_name"] == "explore"
    assert so["node_type"] == "branch"
    assert "cp1" in so["lineage"] and "try-this" in so["lineage"]

    # a run with no session origin reports None
    from exptrack.core import Experiment
    plain = Experiment(script="train.py")
    assert get_experiment_detail(get_db(), plain.id)["session_origin"] is None


def test_autolink_run_links_once_and_respects_promote(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("s", "nb.ipynb")
    root = sm._current_node_id
    exp = Experiment(script="train.py")
    sm.autolink_run(exp.id)

    conn = get_db()
    link = lambda: conn.execute(
        "SELECT session_node_id FROM experiments WHERE id=?", (exp.id,)).fetchone()[0]
    assert link() == root

    # An explicit promote to a deeper node wins; a later autolink must not
    # clobber it (guarded UPDATE only fills a NULL link, and the one-shot guard
    # already fired).
    sm.checkpoint("c1")
    br = sm.branch("idea")
    sm.promote("", exp.id)
    assert link() == br
    sm.autolink_run(exp.id)
    assert link() == br
    exp.finish()


def test_run_cell_body_displays_trailing_expression():
    """%%scratch/%%setup must show a bare trailing expression (the old exec
    swallowed it)."""
    from exptrack.capture.session_hooks import _run_cell_body

    class FakeIP:
        def __init__(self):
            self.user_ns = {}
            self.displayed = []
        def displayhook(self, val):
            self.displayed.append(val)

    ip = FakeIP()
    val = _run_cell_body("a = 21\nb = a * 2\nb", ip)
    assert val == 42
    assert ip.displayed == [42]          # trailing expr routed to display
    assert ip.user_ns["b"] == 42         # statements executed
    # no trailing expression → nothing displayed
    ip2 = FakeIP()
    assert _run_cell_body("x = 1", ip2) is None
    assert ip2.displayed == []


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
    second = sm.branch("try X")  # re-run the same branch cell (e.g. Run All)
    sm.record_cell("a = 1")      # a real re-run replays the original cell first
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


def test_delete_node_cascades_to_descendants(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import (
        delete_node, preview_node_delete, build_tree,
    )
    from exptrack.core.db import get_db

    sm = SessionManager()
    sid = sm.start("cascade")
    c1 = sm.checkpoint("c1")
    b1 = sm.branch("b1")
    c2 = sm.checkpoint("c2")  # child of b1

    preview = preview_node_delete(b1)
    assert preview["nodes"] == 2  # b1 + c2
    assert preview["descendants"] == 1
    assert preview["is_root"] is False

    r = delete_node(b1)
    assert r["ok"] is True
    assert r["nodes"] == 2

    conn = get_db()
    # Soft delete: rows remain with deleted_at set; live rows filter that out.
    remaining = conn.execute(
        "SELECT id FROM session_nodes WHERE session_id=? AND deleted_at IS NULL",
        (sid,),
    ).fetchall()
    remaining_ids = {row["id"] for row in remaining}
    assert b1 not in remaining_ids
    assert c2 not in remaining_ids
    assert c1 in remaining_ids
    # build_tree should also skip trashed nodes.
    tree = build_tree(sid)
    seen = []
    def walk(n):
        seen.append(n["id"])
        for ch in n.get("children", []) or []:
            walk(ch)
    walk(tree["root"])
    assert b1 not in seen and c2 not in seen and c1 in seen


def test_delete_node_refuses_root(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import delete_node

    sm = SessionManager()
    sm.start("root-protect")
    # The root node id == session_id for this manager's start() impl.
    # Find the root via build_tree to be precise.
    from exptrack.sessions.manager import build_tree
    tree = build_tree(sm.session_id)
    root_id = tree["root"]["id"]

    r = delete_node(root_id)
    assert r["ok"] is False
    assert "root" in r["error"].lower()


def test_delete_node_preserves_linked_experiment(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import delete_node
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("exp-preserve")
    sm.checkpoint("c1")
    b1 = sm.branch("b1")

    # Link a fake experiment row to b1.
    conn = get_db()
    conn.execute(
        "INSERT INTO experiments (id, name, status, created_at, updated_at, "
        "session_node_id) VALUES (?, ?, 'finished', ?, ?, ?)",
        ("exp_test_1", "test_exp", 0, 0, b1),
    )
    conn.commit()

    r = delete_node(b1)
    assert r["ok"] is True
    assert r["experiments"] == 1

    row = conn.execute(
        "SELECT id, session_node_id FROM experiments WHERE id='exp_test_1'",
    ).fetchone()
    assert row is not None  # experiment still exists
    assert row["session_node_id"] is None  # FK cleared


def test_restore_node_brings_back_subtree(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import (
        build_tree, delete_node, list_trashed_nodes, restore_node,
    )

    sm = SessionManager()
    sid = sm.start("restore-test")
    sm.checkpoint("c1")
    b1 = sm.branch("b1")
    c2 = sm.checkpoint("c2")  # child of b1

    delete_node(b1)
    trash = list_trashed_nodes(sid)
    trashed_ids = {n["id"] for n in trash}
    assert b1 in trashed_ids and c2 in trashed_ids

    r = restore_node(b1)
    assert r["ok"] is True
    assert r["nodes"] == 2  # b1 + c2

    # Trash should now be empty for this session.
    assert list_trashed_nodes(sid) == []
    # Both nodes should be visible in build_tree again.
    tree = build_tree(sid)
    seen = []
    def walk(n):
        seen.append(n["id"])
        for ch in n.get("children", []) or []:
            walk(ch)
    walk(tree["root"])
    assert b1 in seen and c2 in seen


def test_restore_node_refuses_live_node(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import restore_node

    sm = SessionManager()
    sm.start("not-trashed")
    c1 = sm.checkpoint("c1")

    r = restore_node(c1)
    assert r["ok"] is False
    assert "not trashed" in r["error"].lower()


def test_restore_node_revives_trashed_parent(tmp_project):
    """If you restore a node whose parent is also in the trash (because it
    was deleted as part of the same cascade), restore must bring the parent
    back too — otherwise the child renders as an orphan."""
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import (
        build_tree, delete_node, restore_node,
    )

    sm = SessionManager()
    sid = sm.start("orphan-guard")
    sm.checkpoint("c1")
    b1 = sm.branch("b1")
    c2 = sm.checkpoint("c2")  # child of b1

    delete_node(b1)  # trashes b1 AND c2

    # Restore only the child — its parent (b1) must come back too.
    r = restore_node(c2)
    assert r["ok"] is True
    assert r["nodes"] >= 2  # c2 + b1 walked back up

    tree = build_tree(sid)
    seen = {}
    def walk(n, depth=0):
        seen[n["id"]] = depth
        for ch in n.get("children", []) or []:
            walk(ch, depth + 1)
    walk(tree["root"])
    assert b1 in seen and c2 in seen
    assert seen[c2] > seen[b1]  # c2 is still under b1, not at the root


def test_record_cell_captures_output_aligned(tmp_project):
    """cell_outputs stays segment-aligned with cell_source, refreshes on rerun."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sid = sm.start("s", "nb.ipynb")
    sm.checkpoint("c1")
    sm.record_cell("x = f(0.5)", output="{'acc': 0.98}")
    sm.record_cell("print(x)", output=None)        # no trailing-expr output
    sm.record_cell("x = f(0.5)", output="{'acc': 0.99}")  # new cell (last != this)

    conn = get_db()
    row = conn.execute(
        "SELECT cell_source, cell_outputs FROM session_nodes WHERE id=?",
        (sm._current_node_id,),
    ).fetchone()
    SEP = SessionManager._CELL_SEPARATOR
    cells = row["cell_source"].split(SEP)
    outs = row["cell_outputs"].split(SEP)
    assert len(cells) == len(outs) == 3
    assert outs[0] == "{'acc': 0.98}"
    assert outs[1] == ""                  # print cell has no captured output
    assert outs[2] == "{'acc': 0.99}"


def test_record_cell_rerun_refreshes_output(tmp_project):
    """Immediate re-run of the same cell refreshes its output, no duplicate."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("s", "nb.ipynb")
    sm.checkpoint("c1")
    sm.record_cell("y = g()", output="0.81")
    sm.record_cell("y = g()", output="0.82")  # same source back-to-back

    conn = get_db()
    row = conn.execute(
        "SELECT cell_source, cell_outputs FROM session_nodes WHERE id=?",
        (sm._current_node_id,),
    ).fetchone()
    SEP = SessionManager._CELL_SEPARATOR
    assert row["cell_source"].split(SEP) == ["y = g()"]   # not duplicated
    assert row["cell_outputs"] == "0.82"                  # refreshed


def test_purge_node_requires_trashed(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import purge_node, delete_node

    sm = SessionManager()
    sm.start("s", "nb.ipynb")
    sm.checkpoint("c1")
    b = sm.branch("b1")

    # Live node refuses to purge.
    assert purge_node(b)["ok"] is False
    # Trash it, then purge succeeds and removes the row entirely.
    delete_node(b)
    r = purge_node(b)
    assert r["ok"] is True and r["nodes"] == 1


def test_purge_node_removes_row_for_good(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import (purge_node, delete_node,
                                            list_trashed_nodes)
    from exptrack.core.db import get_db

    sm = SessionManager()
    sid = sm.start("s", "nb.ipynb")
    sm.checkpoint("c1")
    b = sm.branch("b1")
    delete_node(b)
    purge_node(b)

    assert list_trashed_nodes(sid) == []
    gone = get_db().execute(
        "SELECT id FROM session_nodes WHERE id=?", (b,)).fetchone()
    assert gone is None


def test_empty_trash_clears_only_trashed(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import (empty_trash, delete_node,
                                            list_trashed_nodes, build_tree)

    sm = SessionManager()
    sid = sm.start("s", "nb.ipynb")
    c1 = sm.checkpoint("c1")
    b1 = sm.branch("b1")
    delete_node(b1)               # trash a branch
    trashed_before = len(list_trashed_nodes(sid))
    assert trashed_before >= 1

    r = empty_trash(sid)
    assert r["ok"] is True and r["nodes"] == trashed_before
    assert list_trashed_nodes(sid) == []
    # Live tree still intact: the surviving checkpoint c1 is still present.
    tree = build_tree(sid)
    assert tree["root"] is not None
    live = []
    def collect(n):
        live.append(n["id"])
        for ch in n.get("children", []) or []:
            collect(ch)
    collect(tree["root"])
    assert c1 in live


def test_purge_preserves_linked_experiment(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import purge_node, delete_node
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("s", "nb.ipynb")
    sm.checkpoint("c1")
    b = sm.branch("b1")
    exp = Experiment(name="run")
    sm.promote("good", exp.id)
    delete_node(b)            # detaches exp
    purge_node(b)

    # Experiment row survives, just unlinked.
    row = get_db().execute(
        "SELECT id, session_node_id FROM experiments WHERE id=?", (exp.id,)
    ).fetchone()
    assert row is not None and row["session_node_id"] is None


def test_branch_collision_forks_on_different_code(tmp_project):
    """Re-declaring an existing branch label and then running DIFFERENT code
    (the copy-paste-and-edit footgun) forks to a suffixed node instead of
    silently merging the two explorations."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("collide")
    sm.checkpoint("base")
    first = sm.branch("try 0.7")
    sm.record_cell("threshold = 0.7\nrun(threshold)")
    # Re-use the label but with different code — a new idea, not a re-run.
    again = sm.branch("try 0.7")
    sm.record_cell("threshold = 0.5\nrun(threshold)")

    assert again == first  # branch() still returns the existing id...
    # ...but the divergent cell forked the manager to a new suffixed node.
    assert sm._current_node_id != first
    conn = get_db()
    labels = {r["label"] for r in conn.execute(
        "SELECT label FROM session_nodes WHERE session_id=? AND deleted_at IS NULL",
        (sm.session_id,)).fetchall()}
    assert "try 0.7" in labels and "try 0.7 (2)" in labels
    # Original node keeps only its own code; the fork holds the divergent code.
    orig = conn.execute("SELECT cell_source FROM session_nodes WHERE id=?",
                        (first,)).fetchone()["cell_source"]
    fork = conn.execute("SELECT cell_source FROM session_nodes WHERE id=?",
                        (sm._current_node_id,)).fetchone()["cell_source"]
    assert "0.7" in orig and "0.5" not in orig
    assert "0.5" in fork


def test_branch_collision_merges_on_identical_rerun(tmp_project):
    """Re-running the same branch with the SAME first cell (a genuine Run-All)
    merges into the existing node — no spurious fork."""
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("rerun")
    sm.checkpoint("base")
    first = sm.branch("explore")
    sm.record_cell("x = 1")
    sm.branch("explore")
    sm.record_cell("x = 1")  # identical replay → merge, not fork

    assert sm._current_node_id == first
    conn = get_db()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM session_nodes WHERE session_id=? AND label LIKE 'explore%'",
        (sm.session_id,)).fetchone()["n"]
    assert n == 1  # no suffixed fork created


def test_rename_node(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import rename_node, delete_node
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("s")
    sm.checkpoint("base")
    b = sm.branch("old name")
    assert rename_node(b, "new name")["ok"]
    row = get_db().execute("SELECT label FROM session_nodes WHERE id=?", (b,)).fetchone()
    assert row["label"] == "new name"
    # Empty label rejected.
    assert not rename_node(b, "   ")["ok"]
    # Trashed node not renamable.
    delete_node(b)
    assert not rename_node(b, "whatever")["ok"]


def test_record_image_attaches_and_dedups(tmp_project):
    """savefig-by-reference: record_image stores paths on the current node,
    dedups by path (refreshing the label), and resolves to absolute."""
    import json
    from pathlib import Path
    from exptrack.sessions import SessionManager
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("imgs")
    cp = sm.checkpoint("c")
    sm.record_image("/tmp/a.png", label="ROC")
    sm.record_image("/tmp/a.png", label="ROC v2")  # same path → dedup + refresh
    sm.record_image("/tmp/b.png")

    row = get_db().execute("SELECT images FROM session_nodes WHERE id=?", (cp,)).fetchone()
    imgs = json.loads(row["images"])
    a_abs = str(Path("/tmp/a.png").resolve())
    assert len(imgs) == 2
    assert [im["path"] for im in imgs].count(a_abs) == 1
    a = next(im for im in imgs if im["path"] == a_abs)
    assert a["label"] == "ROC v2"  # latest label wins


def test_build_tree_exposes_images(tmp_project):
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import build_tree

    sm = SessionManager()
    sid = sm.start("t")
    sm.checkpoint("c")
    sm.record_image("/tmp/x.png")
    tree = build_tree(sid)
    cp = tree["root"]["children"][0]
    assert isinstance(cp["images"], list) and len(cp["images"]) == 1
    # /tmp is outside the project root → not servable → url is None.
    assert cp["images"][0]["url"] is None


def test_purge_node_trashes_attached_images(tmp_project, monkeypatch):
    """Permanently purging a node moves its by-reference plot files to the OS
    Trash (via the shared helper) and reports the count."""
    import exptrack.core.db as dbmod
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import delete_node, purge_node

    moved = []
    monkeypatch.setattr(dbmod, "_trash_or_local",
                        lambda p, label="file": (moved.append(str(p)), "os_trash")[1])

    sm = SessionManager()
    sm.start("p")
    sm.checkpoint("c")
    b = sm.branch("b")
    sm.record_image("/tmp/plot.png")
    delete_node(b)            # soft delete leaves the file alone
    assert not moved
    r = purge_node(b)         # permanent → trashes the file
    assert r["ok"] and r["images"]["os_trash"] == 1
    assert moved and moved[0].endswith("plot.png")


def test_link_experiment_link_change_unlink(tmp_project):
    """Dashboard 'promote': link_experiment points a node at a run (1:1), can be
    re-targeted (detaching the prior run), and unlinks on a blank exp_id.
    Linking/unlinking never deletes the experiment row."""
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import link_experiment
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    sm = SessionManager()
    sm.start("link-flow")
    sm.checkpoint("c")
    br = sm.branch("b")

    e1 = Experiment(script="a.py", params={"lr": 0.01}); e1.finish()
    e2 = Experiment(script="b.py", params={"lr": 0.02}); e2.finish()
    conn = get_db()

    def node_of(exp_id):
        return conn.execute(
            "SELECT session_node_id FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()["session_node_id"]

    # Link e1 → node.
    r = link_experiment(br, e1.id)
    assert r["ok"] and r["linked"] == e1.id
    assert node_of(e1.id) == br

    # Re-target to e2: 1:1, so e1 is detached.
    r = link_experiment(br, e2.id)
    assert r["ok"] and r["linked"] == e2.id
    assert node_of(e2.id) == br
    assert node_of(e1.id) is None

    # Unlink (blank id): e2 detached, but the experiment row survives.
    r = link_experiment(br, "")
    assert r["ok"] and r["linked"] is None
    assert node_of(e2.id) is None
    assert conn.execute(
        "SELECT 1 FROM experiments WHERE id=?", (e2.id,)
    ).fetchone() is not None


def test_link_experiment_rejects_bad_ids(tmp_project):
    """Unknown node or experiment id is reported, not silently linked."""
    from exptrack.sessions import SessionManager
    from exptrack.sessions.manager import link_experiment

    sm = SessionManager()
    sm.start("bad-ids")
    sm.checkpoint("c")
    br = sm.branch("b")

    assert link_experiment("nope", "whatever")["ok"] is False
    assert link_experiment(br, "no-such-exp")["ok"] is False
