"""Happy-path + error coverage for dashboard write routes (write_routes.py).

test_dashboard_api.py covers the core CRUD routes and test_dashboard_route_errors.py
pins the param error contracts; this file fills the gap for the ~40 remaining
`api_*` POST handlers — studies, metrics/results, artifacts, params (add/rename),
stage, script/command, manual creation, todos/commands, confusion, storage, and
the session routes — exercising both the success path and a representative
not-found / validation branch for each.

Routes take a sqlite3 connection as the first arg, so they're called directly.
"""
from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest

from exptrack.core import Experiment, get_db
from exptrack.dashboard.routes import write_routes as wr


@pytest.fixture()
def exp(tmp_project):
    """A finished experiment with one auto param and a couple of metrics."""
    e = Experiment(script="train.py", params={"lr": 0.01})  # lr → auto param
    e.log_metric("loss", 0.5, step=1)
    e.log_metric("loss", 0.3, step=2)
    e.finish()
    return e


# ── tags: edit ───────────────────────────────────────────────────────────────

def test_edit_tag_happy(exp):
    conn = get_db()
    wr.api_add_tag(conn, exp.id, {"tag": "baseline"})
    res = wr.api_edit_tag(conn, exp.id, {"old_tag": "baseline", "new_tag": "v2"})
    assert res["ok"] is True
    assert "v2" in res["tags"] and "baseline" not in res["tags"]


def test_edit_tag_requires_both(exp):
    res = wr.api_edit_tag(get_db(), exp.id, {"old_tag": "x"})
    assert "old_tag and new_tag" in res["error"]


def test_edit_tag_missing_exp(db_conn):
    assert wr.api_edit_tag(db_conn, "nope", {"old_tag": "a", "new_tag": "b"}) == {
        "error": "not found"
    }


# ── artifacts: add / edit / delete ───────────────────────────────────────────

def test_add_artifact_happy(exp):
    conn = get_db()
    res = wr.api_add_artifact(conn, exp.id, {"label": "model", "path": "out/m.pt"})
    assert res["ok"] is True
    n = conn.execute(
        "SELECT COUNT(*) FROM artifacts WHERE exp_id=? AND label='model'", (exp.id,)
    ).fetchone()[0]
    assert n == 1


def test_add_artifact_infers_label_from_path(exp):
    conn = get_db()
    res = wr.api_add_artifact(conn, exp.id, {"path": "out/weights.pt"})
    assert res["label"] == "weights.pt"


def test_add_artifact_requires_label_or_path(exp):
    res = wr.api_add_artifact(get_db(), exp.id, {})
    assert "label or path" in res["error"]


def test_edit_artifact_happy(exp):
    conn = get_db()
    wr.api_add_artifact(conn, exp.id, {"label": "m", "path": "a.pt"})
    res = wr.api_edit_artifact(
        conn, exp.id, {"old_label": "m", "new_label": "model", "new_path": "b.pt"}
    )
    assert res["ok"] is True
    row = conn.execute(
        "SELECT label, path FROM artifacts WHERE exp_id=? AND label='model'", (exp.id,)
    ).fetchone()
    assert row["label"] == "model" and row["path"] == "b.pt"


def test_delete_artifact_happy(exp):
    conn = get_db()
    wr.api_add_artifact(conn, exp.id, {"label": "m", "path": "a.pt"})
    res = wr.api_delete_artifact(conn, exp.id, {"label": "m", "path": "a.pt"})
    assert res["ok"] is True
    assert conn.execute(
        "SELECT COUNT(*) FROM artifacts WHERE exp_id=? AND label='m'", (exp.id,)
    ).fetchone()[0] == 0


def test_delete_artifact_requires_label_or_path(exp):
    assert "label or path" in wr.api_delete_artifact(get_db(), exp.id, {})["error"]


# ── metrics: log / delete / rename ───────────────────────────────────────────

def test_log_metric_happy(exp):
    conn = get_db()
    res = wr.api_log_metric(conn, exp.id, {"key": "acc", "value": "0.9", "step": "3"})
    assert res["ok"] is True and res["value"] == 0.9 and res["step"] == 3


def test_log_metric_auto_increments_step(exp):
    conn = get_db()
    res = wr.api_log_metric(conn, exp.id, {"key": "f1", "value": "0.7"})
    assert res["ok"] is True
    # second call without step must advance
    res2 = wr.api_log_metric(conn, exp.id, {"key": "f1", "value": "0.8"})
    assert res2["step"] > res["step"]


def test_log_metric_rejects_non_number(exp):
    assert "must be a number" in wr.api_log_metric(
        get_db(), exp.id, {"key": "x", "value": "abc"}
    )["error"]


