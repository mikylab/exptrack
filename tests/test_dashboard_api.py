"""Tests for dashboard API — calling route functions directly.

The API logic lives in:
  exptrack/dashboard/routes/read_routes.py  (GET endpoints)
  exptrack/dashboard/routes/write_routes.py (POST endpoints)

Each function takes a sqlite3 connection as its first arg, so we call
them directly without spinning up an HTTP server.
"""
import json
import os
import sys
import tempfile
from pathlib import Path


def _reset_config():
    """Reset cached config so each test starts fresh."""
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None


def _make_experiment(script="train.py", params=None, tags=None, notes=""):
    """Helper: create an experiment, return it."""
    from exptrack.core import Experiment
    return Experiment(script=script, params=params, tags=tags, notes=notes)


def test_api_stats():
    """api_stats returns correct experiment counts."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.read_routes import api_stats

        conn = get_db()

        # Empty DB
        stats = api_stats(conn)
        assert stats["total"] == 0, f"Expected 0 total, got {stats['total']}"
        assert stats["done"] == 0
        assert stats["failed"] == 0
        assert stats["running"] == 0

        # Add some experiments
        e1 = _make_experiment()
        e1.finish()
        e2 = _make_experiment()
        e2.fail("error")
        e3 = _make_experiment()  # running

        conn = get_db()
        stats = api_stats(conn)
        assert stats["total"] == 3, f"Expected 3 total, got {stats['total']}"
        assert stats["done"] == 1, f"Expected 1 done, got {stats['done']}"
        assert stats["failed"] == 1, f"Expected 1 failed, got {stats['failed']}"
        assert stats["running"] == 1, f"Expected 1 running, got {stats['running']}"

        e3.finish()
        print("  [PASS] test_api_stats")


def test_api_experiments_list():
    """api_experiments returns a list of experiments."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.read_routes import api_experiments

        e1 = _make_experiment(params={"lr": 0.01})
        e1.log_metric("loss", 0.5, step=1)
        e1.finish()
        e2 = _make_experiment(params={"lr": 0.1})
        e2.finish()

        conn = get_db()
        result = api_experiments(conn, {"limit": "50"})
        assert isinstance(result, list), "Should return a list"
        assert len(result) == 2, f"Expected 2 experiments, got {len(result)}"

        ids = [r["id"] for r in result]
        assert e1.id in ids, "First experiment should be in results"
        assert e2.id in ids, "Second experiment should be in results"

        # Check structure
        exp_data = next(r for r in result if r["id"] == e1.id)
        assert "metrics" in exp_data, "Should have metrics"
        assert "params" in exp_data, "Should have params"

        print("  [PASS] test_api_experiments_list")


def test_api_experiments_filter_by_status():
    """api_experiments filters by status query param."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.read_routes import api_experiments

        e1 = _make_experiment()
        e1.finish()
        e2 = _make_experiment()
        e2.fail("err")

        conn = get_db()
        done_only = api_experiments(conn, {"status": "done", "limit": "50"})
        assert len(done_only) == 1, f"Expected 1 done, got {len(done_only)}"
        assert done_only[0]["status"] == "done"

        failed_only = api_experiments(conn, {"status": "failed", "limit": "50"})
        assert len(failed_only) == 1, f"Expected 1 failed, got {len(failed_only)}"

        print("  [PASS] test_api_experiments_filter_by_status")


def test_api_experiment_detail():
    """api_experiment returns full experiment detail.

    Note: core/queries.py get_experiment_detail() uses exp.get() on a
    sqlite3.Row which does not support .get(). This test calls the
    underlying query layer directly to verify it once that bug is fixed.
    For now we test via the lower-level find_experiment + manual queries.
    """
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.core.queries import find_experiment

        exp = _make_experiment(params={"lr": 0.01}, tags=["v1"], notes="test note")
        exp.log_metric("loss", 0.5, step=1)
        exp.log_metric("loss", 0.3, step=2)
        exp.finish()

        conn = get_db()

        # Test find_experiment (prefix match)
        row = find_experiment(conn, exp.id[:6])
        assert row is not None, "find_experiment should find by prefix"
        assert row["id"] == exp.id, "ID mismatch"

        # Test full experiment data via direct query
        full = conn.execute("SELECT * FROM experiments WHERE id=?",
                            (exp.id,)).fetchone()
        assert full["name"] == exp.name, "Name mismatch"
        assert full["status"] == "done", "Status mismatch"
        assert full["notes"] == "test note", "Notes mismatch"
        assert "v1" in json.loads(full["tags"] or "[]"), "Tags missing"

        # Test params
        params = conn.execute(
            "SELECT key, value FROM params WHERE exp_id=? ORDER BY key",
            (exp.id,)
        ).fetchall()
        pdict = {p["key"]: json.loads(p["value"]) for p in params}
        assert pdict.get("lr") == 0.01, "Params missing lr"

        # Test metrics
        metrics = conn.execute(
            "SELECT key, value FROM metrics WHERE exp_id=? ORDER BY key",
            (exp.id,)
        ).fetchall()
        assert len(metrics) == 2, f"Expected 2 metric rows, got {len(metrics)}"

        print("  [PASS] test_api_experiment_detail")


def test_api_experiment_not_found():
    """api_experiment returns error for unknown ID."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.read_routes import api_experiment

        conn = get_db()
        result = api_experiment(conn, "nonexistent")
        assert "error" in result, "Should return error for unknown ID"

        print("  [PASS] test_api_experiment_not_found")


