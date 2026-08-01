"""Session Trees: a Run-All must not duplicate or misattribute recorded work.

Every test here reproduces a bug found in the pre-1.0 review. They share one
shape: drive the manager exactly as a notebook would, twice (a second Run-All),
and assert the stored tree is the same size the first pass produced.
"""
from __future__ import annotations

import pytest


def _cells(conn, node_id, col="cell_source"):
    from exptrack.sessions import SessionManager
    row = conn.execute(
        f"SELECT {col} FROM session_nodes WHERE id=?", (node_id,)
    ).fetchone()
    blob = row[col] if row and row[col] else ""
    return blob.split(SessionManager._CELL_SEPARATOR) if blob else []


def _branch_labels(conn, sid):
    """Labels of the session's live branch/abandoned nodes, in creation order."""
    return [r["label"] for r in conn.execute(
        "SELECT label FROM session_nodes WHERE session_id=? AND node_type IN "
        "('branch','abandoned') AND deleted_at IS NULL ORDER BY seq", (sid,),
    ).fetchall()]


@pytest.fixture()
def sm(tmp_project):
    """A live SessionManager registered as the current session, torn down after."""
    from exptrack.sessions import SessionManager, set_current_session
    mgr = SessionManager()
    set_current_session(mgr)
    yield mgr
    set_current_session(None)


@pytest.fixture()
def no_session(tmp_project):
    """No current session — for tests driving the magics, which create their own."""
    from exptrack.sessions import set_current_session
    set_current_session(None)
    yield
    set_current_session(None)


# ── 1. Deleting a node must not leak its cells onto the survivor ─────────────

def test_deleting_a_node_does_not_leak_its_cells_onto_the_fallback(sm):
    """delete_node re-pointed _current_node_id by assignment, leaving the
    cached cell blob and both replay cursors describing the *deleted* node —
    so the next recorded cell wrote the trashed branch's cells onto the
    checkpoint the deletion fell back to."""
    from exptrack.core.db import get_db
    from exptrack.sessions.manager import delete_node

    sm.start("s", "nb.ipynb")
    cp = sm.checkpoint("base")
    sm.record_cell("base_cell = 1")
    br = sm.branch("A")
    sm.record_cell("a = 1")
    sm.record_cell("b = 2")

    assert delete_node(br)["ok"]
    assert sm._current_node_id == cp

    sm.record_cell("c = 3")

    conn = get_db()
    assert _cells(conn, cp) == ["base_cell = 1", "c = 3"], (
        "the deleted branch's cells reappeared on the checkpoint")


# ── 2. %%setup cells must not double every Run-All ───────────────────────────

def test_setup_cells_are_not_duplicated_by_a_run_all(sm):
    """The setup store deduped only against its last segment, so replaying two
    or more setup cells in order appended a fresh copy of each on every pass."""
    from exptrack.core.db import get_db

    sm.start("s", "nb.ipynb")
    cp = sm.checkpoint("base")
    sm.record_setup_cell("%%setup\ndf = load()", output="<df>")
    sm.record_setup_cell("%%setup\nfeats = build(df)", output="<feats>")
    sm.record_cell("model = train(feats)", output="acc=0.9")

    conn = get_db()
    assert len(_cells(conn, cp, "setup_source")) == 2

    # Run-All #2: the same magics and the same cells, in the same order.
    sm.start("s", "nb.ipynb")
    sm.checkpoint("base")
    sm.record_setup_cell("%%setup\ndf = load()", output="<df>")
    sm.record_setup_cell("%%setup\nfeats = build(df)", output="<feats>")
    sm.record_cell("model = train(feats)", output="acc=0.9")

    setup = _cells(conn, cp, "setup_source")
    outs = _cells(conn, cp, "setup_outputs")
    assert len(setup) == 2, f"setup cells doubled on Run-All: {setup}"
    assert len(outs) == 2, "setup outputs drifted out of alignment"
    assert len(_cells(conn, cp)) == 1


def test_a_new_setup_cell_still_appends(sm):
    """The replay cursor must not swallow genuinely new prep code."""
    from exptrack.core.db import get_db

    sm.start("s", "nb.ipynb")
    cp = sm.checkpoint("base")
    sm.record_setup_cell("%%setup\ndf = load()")
    sm.record_setup_cell("%%setup\nfeats = build(df)")
    sm.record_setup_cell("%%setup\nextra = more(feats)")

    assert len(_cells(get_db(), cp, "setup_source")) == 3


