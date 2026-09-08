"""`exptrack rm` asks about shared files separately, and the manual overrides.

The delete of a run and the delete of a file another run needs are two
questions. `rm` may only answer the second one out loud — and when the claim
itself is wrong, `log-artifact` / `unlink-artifact` are how it is corrected
without touching a byte on disk.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from exptrack.cli.mutate_cmds import cmd_rm
from exptrack.cli.pipeline_cmds import cmd_unlink_artifact
from exptrack.core import Experiment, get_db


def _run_writing(path: Path, content: bytes) -> Experiment:
    exp = Experiment(script="t.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    exp.log_file(str(path))
    exp.finish()
    return exp


def _rm_args(exp_id: str, **kw) -> argparse.Namespace:
    base = dict(id=[exp_id], yes=True, keep_files=False, trash=False,
                shared_files=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_rm_keeps_shared_files_and_says_which(tmp_project, capsys):
    plot = Path("files/plot.png")
    first = _run_writing(plot, b"first")
    second = _run_writing(plot, b"second")

    cmd_rm(_rm_args(first.id, shared_files="keep"))

    err = capsys.readouterr().err
    assert plot.read_bytes() == b"second"
    assert "plot.png" in err
    assert second.id[:6] in err          # names the run it was kept for
    assert "unlink-artifact" in err      # and how to correct a wrong claim


def test_rm_deletes_shared_files_when_told(tmp_project):
    plot = Path("files/plot.png")
    first = _run_writing(plot, b"first")
    _run_writing(plot, b"second")

    cmd_rm(_rm_args(first.id, shared_files="delete"))
    assert not plot.exists()


def test_rm_without_an_answer_never_takes_a_shared_file(tmp_project, monkeypatch):
    """`--yes` answers "delete this run", not "and take another run's file".

    A scripted delete that inherited the run-level yes would remove a file it
    was never asked about, which is the whole failure this decoupling exists to
    prevent — the flag has to be given explicitly.
    """
    plot = Path("files/plot.png")
    first = _run_writing(plot, b"first")
    _run_writing(plot, b"second")

    # Non-interactive: `confirm` sees EOF, which is a refusal.
    monkeypatch.setattr("builtins.input", lambda *_a: (_ for _ in ()).throw(EOFError()))
    cmd_rm(_rm_args(first.id))
    assert plot.read_bytes() == b"second"


def test_unlink_artifact_drops_the_record_and_leaves_the_file(tmp_project, capsys):
    plot = Path("files/plot.png")
    exp = _run_writing(plot, b"mine")

    cmd_unlink_artifact(argparse.Namespace(id=exp.id, path=["files/plot.png"]))

    conn = get_db()
    rows = conn.execute(
        "SELECT path FROM artifacts WHERE exp_id=?", (exp.id,)).fetchall()
    assert not any((r["path"] or "").endswith("plot.png") for r in rows)
    assert plot.is_file()
    assert "not touched" in capsys.readouterr().err


def test_unlink_then_delete_removes_the_file_that_is_now_unclaimed(tmp_project):
    """The override has to actually change the delete's answer, or it is decor.

    Two runs hold one path; detaching the stale run's record leaves a single
    holder, so that holder's delete owns the file again.
    """
    plot = Path("files/plot.png")
    stale = _run_writing(plot, b"first")
    current = _run_writing(plot, b"second")

    cmd_unlink_artifact(argparse.Namespace(id=stale.id, path=[str(plot)]))
    cmd_rm(_rm_args(current.id, shared_files="keep"))
    assert not plot.exists()
