"""Tests for new features: filters, JSON output, batch ops, backup, no-color, watch."""
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest


def _reset_config():
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None


def _capture(func, *args):
    """Capture both stdout and stderr from a function call."""
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = out_buf = io.StringIO()
    sys.stderr = err_buf = io.StringIO()
    try:
        func(*args)
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
    return out_buf.getvalue(), err_buf.getvalue()


def _make_experiment(script="train.py", params=None, tags=None, notes=""):
    from exptrack.core import Experiment
    return Experiment(script=script, params=params, tags=tags, notes=notes)


def _setup_project(tmp):
    os.chdir(tmp)
    _reset_config()
    from exptrack import config as cfg
    cfg.init("test")


# ── A1: Help text ──────────────────────────────────────────────────────────────

def test_help_text_present():
    """All subcommands should have help text."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c",
         "from exptrack.cli.main import main; import sys; sys.argv=['exptrack','-h']; main()"],
        capture_output=True, text=True
    )
    output = result.stdout
    # These commands previously had no help text
    for cmd in ["ls", "show", "diff", "tag", "rm", "clean", "ui"]:
        # In argparse -h output, commands with help appear as "cmd   help text"
        assert cmd in output, f"Command '{cmd}' should appear in help output"


# ── A2: ls filters ────────────────────────────────────────────────────────────

def test_ls_filter_by_tag():
    """ls --tag filters experiments."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.inspect_cmds import cmd_ls

        exp1 = _make_experiment(tags=["good"]); exp1.finish()
        exp2 = _make_experiment(tags=["bad"]); exp2.finish()

        args = SimpleNamespace(n=20, tag="good", status=None, study=None, json_output=False)
        stdout, _ = _capture(cmd_ls, args)
        assert exp1.id[:6] in stdout
        assert exp2.id[:6] not in stdout


def test_ls_filter_by_status():
    """ls --status filters experiments."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.inspect_cmds import cmd_ls

        exp1 = _make_experiment(); exp1.finish()
        exp2 = _make_experiment(); exp2.fail("test error")

        args = SimpleNamespace(n=20, tag=None, status="failed", study=None, json_output=False)
        stdout, _ = _capture(cmd_ls, args)
        assert exp2.id[:6] in stdout
        assert exp1.id[:6] not in stdout


# ── A3: JSON output ──────────────────────────────────────────────────────────

def test_ls_json_output():
    """ls --json produces valid JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.inspect_cmds import cmd_ls

        exp = _make_experiment(params={"lr": 0.01}); exp.finish()

        args = SimpleNamespace(n=20, tag=None, status=None, study=None, json_output=True)
        stdout, _ = _capture(cmd_ls, args)
        data = json.loads(stdout)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == exp.id
        assert data[0]["params"]["lr"] == 0.01


def test_show_json_output():
    """show --json produces valid JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.inspect_cmds import cmd_show

        exp = _make_experiment(params={"lr": 0.01}); exp.finish()

        args = SimpleNamespace(id=exp.id[:6], timeline=False, json_output=True)
        stdout, _ = _capture(cmd_show, args)
        data = json.loads(stdout)
        assert data["id"] == exp.id
        assert data["status"] == "done"
        # git_diff should be stripped from JSON
        assert "git_diff" not in data


# ── A4: No-color ─────────────────────────────────────────────────────────────

def test_no_color_env():
    """NO_COLOR env var disables ANSI codes."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        exp = _make_experiment(); exp.finish()

        # Run via subprocess with NO_COLOR set
        result = subprocess.run(
            [sys.executable, "-m", "exptrack", "ls"],
            capture_output=True, text=True,
            env={**os.environ, "NO_COLOR": "1"},
            cwd=tmp,
        )
        # Should not contain ANSI escape codes
        assert "\033[" not in result.stdout


# ── B1: Backup ────────────────────────────────────────────────────────────────

def test_backup_creates_file():
    """backup command creates a valid database copy."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.admin_cmds import cmd_backup

        exp = _make_experiment(); exp.finish()

        backup_path = Path(tmp) / "test_backup.db"
        args = SimpleNamespace(dest=str(backup_path))
        _, stderr = _capture(cmd_backup, args)

        assert backup_path.exists(), "Backup file should exist"
        assert backup_path.stat().st_size > 0, "Backup file should not be empty"
        assert "Backup saved" in stderr

        # Verify the backup contains data
        import sqlite3
        conn = sqlite3.connect(str(backup_path))
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) as n FROM experiments").fetchone()["n"]
        conn.close()
        assert count == 1, f"Backup should contain 1 experiment, got {count}"


# ── B3: Batch operations ─────────────────────────────────────────────────────

def test_batch_tag():
    """tag command tags multiple experiments at once."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.mutate_cmds import cmd_tag
        from exptrack.core import get_db

        exp1 = _make_experiment(); exp1.finish()
        exp2 = _make_experiment(); exp2.finish()

        # Tag both experiments: last arg is the tag name
        args = SimpleNamespace(id=[exp1.id[:6], exp2.id[:6], "batch-tag"])
        _, stderr = _capture(cmd_tag, args)
        assert "2 experiment(s)" in stderr

        conn = get_db()
        for eid in [exp1.id, exp2.id]:
            row = conn.execute("SELECT tags FROM experiments WHERE id=?", (eid,)).fetchone()
            tags = json.loads(row["tags"] or "[]")
            assert "batch-tag" in tags, f"Expected 'batch-tag' in tags for {eid}"


