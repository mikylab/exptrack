"""
Scope and empty states of the script code panel.

Two rules under test:

1. The panel is about *one script vs. its commit*. A notebook's per-cell edit is
   the Timeline's job and is no longer copied into a `_code_change/cell_N` param.
2. An empty diff has three unrelated causes and only one of them means "this
   script matched the commit", so `_code_status` records the other two.
"""
import json
import subprocess

import pytest

from exptrack.core import Experiment
from exptrack.core.db import get_db
from exptrack.core.script_snapshot import _facts_cache, _script_facts


def _params(exp_id):
    conn = get_db()
    return {r["key"]: json.loads(r["value"]) for r in conn.execute(
        "SELECT key, value FROM params WHERE exp_id=?", (exp_id,))}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, check=True)


def _commit(cwd, *paths):
    """`tmp_project` is not a repo — these tests are about git's answers."""
    if not (cwd / ".git").exists():
        _git(cwd, "init", "-q")
    _git(cwd, "add", *paths)
    _git(cwd, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "add", "--no-gpg-sign")


@pytest.fixture(autouse=True)
def _clear_facts_cache():
    # `_script_facts` memoizes on (path, mtime, size); tmp_path reuse across
    # tests can collide, and every test here changes git state under a file.
    _facts_cache.clear()
    yield
    _facts_cache.clear()


# ── The notebook duplicate is gone ───────────────────────────────────────────

def test_notebook_cell_edit_is_not_copied_into_a_param(tmp_project, monkeypatch):
    """The cell_exec event's source_diff is the record; a param was a second copy.

    Storing both meant one edit rendered on the Timeline *and* in the run's code
    panel, and cost a row per edited cell per run that `compact --code-changes`
    could never reclaim (it is snapshot-gated, and a notebook has no snapshot).
    """
    from exptrack.capture import notebook_hooks

    exp = Experiment(name="nb")
    diff = [{"op": "-", "line": "lr = 0.1"}, {"op": "+", "line": "lr = 0.2"}]
    notebook_hooks._log_hp_params(
        exp, {}, {}, {}, diff,
        code_is_new=False, code_changed=True, already_seen=False, exec_num=3,
    )
    exp.finish()

    assert not [k for k in _params(exp.id) if k.startswith("_code_change/")]


def test_the_edit_still_reaches_the_timeline(tmp_project):
    """Removing the param must not remove the record — only the duplicate."""
    exp = Experiment(name="nb2")
    diff = [{"op": "-", "line": "lr = 0.1"}, {"op": "+", "line": "lr = 0.2"}]
    exp.log_event(event_type="cell_exec", cell_hash="h", key="cell_1",
                  value={}, source_diff=json.dumps(diff))
    exp.finish()

    row = get_db().execute(
        "SELECT source_diff FROM timeline WHERE exp_id=? AND key='cell_1'",
        (exp.id,)).fetchone()
    assert json.loads(row["source_diff"]) == diff


# ── An empty diff says which kind of empty it is ─────────────────────────────

def test_a_modified_tracked_script_reports_changed(tmp_project):
    script = tmp_project / "train.py"
    script.write_text("lr = 0.1\n")
    _commit(tmp_project, "train.py")
    script.write_text("lr = 0.2\n")

    facts = _script_facts(str(script))
    assert facts["code_status"] == "changed"
    assert "lr = 0.2" in facts["code_changes"]


def test_a_clean_tracked_script_reports_clean_and_writes_no_param(tmp_project):
    """The common path costs nothing: no diff and no commit means "matched"."""
    script = tmp_project / "clean.py"
    script.write_text("lr = 0.1\n")
    _commit(tmp_project, "clean.py")

    assert _script_facts(str(script))["code_status"] == "clean"

    exp = Experiment(name="c", script=str(script))
    exp.finish()
    p = _params(exp.id)
    assert "_code_status" not in p and "_code_changes" not in p


def test_an_untracked_script_is_distinguished_from_a_clean_one(tmp_project):
    """`git diff HEAD -- untracked.py` exits 0 with no output, exactly like a
    clean tree — so the empty diff alone cannot tell the two apart, and the
    panel would render "no changes" for a file git has never seen."""
    other = tmp_project / "other.py"
    other.write_text("x = 1\n")
    _commit(tmp_project, "other.py")     # a repo with a commit, but not this file
    script = tmp_project / "untracked.py"
    script.write_text("lr = 0.1\n")

    assert _script_facts(str(script))["code_status"] == "untracked"

    exp = Experiment(name="u", script=str(script))
    exp.finish()
    assert _params(exp.id)["_code_status"] == "untracked"


