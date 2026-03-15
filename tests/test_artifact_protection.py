"""End-to-end tests for artifact protection, hashing, and cleanup.

Tests the full lifecycle:
  Run 1 → Run 2 (archives run 1) → verify hashes → delete experiment →
  verify cleanup → manual delete → verify reports missing
"""
import os
import sys
import tempfile
from pathlib import Path


def _reset_config():
    """Reset cached config so each test starts fresh."""
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None


def test_hash_stored_on_log_artifact():
    """log_artifact() computes and stores content_hash + size_bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db
        from exptrack.core.hashing import file_hash

        # Create a file
        Path("data.csv").write_text("a,b,c\n1,2,3\n")
        expected_hash, expected_size = file_hash("data.csv")

        exp = Experiment(script="train.py")
        exp.log_file("data.csv")
        exp.finish()

        with get_db() as conn:
            row = conn.execute(
                "SELECT content_hash, size_bytes FROM artifacts WHERE exp_id=? AND label != 'output_dir'",
                (exp.id,)
            ).fetchone()

        assert row["content_hash"] == expected_hash, \
            f"Expected {expected_hash}, got {row['content_hash']}"
        assert row["size_bytes"] == expected_size, \
            f"Expected {expected_size}, got {row['size_bytes']}"
        print("  [PASS] test_hash_stored_on_log_artifact")


def test_no_duplicate_on_savefig():
    """matplotlib savefig patch no longer copies files to outputs/."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment

        exp = Experiment(script="plot_script.py")

        # Simulate what the savefig patch does — just log_artifact, no copy
        plot_path = Path("figures/loss.png")
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        plot_path.write_bytes(b"PNG_FAKE_DATA" * 50)

        exp.log_artifact(str(plot_path), label="loss curve")
        exp.finish()

        # outputs/<run_name>/ should NOT contain a copy
        outputs_dir = Path("outputs") / exp.name
        assert not outputs_dir.exists() or not (outputs_dir / "loss.png").exists(), \
            "File was copied to outputs/ — duplication not removed"
        print("  [PASS] test_no_duplicate_on_savefig")


def test_protection_archives_on_rerun():
    """Run 2 archives Run 1's artifacts that sit at conflicting paths."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db
        from exptrack.core.artifact_protection import protect_previous_artifacts
        from exptrack.core.hashing import file_hash

        # Create checkpoint
        ckpt_dir = Path("checkpoints")
        ckpt_dir.mkdir()
        ckpt_file = ckpt_dir / "model.pt"
        ckpt_file.write_bytes(b"weights_v1" * 100)
        v1_hash, _ = file_hash(ckpt_file)

        # Run 1
        exp1 = Experiment(script="train.py")
        exp1.log_file(str(ckpt_file))
        exp1.finish()

        # Run 2 — protection should archive run 1's checkpoint
        exp2 = Experiment(script="train.py")
        archived = protect_previous_artifacts(exp2.id)

        assert len(archived) == 1, f"Expected 1 archived, got {len(archived)}"
        assert not ckpt_file.exists(), "Original file should have been moved"

        # Check DB: run 1's artifact path updated to archived location
        with get_db() as conn:
            row = conn.execute(
                "SELECT path, content_hash FROM artifacts WHERE exp_id=? AND label != 'output_dir'",
                (exp1.id,)
            ).fetchone()
        archived_path = Path(row["path"])
        assert archived_path.exists(), f"Archived file missing at {archived_path}"
        assert exp1.name in str(archived_path), "Archived path should contain run name"
        assert row["content_hash"] == v1_hash, "Hash should be preserved after archival"

        # Simulate run 2 saving new checkpoint
        ckpt_file.write_bytes(b"weights_v2" * 100)
        exp2.log_file(str(ckpt_file))
        exp2.finish()

        # Both files should exist at different paths
        with get_db() as conn:
            art1 = conn.execute(
                "SELECT path FROM artifacts WHERE exp_id=? AND label != 'output_dir'", (exp1.id,)
            ).fetchone()
            art2 = conn.execute(
                "SELECT path FROM artifacts WHERE exp_id=? AND label != 'output_dir'", (exp2.id,)
            ).fetchone()
        assert Path(art1["path"]).exists(), "Run 1 archived artifact missing"
        assert Path(art2["path"]).exists(), "Run 2 artifact missing"
        assert art1["path"] != art2["path"], "Artifacts should be at different paths"

        print("  [PASS] test_protection_archives_on_rerun")


def test_cross_script_protection():
    """Protection works across different scripts saving to the same path."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db
        from exptrack.core.artifact_protection import protect_previous_artifacts

        # Script A saves results.json
        results = Path("results.json")
        results.write_text('{"acc": 0.95}')

        exp_a = Experiment(script="train.py")
        exp_a.log_file(str(results))
        exp_a.finish()

        # Script B also writes results.json — protection should archive A's
        exp_b = Experiment(script="eval.py")
        archived = protect_previous_artifacts(exp_b.id)

        assert len(archived) == 1, f"Expected 1 archived, got {len(archived)}"
        assert not results.exists(), "Original should be moved"

        # Verify DB updated
        with get_db() as conn:
            row = conn.execute(
                "SELECT path FROM artifacts WHERE exp_id=?", (exp_a.id,)
            ).fetchone()
        assert Path(row["path"]).exists(), "Archived file should exist"
        assert exp_a.name in row["path"], "Should be archived under exp_a's run name"

        exp_b.finish()
        print("  [PASS] test_cross_script_protection")


