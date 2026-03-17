"""Tests for exptrack/core/experiment.py — Experiment class lifecycle."""
import json
import os
import sys
import tempfile


def _reset_config():
    """Reset cached config so each test starts fresh."""
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None


def test_create_writes_to_db():
    """Creating an Experiment inserts a row into the experiments table."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py")

        with get_db() as conn:
            row = conn.execute("SELECT * FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()

        assert row is not None, "Experiment row not found in DB"
        assert row["status"] == "running", f"Expected 'running', got {row['status']}"
        assert row["name"] == exp.name, "Name mismatch"
        assert row["id"] == exp.id, "ID mismatch"

        exp.finish()
        print("  [PASS] test_create_writes_to_db")


def test_log_param():
    """log_param stores a single parameter."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py")
        exp.log_param("lr", 0.01)

        with get_db() as conn:
            row = conn.execute(
                "SELECT value FROM params WHERE exp_id=? AND key=?",
                (exp.id, "lr")
            ).fetchone()

        assert row is not None, "Param not found"
        assert json.loads(row["value"]) == 0.01, \
            f"Expected 0.01, got {json.loads(row['value'])}"

        exp.finish()
        print("  [PASS] test_log_param")


def test_log_params():
    """log_params stores multiple parameters at once."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py")
        exp.log_params({"lr": 0.01, "batch_size": 32, "epochs": 10})

        with get_db() as conn:
            rows = conn.execute(
                "SELECT key, value FROM params WHERE exp_id=? ORDER BY key",
                (exp.id,)
            ).fetchall()

        params = {r["key"]: json.loads(r["value"]) for r in rows}
        assert "lr" in params, "lr param missing"
        assert "batch_size" in params, "batch_size param missing"
        assert "epochs" in params, "epochs param missing"
        assert params["lr"] == 0.01
        assert params["batch_size"] == 32
        assert params["epochs"] == 10

        exp.finish()
        print("  [PASS] test_log_params")


def test_log_metric_with_step():
    """log_metric stores a metric with step number."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py")
        exp.log_metric("loss", 0.5, step=1)
        exp.log_metric("loss", 0.3, step=2)
        exp.log_metric("loss", 0.1, step=3)

        with get_db() as conn:
            rows = conn.execute(
                "SELECT value, step FROM metrics WHERE exp_id=? AND key='loss' ORDER BY step",
                (exp.id,)
            ).fetchall()

        assert len(rows) == 3, f"Expected 3 metric rows, got {len(rows)}"
        assert rows[0]["value"] == 0.5
        assert rows[1]["value"] == 0.3
        assert rows[2]["value"] == 0.1
        assert rows[0]["step"] == 1
        assert rows[2]["step"] == 3

        exp.finish()
        print("  [PASS] test_log_metric_with_step")


def test_log_metrics_batch():
    """log_metrics inserts multiple metrics in one call."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py")
        exp.log_metrics({"loss": 0.5, "acc": 0.9}, step=1)

        with get_db() as conn:
            rows = conn.execute(
                "SELECT key, value, step FROM metrics WHERE exp_id=? ORDER BY key",
                (exp.id,)
            ).fetchall()

        by_key = {r["key"]: r["value"] for r in rows}
        assert "loss" in by_key, "loss metric missing"
        assert "acc" in by_key, "acc metric missing"
        assert by_key["loss"] == 0.5
        assert by_key["acc"] == 0.9

        exp.finish()
        print("  [PASS] test_log_metrics_batch")


def test_last_metrics():
    """last_metrics returns the latest value per metric key."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment

        exp = Experiment(script="train.py")
        exp.log_metric("loss", 0.5, step=1)
        exp.log_metric("loss", 0.3, step=2)
        exp.log_metric("loss", 0.1, step=3)
        exp.log_metric("acc", 0.8, step=1)
        exp.log_metric("acc", 0.95, step=2)

        last = exp.last_metrics()
        assert "loss" in last, "loss missing from last_metrics"
        assert "acc" in last, "acc missing from last_metrics"
        assert last["loss"] == 0.1, f"Expected loss=0.1, got {last['loss']}"
        assert last["acc"] == 0.95, f"Expected acc=0.95, got {last['acc']}"

        exp.finish()
        print("  [PASS] test_last_metrics")


