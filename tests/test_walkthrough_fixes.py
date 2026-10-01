"""Fixes from a walk through a script run and a notebook run.

Each test names the thing that went wrong: a run name whose suffix was not the
run's id, one run's files in two output folders, a script's results.json never
read as metrics, `%exp_log final_loss` rejected, a notebook hyperparameter
change overwriting the run that had the result, an argparse failure used as
the next run's baseline, and no record of which library versions a run used.
"""
from __future__ import annotations

import json
import os
import sys
import time
import types

import pytest


def _metric_keys(exp_id):
    from exptrack.core.db import get_db
    return {r[0] for r in get_db().execute(
        "SELECT DISTINCT key FROM metrics WHERE exp_id=?", (exp_id,))}


# ── The name's suffix is the run's id ────────────────────────────────────────

def test_the_generated_name_ends_with_the_run_id(tmp_project):
    from exptrack.core import Experiment
    exp = Experiment(script="train.py", params={"lr": 0.1})
    assert exp.name.endswith("__" + exp.id[:8])
    exp.finish()


def test_a_rename_keeps_the_suffix(tmp_project, capsys):
    from exptrack.core import Experiment
    exp = Experiment(script="train.py", params={"lr": 0.1})
    before = exp.name
    exp.log_params({"epochs": 3})
    exp.refresh_auto_name()
    assert exp.name != before and exp.name.endswith("__" + exp.id[:8])
    exp.refresh_auto_name()          # nothing new: no second rename printed
    assert capsys.readouterr().err.count("-> ") == 1
    exp.finish()


# ── One run, one output folder ───────────────────────────────────────────────

def test_a_folder_not_yet_created_follows_the_rename(tmp_project):
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    exp = Experiment(script="train.py", params={"lr": 0.1})
    exp.log_params({"epochs": 3})
    exp.refresh_auto_name()
    stored = get_db().execute("SELECT output_dir FROM experiments WHERE id=?",
                              (exp.id,)).fetchone()[0]
    assert stored.endswith(exp.name) and exp._output_dir == stored
    assert exp.output_path("x.png").parent.name == exp.name
    exp.finish()


def test_writers_follow_the_recorded_folder_when_a_rename_could_not_move_it(tmp_project):
    from exptrack.core import Experiment
    exp = Experiment(script="train.py", params={"lr": 0.1})
    first = exp._output_dir
    os.makedirs(first)
    import exptrack.core.db as db
    real = db.Path.rename
    try:
        db.Path.rename = lambda self, target: (_ for _ in ()).throw(PermissionError("in use"))
        exp.log_params({"epochs": 3})
        exp.refresh_auto_name()
    finally:
        db.Path.rename = real
    assert exp._output_dir == first
    assert str(exp.output_path("curve.png").parent) == first
    exp.finish()


# ── A results file the script wrote becomes the run's metrics ────────────────

def _run_results(tmp_project, payload, logged=None, name="results.json"):
    from exptrack import __main__ as m
    from exptrack.core import Experiment
    exp = Experiment(script=str(tmp_project / "train.py"))
    if logged:
        exp.log_metrics(logged)
    start = time.time() - 1
    (tmp_project / name).write_text(json.dumps(payload))
    m._capture_results_metrics(exp, start, {"auto_capture": {}},
                               tmp_project / "train.py")
    exp.finish()
    return exp


def test_results_json_numbers_become_metrics(tmp_project, monkeypatch, capsys):
    monkeypatch.chdir(tmp_project)
    exp = _run_results(tmp_project, {"loss": 0.1, "val": {"acc": 0.9},
                                     "note": "text", "ok": True})
    assert _metric_keys(exp.id) == {"loss", "val/acc"}
    assert "metrics from results.json: loss, val/acc" in capsys.readouterr().err