def test_setup_output_change_is_recorded_in_place(sm):
    """A replayed setup cell whose output changed refreshes, not appends."""
    from exptrack.core.db import get_db

    sm.start("s", "nb.ipynb")
    cp = sm.checkpoint("base")
    sm.record_setup_cell("%%setup\ndf = load()", output="rows=10")

    sm.start("s", "nb.ipynb")
    sm.checkpoint("base")
    sm.record_setup_cell("%%setup\ndf = load()", output="rows=20")

    conn = get_db()
    assert len(_cells(conn, cp, "setup_source")) == 1
    assert _cells(conn, cp, "setup_outputs") == ["rows=20"]


# ── 3. Re-declaring the current checkpoint / session re-arms the replay ──────

def test_rerunning_a_checkpoints_own_cells_does_not_duplicate_them(sm):
    """checkpoint()'s "already on this checkpoint" early return skipped
    _switch_to_node, so the cursors stayed where the previous pass left them
    and every cell of the node was appended again on each Run-All."""
    from exptrack.core.db import get_db

    sm.start("s", "nb.ipynb")
    cp = sm.checkpoint("base")
    sm.record_cell("a = 1")
    sm.record_cell("b = 2")

    # Run-All #2 — no branch, so the current node is still this checkpoint.
    sm.start("s", "nb.ipynb")
    sm.checkpoint("base")
    sm.record_cell("a = 1")
    sm.record_cell("b = 2")

    assert _cells(get_db(), cp) == ["a = 1", "b = 2"]


def test_root_cells_are_not_duplicated_or_misattributed_by_a_run_all(sm):
    """Cells run before the first checkpoint — imports, data loading — belong
    to the root. Re-running `session start` used to be a no-op, so the second
    pass recorded them onto whatever node the previous pass ended on."""
    from exptrack.core.db import get_db
    from exptrack.sessions.lifecycle import _session_root_id

    sid = sm.start("s", "nb.ipynb")
    conn = get_db()
    root = _session_root_id(conn, sid)

    sm.record_cell("import numpy as np")
    sm.record_cell("data = load()")
    cp = sm.checkpoint("base")
    sm.record_cell("model = train(data)")

    assert _cells(conn, root) == ["import numpy as np", "data = load()"]

    # Run-All #2, from the very top.
    sm.start("s", "nb.ipynb")
    sm.record_cell("import numpy as np")
    sm.record_cell("data = load()")
    sm.checkpoint("base")
    sm.record_cell("model = train(data)")

    assert _cells(conn, root) == ["import numpy as np", "data = load()"], (
        "root cells duplicated across Run-All passes")
    assert _cells(conn, cp) == ["model = train(data)"], (
        "root-level cells were misattributed to the checkpoint")
    # And no second spine was grown.
    n_nodes = conn.execute(
        "SELECT COUNT(*) FROM session_nodes WHERE session_id=? AND deleted_at IS NULL",
        (sid,),
    ).fetchone()[0]
    assert n_nodes == 2


# ── 4. The branch-label collision fork is idempotent ────────────────────────

def test_an_edited_branch_forks_once_not_once_per_run_all(sm):
    """_resolve_branch_collision compared only against the *original* node, so
    each Run-All of an edited branch forked another suffix: A (2), A (3), …"""
    from exptrack.core.db import get_db

    sid = sm.start("s", "nb.ipynb")
    sm.checkpoint("base")
    sm.branch("A")
    sm.record_cell("t = 0.7")

    # The user edits the branch's first cell and re-runs everything, twice.
    for _ in range(2):
        sm.start("s", "nb.ipynb")
        sm.checkpoint("base")
        sm.branch("A")
        sm.record_cell("t = 0.9")

    conn = get_db()
    labels = _branch_labels(conn, sid)
    assert labels == ["A", "A (2)"], f"forked once per Run-All: {labels}"

    fork = conn.execute(
        "SELECT id FROM session_nodes WHERE session_id=? AND label='A (2)'",
        (sid,),
    ).fetchone()["id"]
    assert _cells(conn, fork) == ["t = 0.9"]
    assert sm._current_node_id == fork


