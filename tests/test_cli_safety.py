"""Regression tests for destructive CLI commands and schema migration (1.4).

The shared theme: a command that deletes, migrates or backs up must never
report success it didn't achieve, and must never do something the user didn't
select.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from conftest import capture as _capture

# ── Migration ────────────────────────────────────────────────────────────────

def test_a_db_is_never_stamped_current_with_columns_missing(tmp_path):
    """The stamp is what makes get_db() skip the migration, so stamping a DB
    whose columns are absent makes the gap permanent: `run-start` then died on
    "no column named command" and no connection ever retried."""
    from exptrack.core import db as dbmod

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    # A pre-1.0 experiments table: no command/hostname/python_ver/duration_s.
    conn.execute("""CREATE TABLE experiments (
        id TEXT PRIMARY KEY, project TEXT, name TEXT NOT NULL,
        status TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        script TEXT, git_branch TEXT, git_commit TEXT, git_diff TEXT)""")
    conn.execute("CREATE TABLE params (exp_id TEXT, key TEXT, value TEXT, "
                 "PRIMARY KEY (exp_id, key))")
    conn.commit()

    dbmod._ensure_schema(conn)

    cols = dbmod._table_columns(conn, "experiments")
    for missing_before in ("command", "hostname", "python_ver", "duration_s",
                           "notes", "tags"):
        assert missing_before in cols, f"{missing_before} was never migrated in"
    assert dbmod._missing_columns(conn) == []
    assert dbmod._stored_schema_version(conn) == dbmod._SCHEMA_VERSION
    conn.close()


def test_the_stamp_is_withheld_when_a_column_is_still_missing(tmp_path,
                                                              monkeypatch):
    from exptrack.core import db as dbmod

    path = tmp_path / "broken.db"
    conn = sqlite3.connect(str(path))
    monkeypatch.setattr(dbmod, "_missing_columns", lambda c: ["experiments.command"])
    dbmod._ensure_schema(conn)
    assert dbmod._stored_schema_version(conn) != dbmod._SCHEMA_VERSION
    conn.close()


# ── confirm() ────────────────────────────────────────────────────────────────

def test_confirm_treats_a_closed_stdin_as_no(monkeypatch):
    """A bare input() raised EOFError under cron/CI — a raw traceback from a
    delete the user never got to answer. An unanswered question is a refusal."""
    from exptrack.cli.formatting import confirm

    def _eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    assert confirm("Delete everything? ") is False
    assert confirm("Delete everything? ", assume_yes=True) is True


def test_confirm_treats_ctrl_c_as_no(monkeypatch):
    from exptrack.cli.formatting import confirm

    def _interrupt(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", _interrupt)
    assert confirm("Delete everything? ") is False


# ── clean ────────────────────────────────────────────────────────────────────

def test_clean_older_than_with_vacuum_still_deletes(tmp_project, monkeypatch):
    """Dispatch on the first matching flag ran *only* the VACUUM: exit 0, no
    warning, and the retention delete silently never happened."""
    from datetime import datetime, timedelta, timezone

    from exptrack.cli.mutate_cmds import cmd_clean
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    exp.fail("boom")
    # 91, not 90: aged exactly to the boundary, "older than 90d" held only if
    # the clock moved between here and the cutoff — and on Windows two reads
    # a moment apart can return the same instant.
    old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    conn = get_db()
    conn.execute("UPDATE experiments SET created_at=? WHERE id=?", (old, exp.id))
    conn.commit()

    args = SimpleNamespace(older_than="90d", vacuum=True, yes=True, dry_run=False,
                           reset=False, orphans=False, baselines=False,
                           all_statuses=False)
    _capture(cmd_clean, args)

    left = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    assert left == 0, "the --older-than selection was skipped in favour of VACUUM"


def test_clean_refuses_two_selections_at_once(tmp_project):
    from exptrack.cli.mutate_cmds import cmd_clean

    args = SimpleNamespace(older_than="30d", vacuum=False, yes=True, dry_run=True,
                           reset=True, orphans=False, baselines=False,
                           all_statuses=False)
    with pytest.raises(SystemExit) as e:
        _capture(cmd_clean, args)
    assert e.value.code != 0


def test_clean_reset_counts_sessions_not_only_experiment_tables(tmp_project):
    """The emptiness check counted five tables, so a project with no runs but
    live sessions reported "Database is already empty" and returned — the
    stranded-sessions state _RESET_TABLES exists to prevent."""
    from exptrack.cli.mutate_cmds import _clean_reset
    from exptrack.core import get_db

    conn = get_db()
    conn.execute("INSERT INTO sessions (id, name, created_at, status) "
                 "VALUES ('s1', 'explore', '2026-01-01T00:00:00Z', 'active')")
    conn.commit()

    out, _ = _capture(_clean_reset, conn, True)      # dry run
    assert "already empty" not in out
    assert "sessions" in out


# ── rm ───────────────────────────────────────────────────────────────────────

def test_rm_does_not_treat_a_wildcard_as_a_prefix(tmp_project):
    """`exptrack rm %` became LIKE '%%' — every run in the project, offered up
    for a permanent delete."""
    from exptrack.cli.mutate_cmds import cmd_rm
    from exptrack.core import Experiment, get_db

    Experiment(script="a.py").finish()
    Experiment(script="b.py").finish()

    _capture(cmd_rm, SimpleNamespace(id=["%"], yes=True, trash=False,
                                     keep_files=False))
    assert get_db().execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 2


def test_rm_trash_is_recoverable(tmp_project):
    """The CLI could only delete permanently; the dashboard has had a Trash
    since 1.1."""
    from exptrack.cli.mutate_cmds import cmd_restore_run, cmd_rm
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py"); exp.finish()
    _capture(cmd_rm, SimpleNamespace(id=[exp.id], yes=True, trash=True,
                                     keep_files=False))

    conn = get_db()
    row = conn.execute("SELECT deleted_at FROM experiments WHERE id=?",
                       (exp.id,)).fetchone()
    assert row is not None and row["deleted_at"]

    _capture(cmd_restore_run, SimpleNamespace(id=exp.id))
    row = conn.execute("SELECT deleted_at FROM experiments WHERE id=?",
                       (exp.id,)).fetchone()
    assert row["deleted_at"] is None


# ── backup / restore ─────────────────────────────────────────────────────────

def test_backup_failure_exits_non_zero(tmp_project):
    """A nightly `exptrack backup || alert` that exits 0 on every failure is a
    backup that silently stops existing."""
    from exptrack.cli.admin_cmds import cmd_backup

    out = tmp_project / "b.db"
    out.write_text("existing")
    with pytest.raises(SystemExit) as e:
        _capture(cmd_backup, SimpleNamespace(path=str(out), force=False))
    assert e.value.code != 0


def test_restore_from_a_missing_file_exits_non_zero_and_points_at_the_trash(
        tmp_project):
    from exptrack.cli.admin_cmds import cmd_restore

    with pytest.raises(SystemExit) as e:
        _capture(cmd_restore, SimpleNamespace(path="abc123", yes=True))
    assert e.value.code != 0


# ── stale ────────────────────────────────────────────────────────────────────

def test_stale_leaves_trashed_runs_alone(tmp_project):
    """A trashed running run was flipped to failed with an injected error param
    while sitting in the Trash; Restore then resurrected mutated state."""
    from datetime import datetime, timedelta, timezone

    from exptrack.cli.admin_cmds import cmd_stale
    from exptrack.core import Experiment, get_db
    from exptrack.core.db import trash_experiment

    exp = Experiment(script="train.py")       # left running
    conn = get_db()
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn.execute("UPDATE experiments SET created_at=? WHERE id=?", (old, exp.id))
    trash_experiment(conn, exp.id)
    conn.commit()

    _capture(cmd_stale, SimpleNamespace(hours=24))

    row = conn.execute("SELECT status FROM experiments WHERE id=?",
                       (exp.id,)).fetchone()
    assert row["status"] == "running"


# ── config ───────────────────────────────────────────────────────────────────

def test_a_wrongly_typed_string_setting_degrades_to_its_default(tmp_project,
                                                                capsys):
    """Only numeric keys were checked, so `"db": 123` reached get_db() as an int
    and raised a TypeError on *every* command."""
    import json

    from exptrack import config as cfg

    (tmp_project / ".exptrack" / "config.json").write_text(json.dumps({"db": 123}))
    cfg.reload()
    conf = cfg.load()
    assert isinstance(conf["db"], str)
    assert conf["db"] == cfg.DEFAULTS["db"]


def test_a_wrongly_typed_boolean_setting_degrades_to_its_default(tmp_project):
    import json

    from exptrack import config as cfg

    (tmp_project / ".exptrack" / "config.json").write_text(
        json.dumps({"warn_duplicate_runs": "yes"}))
    cfg.reload()
    assert cfg.load()["warn_duplicate_runs"] is cfg.DEFAULTS["warn_duplicate_runs"]


def test_a_structured_primary_metric_is_still_accepted(tmp_project):
    """A few text-defaulted keys take a structured override too; the type check
    must not eat those."""
    import json

    from exptrack import config as cfg

    (tmp_project / ".exptrack" / "config.json").write_text(
        json.dumps({"primary_metric": {"key": "val_loss", "goal": "min"}}))
    cfg.reload()
    assert cfg.load()["primary_metric"] == {"key": "val_loss", "goal": "min"}


# ── rename ───────────────────────────────────────────────────────────────────

def test_renaming_a_run_does_not_rewrite_a_sibling_directorys_paths(tmp_project):
    """A bare startswith rewrote artifacts under `outputs/run1_extra/` when
    `run1` was renamed, leaving a dangling row whose file `verify` and the
    delete path could no longer see."""
    from exptrack.core import get_db
    from exptrack.core.db import rename_output_folder

    outputs = tmp_project / "outputs"
    (outputs / "run1").mkdir(parents=True, exist_ok=True)
    (outputs / "run1_extra").mkdir(parents=True, exist_ok=True)

    conn = get_db()
    conn.execute("INSERT INTO experiments (id, name, status, created_at, updated_at) "
                 "VALUES ('e1','run1','done','t','t')")
    sibling = str(outputs / "run1_extra" / "note.txt")
    conn.execute("INSERT INTO artifacts (exp_id, label, path, created_at) "
                 "VALUES ('e1','note',?,'t')", (sibling,))
    conn.execute("INSERT INTO artifacts (exp_id, label, path, created_at) "
                 "VALUES ('e1','own',?,'t')", (str(outputs / "run1" / "m.pt"),))
    conn.commit()

    rename_output_folder(conn, "e1", "run1", "run2")
    conn.commit()

    paths = {r["label"]: r["path"] for r in conn.execute(
        "SELECT label, path FROM artifacts WHERE exp_id='e1'").fetchall()}
    assert paths["note"] == sibling            # untouched
    assert "run2" in paths["own"]              # rewritten


def test_every_documented_setting_is_type_checked(tmp_project):
    """A key read with an inline `conf.get(k, default)` and never listed in
    DEFAULTS escapes `_coerce_numeric`, so a hand-edited value raised where the
    documented invariant says it must degrade to the default."""
    import json

    from exptrack import config as cfg
    path = tmp_project / ".exptrack" / "config.json"
    path.write_text(json.dumps({"metric_max_points": "lots", "timezone": 5,
                                "resume_flags": "nope"}))
    cfg._cache = None
    conf = cfg.load()
    assert conf["metric_max_points"] == 500
    assert conf["timezone"] == ""
    assert conf["resume_flags"] == ["--resume"]


def test_the_documented_config_block_matches_the_real_defaults():
    """docs/configuration.md is the file users copy from. A default that drifts
    from the code there is worse than an undocumented one."""
    import json
    import re
    from pathlib import Path

    from exptrack import config as cfg
    doc = Path(__file__).resolve().parent.parent / "docs" / "configuration.md"
    block = doc.read_text().split("```jsonc")[1].split("```")[0]
    stripped = re.sub(r",(\s*[}\]])", r"\1", re.sub(r"//.*", "", block))
    documented = json.loads(stripped)
    unknown = sorted(k for k in documented if k not in cfg.DEFAULTS)
    assert not unknown, f"documented but not a real setting: {unknown}"
    drifted = {k: (documented[k], cfg.DEFAULTS[k]) for k in documented
               if documented[k] != cfg.DEFAULTS[k]}
    assert not drifted, f"documented default != real default: {drifted}"
    missing = sorted(k for k in cfg.DEFAULTS if k not in documented)
    assert not missing, f"setting missing from docs/configuration.md: {missing}"
