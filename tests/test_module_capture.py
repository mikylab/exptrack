"""Tests for capturing the project-local modules a run imported.

The entry script was the only source a run ever snapshotted, so a project laid
out as ``main.py`` importing ``script.py`` recorded nothing about ``script.py``:

* editing ``script.py`` and rerunning ``main.py`` produced two runs whose
  ``_code_snapshot`` was byte-identical, so ``compare_run_code`` reported
  ``cells: []`` — "no code change" — for two runs that executed different code;
* the run detail's code panel filed the change under "Other files in the
  working tree", behind a headline stating the run's script matched the commit,
  because nothing told the client that ``script.py`` was code this run ran.

Both are the same missing fact: which files besides the entry script the run
actually executed.
"""
from __future__ import annotations

import json

import pytest


def _conn():
    """A live connection. Taken after the run rather than from the ``db_conn``
    fixture: finishing a run can recycle the thread-local connection."""
    from exptrack.core.db import get_db
    return get_db()


def _snapshot_entries(conn, exp_id):
    row = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key='_code_snapshot'",
        (exp_id,),
    ).fetchone()
    if not row:
        return []
    val = json.loads(row["value"])
    if isinstance(val, str):
        val = json.loads(val)
    return val


def _fake_module(path):
    """A stand-in for a sys.modules entry with a real ``__file__``."""
    from types import ModuleType
    m = ModuleType(path.stem)
    m.__file__ = str(path)
    return m


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def test_project_local_module_is_snapshotted(tmp_project):
    from exptrack.core.script_snapshot import capture_module_snapshots

    (tmp_project / "main.py").write_text("import script\n")
    helper = tmp_project / "script.py"
    helper.write_text("LR = 0.02\n")

    from exptrack.core.experiment import Experiment
    exp = Experiment(name="r1", script=str(tmp_project / "main.py"))
    capture_module_snapshots(exp, {"script": _fake_module(helper)})
    exp.finish()

    entries = _snapshot_entries(_conn(), exp.id)
    modules = [e for e in entries if e.get("kind") == "module"]
    assert len(modules) == 1, entries
    assert modules[0]["path"] == "script.py"
    from exptrack.core.db import get_code_snapshot
    assert get_code_snapshot(_conn(), modules[0]["hash"])["content"] == "LR = 0.02\n"


def test_modules_outside_the_project_are_not_snapshotted(tmp_project, tmp_path):
    """A run must not pull site-packages or the stdlib into the database."""
    from exptrack.core.script_snapshot import capture_module_snapshots

    outside = tmp_path.parent / "elsewhere_mod.py"
    outside.write_text("SECRET = 1\n")
    vendored = tmp_project / ".venv" / "lib" / "vendored.py"
    vendored.parent.mkdir(parents=True)
    vendored.write_text("VENDOR = 1\n")

    from exptrack.core.experiment import Experiment
    exp = Experiment(name="r1", script=str(tmp_project / "main.py"))
    capture_module_snapshots(exp, {
        "elsewhere_mod": _fake_module(outside),
        "vendored": _fake_module(vendored),
    })
    exp.finish()

    assert [e for e in _snapshot_entries(_conn(), exp.id)
            if e.get("kind") == "module"] == []


def test_the_entry_script_is_not_snapshotted_twice(tmp_project):
    from exptrack.core.script_snapshot import capture_module_snapshots

    main = tmp_project / "main.py"
    main.write_text("x = 1\n")

    from exptrack.core.experiment import Experiment
    exp = Experiment(name="r1", script=str(main))
    exp._maybe_snapshot_script(str(main))
    capture_module_snapshots(exp, {"__main__": _fake_module(main)})
    exp.finish()

    entries = _snapshot_entries(_conn(), exp.id)
    assert [e["kind"] for e in entries] == ["script"], entries


def test_module_capture_is_capped_and_says_so(tmp_project):
    """snapshot_max_files bounds the capture; truncation is recorded, not silent."""
    import json as _json

    from exptrack.core.script_snapshot import capture_module_snapshots

    conf_path = tmp_project / ".exptrack" / "config.json"
    conf = _json.loads(conf_path.read_text())
    conf["snapshot_max_files"] = 2
    conf_path.write_text(_json.dumps(conf))
    from exptrack import config as cfg
    cfg._cache = None

    mods = {}
    for i in range(5):
        p = tmp_project / f"m{i}.py"
        p.write_text(f"V = {i}\n")
        mods[f"m{i}"] = _fake_module(p)

    from exptrack.core.experiment import Experiment
    exp = Experiment(name="r1", script=str(tmp_project / "main.py"))
    capture_module_snapshots(exp, mods)
    exp.finish()

    entries = _snapshot_entries(_conn(), exp.id)
    assert len([e for e in entries if e.get("kind") == "module"]) == 2
    row = _conn().execute(
        "SELECT value FROM params WHERE exp_id=? AND key='_code_files_truncated'",
        (exp.id,)).fetchone()
    assert row is not None and _json.loads(row["value"]) == 5


