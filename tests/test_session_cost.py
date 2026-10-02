"""What a session costs: git subprocesses per magic, tree payload bytes, and
the storage a materialized node writes.

These are the three places a Session Tree stops being cheap: every structural
magic pays git process spawns (~20 ms each on Windows), the dashboard refetches
the whole tree on every mutation, and materializing N sibling branches copies
their shared ancestor chain N times.
"""
from __future__ import annotations

import json

# ── git subprocess cost per magic ───────────────────────────────────────────

def _count_git_calls(monkeypatch):
    """Patch the spawn (not the memo in front of it) and record every call."""
    from exptrack.core import git as G

    calls: list[tuple] = []

    def fake(*cmd):
        calls.append(tuple(cmd))
        if cmd[:1] == ("rev-parse",):
            return (True, "abc1234")
        if cmd[:1] == ("diff",):
            return (True, "diff --git a/x b/x\n+one line\n")
        return (True, "")

    monkeypatch.setattr(G, "_run_git", fake)
    return calls


def test_one_magic_never_runs_the_same_git_command_twice(tmp_project, monkeypatch):
    """A transition must not re-spawn a git command it already ran.

    Leaving a branch refreshes its diff, and the node we move *to* computes a
    diff against the same checkpoint in the same working tree — two identical
    `git diff <commit>` spawns, plus two `rev-parse --short HEAD`, for one
    keystroke. Each spawn is ~20 ms on Windows, so `%exptrack branch` cost
    ~95 ms where ~50 ms buys the identical result.
    """
    from exptrack.sessions import SessionManager

    sm = SessionManager()
    sm.start("cost")
    sm.checkpoint("cp")
    sm.branch("a")
    sm.record_cell("x = 1", "")

    calls = _count_git_calls(monkeypatch)
    sm.branch("b")
    assert calls, "branch() should still capture git state"
    assert len(calls) == len(set(calls)), f"duplicate git spawns in one magic: {calls}"


def test_a_later_magic_still_re_reads_git(tmp_project, monkeypatch):
    """The memo is per-magic, not per-session: a commit made between two
    magics must still be seen."""
    from exptrack.sessions import SessionManager

    sm = SessionManager()
    sm.start("cost2")
    sm.checkpoint("cp")
    calls = _count_git_calls(monkeypatch)
    sm.branch("a")
    n_first = len(calls)
    sm.branch("b")
    assert len(calls) > n_first, "each magic must re-read git state"


# ── tree payload bytes ──────────────────────────────────────────────────────

def _session_with_siblings(tmp_project, diff_body):
    from exptrack.core.db import get_db, store_git_diff
    from exptrack.sessions import SessionManager

    sm = SessionManager()
    sid = sm.start("payload", notebook="n.ipynb")
    cp = sm.checkpoint("cp")
    ids = [sm.branch(f"b{i}") for i in range(4)]
    conn = get_db()
    ref = store_git_diff(conn, diff_body)
    for nid in ids:
        conn.execute("UPDATE session_nodes SET git_diff=? WHERE id=?", (ref, nid))
    conn.commit()
    return sid, cp, ids


def test_tree_payload_sends_one_copy_of_a_shared_diff(tmp_project):
    """Sibling branches share one working tree, so they share one diff body.

    The server already stores it once (content-addressed) and resolves it
    memoized — but it serialized a full copy per node, so four branches off one
    checkpoint put four copies of the same (up to `max_git_diff_kb`) diff on the
    wire, on every tree refresh.
    """
    from exptrack.dashboard.routes import read_routes

    body = "diff --git a/z b/z\n" + "+UNIQUEMARKER\n" * 20
    sid, _cp, _ids = _session_with_siblings(tmp_project, body)

    payload = read_routes.api_session_tree(None, sid)
    wire = json.dumps(payload)
    assert wire.count("UNIQUEMARKER") == 20, (
        "the shared diff body should appear exactly once on the wire, "
        f"found {wire.count('UNIQUEMARKER') // 20} copies")


