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


# ── exptrack clean --vacuum ──────────────────────────────────────────────────
# Space freed inside the database file is reused as it grows but never handed
# back to the filesystem without a VACUUM, and every other path here VACUUMs
# only after deleting something (`--reset` wipes the project). This is the
# non-destructive way to shrink the file.

def test_vacuum_reclaims_space_without_deleting(tmp_project, capsys):
    from exptrack.cli.mutate_cmds import cmd_clean
    from exptrack.core.db import get_db

    conn = get_db()
    conn.execute("INSERT INTO experiments (id, name, created_at, updated_at) "
                 "VALUES ('e1','n','2026-01-01','2026-01-01')")
    conn.executemany(
        "INSERT INTO metrics (exp_id, key, value, step, ts) VALUES (?,?,?,?,?)",
        [("e1", "loss", float(i), i, "2026-01-01") for i in range(20_000)])
    conn.commit()
    # Free a large run of pages, without removing the experiment itself.
    conn.execute("DELETE FROM metrics WHERE step > 2000")
    conn.commit()

    db = tmp_project / ".exptrack" / "experiments.db"
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = db.stat().st_size

    cmd_clean(_Args(vacuum=True))

    assert db.stat().st_size < before, "VACUUM did not shrink the file"
    # Nothing was deleted.
    assert conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 2001


def test_vacuum_dry_run_changes_nothing(tmp_project):
    from exptrack.cli.mutate_cmds import cmd_clean
    from exptrack.core.db import get_db

    conn = get_db()
    conn.execute("INSERT INTO experiments (id, name, created_at, updated_at) "
                 "VALUES ('e1','n','2026-01-01','2026-01-01')")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db = tmp_project / ".exptrack" / "experiments.db"
    before = db.stat().st_size

    cmd_clean(_Args(vacuum=True, dry_run=True))
    assert db.stat().st_size == before


class _Args:
    """Stand-in for the argparse namespace cmd_clean reads via getattr."""
    def __init__(self, **kw):
        self.__dict__.update(kw)