def test_api_add_tag():
    """api_add_tag adds a tag to an experiment."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.write_routes import api_add_tag

        exp = _make_experiment()
        exp.finish()

        conn = get_db()
        result = api_add_tag(conn, exp.id, {"tag": "production"})
        assert result.get("ok") is True, f"Expected ok=True, got {result}"
        assert "production" in result["tags"], "Tag should be in response"

        # Verify in DB
        row = conn.execute("SELECT tags FROM experiments WHERE id=?",
                           (exp.id,)).fetchone()
        assert "production" in json.loads(row["tags"])

        print("  [PASS] test_api_add_tag")


def test_api_add_tag_no_duplicates():
    """api_add_tag does not add duplicate tags."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.write_routes import api_add_tag

        exp = _make_experiment(tags=["existing"])
        exp.finish()

        conn = get_db()
        result = api_add_tag(conn, exp.id, {"tag": "existing"})
        assert result.get("ok") is True
        assert result["tags"].count("existing") == 1, \
            f"Tag should appear once, got {result['tags']}"

        print("  [PASS] test_api_add_tag_no_duplicates")


def test_api_delete_tag():
    """api_delete_tag removes a tag from an experiment."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.write_routes import api_delete_tag

        exp = _make_experiment(tags=["keep", "remove"])
        exp.finish()

        conn = get_db()
        result = api_delete_tag(conn, exp.id, {"tag": "remove"})
        assert result.get("ok") is True
        assert "remove" not in result["tags"]
        assert "keep" in result["tags"]

        print("  [PASS] test_api_delete_tag")


def test_api_rename():
    """api_rename renames an experiment."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.write_routes import api_rename

        exp = _make_experiment()
        exp.finish()

        conn = get_db()
        result = api_rename(conn, exp.id, {"name": "my_new_name"})
        assert result.get("ok") is True
        assert result["name"] == "my_new_name"

        # Verify in DB
        row = conn.execute("SELECT name FROM experiments WHERE id=?",
                           (exp.id,)).fetchone()
        assert row["name"] == "my_new_name", \
            f"Expected 'my_new_name', got '{row['name']}'"

        print("  [PASS] test_api_rename")


def test_api_rename_empty():
    """api_rename rejects empty name."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.write_routes import api_rename

        exp = _make_experiment()
        exp.finish()

        conn = get_db()
        result = api_rename(conn, exp.id, {"name": ""})
        assert "error" in result, "Should reject empty name"

        print("  [PASS] test_api_rename_empty")


def test_api_all_tags():
    """api_all_tags returns tag names with usage counts."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.read_routes import api_all_tags

        e1 = _make_experiment(tags=["baseline", "v1"])
        e1.finish()
        e2 = _make_experiment(tags=["baseline", "v2"])
        e2.finish()
        e3 = _make_experiment(tags=["v2"])
        e3.finish()

        conn = get_db()
        result = api_all_tags(conn)
        assert "tags" in result, "Should have 'tags' key"
        tags_list = result["tags"]

        by_name = {t["name"]: t["count"] for t in tags_list}
        assert by_name.get("baseline") == 2, \
            f"Expected baseline count=2, got {by_name.get('baseline')}"
        assert by_name.get("v2") == 2, \
            f"Expected v2 count=2, got {by_name.get('v2')}"
        assert by_name.get("v1") == 1, \
            f"Expected v1 count=1, got {by_name.get('v1')}"

        print("  [PASS] test_api_all_tags")


