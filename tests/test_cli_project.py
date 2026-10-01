"""`exptrack project` — inspecting and pruning the registry."""
from __future__ import annotations

import sqlite3

from conftest import capture as _capture

from exptrack import projects
from exptrack.cli import project_cmds
from exptrack.cli.main import _build_parser
from exptrack.core.db import _SCHEMA_VERSION


def _make_project(root, stamp=_SCHEMA_VERSION):
    (root / ".exptrack").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(root / ".exptrack" / "experiments.db"))
    conn.execute(f"PRAGMA user_version = {stamp}")
    conn.commit()
    conn.close()


def test_project_list_parses():
    args = _build_parser().parse_args(["project", "list"])
    assert args.project_sub == "list"


def test_project_forget_parses():
    args = _build_parser().parse_args(["project", "forget", "gpu01"])
    assert args.project_sub == "forget"
    assert args.name == "gpu01"


def test_list_with_no_projects_says_so(tmp_home, tmp_path, monkeypatch):
    # Isolate BOTH discovery sources: an empty registry (tmp_home) and a cwd
    # that is neither registered nor inside a git repo (an empty tmp_path
    # subdirectory), so this repo's own .exptrack/ and worktrees can never
    # leak in and make the "no projects" case unreachable.
    from exptrack import config as cfg
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)
    monkeypatch.setattr(cfg, "_root_cache", None)
    args = _build_parser().parse_args(["project", "list"])
    out, err = _capture(project_cmds.cmd_project, args)
    assert "no projects" in (out + err).lower()


def test_list_shows_a_registered_project(tmp_home, tmp_path):
    _make_project(tmp_path / "alpha")
    projects.register(tmp_path / "alpha")
    args = _build_parser().parse_args(["project", "list"])
    out, _err = _capture(project_cmds.cmd_project, args)
    assert "alpha" in out


def test_list_drops_a_project_that_is_no_longer_there(tmp_home, tmp_path):
    """A registered path with no `.exptrack/` is pruned, not listed.

    This used to assert the opposite — a deleted project stayed on the list,
    marked `stale`, so that a missing entry could never be mistaken for
    discovery itself being broken. What that produced in practice was a
    registry full of dead directories (every `tests/run_all.py` run added a
    few, against the developer's real HOME) and a switcher of greyed-out rows
    with the real projects buried among them. An absence we can confirm is
    now acted on; an absence we cannot is still listed, which the test below
    covers.
    """
    import shutil
    gone = tmp_path / "gone"
    _make_project(gone)
    projects.register(gone)
    shutil.rmtree(gone)
    args = _build_parser().parse_args(["project", "list"])
    out, err = _capture(project_cmds.cmd_project, args)
    assert "gone" not in (out + err)
    assert projects.registered() == []


def test_list_marks_a_project_whose_database_is_missing(tmp_home, tmp_path,
                                                        monkeypatch):
    """`.exptrack/` is there but the database is not — unreadable, not
    absent. It keeps its row, its `stale` marker and its registry entry."""
    from exptrack import config as cfg
    half = tmp_path / "half"
    (half / ".exptrack").mkdir(parents=True)
    projects.register(half)
    # cwd inside an empty directory: `project list` discovers the worktrees of
    # whatever repository it is run in, and this repo's own checkouts would
    # otherwise appear in the output alongside the entry under test.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)
    monkeypatch.setattr(cfg, "_root_cache", None)

    args = _build_parser().parse_args(["project", "list"])
    out, err = _capture(project_cmds.cmd_project, args)
    assert "half" in (out + err)
    assert "stale" in (out + err).lower()
    assert len(projects.registered()) == 1


def test_forget_removes_and_reports(tmp_home, tmp_path):
    _make_project(tmp_path / "alpha")
    projects.register(tmp_path / "alpha")
    args = _build_parser().parse_args(["project", "forget", "alpha"])
    _out, err = _capture(project_cmds.cmd_project, args)
    assert projects.registered() == []
    assert "alpha" in err


def test_forget_an_unknown_name_is_an_error(tmp_home):
    args = _build_parser().parse_args(["project", "forget", "nope"])
    try:
        _capture(project_cmds.cmd_project, args)
    except SystemExit as e:
        assert e.code != 0
        return
    raise AssertionError("forgetting an unknown project should exit non-zero")