def test_outside_a_repo_reports_no_git(tmp_path, monkeypatch):
    from exptrack import config

    proj = tmp_path / "plain"
    (proj / ".exptrack").mkdir(parents=True)
    script = proj / "s.py"
    script.write_text("lr = 0.1\n")
    monkeypatch.chdir(proj)
    monkeypatch.setattr(config, "project_root", lambda: proj)

    assert _script_facts(str(script))["code_status"] == "no_git"


# ── A notebook captures no script facts, tracked or not ──────────────────────
#
# The panel is script-scoped, and the dashboard decides whether to draw it from
# the params below: `_script_hash` is written by `capture_script_snapshot` and
# nothing else, so its absence is what tells the client "this run never had a
# script". If a notebook run ever started writing it, the panel would come back
# — and inside a repo it would render the clean-tree note, which is a claim
# about a file that does not exist.

@pytest.mark.parametrize("tracked", [True, False], ids=["tracked", "untracked"])
def test_a_notebook_run_captures_no_script_facts(tmp_project, tracked):
    nb = tmp_project / "explore.ipynb"
    nb.write_text('{"cells": [], "nbformat": 4, "nbformat_minor": 5}')
    other = tmp_project / "other.py"
    other.write_text("x = 1\n")
    _commit(tmp_project, *(["other.py", "explore.ipynb"] if tracked else ["other.py"]))

    exp = Experiment(name="nb", script=str(nb))
    exp.finish()

    p = _params(exp.id)
    for key in ("_script_hash", "_code_changes", "_code_status", "_code_snapshot"):
        assert key not in p, f"notebook run wrote {key}"


def test_a_script_run_does_capture_the_marker_the_panel_gates_on(tmp_project):
    """The other half: absence must mean "notebook", not "we forgot"."""
    script = tmp_project / "train.py"
    script.write_text("lr = 0.1\n")
    _commit(tmp_project, "train.py")

    exp = Experiment(name="s", script=str(script))
    exp.finish()

    assert "_script_hash" in _params(exp.id)


# ── The script diff reaches the export ───────────────────────────────────────

def test_export_carries_the_script_diff(tmp_project):
    """It was filtered out of user_params by the `_` prefix and matched none of
    the `_code_change/` keys, so no export had ever included it."""
    from exptrack.core.queries import get_export_data

    exp = Experiment(name="e")
    exp.log_param("_code_changes", "+ lr = 0.2; - lr = 0.1")
    exp.finish()

    assert get_export_data(get_db(), exp.id)["code_changes"]["script"] \
        == "+ lr = 0.2; - lr = 0.1"


# ── The Reproduce box never shows a command that cannot be run ───────────────

class _FakeIPython:
    """Stand-in for a live IPython front end.

    `_in_ipython` asks `sys.modules` rather than importing IPython (an optional
    dep, and exptrack is stdlib-only), so a live shell is simulated by putting a
    module-like object there — which is also what makes the check work for
    Jupyter, Colab, VS Code, papermill and qtconsole alike without naming any
    of them.
    """

    def __init__(self, live=True):
        self._live = live

    def get_ipython(self):
        return object() if self._live else None


def test_a_kernel_launch_line_is_not_a_reproduce_command(monkeypatch):
    """Under IPython, `sys.argv` is the *kernel's* launch line.

    Every notebook run therefore recorded a Reproduce command naming a /tmp
    connection file that was deleted when the kernel stopped — unrunnable, and
    with no `python`/`exptrack` prefix the box couldn't even offer its
    plain/tracked toggle. A blank command is better than a false one.
    """
    import sys as _sys

    from exptrack.core.experiment import Experiment as E

    monkeypatch.setitem(_sys.modules, "IPython", _FakeIPython())
    monkeypatch.setattr(_sys, "argv", [
        "/usr/lib/python3/site-packages/ipykernel_launcher.py", "-f",
        "/tmp/tmpabc.json", "--HistoryManager.hist_file=:memory:"])
    assert E._build_command() == ""


def test_the_front_end_is_detected_structurally_not_by_name(monkeypatch):
    """A denylist of launcher names is a list of the front ends we happened to
    know about — Colab, VS Code and papermill all launch differently, and any
    one missing silently reinstates the dead-/tmp-path command. Whatever argv
    says, a live shell means argv is not a runnable command."""
    import sys as _sys

    from exptrack.core.experiment import Experiment as E

    monkeypatch.setitem(_sys.modules, "IPython", _FakeIPython())
    for argv in (["/opt/colab/kernel_launcher.py", "-f", "/tmp/x.json"],
                 ["/some/vscode/ms-toolsai/kernel.py"],
                 ["papermill", "in.ipynb", "out.ipynb"]):
        monkeypatch.setattr(_sys, "argv", argv)
        assert E._build_command() == "", argv


