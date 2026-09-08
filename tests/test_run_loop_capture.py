"""Regression tests for the run loop and the capture patches (1.4 audit).

These cover the ways a run could end, or be recorded, wrongly: an interrupted
run left `running` forever, one run's files attributed to another, a pipeline
run whose captured source was destroyed on the way into the database.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BOOTSTRAP = (
    "import sys; sys.argv = sys.argv[1:]; "
    "from exptrack.cli import main; sys.exit(main() or 0)"
)


def _exptrack(cwd, *args, **kw):
    return subprocess.run([sys.executable, "-c", BOOTSTRAP, "exptrack", *args],
                          cwd=cwd, capture_output=True, text=True, timeout=120, **kw)


def test_ctrl_c_finishes_the_run_instead_of_leaving_it_running(tmp_path):
    """SIGINT is not an Exception, so it fell through both handlers: the run
    stayed `running` with no duration and no error, invisible to every baseline
    until `stale` swept it 24 hours later."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _exptrack(tmp_path, "init", "irq")
    (tmp_path / "train.py").write_text("raise KeyboardInterrupt\n")

    proc = _exptrack(tmp_path, "run", "train.py")
    assert proc.returncode == 130, proc.stdout + proc.stderr

    ls = _exptrack(tmp_path, "ls").stdout
    assert "running" not in ls
    assert "failed" in ls

    show = _exptrack(tmp_path, "show", "--json", _first_id(tmp_path)).stdout
    assert "KeyboardInterrupt" in show


def _first_id(cwd) -> str:
    import json
    out = _exptrack(cwd, "ls", "--json").stdout
    return json.loads(out)[0]["id"]


def test_the_output_scan_does_not_claim_another_runs_files(tmp_project):
    """The finish-time scan filtered only on mtime, so two runs in flight at
    once — a SLURM array, two terminals — swept each other's checkpoints."""
    from exptrack.__main__ import _auto_detect_outputs
    from exptrack.core import Experiment, get_db

    other = Experiment(script="model_b.py")
    theirs = Path("model_b_weights.pt")
    theirs.write_bytes(b"B")
    other.log_file(str(theirs))

    mine = Experiment(script="model_a.py")
    ours = Path("model_a_weights.pt")
    ours.write_bytes(b"A")

    _auto_detect_outputs(mine, mine._start - 60)
    mine.finish()

    conn = get_db()
    paths = [r["path"] for r in conn.execute(
        "SELECT path FROM artifacts WHERE exp_id=?", (mine.id,)).fetchall()]
    assert any(p.endswith("model_a_weights.pt") for p in paths)
    assert not any(p.endswith("model_b_weights.pt") for p in paths)


def test_pipeline_code_snapshot_survives_the_shell_script_capture(tmp_project):
    """`json.loads` on an already-decoded list raised, so the wrapper's own
    snapshot entry was dropped and the rest written back double-encoded —
    `exptrack source` then reported nothing captured."""

    from exptrack.cli.pipeline_cmds import _capture_pipeline_command
    from exptrack.core import Experiment, get_db

    sh = Path("train.sh")
    sh.write_text("#!/bin/sh\npython train.py\n")

    exp = Experiment(script=str(sh))
    exp.log_param("_code_snapshot", [{"hash": "deadbeef", "kind": "script",
                                      "path": "train.py"}])

    conn = get_db()
    _capture_pipeline_command(conn, exp, "python train.py", str(sh.resolve()))
    conn.commit()

    entries = exp._params["_code_snapshot"]
    assert isinstance(entries, list)
    kinds = {e["kind"] for e in entries}
    assert kinds == {"script", "shellscript"}      # neither entry was lost

    # And a second capture (a --resume) does not append a duplicate.
    _capture_pipeline_command(conn, exp, "python train.py", str(sh.resolve()))
    assert len(exp._params["_code_snapshot"]) == len(entries)


