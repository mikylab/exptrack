"""
Shared pytest fixtures for exptrack tests.

Provides isolated temporary project directories and database connections
so every test runs against a fresh environment with no side effects.
"""
from __future__ import annotations

import json
import os

import pytest

# Save the original working directory at import time
_ORIGINAL_CWD = os.getcwd()


def capture(func, *args) -> tuple[str, str]:
    """Run *func* with stdout/stderr captured. Returns ``(stdout, stderr)``.

    The one helper for the CLI-command tests, which call functions that print
    rather than return. Six files had defined their own under the same name in
    two different shapes — some returning the pair, some only stdout — so
    ``out = _capture(...)`` meant different things depending on which file you
    were reading.
    """
    import io
    import sys
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = out = io.StringIO()
    sys.stderr = err = io.StringIO()
    try:
        func(*args)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return out.getvalue(), err.getvalue()


def exp_id_from_stdout(stdout: str, key: str = "EXP_ID") -> str | None:
    """Extract an env var value from run-start stdout (``export KEY="VALUE"``)."""
    for line in stdout.strip().split("\n"):
        if line.startswith(f'export {key}='):
            return line.split('"')[1]
    return None


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


@pytest.fixture()
def live_server_with_token(tmp_project):
    """Run a real dashboard with a known auth token; yield (base_url, token).

    Mirrors the ``live_server`` fixture in test_dashboard_headers.py, but
    pre-writes a token via ``config.write_token`` so auth-gated endpoints are
    reachable and the CSRF invariants (no Set-Cookie, a cookie never
    authenticates) can be exercised over a real socket.
    """
    import threading
    from http.server import HTTPServer

    from exptrack import config as cfg
    from exptrack.dashboard.handler import DashboardHandler

    token = "test-token-not-a-secret"
    cfg.write_token(token)
    server = HTTPServer(("127.0.0.1", 0), DashboardHandler)
    server.allowed_host = "127.0.0.1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", token
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _never_the_real_user_dir(tmp_path_factory, monkeypatch):
    """Point HOME at a temp directory for every test in the suite.

    `config.user_dir()` resolves `~/.exptrack/`, which holds the project
    registry and the saved remotes — user-global state that belongs to the
    person running the tests, not to the tests. `exptrack init` and
    `exptrack ui start` both register the current project, and the tests that
    exercise them isolate the *project* directory without touching HOME, so
    every run of the suite appended its temp paths to the developer's real
    `~/.exptrack/projects.json`. It was found with ~150 dead pytest
    directories in it, which is enough to make the dashboard's project
    switcher useless and to bury the one project the user actually has.

    Autouse and suite-wide rather than per-test: the property wanted is that
    no test *can* write there, and a fixture each new test has to remember to
    request does not give that. `tmp_home` stays for tests that want a handle
    on the directory.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture(autouse=True)
def _never_a_real_browser(monkeypatch):
    """`exptrack ui` and `ui start` open a browser tab. A test driving either
    would open one on the developer's desktop per run; stub it suite-wide."""
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: True)


@pytest.fixture()
def tmp_home(tmp_path, monkeypatch):
    """Point the user-global exptrack directory at a temp path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home
