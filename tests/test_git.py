"""Tests for exptrack/core/git.py — git_info, git_diff, _git, _diff_excludes.

Creates throwaway git repos with subprocess. Skips when git is unavailable.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not available"
)


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _init_repo(path):
    """Initialise a git repo at *path* with one committed file."""
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], path)
    _run(["git", "config", "user.email", "test@example.com"], path)
    _run(["git", "config", "user.name", "Test User"], path)
    # Some environments force commit signing globally; disable per-repo so
    # commits don't fail in CI/sandboxes without a working signing setup.
    _run(["git", "config", "commit.gpgsign", "false"], path)
    (path / "train.py").write_text("lr = 0.01\n")
    _run(["git", "add", "train.py"], path)
    _run(["git", "commit", "-m", "initial"], path)


def _point_config_at(monkeypatch, root, *, git_diff_exclude=None):
    """Make exptrack.config see *root* as the project root and chdir there."""
    from exptrack import config as cfg

    conf = dict(cfg.DEFAULTS)
    if git_diff_exclude is not None:
        conf["git_diff_exclude"] = git_diff_exclude

    monkeypatch.setattr(cfg, "_root_cache", root)
    monkeypatch.setattr(cfg, "_cache", conf)
    monkeypatch.setattr(cfg, "project_root", lambda: root)
    monkeypatch.setattr(cfg, "load", lambda: conf)
    monkeypatch.chdir(root)


def test_git_info_in_repo(tmp_path, monkeypatch):
    """git_info() in a repo returns a branch and a hex commit sha."""
    from exptrack.core import git

    repo = tmp_path / "repo"
    _init_repo(repo)
    _point_config_at(monkeypatch, repo)

    info = git.git_info()
    assert info["git_branch"]  # e.g. main / master
    commit = info["git_commit"]
    assert commit
    # short sha is hex
    int(commit, 16)


def test_git_info_outside_repo_is_empty_and_safe(tmp_path, monkeypatch):
    """git_info() outside any repo returns falsey branch/commit and never raises."""
    from exptrack.core import git

    notrepo = tmp_path / "plain"
    notrepo.mkdir()
    _point_config_at(monkeypatch, notrepo)

    info = git.git_info()  # must not raise
    assert not info["git_branch"]
    assert not info["git_commit"]


def test_git_diff_captures_uncommitted_change(tmp_path, monkeypatch):
    """git_diff('HEAD') reflects an uncommitted edit to a tracked file."""
    from exptrack.core import git

    repo = tmp_path / "repo"
    _init_repo(repo)
    _point_config_at(monkeypatch, repo)

    (repo / "train.py").write_text("lr = 0.001\n")  # uncommitted edit

    diff = git.git_diff("HEAD")
    assert "train.py" in diff
    assert "-lr = 0.01" in diff
    assert "+lr = 0.001" in diff


def test_diff_excludes_drops_excluded_pattern(tmp_path, monkeypatch):
    """A change to an excluded pattern (*.ipynb) is excluded; a .py change is kept."""
    from exptrack.core import git

    repo = tmp_path / "repo"
    _init_repo(repo)

    # Add and commit a notebook so a later edit is a tracked diff.
    nb = repo / "notebook.ipynb"
    nb.write_text("original\n")
    _run(["git", "add", "notebook.ipynb"], repo)
    _run(["git", "commit", "-m", "add nb"], repo)

    _point_config_at(monkeypatch, repo, git_diff_exclude=["*.ipynb"])

    # Edit both a tracked .py and the tracked .ipynb.
    (repo / "train.py").write_text("lr = 0.5\n")
    nb.write_text("changed notebook\n")

    diff = git.git_diff("HEAD")
    assert "train.py" in diff          # .py change included
    assert "notebook.ipynb" not in diff  # .ipynb change excluded

    # _diff_excludes builds the expected pathspec args from config.
    args = git._diff_excludes()
    assert args[0] == "--"
    assert ":(exclude,glob)*.ipynb" in args


def test_git_helper_returns_empty_on_failure(tmp_path, monkeypatch):
    """_git returns '' on a failing git command instead of raising."""
    from exptrack.core import git

    repo = tmp_path / "repo"
    _init_repo(repo)
    _point_config_at(monkeypatch, repo)

    assert git._git("not-a-real-git-subcommand") == ""