def test_pipeline_runs_are_marked_auto_named(tmp_project):
    """run-start passed its generated name in as `name=`, which is what marks a
    run user-named — so the auto badge and bulk rename skipped every shell run."""
    from exptrack.core import Experiment

    exp = Experiment(naming_hint="train.py", params={"lr": 0.1}, script="train.sh")
    assert exp.name_is_auto is True
    assert "lr0.1" in exp.name          # the hint still shapes the name
    exp.finish()


def test_an_explicit_name_is_still_user_named(tmp_project):
    from exptrack.core import Experiment

    exp = Experiment(name="my-baseline", naming_hint="train.py")
    assert exp.name == "my-baseline"
    assert exp.name_is_auto is False
    exp.finish()


def test_cli_log_artifact_dedupes_resolves_and_hashes(tmp_project):
    """Three invocations made three rows carrying relative paths and NULL
    hashes, so `verify` had nothing to check."""
    from types import SimpleNamespace

    from exptrack.cli.pipeline_cmds import cmd_log_artifact
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    f = Path("model.pt")
    f.write_bytes(b"weights")

    args = SimpleNamespace(id=exp.id, path="model.pt", label="model", stdin=False)
    for _ in range(3):
        cmd_log_artifact(args)

    rows = get_db().execute(
        "SELECT path, content_hash, size_bytes FROM artifacts "
        "WHERE exp_id=? AND label='model'", (exp.id,)).fetchall()
    assert len(rows) == 1
    assert os.path.isabs(rows[0]["path"])
    assert rows[0]["content_hash"] and rows[0]["size_bytes"] == len(b"weights")


def test_pipeline_metrics_record_their_source(tmp_project):
    """capture.md promises source='pipeline' and the dashboard styles a badge
    for it; the writers omitted the column, so every pipeline metric claimed to
    be an auto-capture."""
    from types import SimpleNamespace

    from exptrack.cli.pipeline_cmds import cmd_log_metric
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.sh")
    cmd_log_metric(SimpleNamespace(id=exp.id, key="val_acc", value="0.9",
                                   step=1, file=None))

    row = get_db().execute(
        "SELECT source FROM metrics WHERE exp_id=? AND key='val_acc'",
        (exp.id,)).fetchone()
    assert row["source"] == "pipeline"


def test_proc_stat_parsing_survives_a_comm_with_spaces():
    """Field 2 of /proc/<pid>/stat is the executable name in parentheses and
    can contain spaces ("tmux: server"), which shifted every later field and
    made the ppid read garbage — so calling-script detection silently gave up
    under tmux."""
    from exptrack.cli.pipeline_cmds import _ppid_from_proc_stat

    assert _ppid_from_proc_stat("4242 (python3) S 99 4242 4242 0 -1 4194560") == 99
    assert _ppid_from_proc_stat("4242 (tmux: server) S 99 4242 4242 0 -1 41945") == 99
    # A comm containing its own parens is still delimited by the *last* one.
    assert _ppid_from_proc_stat("4242 (weird (name)) S 77 1 1 0 -1 0") == 77


def test_a_second_save_does_not_null_the_columns_it_does_not_write(tmp_project):
    """_save's INSERT OR REPLACE column list omitted duration_s/studies/stage/
    session_node_id, so any re-save would silently blank them."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    conn = get_db()
    conn.execute("UPDATE experiments SET duration_s=12.5, studies='[\"s\"]', "
                 "stage=3 WHERE id=?", (exp.id,))
    conn.commit()

    exp._save()          # the path a re-save would take

    row = conn.execute("SELECT duration_s, studies, stage FROM experiments "
                       "WHERE id=?", (exp.id,)).fetchone()
    assert row["duration_s"] == 12.5
    assert row["studies"] == '["s"]'
    assert row["stage"] == 3
    exp.finish()


def test_raw_argv_capture_refreshes_the_run_name(tmp_project):
    """A non-argparse script never reaches _capture_namespace, so its name never
    picked up the captured params — two different models were indistinguishable
    by name."""
    from exptrack.capture.argparse_patch import capture_argv
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")
    sys.argv = ["train.py", "--lr", "0.25"]
    capture_argv(exp)

    assert "lr0.25" in exp.name
    exp.finish()


def test_argparse_dest_does_not_leave_a_duplicate_argv_key(tmp_project):
    """`--learning-rate` with dest="lr" was stored under both names, so "what
    varies" reported two axes for one knob."""
    from argparse import Namespace

    from exptrack.capture.argparse_patch import _capture_namespace, capture_argv
    from exptrack.core import Experiment

    exp = Experiment(script="train.py")
    sys.argv = ["train.py", "--learning-rate", "0.25"]
    capture_argv(exp)
    assert "learning_rate" in exp._params

    _capture_namespace(exp, Namespace(lr=0.25))
    assert "lr" in exp._params
    assert "learning_rate" not in exp._params
    exp.finish()


