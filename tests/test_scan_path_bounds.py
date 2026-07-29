"""Bounds and containment on the Images / Data Files scan-path walks.

Two problems these guard:

1. ``api_list_logs``/``api_list_images`` walked every saved scan path with no
   ceiling — a full ``os.walk`` plus a ``stat`` per file, with every result
   shipped as JSON. A saved path routinely points at a checkpoint-per-epoch
   tree, and both tabs re-issue the request constantly (a live run's 5-second
   refresh, the two a Compare view opens at once). On an sshfs/NFS project that
   is seconds of held request thread per tab open.
2. Containment was ``abs_dir.startswith(os.path.normpath(root))`` — no
   separator boundary (so ``/home/me/proj`` matched a sibling ``/home/me/proj2``)
   and no ``realpath`` (so a symlink inside the project could point anywhere).
   ``_serve_file`` had always checked it properly; these had not.
"""
from __future__ import annotations

import json
import os

import pytest


def _save_paths(conn, exp_id, column, paths):
    """Set a run's saved scan paths. `column` is log_paths or image_paths — a
    fixed constant here, never user input, so the f-string is injection-safe."""
    conn.execute(f"UPDATE experiments SET {column}=? WHERE id=?",
                 (json.dumps(paths), exp_id))
    conn.commit()


def _saved_log_paths(conn, exp_id, paths):
    _save_paths(conn, exp_id, "log_paths", paths)


def _saved_image_paths(conn, exp_id, paths):
    _save_paths(conn, exp_id, "image_paths", paths)


@pytest.fixture
def run(tmp_project):
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    exp = Experiment(script="train.py")
    exp.finish()
    return exp, get_db()


# ── bounds ──────────────────────────────────────────────────────────────────

def test_log_scan_is_capped_and_says_so(tmp_project, run):
    from exptrack.dashboard.routes import read_routes as rr

    exp, conn = run
    logs = tmp_project / "logs"
    logs.mkdir()
    for i in range(rr._SCAN_MAX_FILES + 25):
        (logs / f"step_{i:05d}.log").write_text("x")
    _saved_log_paths(conn, exp.id, ["logs"])

    res = rr.api_list_logs(conn, exp.id)

    assert res["truncated"] is True
    assert len(res["files"]) == rr._SCAN_MAX_FILES
    assert res["max_files"] == rr._SCAN_MAX_FILES


def test_image_scan_is_capped_and_says_so(tmp_project, run, monkeypatch):
    from exptrack.dashboard.routes import read_routes as rr

    monkeypatch.setattr(rr, "_SCAN_MAX_FILES", 20)
    exp, conn = run
    figs = tmp_project / "figs"
    figs.mkdir()
    for i in range(40):
        (figs / f"fig_{i:03d}.png").write_bytes(b"\x89PNG")
    _saved_image_paths(conn, exp.id, ["figs"])

    res = rr.api_list_images(conn, exp.id)

    assert res["truncated"] is True
    assert len(res["images"]) == 20


def test_deep_tree_walk_is_bounded(tmp_project, run, monkeypatch):
    """The directory count is capped too, not just the file count."""
    from exptrack.dashboard.routes import read_routes as rr

    monkeypatch.setattr(rr, "_SCAN_MAX_WALK_DIRS", 10)
    exp, conn = run
    base = tmp_project / "ckpts"
    for i in range(40):
        d = base / f"epoch_{i:03d}"
        d.mkdir(parents=True)
        (d / "log.txt").write_text("x")
    _saved_log_paths(conn, exp.id, ["ckpts"])

    res = rr.api_list_logs(conn, exp.id)

    assert res["truncated"] is True
    assert len(res["files"]) < 40


def test_dependency_trees_are_pruned(tmp_project, run):
    """A scan path at the project root must not spend its budget in node_modules."""
    from exptrack.dashboard.routes import read_routes as rr

    exp, conn = run
    nm = tmp_project / "stuff" / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "readme.txt").write_text("x")
    (tmp_project / "stuff" / "real.log").write_text("x")
    _saved_log_paths(conn, exp.id, ["stuff"])

    res = rr.api_list_logs(conn, exp.id)

    names = {f["name"] for f in res["files"]}
    assert "real.log" in names
    assert "readme.txt" not in names


