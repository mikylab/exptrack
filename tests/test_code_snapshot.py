"""L3: content-addressed code snapshots + real-command capture."""
from __future__ import annotations

import json
from types import SimpleNamespace

from exptrack.core.db import get_code_snapshot, get_db


def test_script_source_snapshotted(tmp_project):
    """capture_script_snapshot stores the full script source, content-addressed."""
    from exptrack.capture.script_tracking import capture_script_snapshot
    from exptrack.core import Experiment

    script = tmp_project / "train.py"
    script.write_text("lr = 0.01\nprint('train')\n")
    exp = Experiment(script=str(script))
    capture_script_snapshot(exp, str(script))
    exp.finish()

    snap = exp._params.get("_code_snapshot")
    assert snap, "run should reference a code snapshot"
    # log_param stores the native list (encoded once for the DB, not pre-encoded).
    entries = json.loads(snap) if isinstance(snap, str) else snap
    assert entries[0]["kind"] == "script"
    conn = get_db()
    stored = get_code_snapshot(conn, entries[0]["hash"])
    assert stored is not None
    assert "lr = 0.01" in stored["content"]


def test_snapshot_dedups_across_runs(tmp_project):
    """Two runs of the same unchanged script store one snapshot row."""
    from exptrack.capture.script_tracking import capture_script_snapshot
    from exptrack.core import Experiment

    script = tmp_project / "train.py"
    script.write_text("x = 1\n")
    for _ in range(3):
        exp = Experiment(script=str(script))
        capture_script_snapshot(exp, str(script))
        exp.finish()
    conn = get_db()
    n = conn.execute(
        "SELECT COUNT(*) FROM code_snapshots WHERE kind='script'"
    ).fetchone()[0]
    assert n == 1  # deduped


def test_ipynb_never_snapshotted(tmp_project):
    """A .ipynb path is never stored as a code snapshot (design constraint)."""
    from exptrack.capture.script_tracking import capture_script_snapshot
    from exptrack.core import Experiment

    nb = tmp_project / "explore.ipynb"
    nb.write_text('{"cells": []}\n')
    exp = Experiment(script=str(nb))
    capture_script_snapshot(exp, str(nb))
    exp.finish()
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM code_snapshots").fetchone()[0]
    assert n == 0


def test_run_start_records_real_command(tmp_project):
    """--cmd on run-start records the real command, not the wrapper argv."""
    import contextlib
    import io

    from exptrack.cli.pipeline_cmds import cmd_run_start
    buf = io.StringIO()
    args = SimpleNamespace(name="", script="train.py", tags=None, study="",
                           stage=None, stage_name=None, notes="", params=["--lr", "0.01"],
                           cmd="python train.py --lr 0.01", resume=None)
    with contextlib.redirect_stdout(buf):
        cmd_run_start(args)
    out = buf.getvalue()
    exp_id = next(l for l in out.splitlines() if l.startswith("export EXP_ID=")).split('"')[1]

    conn = get_db()
    cmd = conn.execute("SELECT command FROM experiments WHERE id=?", (exp_id,)).fetchone()["command"]
    assert cmd == "python train.py --lr 0.01"


def test_run_finish_cmd_overrides(tmp_project):
    """--cmd on run-finish overrides the command (last writer wins)."""
    import contextlib
    import io

    from exptrack.cli.pipeline_cmds import cmd_run_finish, cmd_run_start
    buf = io.StringIO()
    args = SimpleNamespace(name="", script="train.py", tags=None, study="",
                           stage=None, stage_name=None, notes="", params=[],
                           cmd="", resume=None)
    with contextlib.redirect_stdout(buf):
        cmd_run_start(args)
    exp_id = next(
        l for l in buf.getvalue().splitlines() if l.startswith("export EXP_ID=")
    ).split('"')[1]

    cmd_run_finish(SimpleNamespace(id=exp_id, metrics=None, step=None,
                                   params=None, cmd="python eval.py"))
    conn = get_db()
    cmd = conn.execute("SELECT command FROM experiments WHERE id=?", (exp_id,)).fetchone()["command"]
    assert cmd == "python eval.py"