def test_a_named_run_keeps_its_name_through_param_capture(tmp_project):
    from argparse import Namespace

    from exptrack.capture.argparse_patch import _capture_namespace
    from exptrack.core import Experiment

    exp = Experiment(name="my-baseline", script="train.py")
    _capture_namespace(exp, Namespace(lr=0.25))
    assert exp.name == "my-baseline"
    exp.finish()


def test_a_rerun_reclaims_the_file_it_overwrote(tmp_project):
    """The ownership rule is about runs in flight, not runs that are over.

    Rerunning a script that writes a fixed path (`files/plot.png`) left the
    second run with no artifact row at all: the first run's row claimed the
    path, so the finish-time scan skipped the file the second run had just
    written. The file then belonged, on paper, only to a run whose output was
    already overwritten — so permanently deleting that first run trashed the
    *live* file, and the survivor never showed the plot it produced.
    """
    from exptrack.__main__ import _auto_detect_outputs
    from exptrack.core import Experiment, get_db
    from exptrack.core.db import delete_experiment

    plot = Path("files") / "plot.png"
    plot.parent.mkdir(exist_ok=True)

    first = Experiment(script="t.py")
    plot.write_bytes(b"first")
    first.log_file(str(plot))
    first.finish()

    second = Experiment(script="t.py")
    plot.write_bytes(b"second")          # same path, after the first run ended
    _auto_detect_outputs(second, second._start)
    second.finish()

    conn = get_db()
    mine = [r["path"] for r in conn.execute(
        "SELECT path FROM artifacts WHERE exp_id=?", (second.id,)).fetchall()]
    assert any(p.endswith("plot.png") for p in mine), \
        "the run that wrote the file has no row for it"

    delete_experiment(conn, first.id, delete_files=True)
    conn.commit()
    assert plot.is_file(), "delete of the overwritten run took the live file"


def test_a_stale_claim_from_a_killed_run_is_reported(tmp_project, capsys):
    """A run killed outright stays `running`, so it keeps owning its files —
    nothing can tell it from a run still working. The scan may not steal the
    file, but it must not drop it in silence either: this is the one message
    that points at `exptrack stale`."""
    from exptrack.__main__ import _auto_detect_outputs
    from exptrack.core import Experiment

    zombie = Experiment(script="killed.py")     # never finished
    shared = Path("weights.pt")
    shared.write_bytes(b"z")
    zombie.log_file(str(shared))

    mine = Experiment(script="t.py")
    shared.write_bytes(b"m")
    _auto_detect_outputs(mine, mine._start)

    err = capsys.readouterr().err
    assert "weights.pt" in err and zombie.id[:6] in err


def test_naive_timestamps_are_read_as_utc(tmp_project):
    """`updated_at` gained its offset in a later version; a naive row read as
    *local* time lands hours in the future, which would mark every pre-upgrade
    run as still in flight and block a rerun from recording its own files."""
    from datetime import datetime, timedelta, timezone

    from exptrack.core import Experiment, get_db
    from exptrack.core.db import runs_in_flight_since

    old = Experiment(script="old.py")
    old.finish()
    conn = get_db()
    ended = datetime.now(timezone.utc) - timedelta(minutes=5)
    conn.execute("UPDATE experiments SET updated_at=? WHERE id=?",
                 (ended.replace(tzinfo=None).isoformat(), old.id))
    conn.commit()

    now = datetime.now(timezone.utc).timestamp()
    assert old.id not in runs_in_flight_since(conn, now)