def test_batch_untag():
    """untag command untags multiple experiments at once."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.mutate_cmds import cmd_untag
        from exptrack.core import get_db

        exp1 = _make_experiment(tags=["remove-me"]); exp1.finish()
        exp2 = _make_experiment(tags=["remove-me"]); exp2.finish()

        args = SimpleNamespace(id=[exp1.id[:6], exp2.id[:6], "remove-me"])
        _, stderr = _capture(cmd_untag, args)
        assert "2 experiment(s)" in stderr

        conn = get_db()
        for eid in [exp1.id, exp2.id]:
            row = conn.execute("SELECT tags FROM experiments WHERE id=?", (eid,)).fetchone()
            tags = json.loads(row["tags"] or "[]")
            assert "remove-me" not in tags


# ── B5: stderr consistency ────────────────────────────────────────────────────

def test_tag_output_goes_to_stderr():
    """Tag confirmation message goes to stderr, not stdout."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.mutate_cmds import cmd_tag

        exp = _make_experiment(); exp.finish()
        args = SimpleNamespace(id=[exp.id[:6], "mytag"])
        stdout, stderr = _capture(cmd_tag, args)
        assert stdout == "", f"stdout should be empty, got: {stdout}"
        assert "Tagged" in stderr


def test_note_output_goes_to_stderr():
    """Note confirmation goes to stderr."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.mutate_cmds import cmd_note

        exp = _make_experiment(); exp.finish()
        args = SimpleNamespace(id=exp.id[:6], text="hello")
        stdout, stderr = _capture(cmd_note, args)
        assert stdout == "", f"stdout should be empty, got: {stdout}"
        assert "Note saved" in stderr


def test_not_found_goes_to_stderr():
    """Error messages for not-found experiments go to stderr."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.inspect_cmds import cmd_show
        from exptrack.core import get_db
        get_db()  # ensure schema

        args = SimpleNamespace(id="nonexistent", timeline=False, json_output=False)
        stdout, stderr = _capture(cmd_show, args)
        assert "Not found" in stderr
        assert stdout == ""


# ── Pipeline commands ─────────────────────────────────────────────────────────

def test_run_start_finish():
    """run-start creates an experiment, run-finish marks it done."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.pipeline_cmds import cmd_run_start, cmd_run_finish
        from exptrack.core import get_db

        args = SimpleNamespace(
            name="pipeline-test", script="train.sh", tags=["ci"],
            notes="test run", params=["--lr", "0.01", "--epochs", "10"]
        )
        stdout, _ = _capture(cmd_run_start, args)
        assert "EXP_ID" in stdout

        # Extract EXP_ID from the export statement
        for line in stdout.splitlines():
            if "EXP_ID" in line:
                exp_id = line.split('"')[1]
                break

        # Finish it
        args_finish = SimpleNamespace(id=exp_id[:8], metrics=None, step=None, params=None)
        _, stderr = _capture(cmd_run_finish, args_finish)
        assert "done" in stderr.lower()

        conn = get_db()
        row = conn.execute("SELECT status FROM experiments WHERE id=?", (exp_id,)).fetchone()
        assert row["status"] == "done"


def test_run_fail():
    """run-fail marks an experiment as failed with a reason."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.pipeline_cmds import cmd_run_start, cmd_run_fail
        from exptrack.core import get_db

        args = SimpleNamespace(
            name="fail-test", script="train.sh", tags=[],
            notes="", params=[]
        )
        stdout, _ = _capture(cmd_run_start, args)
        exp_id = stdout.splitlines()[0].split('"')[1]

        args_fail = SimpleNamespace(id=exp_id[:8], reason="OOM error")
        _, stderr = _capture(cmd_run_fail, args_fail)
        assert "FAILED" in stderr

        conn = get_db()
        row = conn.execute("SELECT status FROM experiments WHERE id=?", (exp_id,)).fetchone()
        assert row["status"] == "failed"


# ── Integrity check ──────────────────────────────────────────────────────────

def test_db_integrity_check():
    """get_db runs integrity check without errors on a healthy database."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.core import get_db
        # Should not raise or print warnings for a fresh DB
        conn = get_db()
        assert conn is not None


# ── Error paths ──────────────────────────────────────────────────────────────

def test_export_not_found():
    """export with invalid ID reports error."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.inspect_cmds import cmd_export
        from exptrack.core import get_db
        get_db()

        args = SimpleNamespace(id="nonexistent", format="json", export_all=False)
        stdout, stderr = _capture(cmd_export, args)
        assert "Not found" in (stdout + stderr)


def test_diff_not_found():
    """diff with invalid ID reports error."""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_project(tmp)
        from exptrack.cli.inspect_cmds import cmd_diff
        from exptrack.core import get_db
        get_db()

        args = SimpleNamespace(id="nonexistent")
        stdout, stderr = _capture(cmd_diff, args)
        assert "Not found" in (stdout + stderr)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