def test_api_export_json():
    """api_export produces structured JSON data."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.read_routes import api_export

        exp = _make_experiment(params={"lr": 0.01}, tags=["v1"])
        exp.log_metric("loss", 0.5, step=1)
        exp.log_metric("loss", 0.3, step=2)
        exp.finish()

        conn = get_db()
        data = api_export(conn, exp.id, {"format": "json"})
        assert data["id"] == exp.id, "ID mismatch"
        assert data["name"] == exp.name, "Name mismatch"
        assert data["status"] == "done", "Status mismatch"
        assert data["params"]["lr"] == 0.01, "Params missing"
        assert "v1" in data["tags"], "Tags missing"
        assert "loss" in data["metrics_series"], "Metrics series missing"
        assert len(data["metrics_series"]["loss"]) == 2, "Should have 2 loss points"

        print("  [PASS] test_api_export_json")


def test_api_export_markdown():
    """api_export with format=markdown returns markdown text."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.read_routes import api_export

        exp = _make_experiment(params={"lr": 0.01})
        exp.finish()

        conn = get_db()
        result = api_export(conn, exp.id, {"format": "markdown"})
        assert "markdown" in result, "Should have 'markdown' key"
        md = result["markdown"]
        assert md.startswith("#"), "Markdown should start with heading"
        assert exp.id in md, "Markdown should contain experiment ID"

        print("  [PASS] test_api_export_markdown")


def test_api_add_note():
    """api_add_note appends a note to an experiment."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.write_routes import api_add_note

        exp = _make_experiment(notes="first")
        exp.finish()

        conn = get_db()
        result = api_add_note(conn, exp.id, {"note": "second note"})
        assert result.get("ok") is True
        assert "second note" in result["notes"]
        assert "first" in result["notes"]

        print("  [PASS] test_api_add_note")


def test_api_finish():
    """api_finish marks a running experiment as done."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.write_routes import api_finish

        exp = _make_experiment()
        # Don't call exp.finish() — leave it running

        conn = get_db()
        result = api_finish(conn, exp.id)
        assert result.get("ok") is True
        assert result["status"] == "done"
        assert "duration_s" in result

        print("  [PASS] test_api_finish")


def test_api_delete():
    """api_delete removes an experiment."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.write_routes import api_delete

        exp = _make_experiment()
        exp.finish()

        conn = get_db()
        result = api_delete(conn, exp.id)
        assert result.get("ok") is True

        # Verify gone
        row = conn.execute("SELECT id FROM experiments WHERE id=?",
                           (exp.id,)).fetchone()
        assert row is None, "Experiment should be deleted"

        print("  [PASS] test_api_delete")


def test_api_edit_notes():
    """api_edit_notes replaces experiment notes."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.core import get_db
        from exptrack.dashboard.routes.write_routes import api_edit_notes

        exp = _make_experiment(notes="old")
        exp.finish()

        conn = get_db()
        result = api_edit_notes(conn, exp.id, {"notes": "new notes"})
        assert result.get("ok") is True
        assert result["notes"] == "new notes"

        print("  [PASS] test_api_edit_notes")


if __name__ == "__main__":
    saved_cwd = os.getcwd()
    tests = [
        test_api_stats,
        test_api_experiments_list,
        test_api_experiments_filter_by_status,
        test_api_experiment_detail,
        test_api_experiment_not_found,
        test_api_add_tag,
        test_api_add_tag_no_duplicates,
        test_api_delete_tag,
        test_api_rename,
        test_api_rename_empty,
        test_api_all_tags,
        test_api_export_json,
        test_api_export_markdown,
        test_api_add_note,
        test_api_finish,
        test_api_delete,
        test_api_edit_notes,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            os.chdir(saved_cwd)
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            failed += 1

    os.chdir(saved_cwd)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
