"""Tests for exptrack/core/db.py — schema, connections, deletion, rename, finish."""
import os
import sys
import tempfile
from pathlib import Path


def _reset_config():
    """Reset cached config so each test starts fresh."""
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None


def test_get_db_returns_wal_mode():
    """get_db() returns a connection with WAL journal mode and Row factory."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core.db import get_db
        conn = get_db()

        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal", f"Expected WAL mode, got {mode}"

        # Row factory should be set
        row = conn.execute("SELECT 1 as val").fetchone()
        assert row["val"] == 1, "Row factory not set — can't access by column name"

        print("  [PASS] test_get_db_returns_wal_mode")


def test_schema_creates_all_tables():
    """_ensure_schema creates all 7 expected tables."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core.db import get_db
        conn = get_db()

        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        expected = {"experiments", "params", "metrics", "artifacts",
                    "timeline", "cell_lineage", "code_baselines"}
        missing = expected - tables
        assert not missing, f"Missing tables: {missing}"

        print("  [PASS] test_schema_creates_all_tables")


def test_schema_has_expected_indexes():
    """Schema creates indexes on key columns."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core.db import get_db
        conn = get_db()

        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}

        # Check a few critical indexes exist
        expected_indexes = {"idx_metrics_exp", "idx_params_exp",
                            "idx_exp_created", "idx_exp_status",
                            "idx_artifacts_exp", "idx_timeline_exp_seq"}
        missing = expected_indexes - indexes
        assert not missing, f"Missing indexes: {missing}"

        print("  [PASS] test_schema_has_expected_indexes")


def test_artifacts_has_content_hash_column():
    """Migration adds content_hash and size_bytes columns to artifacts."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core.db import get_db
        conn = get_db()

        cols = {r[1] for r in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        assert "content_hash" in cols, "content_hash column missing from artifacts"
        assert "size_bytes" in cols, "size_bytes column missing from artifacts"
        assert "timeline_seq" in cols, "timeline_seq column missing from artifacts"

        print("  [PASS] test_artifacts_has_content_hash_column")


def test_delete_experiment_cascades():
    """delete_experiment removes rows from all related tables."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db
        from exptrack.core.db import delete_experiment

        exp = Experiment(script="train.py")
        exp.log_param("lr", 0.01)
        exp.log_metric("loss", 0.5, step=1)
        exp.log_event("cell_exec", key="cell_1", value={"source_preview": "x=1"})

        # Create an artifact file
        f = Path("output.csv")
        f.write_text("a,b\n1,2\n")
        exp.log_file(str(f))
        exp.finish()

        eid = exp.id

        # Verify data exists before deletion
        with get_db() as conn:
            assert conn.execute("SELECT COUNT(*) as c FROM params WHERE exp_id=?", (eid,)).fetchone()["c"] > 0
            assert conn.execute("SELECT COUNT(*) as c FROM metrics WHERE exp_id=?", (eid,)).fetchone()["c"] > 0
            assert conn.execute("SELECT COUNT(*) as c FROM artifacts WHERE exp_id=?", (eid,)).fetchone()["c"] > 0
            assert conn.execute("SELECT COUNT(*) as c FROM timeline WHERE exp_id=?", (eid,)).fetchone()["c"] > 0

        # Delete
        with get_db() as conn:
            delete_experiment(conn, eid, delete_files=True)
            conn.commit()

        # Verify all gone
        with get_db() as conn:
            for table in ("experiments", "params", "metrics", "artifacts", "timeline"):
                col_name = "id" if table == "experiments" else "exp_id"
                count = conn.execute(
                    f"SELECT COUNT(*) as c FROM {table} WHERE {col_name}=?", (eid,)
                ).fetchone()["c"]
                assert count == 0, f"Expected 0 rows in {table}, got {count}"

        print("  [PASS] test_delete_experiment_cascades")


def test_rename_output_folder():
    """rename_output_folder moves directory and updates artifact paths."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db
        from exptrack.core.db import rename_output_folder

        exp = Experiment(script="train.py")
        old_name = exp.name

        # Create output directory with a file
        conf = cfg.load()
        outputs_base = cfg.project_root() / conf.get("outputs_dir", "outputs")
        old_dir = outputs_base / old_name
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "model.pt").write_bytes(b"weights")

        # Log the artifact
        exp.log_artifact(str(old_dir / "model.pt"), label="model")
        exp.finish()

        new_name = "renamed_experiment"
        with get_db() as conn:
            rename_output_folder(conn, exp.id, old_name, new_name)
            conn.commit()

        new_dir = outputs_base / new_name
        assert new_dir.exists(), "New directory should exist after rename"
        assert not old_dir.exists(), "Old directory should not exist after rename"
        assert (new_dir / "model.pt").exists(), "File should exist in new directory"

        # Artifact paths should be updated
        with get_db() as conn:
            rows = conn.execute(
                "SELECT path FROM artifacts WHERE exp_id=?", (exp.id,)
            ).fetchall()
        paths = [r["path"] for r in rows]
        updated = [p for p in paths if new_name in p and "model.pt" in p]
        assert len(updated) > 0, f"Expected artifact path updated with new name, got {paths}"

        print("  [PASS] test_rename_output_folder")


def test_finish_experiment_by_prefix():
    """finish_experiment marks a running experiment as done using prefix match."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db
        from exptrack.core.db import finish_experiment

        exp = Experiment(script="train.py")
        eid = exp.id

        # Should be running
        with get_db() as conn:
            row = conn.execute("SELECT status FROM experiments WHERE id=?", (eid,)).fetchone()
        assert row["status"] == "running", f"Expected 'running', got {row['status']}"

        # Finish using prefix
        result = finish_experiment(eid[:6])
        assert result is True, "finish_experiment should return True"

        with get_db() as conn:
            row = conn.execute("SELECT status, duration_s FROM experiments WHERE id=?", (eid,)).fetchone()
        assert row["status"] == "done", f"Expected 'done', got {row['status']}"
        assert row["duration_s"] is not None, "duration_s should be set"
        assert row["duration_s"] >= 0, "duration_s should be non-negative"

        print("  [PASS] test_finish_experiment_by_prefix")


def test_finish_experiment_already_done():
    """finish_experiment returns False if experiment is already done."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment
        from exptrack.core.db import finish_experiment

        exp = Experiment(script="train.py")
        exp.finish()

        result = finish_experiment(exp.id)
        assert result is False, "finish_experiment should return False for already-done exp"

        print("  [PASS] test_finish_experiment_already_done")


def test_finish_experiment_not_found():
    """finish_experiment returns False for nonexistent ID."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        # Force schema creation by opening DB
        from exptrack.core.db import finish_experiment, get_db
        get_db()

        result = finish_experiment("nonexistent_id_12345")
        assert result is False, "finish_experiment should return False for unknown ID"

        print("  [PASS] test_finish_experiment_not_found")


if __name__ == "__main__":
    saved_cwd = os.getcwd()
    tests = [
        test_get_db_returns_wal_mode,
        test_schema_creates_all_tables,
        test_schema_has_expected_indexes,
        test_artifacts_has_content_hash_column,
        test_delete_experiment_cascades,
        test_rename_output_folder,
        test_finish_experiment_by_prefix,
        test_finish_experiment_already_done,
        test_finish_experiment_not_found,
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
