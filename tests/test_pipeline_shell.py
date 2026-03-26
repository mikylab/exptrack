"""Tests for shell / SLURM pipeline commands (run-start, run-finish, run-fail, etc.).

Validates that the pipeline workflow works for pure shell scripts, SLURM jobs,
and any non-Python workloads — not just Python script wrappers.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def _capture(func, *args):
    """Run func capturing stdout and stderr. Returns (stdout, stderr)."""
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = out = io.StringIO()
    sys.stderr = err = io.StringIO()
    try:
        func(*args)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return out.getvalue(), err.getvalue()


def _extract_env(stdout, key="EXP_ID"):
    """Extract an env var value from run-start stdout (export KEY="VALUE")."""
    for line in stdout.strip().split("\n"):
        if line.startswith(f"export {key}="):
            return line.split('"')[1]
    return None


def _start_exp(script="test.sh", **kwargs):
    """Start an experiment and return (exp_id, stdout).

    Pass extra SimpleNamespace fields as keyword args (e.g. study="x").
    """
    from exptrack.cli.pipeline_cmds import cmd_run_start

    defaults = dict(
        name="", script=script, tags=None, study="",
        stage=None, stage_name=None, notes="", params=[]
    )
    defaults.update(kwargs)
    args = SimpleNamespace(**defaults)
    stdout, _ = _capture(cmd_run_start, args)
    return _extract_env(stdout, "EXP_ID"), stdout


def _finish_exp(exp_id, **kwargs):
    """Finish an experiment. Pass metrics=, step=, params= as needed."""
    from exptrack.cli.pipeline_cmds import cmd_run_finish

    defaults = dict(id=exp_id, metrics=None, step=None, params=None)
    defaults.update(kwargs)
    return _capture(cmd_run_finish, SimpleNamespace(**defaults))


# ---------------------------------------------------------------------------
# run-start
# ---------------------------------------------------------------------------


class TestRunStart:
    """Test exptrack run-start — creating experiments from shell."""

    def test_basic_run_start(self, tmp_project):
        """run-start creates an experiment and prints export statements."""
        _, stdout = _start_exp("train.sh", params=["--lr", "0.01"])

        assert 'export EXP_ID=' in stdout
        assert 'export EXP_NAME=' in stdout
        assert 'export EXP_OUT=' in stdout
        assert "train" in stdout

    def test_run_start_captures_params(self, tmp_project):
        """run-start parses --key value pairs from the params list."""
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp("run.sh", params=[
            "--lr", "0.01", "--epochs", "100", "--model", "resnet"
        ])
        assert exp_id

        conn = get_db()
        rows = conn.execute(
            "SELECT key, value FROM params WHERE exp_id=?", (exp_id,)
        ).fetchall()
        params = {r["key"]: json.loads(r["value"]) for r in rows}
        assert params["lr"] == 0.01
        assert params["epochs"] == 100
        assert params["model"] == "resnet"

    def test_run_start_with_equals_syntax(self, tmp_project):
        """run-start handles --key=value syntax."""
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp(params=["--lr=0.001", "--batch-size=32"])

        conn = get_db()
        rows = conn.execute(
            "SELECT key, value FROM params WHERE exp_id=?", (exp_id,)
        ).fetchall()
        params = {r["key"]: json.loads(r["value"]) for r in rows}
        assert params["lr"] == 0.001
        assert params["batch-size"] == 32

    def test_run_start_boolean_flags(self, tmp_project):
        """run-start treats lone --flag as True."""
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp(params=["--use-gpu", "--lr", "0.01"])

        conn = get_db()
        rows = conn.execute(
            "SELECT key, value FROM params WHERE exp_id=?", (exp_id,)
        ).fetchall()
        params = {r["key"]: json.loads(r["value"]) for r in rows}
        assert params["use-gpu"] is True
        assert params["lr"] == 0.01

    def test_run_start_with_custom_name(self, tmp_project):
        """run-start respects --name override."""
        _, stdout = _start_exp(name="my-custom-run")
        assert 'my-custom-run' in stdout

    def test_run_start_with_tags(self, tmp_project):
        """run-start stores tags."""
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp("train.sh", tags=["baseline", "gpu"])

        conn = get_db()
        row = conn.execute(
            "SELECT tags FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        tags = json.loads(row["tags"])
        assert "baseline" in tags
        assert "gpu" in tags

    def test_run_start_with_notes(self, tmp_project):
        """run-start stores notes."""
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp(
            notes="Testing with larger batch size",
            params=["--batch", "128"]
        )

        conn = get_db()
        row = conn.execute(
            "SELECT notes FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        assert row["notes"] == "Testing with larger batch size"

    def test_run_start_creates_output_dir(self, tmp_project):
        """run-start creates the output directory and writes .exptrack_run.env."""
        _, stdout = _start_exp("train.sh", params=["--lr", "0.01"])

        exp_out = _extract_env(stdout, "EXP_OUT")
        assert exp_out
        assert Path(exp_out).is_dir()
        assert (Path(exp_out) / ".exptrack_run.env").is_file()

    def test_run_start_slurm_env(self, tmp_project, monkeypatch):
        """run-start captures SLURM environment variables as params."""
        from exptrack.core.db import get_db

        monkeypatch.setenv("SLURM_JOB_ID", "12345")
        monkeypatch.setenv("SLURM_JOB_NAME", "train_v2")
        monkeypatch.setenv("SLURM_NODELIST", "node[001-004]")

        exp_id, _ = _start_exp(params=["--lr", "0.01"])

        conn = get_db()
        rows = conn.execute(
            "SELECT key, value FROM params WHERE exp_id=?", (exp_id,)
        ).fetchall()
        params = {r["key"]: json.loads(r["value"]) for r in rows}

        assert "_slurm" in params
        assert params["_slurm"]["SLURM_JOB_ID"] == "12345"
        assert params["_slurm"]["SLURM_JOB_NAME"] == "train_v2"
        assert params["_slurm"]["SLURM_NODELIST"] == "node[001-004]"

    def test_run_start_slurm_naming_fallback(self, tmp_project, monkeypatch):
        """Without --script, run-start uses SLURM_JOB_NAME for naming."""
        monkeypatch.setenv("SLURM_JOB_ID", "99999")
        monkeypatch.setenv("SLURM_JOB_NAME", "my_slurm_job")

        _, stdout = _start_exp(script="", params=["--lr", "0.1"])
        assert "my_slurm_job" in _extract_env(stdout, "EXP_NAME")

    def test_run_start_study_and_stage(self, tmp_project):
        """run-start with --study and --stage groups experiments."""
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp(
            "train.sh", study="ablation-v1", stage=1, stage_name="train",
            params=["--lr", "0.01"]
        )

        conn = get_db()
        row = conn.execute(
            "SELECT studies, stage, stage_name FROM experiments WHERE id=?",
            (exp_id,)
        ).fetchone()
        studies = json.loads(row["studies"] or "[]")
        assert "ablation-v1" in studies
        assert row["stage"] == 1
        assert row["stage_name"] == "train"

    def test_run_start_exports_study_and_stage(self, tmp_project):
        """run-start exports EXP_STUDY and EXP_STAGE for subsequent calls."""
        _, stdout = _start_exp(
            "train.sh", study="my-study", stage=1, stage_name="train"
        )
        assert _extract_env(stdout, "EXP_STUDY") == "my-study"
        assert _extract_env(stdout, "EXP_STAGE") == "1"

    def test_run_start_inherits_study_from_env(self, tmp_project, monkeypatch):
        """run-start reads EXP_STUDY from env when --study is not given."""
        from exptrack.core.db import get_db

        monkeypatch.setenv("EXP_STUDY", "inherited-study")

        exp_id, stdout = _start_exp("eval.sh", stage=2, stage_name="eval")

        assert _extract_env(stdout, "EXP_STUDY") == "inherited-study"

        conn = get_db()
        row = conn.execute(
            "SELECT studies FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        studies = json.loads(row["studies"] or "[]")
        assert "inherited-study" in studies

    def test_run_start_auto_increments_stage(self, tmp_project, monkeypatch):
        """run-start auto-increments EXP_STAGE when --stage is not given."""
        from exptrack.core.db import get_db

        monkeypatch.setenv("EXP_STUDY", "auto-stage-study")
        monkeypatch.setenv("EXP_STAGE", "3")

        exp_id, stdout = _start_exp("next.sh", stage_name="postprocess")

        assert _extract_env(stdout, "EXP_STAGE") == "4"

        conn = get_db()
        row = conn.execute(
            "SELECT stage, stage_name FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        assert row["stage"] == 4
        assert row["stage_name"] == "postprocess"

    def test_run_start_explicit_study_overrides_env(self, tmp_project, monkeypatch):
        """--study flag takes precedence over EXP_STUDY env var."""
        monkeypatch.setenv("EXP_STUDY", "env-study")

        _, stdout = _start_exp(study="explicit-study", stage=1)
        assert _extract_env(stdout, "EXP_STUDY") == "explicit-study"

    def test_run_start_no_study_no_env(self, tmp_project):
        """Without --study or EXP_STUDY, no study/stage env vars are exported."""
        _, stdout = _start_exp("solo.sh")
        assert _extract_env(stdout, "EXP_STUDY") is None
        assert _extract_env(stdout, "EXP_STAGE") is None

    def test_multi_stage_wrapper_pattern(self, tmp_project, monkeypatch):
        """Simulate a wrapper script: stage 1 sets study, stage 2 inherits."""
        from exptrack.core.db import get_db

        # Stage 1: explicit --study and --stage
        id1, stdout1 = _start_exp(
            "train.sh", study="wrapper-test", stage=1, stage_name="train",
            params=["--lr", "0.01"]
        )
        _finish_exp(id1)

        # Simulate eval $() setting env vars for the next call
        monkeypatch.setenv("EXP_STUDY", _extract_env(stdout1, "EXP_STUDY"))
        monkeypatch.setenv("EXP_STAGE", _extract_env(stdout1, "EXP_STAGE"))

        # Stage 2: no --study or --stage, should inherit and auto-increment
        id2, _ = _start_exp("eval.sh", stage_name="eval")
        _finish_exp(id2)

        # Verify both are in the same study with correct stages
        conn = get_db()
        for eid, expected_stage, expected_name in [
            (id1, 1, "train"), (id2, 2, "eval")
        ]:
            row = conn.execute(
                "SELECT studies, stage, stage_name FROM experiments WHERE id=?",
                (eid,)
            ).fetchone()
            studies = json.loads(row["studies"] or "[]")
            assert "wrapper-test" in studies, f"exp {eid} not in study"
            assert row["stage"] == expected_stage, f"exp {eid} stage={row['stage']}"
            assert row["stage_name"] == expected_name


# ---------------------------------------------------------------------------
# run-finish
# ---------------------------------------------------------------------------


class TestRunFinish:
    """Test exptrack run-finish — completing experiments from shell."""

    def test_basic_finish(self, tmp_project):
        """run-finish marks the experiment as done."""
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp()
        _finish_exp(exp_id)

        conn = get_db()
        row = conn.execute(
            "SELECT status, duration_s FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        assert row["status"] == "done"
        assert row["duration_s"] is not None
        assert row["duration_s"] >= 0

    def test_finish_with_metrics_file(self, tmp_project):
        """run-finish loads metrics from a JSON file."""
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp()

        metrics_file = tmp_project / "results.json"
        metrics_file.write_text(json.dumps({
            "accuracy": 0.95,
            "loss": 0.05,
            "nested": {"val_loss": 0.08, "val_acc": 0.93}
        }))

        _, stderr = _finish_exp(exp_id, metrics=str(metrics_file))
        assert "Logged 4 metrics" in stderr

        conn = get_db()
        rows = conn.execute(
            "SELECT key, value FROM metrics WHERE exp_id=?", (exp_id,)
        ).fetchall()
        metrics = {r["key"]: r["value"] for r in rows}
        assert metrics["accuracy"] == 0.95
        assert metrics["loss"] == 0.05
        assert metrics["nested/val_loss"] == 0.08
        assert metrics["nested/val_acc"] == 0.93

    def test_finish_with_extra_params(self, tmp_project):
        """run-finish can log extra params via --params KEY=VALUE."""
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp()
        _finish_exp(exp_id, params=["best_epoch=42", "converged=true"])

        conn = get_db()
        rows = conn.execute(
            "SELECT key, value FROM params WHERE exp_id=?", (exp_id,)
        ).fetchall()
        params = {r["key"]: json.loads(r["value"]) for r in rows}
        assert params["best_epoch"] == 42
        assert params["converged"] is True

    def test_finish_scans_output_dir(self, tmp_project):
        """run-finish auto-discovers files in the output directory."""
        from exptrack.core.db import get_db

        exp_id, stdout = _start_exp("sim.sh")
        exp_out = _extract_env(stdout, "EXP_OUT")

        Path(exp_out).mkdir(parents=True, exist_ok=True)
        (Path(exp_out) / "model.pt").write_bytes(b"fake model")
        (Path(exp_out) / "log.txt").write_text("training log")

        _finish_exp(exp_id)

        conn = get_db()
        rows = conn.execute(
            "SELECT label, path FROM artifacts WHERE exp_id=?", (exp_id,)
        ).fetchall()
        labels = {r["label"] for r in rows}
        assert "model.pt" in labels
        assert "log.txt" in labels

    def test_finish_missing_experiment(self, tmp_project):
        """run-finish exits with error for non-existent experiment."""
        import pytest

        with pytest.raises(SystemExit):
            _finish_exp("nonexistent123")


# ---------------------------------------------------------------------------
# run-fail
# ---------------------------------------------------------------------------


class TestRunFail:
    """Test exptrack run-fail — marking experiments as failed."""

    def test_basic_fail(self, tmp_project):
        """run-fail marks experiment as failed with reason."""
        from exptrack.cli.pipeline_cmds import cmd_run_fail
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp("failing.sh")

        args = SimpleNamespace(id=exp_id, reason="OOM killed")
        _, stderr = _capture(cmd_run_fail, args)
        assert "FAILED" in stderr

        conn = get_db()
        row = conn.execute(
            "SELECT status, duration_s FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        assert row["status"] == "failed"
        assert row["duration_s"] is not None

        err_row = conn.execute(
            "SELECT value FROM params WHERE exp_id=? AND key='error'", (exp_id,)
        ).fetchone()
        assert json.loads(err_row["value"]) == "OOM killed"

    def test_fail_default_reason(self, tmp_project):
        """run-fail without reason uses default message."""
        from exptrack.cli.pipeline_cmds import cmd_run_fail
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp("failing.sh")

        _capture(cmd_run_fail, SimpleNamespace(id=exp_id, reason=""))

        conn = get_db()
        err_row = conn.execute(
            "SELECT value FROM params WHERE exp_id=? AND key='error'", (exp_id,)
        ).fetchone()
        assert "non-zero" in json.loads(err_row["value"])

    def test_fail_missing_experiment(self, tmp_project):
        """run-fail exits with error for non-existent experiment."""
        from exptrack.cli.pipeline_cmds import cmd_run_fail
        import pytest

        with pytest.raises(SystemExit):
            _capture(cmd_run_fail, SimpleNamespace(id="nonexistent", reason=""))


# ---------------------------------------------------------------------------
# log-metric
# ---------------------------------------------------------------------------


class TestLogMetric:
    """Test exptrack log-metric — logging metrics mid-pipeline."""

    def test_log_single_metric(self, tmp_project):
        """log-metric stores a single metric with optional step."""
        from exptrack.cli.pipeline_cmds import cmd_log_metric
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp()

        _capture(cmd_log_metric, SimpleNamespace(
            id=exp_id, key="loss", value=0.234, step=10, file=None
        ))

        conn = get_db()
        row = conn.execute(
            "SELECT key, value, step FROM metrics WHERE exp_id=?", (exp_id,)
        ).fetchone()
        assert row["key"] == "loss"
        assert row["value"] == 0.234
        assert row["step"] == 10

    def test_log_metric_no_step(self, tmp_project):
        """log-metric works without --step."""
        from exptrack.cli.pipeline_cmds import cmd_log_metric
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp()

        _capture(cmd_log_metric, SimpleNamespace(
            id=exp_id, key="accuracy", value=0.95, step=None, file=None
        ))

        conn = get_db()
        row = conn.execute(
            "SELECT key, value, step FROM metrics WHERE exp_id=?", (exp_id,)
        ).fetchone()
        assert row["key"] == "accuracy"
        assert row["step"] is None

    def test_log_metrics_from_file(self, tmp_project):
        """log-metric --file imports all numeric values from JSON."""
        from exptrack.cli.pipeline_cmds import cmd_log_metric
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp()

        metrics_file = tmp_project / "metrics.json"
        metrics_file.write_text(json.dumps({
            "loss": 0.1, "acc": 0.9, "f1": 0.88,
            "note": "not a number"
        }))

        _capture(cmd_log_metric, SimpleNamespace(
            id=exp_id, key=None, value=None, step=5, file=str(metrics_file)
        ))

        conn = get_db()
        rows = conn.execute(
            "SELECT key, value FROM metrics WHERE exp_id=?", (exp_id,)
        ).fetchall()
        metrics = {r["key"]: r["value"] for r in rows}
        assert len(metrics) == 3
        assert metrics["loss"] == 0.1
        assert metrics["acc"] == 0.9


# ---------------------------------------------------------------------------
# log-artifact
# ---------------------------------------------------------------------------


class TestLogArtifact:
    """Test exptrack log-artifact — registering output files."""

    def test_log_artifact(self, tmp_project):
        """log-artifact registers a file path."""
        from exptrack.cli.pipeline_cmds import cmd_log_artifact
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp()

        artifact = tmp_project / "model.pt"
        artifact.write_bytes(b"model data")

        _capture(cmd_log_artifact, SimpleNamespace(
            id=exp_id, path=str(artifact), label="checkpoint", stdin=False
        ))

        conn = get_db()
        row = conn.execute(
            "SELECT label, path FROM artifacts WHERE exp_id=? AND label='checkpoint'",
            (exp_id,)
        ).fetchone()
        assert row is not None
        assert "model.pt" in row["path"]


# ---------------------------------------------------------------------------
# log-result
# ---------------------------------------------------------------------------


class TestLogResult:
    """Test exptrack log-result — logging final results."""

    def test_log_result_key_value(self, tmp_project):
        """log-result stores a key=value result as a metric."""
        from exptrack.cli.pipeline_cmds import cmd_log_result
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp()

        _capture(cmd_log_result, SimpleNamespace(
            id=exp_id, key="accuracy", value="0.95",
            file=None, source="manual"
        ))

        conn = get_db()
        row = conn.execute(
            "SELECT key, value, source FROM metrics WHERE exp_id=? AND key='accuracy'",
            (exp_id,)
        ).fetchone()
        assert row["value"] == 0.95
        assert row["source"] == "manual"

    def test_log_result_from_file(self, tmp_project):
        """log-result --file imports results from JSON."""
        from exptrack.cli.pipeline_cmds import cmd_log_result
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp()

        results_file = tmp_project / "results.json"
        results_file.write_text(json.dumps({
            "accuracy": 0.95, "f1": 0.91, "precision": 0.93
        }))

        _capture(cmd_log_result, SimpleNamespace(
            id=exp_id, key=None, value=None,
            file=str(results_file), source="pipeline"
        ))

        conn = get_db()
        rows = conn.execute(
            "SELECT key, value, source FROM metrics WHERE exp_id=?", (exp_id,)
        ).fetchall()
        results = {r["key"]: r["value"] for r in rows}
        assert len(results) == 3
        assert results["accuracy"] == 0.95
        assert all(r["source"] == "pipeline" for r in rows)


# ---------------------------------------------------------------------------
# link-dir
# ---------------------------------------------------------------------------


class TestLinkDir:
    """Test exptrack link-dir — linking output directories."""

    def test_link_dir_registers_files(self, tmp_project):
        """link-dir scans a directory and registers all files as artifacts."""
        from exptrack.cli.pipeline_cmds import cmd_link_dir
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp()

        log_dir = tmp_project / "logs" / "run1"
        log_dir.mkdir(parents=True)
        (log_dir / "train.log").write_text("training output")
        (log_dir / "events.out").write_text("tensorboard data")

        _capture(cmd_link_dir, SimpleNamespace(
            id=exp_id, path=str(log_dir), label="tensorboard"
        ))

        conn = get_db()
        rows = conn.execute(
            "SELECT label, path FROM artifacts WHERE exp_id=?", (exp_id,)
        ).fetchall()
        labels = {r["label"] for r in rows}
        assert "train.log" in labels
        assert "events.out" in labels
        assert "[dir] tensorboard" in labels


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """End-to-end pipeline tests simulating real shell/SLURM workflows."""

    def test_single_step_shell_pipeline(self, tmp_project):
        """Complete single-step pipeline: start -> log metrics -> finish."""
        from exptrack.cli.pipeline_cmds import cmd_log_metric
        from exptrack.core.db import get_db

        exp_id, stdout = _start_exp(
            "simulate.sh", tags=["shell-test"],
            params=["--iterations", "1000", "--seed", "42"]
        )
        exp_out = _extract_env(stdout, "EXP_OUT")

        for step in range(1, 4):
            _capture(cmd_log_metric, SimpleNamespace(
                id=exp_id, key="error", value=1.0 / step,
                step=step, file=None
            ))

        Path(exp_out).mkdir(parents=True, exist_ok=True)
        results_file = Path(exp_out) / "results.json"
        results_file.write_text(json.dumps({"final_error": 0.33, "converged": True}))

        _finish_exp(exp_id, metrics=str(results_file))

        conn = get_db()
        row = conn.execute(
            "SELECT status, duration_s FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        assert row["status"] == "done"
        assert row["duration_s"] >= 0

        error_metrics = conn.execute(
            "SELECT * FROM metrics WHERE exp_id=? AND key='error'", (exp_id,)
        ).fetchall()
        assert len(error_metrics) == 3

        params = {r["key"]: json.loads(r["value"]) for r in
                  conn.execute("SELECT key, value FROM params WHERE exp_id=?",
                               (exp_id,)).fetchall()}
        assert params["iterations"] == 1000
        assert params["seed"] == 42

    def test_multi_step_pipeline_with_study(self, tmp_project):
        """Multi-step pipeline grouped in a study with stages."""
        from exptrack.cli.pipeline_cmds import cmd_log_metric
        from exptrack.core.db import get_db

        study_name = "full-pipeline-test"
        exp_ids = []

        # Stage 1: Preprocess
        eid, _ = _start_exp(
            "preprocess.sh", study=study_name, stage=1, stage_name="preprocess",
            params=["--input", "data.csv"]
        )
        exp_ids.append(eid)
        _finish_exp(eid)

        # Stage 2: Train
        eid, _ = _start_exp(
            "train.sh", study=study_name, stage=2, stage_name="train",
            params=["--lr", "0.01", "--epochs", "50"]
        )
        exp_ids.append(eid)
        _capture(cmd_log_metric, SimpleNamespace(
            id=eid, key="loss", value=0.1, step=50, file=None
        ))
        _finish_exp(eid)

        # Stage 3: Evaluate
        eid, _ = _start_exp(
            "eval.sh", study=study_name, stage=3, stage_name="evaluate"
        )
        exp_ids.append(eid)
        _finish_exp(eid)

        conn = get_db()
        for eid in exp_ids:
            row = conn.execute(
                "SELECT studies, status FROM experiments WHERE id=?", (eid,)
            ).fetchone()
            studies = json.loads(row["studies"] or "[]")
            assert study_name in studies
            assert row["status"] == "done"

        stages = {}
        for eid in exp_ids:
            row = conn.execute(
                "SELECT stage, stage_name FROM experiments WHERE id=?", (eid,)
            ).fetchone()
            stages[row["stage"]] = row["stage_name"]
        assert stages == {1: "preprocess", 2: "train", 3: "evaluate"}

    def test_pipeline_with_failure_and_trap(self, tmp_project):
        """Simulates a shell script with trap that calls run-fail on error."""
        from exptrack.cli.pipeline_cmds import cmd_log_metric, cmd_run_fail
        from exptrack.core.db import get_db

        exp_id, _ = _start_exp(
            "risky.sh", params=["--config", "experimental"]
        )

        _capture(cmd_log_metric, SimpleNamespace(
            id=exp_id, key="step", value=1, step=1, file=None
        ))

        _capture(cmd_run_fail, SimpleNamespace(
            id=exp_id, reason="Segfault in libcuda.so"
        ))

        conn = get_db()
        row = conn.execute(
            "SELECT status FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        assert row["status"] == "failed"

        metric = conn.execute(
            "SELECT value FROM metrics WHERE exp_id=? AND key='step'",
            (exp_id,)
        ).fetchone()
        assert metric["value"] == 1.0


# ---------------------------------------------------------------------------
# _detect_calling_script / _looks_like_script
# ---------------------------------------------------------------------------


class TestDetectCallingScript:
    """Test the script detection helper."""

    def test_looks_like_script_sh(self, tmp_path):
        from exptrack.cli.pipeline_cmds import _looks_like_script

        sh_file = tmp_path / "run.sh"
        sh_file.write_text("#!/bin/bash\necho hello")
        assert _looks_like_script(sh_file) is True

    def test_looks_like_script_slurm(self, tmp_path):
        from exptrack.cli.pipeline_cmds import _looks_like_script

        slurm_file = tmp_path / "job.slurm"
        slurm_file.write_text("#!/bin/bash\n#SBATCH --job-name=test")
        assert _looks_like_script(slurm_file) is True

    def test_looks_like_script_sbatch(self, tmp_path):
        from exptrack.cli.pipeline_cmds import _looks_like_script

        sbatch_file = tmp_path / "submit.sbatch"
        sbatch_file.write_text("#!/bin/bash\n#SBATCH -N 4")
        assert _looks_like_script(sbatch_file) is True

    def test_rejects_json(self, tmp_path):
        from exptrack.cli.pipeline_cmds import _looks_like_script

        json_file = tmp_path / "config.json"
        json_file.write_text('{"key": "value"}')
        assert _looks_like_script(json_file) is False

    def test_rejects_yaml(self, tmp_path):
        from exptrack.cli.pipeline_cmds import _looks_like_script

        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value")
        assert _looks_like_script(yaml_file) is False

    def test_extensionless_with_shebang(self, tmp_path):
        from exptrack.cli.pipeline_cmds import _looks_like_script

        script = tmp_path / "run_job"
        script.write_text("#!/bin/bash\necho hello")
        assert _looks_like_script(script) is True

    def test_extensionless_without_shebang(self, tmp_path):
        from exptrack.cli.pipeline_cmds import _looks_like_script

        data_file = tmp_path / "data"
        data_file.write_text("just some data")
        assert _looks_like_script(data_file) is False

    def test_nonexistent_file(self, tmp_path):
        from exptrack.cli.pipeline_cmds import _looks_like_script

        assert _looks_like_script(tmp_path / "nope.sh") is False

    def test_python_scripts_accepted(self, tmp_path):
        from exptrack.cli.pipeline_cmds import _looks_like_script

        py_file = tmp_path / "train.py"
        py_file.write_text("print('hello')")
        assert _looks_like_script(py_file) is True

    def test_pbs_sge_lsf_scripts(self, tmp_path):
        from exptrack.cli.pipeline_cmds import _looks_like_script

        for ext in [".pbs", ".sge", ".lsf"]:
            f = tmp_path / f"job{ext}"
            f.write_text("#!/bin/bash\necho job")
            assert _looks_like_script(f) is True, f"Expected {ext} to be recognized"


# ---------------------------------------------------------------------------
# _coerce_str
# ---------------------------------------------------------------------------


class TestCoerceStr:
    """Test the value coercion helper."""

    def test_coerce_int(self):
        from exptrack.cli.pipeline_cmds import _coerce_str
        assert _coerce_str("42") == 42

    def test_coerce_float(self):
        from exptrack.cli.pipeline_cmds import _coerce_str
        assert _coerce_str("0.01") == 0.01

    def test_coerce_bool_true(self):
        from exptrack.cli.pipeline_cmds import _coerce_str
        assert _coerce_str("true") is True

    def test_coerce_bool_false(self):
        from exptrack.cli.pipeline_cmds import _coerce_str
        assert _coerce_str("false") is False

    def test_coerce_string(self):
        from exptrack.cli.pipeline_cmds import _coerce_str
        assert _coerce_str("resnet50") == "resnet50"


# ---------------------------------------------------------------------------
# _flatten_dict
# ---------------------------------------------------------------------------


class TestFlattenDict:
    """Test nested dict flattening for metrics/results files."""

    def test_flat_dict(self):
        from exptrack.cli.pipeline_cmds import _flatten_dict
        assert _flatten_dict({"a": 1, "b": 2}) == {"a": 1, "b": 2}

    def test_nested_dict(self):
        from exptrack.cli.pipeline_cmds import _flatten_dict
        result = _flatten_dict({"val": {"loss": 0.3, "acc": 0.9}})
        assert result == {"val/loss": 0.3, "val/acc": 0.9}

    def test_deeply_nested(self):
        from exptrack.cli.pipeline_cmds import _flatten_dict
        result = _flatten_dict({"a": {"b": {"c": 1}}})
        assert result == {"a/b/c": 1}
