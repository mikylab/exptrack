"""
Shared pytest fixtures for exptrack tests.

Provides isolated temporary project directories and database connections
so every test runs against a fresh environment with no side effects.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

# Save the original working directory at import time
_ORIGINAL_CWD = os.getcwd()


@pytest.fixture(autouse=True)
def _restore_cwd():
    """Ensure every test starts from a known working directory."""
    os.chdir(_ORIGINAL_CWD)
    yield
    try:
        os.getcwd()
    except FileNotFoundError:
        os.chdir(_ORIGINAL_CWD)


@pytest.fixture()
def tmp_project(tmp_path, monkeypatch):
    """Create an isolated exptrack project in a temp directory.

    Sets up ``.exptrack/`` with a default ``config.json`` and patches
    ``config.project_root()`` / ``config.load()`` / ``config._root_cache``
    so all exptrack code sees *tmp_path* as the project root.

    Also patches ``git_info`` and ``gpu_info`` so tests don't require a
    real git repository or GPU hardware.

    Yields the *tmp_path* (``pathlib.Path``).
    """
    from exptrack import config as cfg
    from exptrack.core import db as _db

    # ── Set up .exptrack dir and config ──────────────────────────────────
    exptrack_dir = tmp_path / ".exptrack"
    exptrack_dir.mkdir()

    conf = dict(cfg.DEFAULTS)
    conf["db"] = ".exptrack/experiments.db"
    conf["outputs_dir"] = "outputs"
    (exptrack_dir / "config.json").write_text(json.dumps(conf, indent=2))

    # ── Patch config caches to point at tmp_path ─────────────────────────
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    monkeypatch.setattr(cfg, "_cache", None)
    monkeypatch.setattr(cfg, "project_root", lambda: tmp_path)

    # chdir so any code that falls back to cwd also sees tmp_path
    monkeypatch.chdir(tmp_path)

    # ── Mock git_info (no real git repo needed) ──────────────────────────
    monkeypatch.setattr(
        "exptrack.core.git.git_info",
        lambda: {"git_branch": "main", "git_commit": "abc1234", "git_diff": ""},
    )

    # ── Mock gpu_info (no nvidia-smi needed) ─────────────────────────────
    monkeypatch.setattr(
        "exptrack.core.gpu.gpu_info",
        lambda: {"gpu_count": 0, "gpu_devices": [], "cuda_visible_devices": None},
    )

    # ── Clear cached DB connection from previous tests ───────────────────
    _db._local.conn = None
    _db._local.db_path = None

    yield tmp_path

    # ── Teardown: close DB, reset caches ─────────────────────────────────
    try:
        _db.close_db()
    except Exception:
        pass
    cfg._root_cache = None
    cfg._cache = None


@pytest.fixture()
def db_conn(tmp_project):
    """Provide a ready-to-use SQLite connection to the test project's DB.

    The connection has the full exptrack schema already applied (via
    ``get_db()``'s ``_ensure_schema`` call).
    """
    from exptrack.core.db import get_db

    conn = get_db()
    yield conn


@pytest.fixture()
def sample_experiment(tmp_project):
    """Create a finished experiment with params, metrics, and an artifact.

    Useful for tests that need a fully populated experiment to query against.
    """
    from exptrack.core import Experiment

    exp = Experiment(script="train.py", params={"lr": 0.01, "epochs": 10})
    exp.log_metric("loss", 0.5, step=1)
    exp.log_metric("loss", 0.3, step=2)
    exp.log_metric("acc", 0.85, step=2)

    # Create a dummy artifact file
    art_path = tmp_project / "outputs" / exp.name / "model.pt"
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_bytes(b"fake model data")
    exp.log_artifact(str(art_path), label="model")

    exp.finish()
    return exp