def test_a_renamed_fork_is_not_re_forked(sm):
    """The fork notice invites the user to rename the node, which used to defeat
    the guard: identity was a `label (N)` prefix match, so a renamed fork stopped
    being findable and the next Run-All forked again beside it. Identity is the
    first recorded cell instead."""
    from exptrack.core.db import get_db
    from exptrack.sessions.manager import rename_node

    sid = sm.start("s", "nb.ipynb")
    sm.checkpoint("base")
    sm.branch("A")
    sm.record_cell("t = 0.7")

    sm.start("s", "nb.ipynb")
    sm.checkpoint("base")
    sm.branch("A")
    sm.record_cell("t = 0.9")          # → A (2)
    fork = sm._current_node_id
    rename_node(fork, "threshold sweep")

    sm.start("s", "nb.ipynb")          # Run-All after the rename
    sm.checkpoint("base")
    sm.branch("A")
    sm.record_cell("t = 0.9")

    assert sm._current_node_id == fork, "the renamed fork was not recognized"
    labels = [r["label"] for r in get_db().execute(
        "SELECT label FROM session_nodes WHERE session_id=? AND parent_id IS NOT NULL "
        "AND node_type!='checkpoint' AND deleted_at IS NULL ORDER BY seq", (sid,),
    ).fetchall()]
    assert labels == ["A", "threshold sweep"], f"re-forked after a rename: {labels}"


def test_a_fork_promoted_to_checkpoint_is_not_re_forked(sm):
    """Same identity question for a fork the user promoted — the old node_type
    filter made a promoted fork invisible to the guard."""
    from exptrack.sessions.manager import promote_to_checkpoint

    sm.start("s", "nb.ipynb")
    sm.checkpoint("base")
    sm.branch("A")
    sm.record_cell("t = 0.7")

    sm.start("s", "nb.ipynb")
    sm.checkpoint("base")
    sm.branch("A")
    sm.record_cell("t = 0.9")
    fork = sm._current_node_id
    promote_to_checkpoint(fork)

    sm.start("s", "nb.ipynb")
    sm.checkpoint("base")
    sm.branch("A")
    sm.record_cell("t = 0.9")

    assert sm._current_node_id == fork, "a promoted fork was re-forked"


def test_a_genuinely_different_third_idea_still_forks(sm):
    """Idempotence must not collapse distinct explorations into one node."""
    from exptrack.core.db import get_db

    sid = sm.start("s", "nb.ipynb")
    sm.checkpoint("base")
    sm.branch("A")
    sm.record_cell("t = 0.7")

    sm.branch("A")
    sm.record_cell("t = 0.9")      # → A (2)
    sm.branch("A")
    sm.record_cell("t = 0.5")      # → A (3), a third distinct idea

    assert _branch_labels(get_db(), sid) == ["A", "A (2)", "A (3)"]


def test_the_session_start_magic_returns_to_the_root_on_a_rerun(no_session):
    """The magic returned early on an active session, so start()'s replay
    handling was never reached from a real notebook."""
    from exptrack.capture.session_hooks import _session_start
    from exptrack.core.db import get_db
    from exptrack.sessions import get_current_session
    from exptrack.sessions.lifecycle import _session_root_id

    _session_start("explore")
    mgr = get_current_session()
    sid = mgr.session_id
    conn = get_db()
    root = _session_root_id(conn, sid)

    mgr.record_cell("import numpy as np")
    mgr.checkpoint("base")
    mgr.record_cell("model = train()")

    _session_start("explore")            # Run-All #2
    assert get_current_session().session_id == sid, "a second session was created"
    assert mgr._current_node_id == root, "the magic did not return to the root"

    mgr.record_cell("import numpy as np")
    assert _cells(conn, root) == ["import numpy as np"]


def test_starting_a_differently_named_session_still_warns(no_session):
    """Only the *same* name is a replay; a different one is a mistake to flag.
    start() itself refuses it, so every caller gets the rule, not just the magic."""
    from exptrack.capture.session_hooks import _session_start
    from exptrack.sessions import get_current_session

    _session_start("first")
    mgr = get_current_session()
    sid = mgr.session_id
    _session_start("second")
    assert get_current_session().session_id == sid, (
        "a second session was started over a live one")
    assert mgr.start("second") == "", "start() must refuse a different name"


# ── 5. The dashboard's end-session matches the magic's ──────────────────────

