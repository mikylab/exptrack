"""Filesystem permissions and bind exposure.

On a shared workstation the runs database is protected by directory
permissions and nothing else — this matters more than any question about the
dashboard token, because a colleague who can read .exptrack/experiments.db has
every run regardless of whether they can reach the dashboard.
"""
from __future__ import annotations

import argparse
import sys

import pytest

from exptrack import config as cfg

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                 reason="POSIX modes are inert on Windows")


def test_new_exptrack_dir_is_private(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    d = cfg.exptrack_dir()
    assert oct(d.stat().st_mode)[-3:] == "700"


def test_existing_dir_is_not_silently_tightened(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    d = tmp_path / ".exptrack"
    d.mkdir()
    d.chmod(0o755)
    cfg.exptrack_dir()
    assert oct(d.stat().st_mode)[-3:] == "755", "must not change what the user set"


def test_loose_permissions_produce_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    d = tmp_path / ".exptrack"
    d.mkdir()
    d.chmod(0o755)
    msg = cfg.warn_if_world_readable()
    # The warning has to name the mode it found and the way out of it. It said
    # "chmod 700 <path>" until `exptrack fix-perms` existed to do it; this
    # asserts the two properties that matter rather than the exact remedy, so
    # rewording the fix does not fail a test about the warning existing.
    assert "755" in msg
    assert "exptrack fix-perms" in msg


def test_tight_permissions_produce_no_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    d = tmp_path / ".exptrack"
    d.mkdir(mode=0o700)
    assert cfg.warn_if_world_readable() == ""


def test_token_file_is_private(tmp_project):
    p = cfg.write_token("abc")
    assert oct(p.stat().st_mode)[-3:] == "600"


def test_write_token_refuses_a_symlink(tmp_project, tmp_path):
    """write_token used to write-then-chmod, the exact window
    daemon.open_private was built to close for dashboard.json/dashboard.log —
    left open here for the *most* security-relevant of the three files. A
    symlink planted at the token path must cause a refusal, not a write
    through it to wherever the link points.
    """
    target = tmp_path / "elsewhere"
    target.write_text("")
    link = cfg.token_file_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    with pytest.raises(OSError):
        cfg.write_token("abc")
    assert target.read_text() == "", "must not have written through the symlink"


def test_the_database_does_not_create_a_world_readable_exptrack_dir(tmp_path,
                                                                    monkeypatch):
    """A plain `python train.py` must not be what exposes the runs database.

    `get_db()` created the database's parent with a bare mkdir, which takes
    the process umask — 022 on a normal account. So whenever the database was
    the first thing written to a fresh project, before anything called
    `config.exptrack_dir()`, `.exptrack/` was born 755: every account on the
    machine could read the runs database and the dashboard token, and
    `warn_if_world_readable` then told the user to chmod a directory they
    never knowingly created.
    """
    from exptrack.core import db as _db

    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    monkeypatch.setattr(cfg, "_cache", None)
    monkeypatch.setattr(cfg, "project_root", lambda: tmp_path)
    monkeypatch.setattr(_db._local, "conn", None, raising=False)
    monkeypatch.setattr(_db._local, "db_path", None, raising=False)

    assert not (tmp_path / ".exptrack").exists()
    conn = _db.get_db()
    try:
        mode = (tmp_path / ".exptrack").stat().st_mode & 0o777
        assert not mode & 0o077, f".exptrack created world/group accessible ({oct(mode)})"
        assert cfg.warn_if_world_readable() == ""
    finally:
        conn.close()
        _db._local.conn = None
        _db._local.db_path = None


def test_fix_perms_makes_the_directory_private(tmp_path, monkeypatch, capsys):
    """The warning names a command, and the command has to actually work.

    `warn_if_world_readable` used to tell the user to `chmod 700` a directory
    an older exptrack had created 0755 itself — asking them to repair a bug by
    hand, in a shell, with a path they had to copy. `exptrack fix-perms` is
    that remedy as a command; this asserts it tightens the directory and that
    the warning goes quiet afterwards.
    """
    from exptrack.cli.admin_cmds import cmd_fix_perms

    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    monkeypatch.setattr(cfg, "project_root", lambda: tmp_path)
    d = tmp_path / ".exptrack"
    d.mkdir()
    d.chmod(0o755)
    assert cfg.warn_if_world_readable() != ""

    cmd_fix_perms(argparse.Namespace())

    assert d.stat().st_mode & 0o077 == 0
    assert cfg.warn_if_world_readable() == ""


def test_the_permission_warning_names_a_command_not_a_chmod(tmp_path, monkeypatch):
    """A tool that detects a problem exactly should not make the user retype
    its remedy — and a raw `chmod 700 <path>` in a warning is a remedy the
    user has to copy, paste and get right."""
    monkeypatch.setattr(cfg, "_root_cache", tmp_path)
    monkeypatch.setattr(cfg, "project_root", lambda: tmp_path)
    d = tmp_path / ".exptrack"
    d.mkdir()
    d.chmod(0o755)

    msg = cfg.warn_if_world_readable()
    assert "exptrack fix-perms" in msg
    assert "chmod" not in msg
