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
