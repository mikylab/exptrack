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