def test_log_metric_requires_key_and_value(exp):
    assert "key and value" in wr.api_log_metric(get_db(), exp.id, {"key": "x"})["error"]


def test_delete_metric_last(exp):
    conn = get_db()
    res = wr.api_delete_metric(conn, exp.id, {"key": "loss", "mode": "last"})
    assert res["ok"] is True and res["remaining"] == 1


def test_delete_metric_all(exp):
    conn = get_db()
    res = wr.api_delete_metric(conn, exp.id, {"key": "loss", "mode": "all"})
    assert res["remaining"] == 0


def test_rename_metric_happy(exp):
    conn = get_db()
    res = wr.api_rename_metric(conn, exp.id, {"old_key": "loss", "new_key": "train/loss"})
    assert res["ok"] is True
    assert conn.execute(
        "SELECT COUNT(*) FROM metrics WHERE exp_id=? AND key='train/loss'", (exp.id,)
    ).fetchone()[0] == 2


def test_rename_metric_missing_key(exp):
    res = wr.api_rename_metric(get_db(), exp.id, {"old_key": "ghost", "new_key": "x"})
    assert "not found" in res["error"]


# ── results (manual metrics) ─────────────────────────────────────────────────

def test_log_result_then_edit_then_delete(exp):
    conn = get_db()
    res = wr.api_log_result(conn, exp.id, {"key": "final_acc", "value": "0.95"})
    assert res["ok"] is True
    edited = wr.api_edit_result(conn, exp.id, {"key": "final_acc", "value": "0.97"})
    assert edited["value"] == 0.97
    deleted = wr.api_delete_result(conn, exp.id, {"key": "final_acc"})
    assert deleted["ok"] is True
    assert conn.execute(
        "SELECT COUNT(*) FROM metrics WHERE exp_id=? AND key='final_acc'", (exp.id,)
    ).fetchone()[0] == 0


# ── params: add / rename ─────────────────────────────────────────────────────

def test_add_param_happy(exp):
    conn = get_db()
    res = wr.api_add_param(conn, exp.id, {"key": "seed", "value": "42"})
    assert res["ok"] is True and res["value"] == 42  # JSON-decoded


def test_rename_param_happy(exp):
    conn = get_db()
    wr.api_add_param(conn, exp.id, {"key": "seed", "value": "42"})
    res = wr.api_rename_param(conn, exp.id, {"old_key": "seed", "new_key": "rng_seed"})
    assert res["ok"] is True
    assert conn.execute(
        "SELECT COUNT(*) FROM params WHERE exp_id=? AND key='rng_seed'", (exp.id,)
    ).fetchone()[0] == 1


def test_rename_param_auto_blocked(exp):
    res = wr.api_rename_param(get_db(), exp.id, {"old_key": "lr", "new_key": "x"})
    assert "auto-captured" in res["error"]


def test_rename_param_collision(exp):
    conn = get_db()
    wr.api_add_param(conn, exp.id, {"key": "a", "value": "1"})
    wr.api_add_param(conn, exp.id, {"key": "b", "value": "2"})
    res = wr.api_rename_param(conn, exp.id, {"old_key": "a", "new_key": "b"})
    assert "already exists" in res["error"]


# ── stage ────────────────────────────────────────────────────────────────────

def test_set_stage_happy(exp):
    conn = get_db()
    res = wr.api_set_stage(conn, exp.id, {"stage": "2", "stage_name": "eval"})
    assert res["ok"] is True and res["stage"] == 2


def test_set_stage_rejects_non_int(exp):
    res = wr.api_set_stage(get_db(), exp.id, {"stage": "abc"})
    assert "integer" in res["error"]


def test_set_stage_requires_something(exp):
    res = wr.api_set_stage(get_db(), exp.id, {})
    assert "stage or stage_name" in res["error"]


# ── script / command ─────────────────────────────────────────────────────────

def test_edit_script_and_command(exp):
    conn = get_db()
    assert wr.api_edit_script(conn, exp.id, {"script": "new.py"})["script"] == "new.py"
    assert wr.api_edit_command(conn, exp.id, {"command": "python new.py"})[
        "command"
    ] == "python new.py"
    row = conn.execute(
        "SELECT script, command FROM experiments WHERE id=?", (exp.id,)
    ).fetchone()
    assert row["script"] == "new.py" and row["command"] == "python new.py"


# ── confusion ────────────────────────────────────────────────────────────────

def test_save_confusion_happy(exp):
    conn = get_db()
    res = wr.api_save_confusion(conn, exp.id, {"matrices": [{"name": "m", "data": []}]})
    assert res["ok"] is True and res["count"] == 1


