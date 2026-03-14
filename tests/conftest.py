"""Shared pytest fixtures for exptrack tests."""
import json
import os
import tempfile
from pathlib import Path

import pytest

# Save the original working directory at import time
_ORIGINAL_CWD = os.getcwd()


@pytest.fixture(autouse=True)
def _restore_cwd():
    """Ensure every test starts from a known working directory."""
    os.chdir(_ORIGINAL_CWD)
    yield
    # Restore again after test, in case it changed cwd
    try:
        os.getcwd()
    except FileNotFoundError:
        os.chdir(_ORIGINAL_CWD)


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """Create a temporary exptrack project directory and chdir into it."""
    monkeypatch.chdir(tmp_path)
    # Reset cached config
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None
    cfg.init("test-project")
    yield tmp_path
    # Cleanup caches
    cfg._root_cache = None
    cfg._cache = None


@pytest.fixture
def sample_experiment(tmp_project):
    """Create a finished experiment with params, metrics, and an artifact."""
    from exptrack.core import Experiment, get_db

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


@pytest.fixture
def db_conn(tmp_project):
    """Get a database connection to the test project's DB."""
    from exptrack.core import get_db
    return get_db()
