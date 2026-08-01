"""Three hardening fixes:

1. A failed ``_migrate_*`` helper must not let ``_ensure_schema`` stamp
   ``user_version`` — the stamp is what makes ``get_db`` skip the migration
   forever, so a transient failure would permanently strand the column.
2. ``?token=`` is credentials only on ``/api/file/`` (``<img>`` can't send a
   header); every other route requires the Authorization header.
3. ``rename_output_folder`` must not follow a ``..`` (or any separator) out of
   ``outputs/``.
"""
from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest

from exptrack.core import db as _db
from exptrack.dashboard.handler import DashboardHandler

# ── 1. Schema stamp only on a fully-successful migration ─────────────────────

def _fresh_conn(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def test_failed_migration_does_not_stamp_user_version(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    conn = _fresh_conn(dbp)
    monkeypatch.setattr(_db, "_migrate_params", lambda c: False)
    _db._ensure_schema(conn)
    assert _db._stored_schema_version(conn) != _db._SCHEMA_VERSION
    conn.close()


def test_next_open_retries_and_then_stamps(tmp_path, monkeypatch):
    """The un-stamped DB must be re-migrated by the next connection."""
    dbp = tmp_path / "t.db"
    calls = []

    real = _db._migrate_params

    def flaky(c):
        calls.append(1)
        if len(calls) == 1:
            return False   # e.g. "database is locked" during the ALTER
        return real(c)

    monkeypatch.setattr(_db, "_migrate_params", flaky)

    conn = _fresh_conn(dbp)
    _db._ensure_schema(conn)
    assert _db._stored_schema_version(conn) != _db._SCHEMA_VERSION
    conn.close()

    # Second open: helper succeeds, so the stamp lands.
    conn = _fresh_conn(dbp)
    _db._ensure_schema(conn)
    assert len(calls) == 2
    assert _db._stored_schema_version(conn) == _db._SCHEMA_VERSION

    # Third open takes the steady-state fast path (helper not called again).
    _db._ensure_schema(conn)
    assert len(calls) == 2
    conn.close()


def test_operational_error_in_helper_is_reported_not_raised(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    conn = _fresh_conn(dbp)

    def boom(c, table, columns, existing=None):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(_db, "_add_columns", boom)
    assert _db._migrate_params(conn) is False
    assert _db._migrate_artifacts(conn) is False
    assert _db._migrate_experiment_session_link(conn) is False
    conn.close()


def test_clean_migration_stamps_and_helpers_report_true(tmp_path):
    dbp = tmp_path / "t.db"
    conn = _fresh_conn(dbp)
    _db._ensure_schema(conn)
    assert _db._stored_schema_version(conn) == _db._SCHEMA_VERSION
    # Idempotency preserved: forcing a re-run is a no-op that still succeeds.
    _db._ensure_schema(conn, force=True)
    assert _db._stored_schema_version(conn) == _db._SCHEMA_VERSION
    for fn in (_db._migrate_sessions, _db._migrate_session_nodes,
               _db._migrate_experiment_session_link, _db._migrate_artifacts,
               _db._migrate_metrics, _db._migrate_params,
               _db._migrate_experiments):
        assert fn(conn) is True, fn.__name__
    conn.close()


# ── 2. Query-string token restricted to /api/file/ ───────────────────────────

class _FakeServer:
    allowed_host = ""


def _auth_handler(path, headers=None):
    h = object.__new__(DashboardHandler)
    h.path = path
    h.server = _FakeServer()
    h.headers = headers or {}
    h.rfile = io.BytesIO()
    h.wfile = io.BytesIO()
    sent = {"error": None, "msg": ""}

    def send_error(code, msg=""):
        sent["error"] = code
        sent["msg"] = msg

    h.send_error = send_error
    return h, sent


@pytest.fixture()
def token(monkeypatch):
    monkeypatch.setenv("EXPTRACK_DASHBOARD_TOKEN", "s3cret")
    return "s3cret"


def test_qs_token_accepted_for_api_file(token):
    h, sent = _auth_handler("/api/file/outputs/run/plot.png?token=s3cret")
    assert h._check_auth() is True
    assert sent["error"] is None


def test_qs_token_rejected_on_other_routes(token):
    for path in ("/api/experiments?token=s3cret",
                 "/api/stats?token=s3cret",
                 "/api/experiment/abc/rename?token=s3cret"):
        h, sent = _auth_handler(path)
        assert h._check_auth() is False, path
        assert sent["error"] == 401
        # The hint must not advertise a query param where it isn't accepted.
        assert "?token=" not in sent["msg"]


def test_header_token_works_everywhere(token):
    for path in ("/api/experiments", "/api/file/outputs/a.png"):
        h, _ = _auth_handler(path, {"Authorization": "Bearer s3cret"})
        assert h._check_auth() is True


def test_wrong_qs_token_on_file_route_rejected(token):
    h, sent = _auth_handler("/api/file/outputs/a.png?token=nope")
    assert h._check_auth() is False
    assert sent["error"] == 401


def test_no_auth_configured_allows_everything(monkeypatch):
    monkeypatch.setenv("EXPTRACK_DASHBOARD_TOKEN", "")
    monkeypatch.setattr("exptrack.dashboard.handler._read_token_file", lambda: "")
    monkeypatch.setattr("exptrack.dashboard.handler._session_token", "")
    h, _ = _auth_handler("/api/experiments")
    assert h._check_auth() is True


# ── 3. rename_output_folder path traversal ───────────────────────────────────

def _make_run(tmp_project, name="run1"):
    from exptrack.core import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO experiments (id, name, status, created_at, updated_at) "
        "VALUES (?,?,?,?,?)", ("e1", name, "done", "2026-01-01", "2026-01-01"))
    conn.commit()
    return conn


def test_rename_never_escapes_outputs_dir(tmp_project):
    """A `..` name is reduced to a single component, never followed."""
    conn = _make_run(tmp_project)
    outputs = tmp_project / "outputs"
    (outputs / "run1").mkdir(parents=True)
    (outputs / "run1" / "a.txt").write_text("x")

    _db.rename_output_folder(conn, "e1", "run1", "../../evil")

    assert not (tmp_project.parent / "evil").exists()
    assert not (tmp_project / "evil").exists()
    row = conn.execute("SELECT output_dir FROM experiments WHERE id='e1'").fetchone()
    assert row["output_dir"].startswith(str(outputs) + "/")


def test_rename_refuses_absolute_and_dot_names(tmp_project):
    conn = _make_run(tmp_project)
    outputs = tmp_project / "outputs"
    (outputs / "run1").mkdir(parents=True)
    # "..", "." and "" have no usable component at all — refused outright.
    for bad in ("..", ".", ""):
        _db.rename_output_folder(conn, "e1", "run1", bad)
        assert (outputs / "run1").is_dir(), bad
    # An absolute path or a nested path keeps only its last component, so the
    # destination is always a direct child of outputs/.
    for bad, expect in (("/tmp/evil", "evil"), ("sub/dir", "dir")):
        (outputs / "run1").mkdir(exist_ok=True)
        _db.rename_output_folder(conn, "e1", "run1", bad)
        assert not Path("/tmp/evil").exists()
        assert (outputs / expect).is_dir(), bad


def test_rename_does_not_escape_to_prefix_sibling(tmp_project):
    """A destination that merely *shares a prefix* with outputs/ is not inside it."""
    conn = _make_run(tmp_project)
    outputs = tmp_project / "outputs"
    (outputs / "run1").mkdir(parents=True)

    _db.rename_output_folder(conn, "e1", "run1", "../outputs_evil")

    # `outputs_evil` shares a prefix with `outputs` but is not inside it, so it
    # must never be created at the project root.
    assert not (tmp_project / "outputs_evil").exists()
    assert (outputs / "outputs_evil").is_dir()


def test_safe_output_dir_unit(tmp_path):
    base = tmp_path / "outputs"
    base.mkdir()
    (tmp_path / "outputs_evil").mkdir()

    assert _db._safe_output_dir(base, "run1") == base / "run1"
    assert _db._safe_output_dir(base, "../../evil") == base / "evil"
    assert _db._safe_output_dir(base, "..") is None
    assert _db._safe_output_dir(base, "") is None
    # A symlink out of outputs/ is caught by the realpath check even though the
    # name itself is a single clean component.
    (base / "link").symlink_to(tmp_path / "outputs_evil")
    assert _db._safe_output_dir(base, "link") is None


def test_normal_rename_still_works(tmp_project):
    conn = _make_run(tmp_project)
    outputs = tmp_project / "outputs"
    (outputs / "run1").mkdir(parents=True)
    (outputs / "run1" / "a.txt").write_text("x")
    conn.execute("INSERT INTO artifacts (exp_id, label, path) VALUES (?,?,?)",
                 ("e1", "a", str(outputs / "run1" / "a.txt")))
    conn.commit()

    _db.rename_output_folder(conn, "e1", "run1", "run2")

    assert (outputs / "run2" / "a.txt").exists()
    row = conn.execute("SELECT output_dir FROM experiments WHERE id='e1'").fetchone()
    assert row["output_dir"] == str(outputs / "run2")
    art = conn.execute("SELECT path FROM artifacts WHERE exp_id='e1'").fetchone()
    assert art["path"] == str(outputs / "run2" / "a.txt")
