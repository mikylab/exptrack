"""Tests for `exptrack clean --orphans`.

Regression guard for the missing `from pathlib import Path` import in
mutate_cmds.py, which crashed `_clean_orphans` with NameError whenever the
configured outputs dir existed.
"""
from __future__ import annotations

from types import SimpleNamespace


def _clean_args(**kwargs):
    defaults = dict(
        orphans=True, reset=False, baselines=False, older_than=None,
        all_statuses=False, dry_run=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_clean_orphans_no_crash_and_reports(tmp_project, monkeypatch, capsys):
    from exptrack.cli.mutate_cmds import cmd_clean
    from exptrack.core import Experiment

    # A real experiment with an output dir under outputs/
    exp = Experiment(script="train.py")
    referenced = tmp_project / "outputs" / exp.name
    referenced.mkdir(parents=True, exist_ok=True)
    (referenced / "model.pt").write_bytes(b"data")
    exp.finish()

    # An orphan output dir not referenced by any experiment
    orphan = tmp_project / "outputs" / "orphan_run"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "junk.txt").write_text("junk")

    # dry-run so no interactive confirm is needed; the NameError happened during
    # the scan itself, before any prompt.
    cmd_clean(_clean_args(dry_run=True))

    err = capsys.readouterr().err
    assert "orphan_run" in err            # orphan reported
    assert "outputs:" in err              # scan reached the outputs section
    # Referenced dir left untouched
    assert referenced.is_dir()
    assert (referenced / "model.pt").exists()
    # Dry run purges nothing
    assert orphan.is_dir()
