"""Tests for post-hoc metric logging (`log_last` / `%exp_log`).

The notebook loop routinely finishes the run before the numbers exist: you run
the notebook, close it out, then evaluate and only then have test accuracy.
`log_last` attaches those numbers to the run that just happened without making
the user hunt for its id.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_active_run():
    """Every test here starts with no live run (the post-hoc case)."""
    from exptrack import notebook
    notebook._active = None
    yield
    notebook._active = None


def _metrics_of(exp_id):
    from exptrack.core.db import get_db
    rows = get_db().execute(
        "SELECT key, value, source FROM metrics WHERE exp_id=? ORDER BY key",
        (exp_id,),
    ).fetchall()
    return {r["key"]: (r["value"], r["source"]) for r in rows}


def test_logs_onto_latest_finished_run(tmp_project):
    from exptrack import notebook
    from exptrack.core import Experiment

    exp = Experiment(script="analysis.ipynb")
    exp.finish()

    notebook.log_last(_nb_file="analysis.ipynb", test_acc=0.93, train_acc=0.98)

    m = _metrics_of(exp.id)
    assert m["test_acc"][0] == pytest.approx(0.93)
    assert m["train_acc"][0] == pytest.approx(0.98)


def test_picks_the_newest_run_of_that_notebook(tmp_project):
    from exptrack import notebook
    from exptrack.core import Experiment

    older = Experiment(script="analysis.ipynb")
    older.finish()
    newer = Experiment(script="analysis.ipynb")
    newer.finish()

    notebook.log_last(_nb_file="analysis.ipynb", test_acc=0.5)

    assert "test_acc" in _metrics_of(newer.id)
    assert "test_acc" not in _metrics_of(older.id)


def test_does_not_log_onto_a_trashed_run(tmp_project, capsys):
    """A trashed run is gone from every list — putting today's accuracy on it
    would file the number somewhere the user cannot see it."""
    from exptrack import notebook
    from exptrack.core import Experiment
    from exptrack.core.db import get_db, trash_experiment

    kept = Experiment(script="analysis.ipynb")
    kept.finish()
    dumped = Experiment(script="analysis.ipynb")
    dumped.finish()
    trash_experiment(get_db(), dumped.id)

    notebook.log_last(_nb_file="analysis.ipynb", test_acc=0.77)

    assert "test_acc" in _metrics_of(kept.id)
    assert "test_acc" not in _metrics_of(dumped.id)


def test_leaves_the_run_finished(tmp_project):
    """Resuming reopens the run; it must be handed back in the state we found
    it, not left 'running' forever."""
    from exptrack import notebook
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    exp = Experiment(script="analysis.ipynb")
    exp.finish()

    notebook.log_last(_nb_file="analysis.ipynb", test_acc=0.9)

    status = get_db().execute(
        "SELECT status FROM experiments WHERE id=?", (exp.id,)).fetchone()["status"]
    assert status == "done"


def test_logs_onto_the_active_run_when_one_is_live(tmp_project):
    from exptrack import notebook
    from exptrack.core import Experiment

    finished = Experiment(script="analysis.ipynb")
    finished.finish()
    live = Experiment(script="analysis.ipynb")
    notebook._active = live

    notebook.log_last(test_acc=0.42)

    assert "test_acc" in _metrics_of(live.id)
    assert "test_acc" not in _metrics_of(finished.id)


def test_no_matching_run_reports_instead_of_raising(tmp_project, capsys):
    from exptrack import notebook

    assert notebook.log_last(_nb_file="never_ran.ipynb", acc=1.0) is None
    assert "no previous run" in capsys.readouterr().err


def test_empty_call_is_refused(tmp_project, capsys):
    from exptrack import notebook

    assert notebook.log_last(_nb_file="analysis.ipynb") is None
    assert "at least one metric" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# %exp_log argument parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line,expected", [
    ("test_acc=0.93", {"test_acc": 0.93}),
    ("a=1 b=2", {"a": 1.0, "b": 2.0}),
    ("a=1, b=2", {"a": 1.0, "b": 2.0}),          # commas are tolerated
    ("val/loss=0.25", {"val/loss": 0.25}),        # slashes are normal in keys
    ("neg=-0.5", {"neg": -0.5}),
    ("sci=1e-4", {"sci": 0.0001}),
])
def test_parses_assignments(line, expected):
    from exptrack.notebook import _parse_metric_assignments

    vals, bad = _parse_metric_assignments(line)
    assert vals == pytest.approx(expected)
    assert bad == []


@pytest.mark.parametrize("line", ["justaword", "key=", "=0.5", "key=notanumber"])
def test_rejects_malformed_tokens(line):
    """A typo must be reported, never silently dropped — a metric that looks
    logged but isn't is worse than an error."""
    from exptrack.notebook import _parse_metric_assignments

    vals, bad = _parse_metric_assignments(line)
    assert vals == {}
    assert bad == [line]


@pytest.mark.parametrize("line", ["acc=inf", "acc=-inf", "acc=nan"])
def test_rejects_non_finite(line):
    """`json.dumps` renders these as bare Infinity/NaN, which no browser can
    parse back — they must never reach the metrics table."""
    from exptrack.notebook import _parse_metric_assignments

    vals, bad = _parse_metric_assignments(line)
    assert vals == {}
    assert bad == [line]