def test_a_key_the_script_logged_is_not_overwritten(tmp_project, monkeypatch):
    from exptrack.core.db import get_db
    monkeypatch.chdir(tmp_project)
    exp = _run_results(tmp_project, {"loss": 99.0, "acc": 0.5}, logged={"loss": 0.2})
    vals = [r[0] for r in get_db().execute(
        "SELECT value FROM metrics WHERE exp_id=? AND key='loss'", (exp.id,))]
    assert vals == [0.2] and "acc" in _metric_keys(exp.id)


def test_a_results_file_from_before_the_run_is_ignored(tmp_project, monkeypatch):
    from exptrack import __main__ as m
    from exptrack.core import Experiment
    monkeypatch.chdir(tmp_project)
    (tmp_project / "results.json").write_text('{"loss": 1}')
    old = time.time() - 3600
    os.utime(tmp_project / "results.json", (old, old))
    exp = Experiment(script=str(tmp_project / "train.py"))
    m._capture_results_metrics(exp, time.time() - 1, {"auto_capture": {}},
                               tmp_project / "train.py")
    exp.finish()
    assert _metric_keys(exp.id) == set()


@pytest.mark.parametrize("value, expected", [
    ([], ()), ("results.json", None), ([1, 2], None), (None, None),
])
def test_results_files_setting_degrades_to_the_default(value, expected):
    from exptrack import __main__ as m
    got = m._results_file_patterns({"auto_capture": {"results_files": value}})
    assert got == (m._DEFAULT_RESULTS_FILES if expected is None else expected)


# ── %exp_log takes a variable name ───────────────────────────────────────────

def test_exp_log_reads_a_bare_variable_name():
    from exptrack.notebook import _parse_metric_assignments
    ns = {"final_loss": 0.25, "acc": 0.9, "flag": True, "label": "x"}
    vals, bad = _parse_metric_assignments("final_loss test_acc=acc flag label nope", ns)
    assert vals == {"final_loss": 0.25, "test_acc": 0.9}
    assert bad == ["flag", "label", "nope"]


def test_exp_log_without_a_namespace_still_wants_numbers():
    from exptrack.notebook import _parse_metric_assignments
    assert _parse_metric_assignments("final_loss acc=0.5") == ({"acc": 0.5}, ["final_loss"])


# ── A notebook run ends where its result does ────────────────────────────────

def _split_env(tmp_project, monkeypatch, *, metrics=True, session=False, enabled=True):
    from exptrack import config as cfg
    from exptrack import notebook
    from exptrack.core import Experiment
    exp = Experiment(script="nb.ipynb", params={"lr": 0.05, "epochs": 8})
    if metrics:
        exp.log_metrics({"loss": 0.3})
    conf = cfg.load()
    monkeypatch.setattr(cfg, "load", lambda: {**conf, "auto_capture": {
        **conf.get("auto_capture", {}), "notebook_new_run_on_hp_change": enabled}})
    calls = []
    monkeypatch.setattr(notebook, "split_for_hp_change",
                        lambda changed: calls.append(changed) or "NEW")
    if session:
        import exptrack.sessions as sessions
        monkeypatch.setattr(sessions, "get_current_session",
                            lambda: types.SimpleNamespace(session_id="s1"))
    return exp, calls


def test_a_hyperparameter_changed_after_a_result_starts_a_new_run(tmp_project, monkeypatch):
    from exptrack.capture.notebook_hooks import _maybe_split_on_hp_change
    exp, calls = _split_env(tmp_project, monkeypatch)
    got = _maybe_split_on_hp_change(exp, {"lr": 0.1, "epochs": 8}, {"lr": {}})
    assert got == "NEW" and calls == [{"lr": 0.1}]
    exp.finish()


@pytest.mark.parametrize("kw", [{"metrics": False}, {"session": True}, {"enabled": False}])
def test_no_split_before_a_result_under_a_session_or_when_off(tmp_project, monkeypatch, kw):
    from exptrack.capture.notebook_hooks import _maybe_split_on_hp_change
    exp, calls = _split_env(tmp_project, monkeypatch, **kw)
    assert _maybe_split_on_hp_change(exp, {"lr": 0.1}, {"lr": {}}) is exp and not calls
    exp.finish()


