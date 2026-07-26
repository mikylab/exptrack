"""Tests for the shared plugin proxy (plugins.make_exp_proxy).

The lifecycle-command paths (`exptrack finish`, `exptrack run-finish`) built
incomplete stand-ins for plugins, so github_sync's _push() raised AttributeError
on the first missing field — swallowed by the registry, making every sync
silently fail. These assert the proxy exposes the full interface github_sync
reads, on both paths.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

# Every attribute github_sync._push() touches on the experiment object.
GITHUB_SYNC_FIELDS = [
    "id", "name", "status", "project", "created_at", "duration_s",
    "script", "git_branch", "git_commit", "git_diff",
    "tags", "notes",
]


class CapturePlugin:
    name = "capture"

    def __init__(self, config=None):
        self.captured = None

    def on_finish(self, exp):
        self.captured = exp


@pytest.fixture()
def capture_plugin():
    """Install a CapturePlugin on the registry, restoring state after."""
    from exptrack.plugins import registry
    saved_plugins, saved_loaded = registry._plugins, registry._loaded
    cap = CapturePlugin()
    registry._plugins = [cap]
    registry._loaded = True
    try:
        yield cap
    finally:
        registry._plugins, registry._loaded = saved_plugins, saved_loaded


def _assert_full_interface(exp, expect_tags):
    for field in GITHUB_SYNC_FIELDS:
        assert hasattr(exp, field), f"proxy missing {field!r}"
    assert exp.project                       # derived, never AttributeError
    assert isinstance(exp.tags, list)        # list, not raw JSON string
    assert exp.tags == expect_tags
    assert exp._params                        # params dict present
    assert exp.last_metrics() == {"acc": 0.9}


def test_cmd_finish_proxy_full_interface(tmp_project, capture_plugin):
    from exptrack.cli.mutate_cmds import cmd_finish
    from exptrack.core import Experiment

    exp = Experiment(script="train.py", params={"lr": 0.01}, tags=["baseline"])
    exp.log_metric("acc", 0.9)
    # leave running — cmd_finish marks it done

    cmd_finish(SimpleNamespace(id=exp.id))

    captured = capture_plugin.captured
    assert captured is not None
    assert captured.status == "done"
    _assert_full_interface(captured, ["baseline"])


def test_cmd_run_finish_proxy_full_interface(tmp_project, capture_plugin):
    # Start a shell-pipeline run, then tag it and log a metric directly.
    import io
    import sys as _sys

    from exptrack.cli.pipeline_cmds import cmd_run_finish, cmd_run_start
    from exptrack.core.db import get_db
    old = _sys.stdout
    _sys.stdout = buf = io.StringIO()
    try:
        cmd_run_start(SimpleNamespace(
            name="", script="pipe.sh", tags=["baseline"], study="",
            stage=None, stage_name=None, notes="", params=["--lr", "0.01"]))
    finally:
        _sys.stdout = old
    from conftest import exp_id_from_stdout
    exp_id = exp_id_from_stdout(buf.getvalue())
    assert exp_id

    conn = get_db()
    conn.execute("UPDATE experiments SET tags=? WHERE id=?", ('["baseline"]', exp_id))
    conn.execute(
        "INSERT INTO metrics (exp_id, key, value, step, ts, source) "
        "VALUES (?,?,?,NULL,?,?)", (exp_id, "acc", 0.9, "2026-01-01", "manual"))
    conn.commit()

    cmd_run_finish(SimpleNamespace(id=exp_id, metrics=None, step=None, params=None))

    captured = capture_plugin.captured
    assert captured is not None
    assert captured.status == "done"
    _assert_full_interface(captured, ["baseline"])
