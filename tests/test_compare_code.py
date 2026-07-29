"""L6: run-vs-run code diff in the Compare view (compare_run_code) + the
git-failure-vs-clean-tree sentinel."""
from __future__ import annotations

from exptrack.core import Experiment
from exptrack.core.db import get_db
from exptrack.core.queries import compare_run_code


def _nb_run(script, cells):
    """A run whose executed cells are (cell_pos, source) pairs, wired into the
    timeline + content-addressed cell_lineage the way the notebook hooks do."""
    from exptrack.capture.cell_lineage import cell_hash, store_cell_lineage
    exp = Experiment(script=script)
    conn = get_db()
    for seq, (pos, src) in enumerate(cells, start=1):
        ch = cell_hash(src)
        store_cell_lineage(script, src)
        conn.execute(
            "INSERT INTO timeline (exp_id, seq, event_type, cell_hash, cell_pos, key, ts) "
            "VALUES (?,?,?,?,?,?,datetime('now'))",
            (exp.id, seq, "cell_exec", ch, pos, f"cell_{pos}"),
        )
    conn.commit()
    exp.finish()
    return exp.id


def test_compare_notebook_cells_shows_edit(tmp_project):
    """Two notebook runs where one cell changed → that cell is returned as an
    (a, b) pair; unchanged cells are omitted."""
    a = _nb_run("explore.ipynb", [(1, "x = 1\n"), (2, "y = 2\n")])
    b = _nb_run("explore.ipynb", [(1, "x = 1\n"), (2, "y = 99\n")])
    conn = get_db()
    cd = compare_run_code(conn, a, b)
    assert cd["mode"] == "cells"
    assert len(cd["cells"]) == 1
    c = cd["cells"][0]
    assert c["pos"] == 2
    assert c["a"] == "y = 2\n"
    assert c["b"] == "y = 99\n"


def test_compare_notebook_identical_cells_empty(tmp_project):
    a = _nb_run("explore.ipynb", [(1, "x = 1\n")])
    b = _nb_run("explore.ipynb", [(1, "x = 1\n")])
    conn = get_db()
    cd = compare_run_code(conn, a, b)
    assert cd["mode"] == "cells"
    assert cd["cells"] == []


def test_compare_script_snapshot_diff(tmp_project):
    """Two script runs with different source → a single script-source pair."""
    from exptrack.capture.script_tracking import capture_script_snapshot
    script = tmp_project / "train.py"

    script.write_text("lr = 0.01\n")
    ea = Experiment(script=str(script))
    capture_script_snapshot(ea, str(script))
    ea.finish()

    script.write_text("lr = 0.05\n")
    eb = Experiment(script=str(script))
    capture_script_snapshot(eb, str(script))
    eb.finish()

    conn = get_db()
    cd = compare_run_code(conn, ea.id, eb.id)
    assert cd["mode"] == "script"
    assert len(cd["cells"]) == 1
    assert "0.01" in cd["cells"][0]["a"]
    assert "0.05" in cd["cells"][0]["b"]


def test_compare_no_code_returns_none(tmp_project):
    a = Experiment(script="s.py"); a.finish()
    b = Experiment(script="s.py"); b.finish()
    conn = get_db()
    cd = compare_run_code(conn, a.id, b.id)
    assert cd["mode"] == "none"
    assert cd["cells"] == []


def test_git_diff_sentinel_distinguishes_failure(monkeypatch):
    """git_diff returns the CAPTURE_FAILED sentinel when inside a repo but the
    diff command errors — never a bare '' that looks like a clean tree."""
    from exptrack.core import git

    monkeypatch.setattr(git, "_git_status", lambda *cmd: (False, ""))
    monkeypatch.setattr(git, "_is_git_repo", lambda: True)
    assert git.git_diff("HEAD") == git.CAPTURE_FAILED

    # Not a repo → an empty diff is honest, not a capture failure.
    monkeypatch.setattr(git, "_is_git_repo", lambda: False)
    assert git.git_diff("HEAD") == ""


# ── Snapshot capture is not exclusive to `exptrack run` ──────────────────────
#
# capture_script_snapshot used to be called only from __main__, so a script run
# as plain `python train.py` (building its own Experiment, a fully supported
# pattern) recorded no source at all. The visible symptom was a contradiction:
# the "vs previous run" strip said `code changed` — that signal is computed from
# the repository-wide signature and needs no snapshot — while the Code-changes
# panel directly below it had nothing to diff.

def _script_run(tmp_project, source: str):
    """A run started the way a plain `python script.py` does: the script exists
    on disk and the Experiment is constructed by the script itself."""
    path = tmp_project / "train.py"
    path.write_text(source)
    exp = Experiment(script=str(path))
    exp.finish()
    return exp.id


def test_plain_python_run_captures_its_script(tmp_project):
    """A run that was not launched by `exptrack run` still snapshots its code."""
    exp_id = _script_run(tmp_project, "THRESHOLD = 0.5\n")
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM params WHERE exp_id=? AND key='_code_snapshot'", (exp_id,)
    ).fetchone()
    assert row is not None, "plain `python script.py` run captured no code snapshot"


def test_compare_two_plain_python_runs_shows_the_edit(tmp_project):
    """Two runs that both differ from HEAD *and* from each other diff against
    each other — not against the committed file."""
    a = _script_run(tmp_project, "THRESHOLD = 0.7\n")
    b = _script_run(tmp_project, "THRESHOLD = 0.9\n")
    cd = compare_run_code(get_db(), a, b)
    assert cd["mode"] == "script"
    assert len(cd["cells"]) == 1
    assert cd["cells"][0]["a"] == "THRESHOLD = 0.7\n"
    assert cd["cells"][0]["b"] == "THRESHOLD = 0.9\n"


def test_script_snapshot_is_idempotent(tmp_project):
    """__main__ still calls capture_script_snapshot explicitly after
    Experiment.__init__ already did; the second call must be a no-op rather
    than a duplicate timeline event and a second set of params."""
    from exptrack.capture.script_tracking import capture_script_snapshot
    path = tmp_project / "train.py"
    path.write_text("x = 1\n")
    exp = Experiment(script=str(path))
    capture_script_snapshot(exp, str(path))   # what __main__ does
    exp.finish()
    conn = get_db()
    n_events = conn.execute(
        "SELECT COUNT(*) FROM timeline WHERE exp_id=? AND event_type='cell_exec'",
        (exp.id,)).fetchone()[0]
    n_params = conn.execute(
        "SELECT COUNT(*) FROM params WHERE exp_id=? AND key='_code_snapshot'",
        (exp.id,)).fetchone()[0]
    assert n_events == 1
    assert n_params == 1


def test_label_script_is_not_snapshotted(tmp_project):
    """`run-start --script pipeline` passes a label, not a file — nothing to
    snapshot, and no crash trying."""
    exp = Experiment(script="pipeline")
    exp.finish()
    row = get_db().execute(
        "SELECT 1 FROM params WHERE exp_id=? AND key='_code_snapshot'", (exp.id,)
    ).fetchone()
    assert row is None