def test_save_confusion_requires_list(exp):
    res = wr.api_save_confusion(get_db(), exp.id, {"matrices": "nope"})
    assert "must be a list" in res["error"]


# ── studies ──────────────────────────────────────────────────────────────────

def test_study_lifecycle(exp):
    conn = get_db()
    created = wr.api_create_study(conn, {"name": "sweep-1", "experiment_ids": [exp.id]})
    assert created["ok"] is True and created["added"] == 1
    added = wr.api_add_study(conn, exp.id, {"study": "sweep-2"})
    assert "sweep-2" in added["studies"]
    removed = wr.api_delete_exp_study(conn, exp.id, {"study": "sweep-2"})
    assert "sweep-2" not in removed["studies"]
    all_studies = wr.api_all_studies(conn)
    assert any(s.get("name") == "sweep-1" for s in all_studies["studies"])


def test_create_study_empty_name(db_conn):
    assert "empty study name" in wr.api_create_study(db_conn, {"name": ""})["error"]


def test_add_to_study_requires_fields(db_conn):
    assert "study and experiment_id" in wr.api_add_to_study(db_conn, {})["error"]


def test_bulk_add_to_study(exp):
    conn = get_db()
    res = wr.api_bulk_add_to_study(conn, {"study": "grp", "ids": [exp.id]})
    assert res["ok"] is True and res["added"] == 1


def test_bulk_add_to_study_no_ids(db_conn):
    assert "no ids" in wr.api_bulk_add_to_study(db_conn, {"study": "g"})["error"]


# ── manual experiment creation ───────────────────────────────────────────────

def test_create_experiment_happy(db_conn):
    res = wr.api_create_experiment(
        db_conn,
        {"name": "manual-run", "params": {"lr": 0.1}, "metrics": {"acc": 0.9},
         "tags": ["t1"]},
    )
    assert res["ok"] is True
    eid = res["id"]
    row = db_conn.execute(
        "SELECT name, status FROM experiments WHERE id=?", (eid,)
    ).fetchone()
    assert row["name"] == "manual-run" and row["status"] == "done"
    assert db_conn.execute(
        "SELECT COUNT(*) FROM params WHERE exp_id=?", (eid,)
    ).fetchone()[0] == 1
    assert db_conn.execute(
        "SELECT COUNT(*) FROM metrics WHERE exp_id=?", (eid,)
    ).fetchone()[0] == 1


def test_create_experiment_requires_name(db_conn):
    assert "name is required" in wr.api_create_experiment(db_conn, {"name": ""})["error"]


# ── storage ──────────────────────────────────────────────────────────────────

def test_storage_info(exp):
    info = wr.api_storage_info(get_db())
    assert info["ok"] is True
    assert info["experiments"] >= 1
    assert info["metrics"] >= 2


# ── todos / commands (config-backed) ─────────────────────────────────────────

def test_todo_lifecycle(tmp_project):
    added = wr.api_add_todo({"text": "write tests"})
    assert added["ok"] is True
    tid = added["todo"]["id"]
    assert tid
    upd = wr.api_update_todo({"id": tid, "done": True})
    assert upd["ok"] is True
    assert wr.api_delete_todo({"id": tid})["ok"] is True


def test_command_lifecycle_and_reorder(tmp_project):
    a = wr.api_add_command({"command": "echo a", "label": "a"})
    b = wr.api_add_command({"command": "echo b", "label": "b"})
    aid = a["command"]["id"]
    bid = b["command"]["id"]
    assert aid and bid
    res = wr.api_reorder_commands({"ids": [bid, aid]})
    assert res["ok"] is True
    from exptrack import config as cfg
    cmds = cfg.load().get("commands", [])
    assert [c["id"] for c in cmds][:2] == [bid, aid]
    assert wr.api_delete_command({"id": aid})["ok"] is True


def test_reorder_commands_requires_list(tmp_project):
    assert "must be a list" in wr.api_reorder_commands({"ids": "x"})["error"]


# ── session routes ───────────────────────────────────────────────────────────

@pytest.fixture()
def session_tree(tmp_project):
    """A started session root → checkpoint → branch. Returns (sid, root, cp, br)."""
    from exptrack.sessions import SessionManager

    sm = SessionManager()
    sid = sm.start("explore", notebook="nb.ipynb")
    cp = sm.checkpoint("after preprocess")
    br = sm.branch("try threshold 0.7")
    sm.record_cell("x = 1\n", "1")
    conn = get_db()
    root = conn.execute(
        "SELECT id FROM session_nodes WHERE session_id=? AND node_type='root'", (sid,)
    ).fetchone()["id"]
    return sid, root, cp, br