def test_argv_shapes_that_are_never_a_command(monkeypatch):
    """`python -c \"…\"` and the bare REPL are argv *forms*, not front ends, so
    they stay listed — and they hold with no IPython in sight."""
    import sys as _sys

    from exptrack.core.experiment import Experiment as E

    monkeypatch.delitem(_sys.modules, "IPython", raising=False)
    for argv in (["-c"], [""]):
        monkeypatch.setattr(_sys, "argv", argv)
        assert E._build_command() == "", argv


def test_a_real_script_launch_still_builds_its_command(monkeypatch):
    """The guard must not swallow the commands the box exists to show."""
    import sys as _sys

    from exptrack.core.experiment import Experiment as E

    monkeypatch.delitem(_sys.modules, "IPython", raising=False)
    monkeypatch.setattr(_sys, "argv", ["/venv/bin/exptrack", "run", "train.py",
                                       "--lr", "0.1"])
    assert E._build_command() == "exptrack run train.py --lr 0.1"


def test_importing_ipython_without_a_shell_is_still_a_script(monkeypatch):
    """A script that merely imports IPython has `get_ipython() is None`, and its
    argv really is the command that ran it."""
    import sys as _sys

    from exptrack.core.experiment import Experiment as E

    monkeypatch.setitem(_sys.modules, "IPython", _FakeIPython(live=False))
    monkeypatch.setattr(_sys, "argv", ["train.py", "--lr", "0.1"])
    assert E._build_command() == "train.py --lr 0.1"


def test_a_notebook_run_records_its_path_not_a_launcher(tmp_project, monkeypatch):
    """Reproducing a notebook means opening it — but with what?

    exptrack cannot know whether that is Jupyter Lab, notebook, nbclassic or an
    editor, so naming one would be a guess printed as an instruction. Record the
    path and let the reader open it however they open notebooks. The fallback
    lives in `Experiment._resolved_command`, not at each notebook entry point,
    which had to repeat it verbatim.
    """
    import sys as _sys

    from exptrack import notebook as nb_mod

    monkeypatch.setitem(_sys.modules, "IPython", _FakeIPython())
    monkeypatch.setattr(_sys, "argv", ["ipykernel_launcher.py", "-f", "/tmp/k.json"])
    nb = tmp_project / "explore.ipynb"
    nb.write_text('{"cells": [], "nbformat": 4, "nbformat_minor": 5}')

    exp = nb_mod.start(nb_file=str(nb))
    try:
        row = get_db().execute("SELECT command FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        assert row["command"] == str(nb)
    finally:
        nb_mod._active = None


def test_an_unidentified_notebook_records_no_command(tmp_project, monkeypatch):
    """With no notebook file there is nothing honest to record, so the box keeps
    its "double-click to add command" prompt rather than showing a launcher."""
    import sys as _sys

    from exptrack import notebook as nb_mod

    monkeypatch.setitem(_sys.modules, "IPython", _FakeIPython())
    monkeypatch.setattr(_sys, "argv", ["ipykernel_launcher.py", "-f", "/tmp/k.json"])
    monkeypatch.setattr(nb_mod, "_detect_nb_name", lambda: "")

    exp = nb_mod.start()
    try:
        row = get_db().execute("SELECT command FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        assert row["command"] == ""
    finally:
        nb_mod._active = None


def test_the_payload_states_whether_a_script_was_captured(tmp_project):
    """The client should read a stated fact, not reverse-engineer one from which
    internal param keys happen to be present."""
    from exptrack.core.queries import get_experiment_detail

    script = tmp_project / "train.py"
    script.write_text("lr = 0.1\n")
    _commit(tmp_project, "train.py")
    s_run = Experiment(name="s", script=str(script))
    s_run.finish()

    nb = tmp_project / "explore.ipynb"
    nb.write_text('{"cells": [], "nbformat": 4, "nbformat_minor": 5}')
    nb_run = Experiment(name="nb", script=str(nb))
    nb_run.finish()

    conn = get_db()
    assert get_experiment_detail(conn, s_run.id)["has_script_capture"] is True
    assert get_experiment_detail(conn, nb_run.id)["has_script_capture"] is False