def test_an_uncapped_scan_reports_no_truncation(tmp_project, run):
    from exptrack.dashboard.routes import read_routes as rr

    exp, conn = run
    logs = tmp_project / "logs"
    logs.mkdir()
    (logs / "train.log").write_text("hello")
    _saved_log_paths(conn, exp.id, ["logs"])

    res = rr.api_list_logs(conn, exp.id)

    assert res["truncated"] is False
    assert [f["name"] for f in res["files"]] == ["train.log"]


# ── containment ─────────────────────────────────────────────────────────────

def test_sibling_directory_sharing_a_name_prefix_is_rejected(tmp_project, run):
    """`/home/me/proj` must not match `/home/me/proj2`."""
    from exptrack.dashboard.routes import read_routes as rr

    exp, conn = run
    sibling = tmp_project.parent / (tmp_project.name + "2")
    sibling.mkdir(exist_ok=True)
    (sibling / "secret.log").write_text("not yours")
    _saved_log_paths(conn, exp.id, [f"../{sibling.name}"])

    res = rr.api_list_logs(conn, exp.id)

    assert res["files"] == []


def test_symlink_escaping_the_project_is_rejected(tmp_project, run):
    """Without realpath, a link inside the project reached anywhere on disk."""
    from exptrack.dashboard.routes import read_routes as rr

    exp, conn = run
    outside = tmp_project.parent / "outside_data"
    outside.mkdir(exist_ok=True)
    (outside / "private.log").write_text("not yours")
    link = tmp_project / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    _saved_log_paths(conn, exp.id, ["linked"])

    res = rr.api_list_logs(conn, exp.id)

    assert res["files"] == []


def test_a_single_file_scan_path_still_works(tmp_project, run):
    from exptrack.dashboard.routes import read_routes as rr

    exp, conn = run
    (tmp_project / "train.log").write_text("one file")
    _saved_log_paths(conn, exp.id, ["train.log"])

    res = rr.api_list_logs(conn, exp.id)

    assert [f["name"] for f in res["files"]] == ["train.log"]
    assert not os.path.isabs(res["files"][0]["path"])


# ── the experiment list's page size is server-capped ────────────────────────

def test_experiments_limit_is_capped(tmp_project, db_conn, monkeypatch):
    """`limit` is client-supplied and was unbounded — one request could ask the
    server to build and serialize the whole project's list."""
    from exptrack.core import Experiment
    from exptrack.dashboard.routes import read_routes as rr

    monkeypatch.setattr(rr, "_MAX_LIST_LIMIT", 3)
    for _ in range(5):
        Experiment(script="train.py").finish()

    from exptrack.core.db import get_db
    conn = get_db()

    assert len(rr.api_experiments(conn, {"limit": "999999"})) == 3
    assert len(rr.api_experiments(conn, {"limit": "2"})) == 2


def test_experiments_offset_cannot_go_negative(tmp_project, db_conn):
    """Clamped at the route as well as in list_experiments — the route is where
    the untrusted value arrives, so it shouldn't rely on the query layer."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.dashboard.routes import read_routes as rr

    Experiment(script="train.py").finish()
    conn = get_db()

    assert len(rr.api_experiments(conn, {"limit": "10", "offset": "-5"})) == 1


def test_exptrack_internals_are_not_scannable(tmp_project, run):
    """`.exptrack/` holds the DB, the dashboard token and notebook history.

    `/api/file/` has always refused it; the scan routes carried only half the
    rule, so a saved scan path of `.exptrack` listed config.json and every
    notebook-history JSON (both `.json`, both in the Data Files ext set).
    """
    from exptrack.dashboard.routes import read_routes as rr

    exp, conn = run
    hist = tmp_project / ".exptrack" / "notebook_history" / "nb"
    hist.mkdir(parents=True, exist_ok=True)
    (hist / "snap.json").write_text('{"exp_id": "x"}')
    _saved_log_paths(conn, exp.id, [".exptrack"])

    res = rr.api_list_logs(conn, exp.id)

    assert res["files"] == []