def test_a_non_hyperparameter_change_never_splits(tmp_project, monkeypatch):
    from exptrack.capture.notebook_hooks import _maybe_split_on_hp_change
    exp, calls = _split_env(tmp_project, monkeypatch)
    assert _maybe_split_on_hp_change(exp, {"losses": [1]}, {"losses": {}}) is exp
    assert not calls
    exp.finish()


# ── An argparse failure is not a baseline ────────────────────────────────────

def test_argparse_exit_is_recognised():
    import argparse

    from exptrack.__main__ import _raised_by_argparse
    p = argparse.ArgumentParser()
    p.add_argument("--lr", type=float)
    with pytest.raises(SystemExit) as info:
        _stderr, sys.stderr = sys.stderr, open(os.devnull, "w")
        try:
            p.parse_args(["--lr", "nope"])
        finally:
            sys.stderr.close()
            sys.stderr = _stderr
    assert _raised_by_argparse(info.value)
    try:
        sys.exit(1)
    except SystemExit as e:
        assert not _raised_by_argparse(e)


def test_a_run_that_died_in_argparse_is_skipped_as_baseline(tmp_project):
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import ARG_ERROR_KEY, get_previous_run
    good = Experiment(script="train.py", params={"lr": 0.1})
    good.finish()
    bad = Experiment(script="train.py", params={"lr": "nope"})
    bad.log_param(ARG_ERROR_KEY, True)
    bad.fail("SystemExit(2)")
    crash = Experiment(script="train.py", params={"lr": 0.2})
    crash.fail("ZeroDivisionError")
    nxt = Experiment(script="train.py", params={"lr": 0.3})
    nxt.finish()
    conn = get_db()
    assert get_previous_run(conn, nxt.id)["id"] == crash.id   # a crash still counts
    assert get_previous_run(conn, crash.id)["id"] == good.id  # the arg error does not


# ── Which library versions a run used ────────────────────────────────────────

def _fake_module(name, version, where="site-packages"):
    m = types.ModuleType(name)
    m.__file__ = f"/env/lib/{where}/{name}/__init__.py"
    if version is not None:
        m.__version__ = version
    return m


def test_imported_packages_lists_non_stdlib_versions_only(tmp_path):
    import json as real_json

    from exptrack.core.environment import imported_packages
    editable = types.ModuleType("mylib")          # `pip install -e`: a source checkout
    editable.__file__ = str(tmp_path / "src" / "mylib" / "__init__.py")
    editable.__version__ = "0.3.1"
    mods = {"numpy": _fake_module("numpy", "2.1.0"),
            "numpy.linalg": _fake_module("numpy.linalg", "2.1.0"),
            "json": real_json,                    # stdlib, though it has __version__
            "mylib": editable,
            "novers": _fake_module("novers", None),
            "exptrack": _fake_module("exptrack", "2.0.0")}
    assert imported_packages(mods) == {"mylib": "0.3.1", "numpy": "2.1.0"}


@pytest.fixture
def fake_env(monkeypatch):
    """finish() records from `sys.modules`; pin what it sees."""
    from exptrack.core import environment
    mods = {"torch": _fake_module("torch", "2.4.0")}
    real = environment.imported_packages
    monkeypatch.setattr(environment, "imported_packages",
                        lambda modules=None: real(mods if modules is None else modules))


def test_the_environment_is_stored_once_and_survives_the_blob_sweep(tmp_project, fake_env):
    from exptrack.core import Experiment
    from exptrack.core.db import _sweep_blobs, get_db
    from exptrack.core.environment import ENV_PARAM, load_environment
    a = Experiment(script="train.py")
    b = Experiment(script="train.py")
    a.finish()
    b.finish()
    conn = get_db()
    assert a._params[ENV_PARAM] == b._params[ENV_PARAM]
    assert conn.execute("SELECT COUNT(*) FROM code_snapshots WHERE kind='environment'"
                        ).fetchone()[0] == 1
    _sweep_blobs(conn)
    assert load_environment(conn, a._params[ENV_PARAM])["packages"] == {"torch": "2.4.0"}