def test_tree_payload_is_hydratable(tmp_project):
    """The compacted payload must carry everything needed to rebuild the full
    tree client-side: a ref per node and the body map."""
    from exptrack.dashboard.routes import read_routes
    from exptrack.sessions.manager import build_tree

    body = "diff --git a/z b/z\n+x\n"
    sid, _cp, ids = _session_with_siblings(tmp_project, body)
    payload = read_routes.api_session_tree(None, sid)

    bodies = payload.get("diffs")
    assert isinstance(bodies, dict) and bodies, "payload needs a diff body map"
    seen = {}

    def walk(n):
        seen[n["id"]] = n
        for c in n.get("children") or []:
            walk(c)

    walk(payload["root"])
    for nid in ids:
        node = seen[nid]
        assert "git_diff" not in node, "body should be replaced by a ref"
        assert bodies[node["git_diff_ref"]] == body

    # build_tree itself stays hydrated — the CLI renders from it.
    full = build_tree(sid)
    def first_branch(n):
        if n.get("node_type") == "branch":
            return n
        for c in n.get("children") or []:
            hit = first_branch(c)
            if hit:
                return hit
        return None
    assert first_branch(full["root"])["git_diff"] == body


def test_tree_payload_drops_the_per_node_lineage_chain(tmp_project):
    """Lineage is the node's ancestor labels — O(nodes x depth) bytes for a
    breadcrumb the client can walk itself from `parent_id`."""
    from exptrack.dashboard.routes import read_routes

    sid, _cp, _ids = _session_with_siblings(tmp_project, "diff --git a/z b/z\n+x\n")
    payload = read_routes.api_session_tree(None, sid)

    def walk(n):
        assert "lineage" not in n, "lineage should be rebuilt client-side"
        for c in n.get("children") or []:
            walk(c)

    walk(payload["root"])


# ── materialize storage ─────────────────────────────────────────────────────

def test_materialized_run_does_not_copy_ancestor_outputs(tmp_project):
    """A node's inherited ancestor cells carry identity, not results.

    `materialize_experiment` replays the whole ancestor chain so the run is
    self-contained — but it copied each ancestor cell's 200-char source preview
    *and* its captured output onto every descendant's timeline. N branches under
    a deep spine meant N copies of the same upstream previews and outputs:
    O(nodes x depth) rows of duplicated text, the dominant storage cost of
    finalizing a session. The full source already lives once in `cell_lineage`,
    keyed by the event's `cell_hash`.
    """
    from exptrack.core.db import get_db
    from exptrack.sessions import SessionManager
    from exptrack.sessions.materialize import materialize_experiment

    sm = SessionManager()
    sm.start("space", notebook="n.ipynb")
    sm.checkpoint("cp")
    sm.record_cell("import numpy as np\nANCESTOR_LINE = 1\nprint('up')",
                   "ANCESTOR_OUTPUT " + "x" * 500)
    node = sm.branch("b0")
    sm.record_cell("lr = 0.1\nOWN_LINE = 2", "OWN_OUTPUT 0.91")

    res = materialize_experiment(node)
    assert res["ok"], res
    conn = get_db()
    rows = conn.execute(
        "SELECT cell_hash, value FROM timeline WHERE exp_id=? AND event_type='cell_exec' "
        "ORDER BY seq", (res["id"],)).fetchall()
    assert len(rows) == 2, "own cell plus its one ancestor"
    anc, own = (json.loads(r["value"]) for r in rows)

    # The ancestor keeps a one-line label and its hash; the body is in
    # cell_lineage and the output belonged to the run that produced it.
    assert "ANCESTOR_OUTPUT" not in json.dumps(anc)
    assert anc["source_preview"] == "import numpy as np"
    assert rows[0]["cell_hash"], "ancestor identity is its cell hash"
    src = conn.execute("SELECT source FROM cell_lineage WHERE cell_hash=?",
                       (rows[0]["cell_hash"],)).fetchone()
    assert "ANCESTOR_LINE" in src["source"], "full ancestor source still recoverable"

    # The node's own cell is unchanged: full preview and its own result.
    assert "OWN_OUTPUT" in own["output_preview"]
    assert "OWN_LINE" in own["source_preview"]