def test_session_note_node(session_tree):
    sid, root, cp, br = session_tree
    conn = get_db()
    res = wr.api_session_note_node(conn, sid, {"node_id": br, "text": "hi"})
    assert res["ok"] is True
    assert conn.execute(
        "SELECT note FROM session_nodes WHERE id=?", (br,)
    ).fetchone()["note"] == "hi"


def test_session_note_node_missing(session_tree):
    sid = session_tree[0]
    assert wr.api_session_note_node(get_db(), sid, {"node_id": "zzz", "text": "x"}) == {
        "error": "not found"
    }


def test_session_rename_node(session_tree):
    sid, root, cp, br = session_tree
    res = wr.api_session_rename_node(get_db(), sid, {"node_id": br, "label": "renamed"})
    assert res["ok"] is True and res["label"] == "renamed"


def test_session_promote_to_checkpoint(session_tree):
    sid, root, cp, br = session_tree
    res = wr.api_session_promote_to_checkpoint(get_db(), sid, {"node_id": br})
    assert res["ok"] is True and res["node_type"] == "checkpoint"


def test_session_delete_restore_node(session_tree):
    sid, root, cp, br = session_tree
    conn = get_db()
    deleted = wr.api_session_delete_node(conn, sid, {"node_id": br})
    assert deleted["ok"] is True
    assert conn.execute(
        "SELECT deleted_at FROM session_nodes WHERE id=?", (br,)
    ).fetchone()["deleted_at"] is not None
    restored = wr.api_session_restore_node(conn, sid, {"node_id": br})
    assert restored["ok"] is True
    assert conn.execute(
        "SELECT deleted_at FROM session_nodes WHERE id=?", (br,)
    ).fetchone()["deleted_at"] is None


def test_session_delete_node_missing_id(session_tree):
    sid = session_tree[0]
    assert "missing node_id" in wr.api_session_delete_node(get_db(), sid, {})["error"]


def test_session_purge_and_empty_trash(session_tree):
    sid, root, cp, br = session_tree
    conn = get_db()
    wr.api_session_delete_node(conn, sid, {"node_id": br})
    res = wr.api_session_purge_node(conn, sid, {"node_id": br})
    assert res["ok"] is True
    # empty_trash on a now-clean session still succeeds
    res2 = wr.api_session_empty_trash(conn, sid, {})
    assert res2["ok"] is True


def test_session_empty_trash_missing_session(db_conn):
    assert wr.api_session_empty_trash(db_conn, "nope", {}) == {"error": "not found"}


def test_session_materialize_experiment(session_tree):
    sid, root, cp, br = session_tree
    conn = get_db()
    res = wr.api_session_materialize_experiment(conn, sid, {"node_id": br})
    assert res["ok"] is True and res["id"]
    # node now linked to the new experiment
    assert conn.execute(
        "SELECT session_node_id FROM experiments WHERE id=?", (res["id"],)
    ).fetchone()["session_node_id"] == br


def test_session_link_experiment(session_tree):
    sid, root, cp, br = session_tree
    e = Experiment(script="train.py", params={"lr": 0.01})
    e.finish()
    conn = get_db()
    res = wr.api_session_link_experiment(conn, sid, {"node_id": br, "exp_id": e.id})
    assert res["ok"] is True
    assert conn.execute(
        "SELECT session_node_id FROM experiments WHERE id=?", (e.id,)
    ).fetchone()["session_node_id"] == br


def test_session_end(session_tree):
    sid = session_tree[0]
    conn = get_db()
    res = wr.api_session_end(conn, sid, {})
    assert res["ok"] is True
    assert conn.execute(
        "SELECT status FROM sessions WHERE id=?", (sid,)
    ).fetchone()["status"] == "ended"


def test_session_delete_whole(session_tree):
    sid = session_tree[0]
    conn = get_db()
    # Soft delete by default — session row stays (trashed), then purge removes it.
    assert wr.api_session_delete(conn, sid, {})["ok"] is True
    assert conn.execute(
        "SELECT deleted_at FROM sessions WHERE id=?", (sid,),
    ).fetchone()["deleted_at"] is not None
    assert wr.api_session_delete(conn, sid, {"permanent": True})["ok"] is True
    assert conn.execute("SELECT id FROM sessions WHERE id=?", (sid,)).fetchone() is None


def test_session_delete_missing(db_conn):
    assert wr.api_session_delete(db_conn, "nope", {}) == {"error": "not found"}