def test_finish_sets_done():
    """finish() sets status='done' and records duration."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py")
        exp.finish()

        assert exp.status == "done", f"Expected status 'done', got {exp.status}"
        assert exp.duration_s is not None, "duration_s should be set"
        assert exp.duration_s >= 0, "duration_s should be non-negative"

        with get_db() as conn:
            row = conn.execute("SELECT status, duration_s FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        assert row["status"] == "done", f"DB status: expected 'done', got {row['status']}"
        assert row["duration_s"] is not None, "DB duration_s should be set"

        print("  [PASS] test_finish_sets_done")


def test_fail_sets_failed():
    """fail() sets status='failed' and logs error as param."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py")
        exp.fail("OOM error")

        assert exp.status == "failed", f"Expected 'failed', got {exp.status}"

        with get_db() as conn:
            row = conn.execute("SELECT status FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
            param = conn.execute(
                "SELECT value FROM params WHERE exp_id=? AND key='error'",
                (exp.id,)
            ).fetchone()

        assert row["status"] == "failed"
        assert param is not None, "Error param should be logged"
        assert json.loads(param["value"]) == "OOM error"

        print("  [PASS] test_fail_sets_failed")


def test_context_manager_finish():
    """Context manager calls finish() on normal exit."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        with Experiment(script="train.py") as exp:
            exp.log_metric("loss", 0.1)
            eid = exp.id

        with get_db() as conn:
            row = conn.execute("SELECT status FROM experiments WHERE id=?",
                               (eid,)).fetchone()
        assert row["status"] == "done", f"Expected 'done', got {row['status']}"

        print("  [PASS] test_context_manager_finish")


def test_context_manager_fail_on_exception():
    """Context manager calls fail() when exception is raised."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        eid = None
        try:
            with Experiment(script="train.py") as exp:
                eid = exp.id
                raise ValueError("test error")
        except ValueError:
            pass

        assert eid is not None, "Experiment ID should have been set"

        with get_db() as conn:
            row = conn.execute("SELECT status FROM experiments WHERE id=?",
                               (eid,)).fetchone()
        assert row["status"] == "failed", f"Expected 'failed', got {row['status']}"

        print("  [PASS] test_context_manager_fail_on_exception")


def test_add_tag():
    """add_tag adds a tag to the experiment."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py")
        exp.add_tag("baseline")
        exp.add_tag("v1")

        assert "baseline" in exp.tags, "Tag 'baseline' missing from exp.tags"
        assert "v1" in exp.tags, "Tag 'v1' missing from exp.tags"

        with get_db() as conn:
            row = conn.execute("SELECT tags FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        db_tags = json.loads(row["tags"])
        assert "baseline" in db_tags, "Tag 'baseline' missing from DB"
        assert "v1" in db_tags, "Tag 'v1' missing from DB"

        exp.finish()
        print("  [PASS] test_add_tag")


def test_add_tag_no_duplicates():
    """add_tag does not add the same tag twice."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment

        exp = Experiment(script="train.py")
        exp.add_tag("dup")
        exp.add_tag("dup")

        assert exp.tags.count("dup") == 1, \
            f"Expected tag 'dup' once, got {exp.tags.count('dup')} times"

        exp.finish()
        print("  [PASS] test_add_tag_no_duplicates")


def test_remove_tag():
    """remove_tag removes a tag from the experiment."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py", tags=["a", "b", "c"])
        exp.remove_tag("b")

        assert "b" not in exp.tags, "Tag 'b' should be removed"
        assert "a" in exp.tags, "Tag 'a' should remain"
        assert "c" in exp.tags, "Tag 'c' should remain"

        with get_db() as conn:
            row = conn.execute("SELECT tags FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        db_tags = json.loads(row["tags"])
        assert "b" not in db_tags, "Tag 'b' should be removed from DB"

        exp.finish()
        print("  [PASS] test_remove_tag")


def test_add_note():
    """add_note appends text to existing notes."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py", notes="initial note")
        exp.add_note("second note")

        assert "initial note" in exp.notes, "Original note should remain"
        assert "second note" in exp.notes, "Appended note should be present"

        with get_db() as conn:
            row = conn.execute("SELECT notes FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        assert "initial note" in row["notes"], "DB: original note missing"
        assert "second note" in row["notes"], "DB: appended note missing"

        exp.finish()
        print("  [PASS] test_add_note")


def test_set_note():
    """set_note replaces the entire notes text."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py", notes="old note")
        exp.set_note("new note")

        assert exp.notes == "new note", f"Expected 'new note', got '{exp.notes}'"

        with get_db() as conn:
            row = conn.execute("SELECT notes FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        assert row["notes"] == "new note", f"DB notes: expected 'new note', got '{row['notes']}'"

        exp.finish()
        print("  [PASS] test_set_note")


def test_init_with_params():
    """Experiment created with initial params stores them."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py", params={"lr": 0.01, "epochs": 10})

        with get_db() as conn:
            rows = conn.execute(
                "SELECT key, value FROM params WHERE exp_id=?", (exp.id,)
            ).fetchall()
        params = {r["key"]: json.loads(r["value"]) for r in rows}
        assert params.get("lr") == 0.01, f"Expected lr=0.01, got {params.get('lr')}"
        assert params.get("epochs") == 10, f"Expected epochs=10, got {params.get('epochs')}"

        exp.finish()
        print("  [PASS] test_init_with_params")


def test_log_event_timeline():
    """log_event adds entries to the timeline table."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db

        exp = Experiment(script="train.py")
        seq1 = exp.log_event("var_set", key="lr", value=0.01)
        seq2 = exp.log_event("var_set", key="lr", value=0.001, prev_value=0.01)

        assert seq1 == 1, f"First event should be seq=1, got {seq1}"
        assert seq2 == 2, f"Second event should be seq=2, got {seq2}"

        with get_db() as conn:
            rows = conn.execute(
                "SELECT seq, event_type, key, value FROM timeline WHERE exp_id=? ORDER BY seq",
                (exp.id,)
            ).fetchall()
        assert len(rows) == 2, f"Expected 2 timeline rows, got {len(rows)}"
        assert rows[0]["key"] == "lr"
        assert json.loads(rows[0]["value"]) == 0.01

        exp.finish()
        print("  [PASS] test_log_event_timeline")


if __name__ == "__main__":
    saved_cwd = os.getcwd()
    tests = [
        test_create_writes_to_db,
        test_log_param,
        test_log_params,
        test_log_metric_with_step,
        test_log_metrics_batch,
        test_last_metrics,
        test_finish_sets_done,
        test_fail_sets_failed,
        test_context_manager_finish,
        test_context_manager_fail_on_exception,
        test_add_tag,
        test_add_tag_no_duplicates,
        test_remove_tag,
        test_add_note,
        test_set_note,
        test_init_with_params,
        test_log_event_timeline,
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