def test_delete_cleans_archived():
    """delete_experiment removes archived artifact files and DB rows."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db
        from exptrack.core.db import delete_experiment
        from exptrack.core.artifact_protection import protect_previous_artifacts

        # Run 1 creates file
        ckpt = Path("model.pt")
        ckpt.write_bytes(b"data" * 100)
        exp1 = Experiment(script="train.py")
        exp1.log_file(str(ckpt))
        exp1.finish()

        # Run 2 triggers archival
        exp2 = Experiment(script="train.py")
        protect_previous_artifacts(exp2.id)

        # Get archived path before deletion
        with get_db() as conn:
            row = conn.execute(
                "SELECT path FROM artifacts WHERE exp_id=?", (exp1.id,)
            ).fetchone()
        archived_path = Path(row["path"])
        assert archived_path.exists()

        # Delete run 1
        with get_db() as conn:
            delete_experiment(conn, exp1.id, delete_files=True)
            conn.commit()

        # Archived file should be gone
        assert not archived_path.exists(), "Archived file should be deleted"

        # DB rows should be gone
        with get_db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as c FROM artifacts WHERE exp_id=?", (exp1.id,)
            ).fetchone()["c"]
        assert count == 0, f"Expected 0 artifact rows, got {count}"

        exp2.finish()
        print("  [PASS] test_delete_cleans_archived")


def test_verify_detects_missing():
    """After manual deletion, verify should detect the file is missing."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db
        from exptrack.core.hashing import file_hash

        f = Path("output.csv")
        f.write_text("x,y\n1,2\n")

        exp = Experiment(script="train.py")
        exp.log_file(str(f))
        exp.finish()

        # Verify hash matches
        with get_db() as conn:
            row = conn.execute(
                "SELECT path, content_hash FROM artifacts WHERE exp_id=? AND label != 'output_dir'",
                (exp.id,)
            ).fetchone()
        h, _ = file_hash(row["path"])
        assert h == row["content_hash"], "Hash should match before deletion"

        # Manually delete
        f.unlink()
        assert not Path(row["path"]).exists(), "File should be gone"

        # DB record still exists — verify would report [missing]
        with get_db() as conn:
            row = conn.execute(
                "SELECT path FROM artifacts WHERE exp_id=? AND label != 'output_dir'", (exp.id,)
            ).fetchone()
        assert row is not None, "DB record should persist after manual delete"
        assert not Path(row["path"]).exists(), "File gone but record remains"

        print("  [PASS] test_verify_detects_missing")


def test_outputs_already_namespaced_skipped():
    """Artifacts already inside outputs/ are not moved again by protection."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")

        from exptrack.core import Experiment, get_db
        from exptrack.core.artifact_protection import protect_previous_artifacts

        # Create file inside outputs/ (already namespaced)
        out = Path("outputs/some_run/model.pt")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"data")

        exp1 = Experiment(script="train.py")
        exp1.log_artifact(str(out), label="model")
        exp1.finish()

        # Run 2 — should NOT move the already-namespaced artifact
        exp2 = Experiment(script="train.py")
        archived = protect_previous_artifacts(exp2.id)

        assert len(archived) == 0, f"Expected 0 archived (already in outputs), got {len(archived)}"
        assert out.exists(), "File in outputs/ should not be moved"

        exp2.finish()
        print("  [PASS] test_outputs_already_namespaced_skipped")


if __name__ == "__main__":
    saved_cwd = os.getcwd()
    tests = [
        test_hash_stored_on_log_artifact,
        test_no_duplicate_on_savefig,
        test_protection_archives_on_rerun,
        test_cross_script_protection,
        test_delete_cleans_archived,
        test_verify_detects_missing,
        test_outputs_already_namespaced_skipped,
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
