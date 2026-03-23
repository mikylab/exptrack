"""Tests for exptrack CLI commands — smoke tests calling command functions directly."""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


def _capture_output(func, *args):
    """Run *func* while capturing both stdout and stderr.

    Returns ``(stdout_str, stderr_str)``.
    """
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = out_buf = io.StringIO()
    sys.stderr = err_buf = io.StringIO()
    try:
        func(*args)
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
    return out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# cmd_init
# ---------------------------------------------------------------------------

def test_cmd_init_creates_exptrack_dir(tmp_path, monkeypatch):
    """cmd_init creates the .exptrack directory and config.json."""
    from exptrack import config as cfg

    # Start with a bare directory (no .exptrack yet)
    monkeypatch.chdir(tmp_path)
    cfg._root_cache = None
    cfg._cache = None
    monkeypatch.setattr(cfg, "_root_cache", None)
    monkeypatch.setattr(cfg, "_cache", None)
    # Patch project_root to return tmp_path (since there's no .git or .exptrack yet)
    monkeypatch.setattr(cfg, "project_root", lambda: tmp_path)

    from exptrack.cli.admin_cmds import cmd_init

    args = SimpleNamespace(name="myproject", here=False)
    _capture_output(cmd_init, args)

    assert (tmp_path / ".exptrack").is_dir(), ".exptrack/ should be created"
    assert (tmp_path / ".exptrack" / "config.json").is_file(), "config.json should exist"

    # Config should contain the project name
    data = json.loads((tmp_path / ".exptrack" / "config.json").read_text())
    assert data.get("project") == "myproject"


def test_cmd_init_patches_gitignore(tmp_path, monkeypatch):
    """cmd_init appends exptrack rules to .gitignore."""
    from exptrack import config as cfg

    monkeypatch.chdir(tmp_path)
    cfg._root_cache = None
    cfg._cache = None
    monkeypatch.setattr(cfg, "_root_cache", None)
    monkeypatch.setattr(cfg, "_cache", None)
    monkeypatch.setattr(cfg, "project_root", lambda: tmp_path)

    from exptrack.cli.admin_cmds import cmd_init

    args = SimpleNamespace(name="", here=False)
    _capture_output(cmd_init, args)

    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists(), ".gitignore should be created or updated"
    text = gitignore.read_text()
    assert ".exptrack/experiments.db" in text


# ---------------------------------------------------------------------------
# cmd_stale
# ---------------------------------------------------------------------------

def test_cmd_stale_marks_old_running_experiments(tmp_project):
    """cmd_stale marks experiments running longer than --hours as failed."""
    from exptrack.core import Experiment, get_db
    from exptrack.cli.admin_cmds import cmd_stale

    # Create an experiment and manually backdate its created_at
    exp = Experiment(script="train.py")
    eid = exp.id

    conn = get_db()
    old_time = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
    conn.execute(
        "UPDATE experiments SET created_at=? WHERE id=?", (old_time, eid)
    )
    conn.commit()

    # Verify it's still running
    row = conn.execute(
        "SELECT status FROM experiments WHERE id=?", (eid,)
    ).fetchone()
    assert row["status"] == "running"

    # Run cmd_stale with --hours=24
    args = SimpleNamespace(hours=24)
    _capture_output(cmd_stale, args)

    # Should now be marked as failed
    row = conn.execute(
        "SELECT status FROM experiments WHERE id=?", (eid,)
    ).fetchone()
    assert row["status"] == "failed", (
        f"Expected 'failed' after stale detection, got '{row['status']}'"
    )


def test_cmd_stale_ignores_recent_experiments(tmp_project):
    """cmd_stale does not touch experiments that are still within the threshold."""
    from exptrack.core import Experiment, get_db
    from exptrack.cli.admin_cmds import cmd_stale

    exp = Experiment(script="train.py")
    eid = exp.id

    # Run cmd_stale with --hours=24 (experiment was just created)
    args = SimpleNamespace(hours=24)
    _capture_output(cmd_stale, args)

    conn = get_db()
    row = conn.execute(
        "SELECT status FROM experiments WHERE id=?", (eid,)
    ).fetchone()
    assert row["status"] == "running", "Recent experiment should not be marked stale"

    # Clean up
    exp.finish()
