"""Tests for dashboard write-route error contracts.

The happy paths are exercised in test_dashboard_api.py; this file pins down
the *error* branches (missing experiment, empty/invalid input, read-only auto
params) that were previously untested. Routes take a sqlite3 connection as the
first arg, so we call them directly.
"""
from __future__ import annotations

import pytest

from exptrack.core import Experiment, get_db
from exptrack.dashboard.routes import write_routes as wr


@pytest.fixture()
def exp(tmp_project):
    """A finished experiment with one auto param and one manual param."""
    e = Experiment(script="train.py", params={"lr": 0.01})  # lr → auto param
    e.finish()
    conn = get_db()
    conn.execute(
        "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
        (e.id, "note_scale", "2", "manual"),
    )
    conn.commit()
    return e


# ── not-found contract ───────────────────────────────────────────────────────

def test_rename_missing_experiment(db_conn):
    assert wr.api_rename(db_conn, "nope", {"name": "x"}) == {"error": "not found"}


def test_delete_missing_experiment(db_conn):
    assert wr.api_delete(db_conn, "nope") == {"error": "not found"}


def test_add_param_missing_experiment(db_conn):
    assert wr.api_add_param(db_conn, "nope", {"key": "k"}) == {"error": "not found"}


# ── rename validation ────────────────────────────────────────────────────────

def test_rename_empty_name_rejected(exp):
    assert wr.api_rename(get_db(), exp.id, {"name": "   "}) == {"error": "empty name"}


def test_rename_clears_auto_flag(exp):
    conn = get_db()
    res = wr.api_rename(conn, exp.id, {"name": "my-real-name"})
    assert res["ok"] is True
    flag = conn.execute(
        "SELECT name_is_auto FROM experiments WHERE id=?", (exp.id,)
    ).fetchone()[0]
    assert flag == 0


# ── param add/edit/delete error branches ─────────────────────────────────────

def test_add_param_empty_key(exp):
    assert wr.api_add_param(get_db(), exp.id, {"key": "  "}) == {"error": "provide key"}


def test_add_param_reserved_underscore(exp):
    res = wr.api_add_param(get_db(), exp.id, {"key": "_secret", "value": "1"})
    assert "reserved" in res["error"]


def test_add_param_cannot_overwrite_auto(exp):
    res = wr.api_add_param(get_db(), exp.id, {"key": "lr", "value": "0.5"})
    assert "read-only" in res["error"]


def test_edit_param_auto_is_readonly(exp):
    res = wr.api_edit_param(get_db(), exp.id, {"key": "lr", "value": "0.5"})
    assert "auto-captured" in res["error"]


def test_edit_manual_param_succeeds(exp):
    conn = get_db()
    res = wr.api_edit_param(conn, exp.id, {"key": "note_scale", "value": "9"})
    assert res["ok"] is True
    stored = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key='note_scale'", (exp.id,)
    ).fetchone()[0]
    assert "9" in stored


def test_delete_param_missing_key(exp):
    res = wr.api_delete_param(get_db(), exp.id, {"key": "ghost"})
    assert "not found" in res["error"]


def test_delete_auto_param_blocked(exp):
    res = wr.api_delete_param(get_db(), exp.id, {"key": "lr"})
    assert "cannot be deleted" in res["error"]


# ── typed-body robustness: a non-dashboard client sending valid JSON with the
#    wrong shape must get a clean error / no-op, not an opaque 500 ─────────────

def test_log_path_string_index_coerces_not_crash(exp):
    """A string *number* index coerces (like body_str does for strings); a
    non-numeric index becomes an out-of-range no-op. Neither raises TypeError
    in `0 <= index < len` the way `body.get("index", -1)` used to."""
    conn = get_db()
    wr.api_log_path(conn, exp.id, {"action": "add", "path": "logs/a.txt"})
    # "x" (non-numeric) → -1 → out-of-range → no-op, path retained.
    res = wr.api_log_path(conn, exp.id, {"action": "delete", "index": "x"})
    assert res["ok"] is True and res["paths"] == ["logs/a.txt"]
    # "0" (string number) → 0 → valid index → deletes, no crash.
    res = wr.api_log_path(conn, exp.id, {"action": "delete", "index": "0"})
    assert res["ok"] is True and res["paths"] == []


def test_image_path_bad_index_is_noop(exp):
    conn = get_db()
    wr.api_image_path(conn, exp.id, {"action": "add", "path": "img/a.png"})
    res = wr.api_image_path(conn, exp.id, {"action": "delete", "index": "x"})
    assert res["ok"] is True and res["paths"] == ["img/a.png"]


def test_delete_metric_bad_step_returns_error(exp):
    """mode='step' with a non-integer step returns a clean error, not a 500."""
    conn = get_db()
    res = wr.api_delete_metric(conn, exp.id, {"key": "loss", "mode": "step",
                                              "step": "x"})
    assert res == {"error": "step must be an integer"}


def test_edit_notes_non_string_does_not_crash(exp):
    """A JSON object for `notes` used to hit sqlite3.ProgrammingError; it is now
    coerced through body_str like every other string field."""
    conn = get_db()
    res = wr.api_edit_notes(conn, exp.id, {"notes": {"x": 1}})
    assert res.get("ok") is True  # coerced, not crashed


def test_bulk_delete_raises_ambiguous_prefix(db_conn):
    """The bulk routes resolve a whole posted id list in a loop; an ambiguous
    prefix raises AmbiguousPrefixError, which the handler boundary (_run_post)
    turns into a clean error instead of a mid-loop 500. Here we pin the raise."""
    from exptrack.core.queries import AmbiguousPrefixError

    ts = "2026-01-01T00:00:00"
    for eid in ("ab12345000", "ab12345999"):
        db_conn.execute(
            "INSERT INTO experiments (id,name,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?)", (eid, eid, "done", ts, ts))
    db_conn.commit()
    with pytest.raises(AmbiguousPrefixError):
        wr.api_bulk_delete(db_conn, {"ids": ["ab"]})


# ── handler POST boundary: _run_post catches AmbiguousPrefixError ─────────────

class _CapHandler:
    """Minimal stand-in exposing just what _run_post touches."""
    def __init__(self):
        self.sent = None
        self.checkpointed = False

    def _json(self, data):
        self.sent = data

    def _wal_checkpoint(self, conn):
        self.checkpointed = True


def test_run_post_catches_ambiguous_prefix():
    from exptrack.core.queries import AmbiguousPrefixError
    from exptrack.dashboard.handler import DashboardHandler

    cap = _CapHandler()

    def handler():
        raise AmbiguousPrefixError("ambiguous", [("ab1", "x"), ("ab2", "y")])

    DashboardHandler._run_post(cap, handler, conn=None)
    assert "error" in cap.sent           # clean JSON error, not a 500
    assert cap.checkpointed is False     # no checkpoint on the error path


def test_run_post_passes_result_and_checkpoints():
    from exptrack.dashboard.handler import DashboardHandler

    cap = _CapHandler()
    DashboardHandler._run_post(cap, lambda: {"ok": True}, conn=object())
    assert cap.sent == {"ok": True}
    assert cap.checkpointed is True