def test_dashboard_end_session_ignores_trashed_nodes(tmp_project):
    """The route had its own copy of the abandon-open-branches UPDATE without
    the `deleted_at IS NULL` filters, so it relabelled trashed branches and
    counted trashed children as children."""
    from exptrack.core.db import get_db
    from exptrack.dashboard.routes.write_routes.sessions import api_session_end
    from exptrack.sessions import SessionManager, set_current_session
    from exptrack.sessions.manager import delete_node

    sm = SessionManager()
    set_current_session(sm)
    try:
        sid = sm.start("s", "nb.ipynb")
        sm.checkpoint("base")
        trashed = sm.branch("gone")
        sm.record_cell("x = 1")
        open_branch = sm.branch("open")
        sm.record_cell("y = 2")
        # A branch whose only child is trashed is still open.
        parent = sm.branch("has-trashed-child")
        sm.record_cell("z = 3")
        child = sm.checkpoint("child-cp")
        assert delete_node(child)["ok"]
        assert delete_node(trashed)["ok"]
    finally:
        set_current_session(None)

    conn = get_db()
    assert api_session_end(conn, sid, {}) == {"ok": True}

    def node_type(nid):
        return conn.execute(
            "SELECT node_type FROM session_nodes WHERE id=?", (nid,)
        ).fetchone()["node_type"]

    assert node_type(trashed) == "branch", (
        "a trashed branch was relabelled — it comes back wrong on restore")
    assert node_type(open_branch) == "abandoned"
    assert node_type(parent) == "abandoned", (
        "a branch whose only child is trashed is open and must be abandoned")
    assert conn.execute(
        "SELECT status FROM sessions WHERE id=?", (sid,)
    ).fetchone()["status"] == "ended"


def test_dashboard_end_session_uses_the_manager_for_the_live_session(tmp_project):
    """When the session being ended is live in this process, the full manager
    path runs — so its in-process state is cleared rather than left pointing at
    an ended session."""
    from exptrack.core.db import get_db
    from exptrack.dashboard.routes.write_routes.sessions import api_session_end
    from exptrack.sessions import SessionManager, set_current_session

    sm = SessionManager()
    set_current_session(sm)
    try:
        sid = sm.start("s", "nb.ipynb")
        sm.checkpoint("base")
        sm.branch("A")
        sm.record_cell("x = 1")

        assert api_session_end(get_db(), sid, {}) == {"ok": True}
        assert sm.session_id is None
        assert sm._current_node_id is None
    finally:
        set_current_session(None)


# ── The invariant behind all of the above ────────────────────────────────────

def test_every_node_returning_magic_routes_through_switch_to_node(sm, monkeypatch):
    """`_switch_to_node` is the single choke point for changing the current node
    — it refreshes the cached cell blobs and re-arms both replay cursors. Four of
    the bugs above were paths that moved the current node without it (or that
    resolved to a node and returned bare).

    The docstring says "every path that changes the current node must go through
    here"; this asserts it rather than trusting prose, so the fifth such magic
    can't quietly skip it.
    """
    from exptrack.sessions import SessionManager

    calls = []
    real = SessionManager._switch_to_node

    def spy(self, node_id):
        calls.append(node_id)
        return real(self, node_id)

    monkeypatch.setattr(SessionManager, "_switch_to_node", spy)

    sm.start("s", "nb.ipynb")
    sm.record_cell("x = 1")

    # Each of these resolves to a node and returns its id; each must have armed
    # the cursors on the way, whether it created the node or returned to it.
    for label, call in (
        ("new checkpoint",      lambda: sm.checkpoint("base")),
        ("re-declared same",    lambda: sm.checkpoint("base")),
        ("new branch",          lambda: sm.branch("A")),
        ("re-declared branch",  lambda: sm.branch("A")),
        ("second checkpoint",   lambda: sm.checkpoint("second")),
        ("ancestor checkpoint", lambda: sm.checkpoint("base")),
        ("replayed session",    lambda: sm.start("s", "nb.ipynb")),
    ):
        calls.clear()
        nid = call()
        assert nid, f"{label}: returned no id"
        assert calls, f"{label}: changed the current node without _switch_to_node"
        assert sm._current_node_id == calls[-1], (
            f"{label}: current node disagrees with the last switch")
        assert sm._replay_idx == 0, f"{label}: replay cursor was not re-armed"
        assert sm._last_cell_idx is None, f"{label}: last-cell cursor stale"
        assert sm._setup_replay_idx == 0, f"{label}: setup cursor was not re-armed"