def test_the_detail_and_export_carry_the_environment(tmp_project, fake_env):
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import (
        format_export_markdown,
        get_experiment_detail,
        get_export_data,
    )
    exp = Experiment(script="train.py")
    exp.finish()
    conn = get_db()
    detail = get_experiment_detail(conn, exp.id)
    assert "_environment" not in detail["params"]
    assert detail["environment"]["packages"]["torch"] == "2.4.0"
    md = format_export_markdown(get_export_data(conn, exp.id))
    assert "## Environment" in md and "| `torch` | `2.4.0` |" in md


# ── The dashboard URL names the project it was started in ────────────────────

def test_browser_url_carries_the_project():
    from exptrack.dashboard.app import browser_url
    assert browser_url("0.0.0.0", 7331, "tok", "abc") == \
        "http://127.0.0.1:7331/?token=tok&project=abc"
    assert browser_url("127.0.0.1", 7331, "", "") == "http://127.0.0.1:7331/"


def test_a_project_can_be_forgotten_by_its_id(tmp_path, monkeypatch):
    from exptrack import projects
    monkeypatch.setattr(projects, "registry_path", lambda: tmp_path / "projects.json")
    root = tmp_path / "proj"
    (root / ".exptrack").mkdir(parents=True)
    projects.register(root)
    assert projects.forget(projects.project_id(root))


# ── A delete never touches a Python environment ─────────────────────────────

def _make_env(path, conda=False):
    path.mkdir(parents=True)
    if conda:
        (path / "conda-meta").mkdir()
    else:
        (path / "pyvenv.cfg").write_text("home = x\n")
    (path / "Lib").mkdir()
    (path / "Lib" / "mod.py").write_text("x = 1\n")
    return path


@pytest.mark.parametrize("conda", [False, True])
def test_a_file_inside_an_env_is_never_trashed(tmp_path, conda):
    from exptrack.core.db import _trash_or_local
    env = _make_env(tmp_path / "myenv", conda=conda)
    assert _trash_or_local(env / "Lib" / "mod.py") == "protected"
    assert _trash_or_local(env) == "protected"
    assert (env / "Lib" / "mod.py").is_file()


def test_a_folder_holding_an_env_is_never_trashed(tmp_path):
    from exptrack.core.db import _trash_or_local
    outer = tmp_path / "runs"
    _make_env(outer / "tbenv")
    assert _trash_or_local(outer) == "protected" and (outer / "tbenv").is_dir()


def test_deleting_a_run_keeps_an_env_file_it_claimed(tmp_project):
    from exptrack.core import Experiment
    from exptrack.core.db import delete_experiment, get_db
    env = _make_env(tmp_project / "env")
    exp = Experiment(script="train.py")
    exp.log_artifact(str(env / "Lib" / "mod.py"))
    exp.finish()
    delete_experiment(get_db(), exp.id, delete_files=True, delete_shared_files=True)
    assert (env / "Lib" / "mod.py").is_file()


def test_the_output_scan_does_not_walk_into_an_env(tmp_project, monkeypatch):
    from exptrack import __main__ as m
    from exptrack.core import Experiment
    monkeypatch.chdir(tmp_project)
    env = _make_env(tmp_project / "env")
    exp = Experiment(script=str(tmp_project / "train.py"))
    start = time.time() - 1
    (env / "Lib" / "new.py").write_text("y = 2\n")
    (tmp_project / "out.csv").write_text("a\n1\n")
    m._auto_detect_outputs(exp, start)
    exp.finish()
    from exptrack.core.db import get_db
    paths = [r[0] for r in get_db().execute(
        "SELECT path FROM artifacts WHERE exp_id=?", (exp.id,))]
    assert any(p.endswith("out.csv") for p in paths)
    assert not any("new.py" in p for p in paths)