def test_capture_is_idempotent(tmp_project):
    from exptrack.core.script_snapshot import capture_module_snapshots

    helper = tmp_project / "script.py"
    helper.write_text("LR = 0.02\n")
    from exptrack.core.experiment import Experiment
    exp = Experiment(name="r1", script=str(tmp_project / "main.py"))
    capture_module_snapshots(exp, {"script": _fake_module(helper)})
    capture_module_snapshots(exp, {"script": _fake_module(helper)})
    exp.finish()

    entries = _snapshot_entries(_conn(), exp.id)
    assert len([e for e in entries if e.get("kind") == "module"]) == 1


# ---------------------------------------------------------------------------
# Run-vs-run code diff
# ---------------------------------------------------------------------------

def _run_with_module(tmp_project, name, module_src, main_src="import script\n"):
    from exptrack.core.experiment import Experiment
    from exptrack.core.script_snapshot import capture_module_snapshots
    main = tmp_project / "main.py"
    main.write_text(main_src)
    helper = tmp_project / "script.py"
    helper.write_text(module_src)
    exp = Experiment(name=name, script=str(main))
    exp._maybe_snapshot_script(str(main))
    capture_module_snapshots(exp, {"script": _fake_module(helper)})
    exp.finish()
    return exp


def test_changed_module_shows_as_a_code_change_between_runs(tmp_project):
    """The reported bug: same main.py, edited script.py, 'no code change'."""
    from exptrack.core.queries import compare_run_code

    a = _run_with_module(tmp_project, "r1", "LR = 0.02\n")
    b = _run_with_module(tmp_project, "r2", "LR = 0.03\n")

    result = compare_run_code(_conn(), a.id, b.id)
    assert result["mode"] == "script"
    labels = [c["label"] for c in result["cells"]]
    assert "script.py" in labels, result
    cell = next(c for c in result["cells"] if c["label"] == "script.py")
    assert cell["a"] == "LR = 0.02\n"
    assert cell["b"] == "LR = 0.03\n"


def test_unchanged_module_is_not_reported(tmp_project):
    from exptrack.core.queries import compare_run_code

    a = _run_with_module(tmp_project, "r1", "LR = 0.02\n")
    b = _run_with_module(tmp_project, "r2", "LR = 0.02\n")

    assert compare_run_code(_conn(), a.id, b.id)["cells"] == []


def test_changed_script_and_module_are_both_reported(tmp_project):
    from exptrack.core.queries import compare_run_code

    a = _run_with_module(tmp_project, "r1", "LR = 0.02\n", "import script  # v1\n")
    b = _run_with_module(tmp_project, "r2", "LR = 0.03\n", "import script  # v2\n")

    result = compare_run_code(_conn(), a.id, b.id)
    labels = [c["label"] for c in result["cells"]]
    assert "main.py" in labels and "script.py" in labels, result
    # The entry script leads: it is the file the reader ran.
    assert labels[0] == "main.py"


def test_a_module_only_one_run_imported_is_reported(tmp_project):
    """An added import is a code change, not an absence."""
    from exptrack.core.experiment import Experiment
    from exptrack.core.queries import compare_run_code
    from exptrack.core.script_snapshot import capture_module_snapshots

    main = tmp_project / "main.py"
    main.write_text("x = 1\n")
    a = Experiment(name="r1", script=str(main))
    a._maybe_snapshot_script(str(main))
    a.finish()

    helper = tmp_project / "script.py"
    helper.write_text("LR = 0.03\n")
    b = Experiment(name="r2", script=str(main))
    b._maybe_snapshot_script(str(main))
    capture_module_snapshots(b, {"script": _fake_module(helper)})
    b.finish()

    result = compare_run_code(_conn(), a.id, b.id)
    cell = next(c for c in result["cells"] if c["label"] == "script.py")
    assert cell["a"] == "" and cell["b"] == "LR = 0.03\n"


# ---------------------------------------------------------------------------
# The detail payload needs to name these files
# ---------------------------------------------------------------------------

def test_experiment_detail_lists_the_files_the_run_executed(tmp_project):
    """So the code panel can group script.py with the run's own code rather
    than filing it under 'Other files in the working tree'."""
    from exptrack.core.queries import get_experiment_detail

    exp = _run_with_module(tmp_project, "r1", "LR = 0.02\n")
    detail = get_experiment_detail(_conn(), exp.id)
    assert sorted(detail["code_files"]) == ["main.py", "script.py"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
