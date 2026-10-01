"""Project discovery, the registry, and the schema probe.

The probe is the load-bearing part: `get_db()` migrates a database whose
`user_version` differs from the running install's `_SCHEMA_VERSION` — in
EITHER direction — and then stamps it to its own version. So discovery must
never open a project through `get_db()`, and a mismatch must refuse rather
than open. Otherwise switching to a project owned by a different virtualenv
silently migrates it, and the two installs thrash the stamp on every open.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from exptrack import projects
from exptrack.core.db import _SCHEMA_VERSION


def _make_project(root, stamp):
    (root / ".exptrack").mkdir(parents=True, exist_ok=True)
    db = root / ".exptrack" / "experiments.db"
    conn = sqlite3.connect(str(db))
    conn.execute(f"PRAGMA user_version = {stamp}")
    conn.commit()
    conn.close()
    return db


def test_matching_stamp_is_ok(tmp_path):
    _make_project(tmp_path, _SCHEMA_VERSION)
    assert projects.probe_status(tmp_path) == projects.SCHEMA_OK


def test_older_stamp_needs_upgrade(tmp_path):
    _make_project(tmp_path, _SCHEMA_VERSION - 1)
    assert projects.probe_status(tmp_path) == projects.SCHEMA_OLD


def test_newer_stamp_is_too_new(tmp_path):
    """The direction a per-project virtualenv actually produces."""
    _make_project(tmp_path, _SCHEMA_VERSION + 1)
    assert projects.probe_status(tmp_path) == projects.SCHEMA_NEW


def test_missing_project_is_stale(tmp_path):
    assert projects.probe_status(tmp_path / "gone") == projects.STALE


def test_directory_without_exptrack_is_stale(tmp_path):
    (tmp_path / "plain").mkdir()
    assert projects.probe_status(tmp_path / "plain") == projects.STALE


def test_probe_does_not_modify_the_database(tmp_path):
    """The whole point: probing must not migrate."""
    db = _make_project(tmp_path, _SCHEMA_VERSION - 1)
    before = db.read_bytes()
    projects.probe_status(tmp_path)
    assert db.read_bytes() == before, "the probe wrote to the database"

    conn = sqlite3.connect(str(db))
    stamp = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert stamp == _SCHEMA_VERSION - 1, "the probe changed user_version"


def test_status_messages_name_the_remedy(tmp_path):
    old = projects.status_message(projects.SCHEMA_OLD, tmp_path)
    assert "exptrack upgrade" in old and str(tmp_path) in old
    new = projects.status_message(projects.SCHEMA_NEW, tmp_path)
    assert "newer" in new.lower()
    assert projects.status_message(projects.SCHEMA_OK, tmp_path) == ""


def test_project_id_is_stable_and_path_derived(tmp_path):
    first = projects.project_id(tmp_path)
    assert first == projects.project_id(tmp_path)
    assert first != projects.project_id(tmp_path / "other")
    assert str(tmp_path) not in first, "the id must not embed the path"


def test_register_then_registered_round_trips(tmp_home, tmp_path):
    _make_project(tmp_path, _SCHEMA_VERSION)
    projects.register(tmp_path)
    entries = projects.registered()
    assert [e["path"] for e in entries] == [str(tmp_path.resolve())]


def test_register_is_idempotent(tmp_home, tmp_path):
    _make_project(tmp_path, _SCHEMA_VERSION)
    projects.register(tmp_path)
    projects.register(tmp_path)
    assert len(projects.registered()) == 1


def test_forget_by_path_and_by_name(tmp_home, tmp_path):
    a, b = tmp_path / "alpha", tmp_path / "beta"
    for d in (a, b):
        _make_project(d, _SCHEMA_VERSION)
        projects.register(d)
    assert projects.forget(str(a)) is True
    assert projects.forget("beta") is True
    assert projects.registered() == []
    assert projects.forget("nope") is False


def test_a_corrupt_registry_reads_as_empty(tmp_home):
    projects.registry_path().write_text("{not json", encoding="utf-8")
    assert projects.registered() == []


def test_the_registry_temp_file_is_per_process(tmp_home, tmp_path, monkeypatch):
    """One fixed temp name is not a private scratch file.

    Two processes writing the registry at once (an `exptrack init` and an
    `exptrack ui start`, say) would open, write and `os.replace` the SAME
    temp path — so `replace` installs whichever interleaving happened to be
    on disk. `_read_registry` degrades unparseable JSON to `{}`, and the next
    `register()` then rewrites just its own entry over an empty file: every
    other project lost. That is exactly the total-loss failure the atomic
    write exists to prevent, so the temp name carries the pid.
    """
    import os

    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(str(src))
        return real_replace(src, dst)

    monkeypatch.setattr(projects.os, "replace", spy)
    _make_project(tmp_path, _SCHEMA_VERSION)
    projects.register(tmp_path)
    assert seen, "the registry write never went through os.replace()"
    assert str(os.getpid()) in seen[0], seen[0]
    # And the temp file is still cleaned up — it must not outlive the write.
    assert not list(projects.registry_path().parent.glob("*.tmp"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes are inert on Windows")
def test_registry_is_private(tmp_home, tmp_path):
    _make_project(tmp_path, _SCHEMA_VERSION)
    projects.register(tmp_path)
    assert oct(projects.registry_path().stat().st_mode)[-3:] == "600"


def test_discover_prunes_a_registry_entry_whose_project_is_gone(tmp_home, tmp_path):
    """A path with no `.exptrack/` at all is unrecoverable, so it is dropped
    from the listing AND from the registry.

    It used to be listed as `stale` and left in projects.json forever, on the
    theory that silently dropping an entry is indistinguishable from discovery
    being broken. That reasoning holds for a project that is merely *unreadable*
    — it does not hold for one that provably is not there, and in practice the
    registry filled with dead pytest temp directories that buried the one or
    two real projects behind a list of greyed-out rows nobody could click.
    """
    gone = tmp_path / "gone"
    _make_project(gone, _SCHEMA_VERSION)
    projects.register(gone)
    import shutil
    shutil.rmtree(gone)

    assert projects.discover() == []
    # Pruned, not merely hidden: the next call must not have to re-decide it.
    assert projects.registered() == []


def test_discover_prunes_a_directory_that_is_no_longer_a_project(tmp_home, tmp_path):
    """The root survived but `.exptrack/` was deleted — same verdict."""
    root = tmp_path / "ex"
    _make_project(root, _SCHEMA_VERSION)
    projects.register(root)
    import shutil
    shutil.rmtree(root / ".exptrack")

    assert projects.discover() == []
    assert projects.registered() == []


def test_discover_keeps_a_project_whose_database_is_missing(tmp_home, tmp_path):
    """`.exptrack/` present but no database: a project mid-init, or one whose
    db was moved by the `db` config key. Unreadable is not the same as absent,
    so this stays listed, disabled, carrying its reason — and stays registered.
    """
    half = tmp_path / "half"
    (half / ".exptrack").mkdir(parents=True)
    projects.register(half)

    found = projects.discover()
    assert [e["status"] for e in found] == [projects.STALE]
    assert found[0]["message"]
    assert len(projects.registered()) == 1


def test_absence_is_not_confirmed_on_an_unmounted_anchor(tmp_path, monkeypatch):
    """Absence we cannot confirm is not absence.

    An unplugged external disk or an unmounted network share makes every path
    under it look exactly like a deleted project. Pruning there would drop a
    project the user still has, so the path's anchor (the drive root on
    Windows, `/` on POSIX) must itself exist before an absence counts.
    """
    gone = tmp_path / "gone"
    assert projects._absence_confirmed(gone) is True

    real_is_dir = Path.is_dir
    # Only the anchor reads as missing; everything else answers normally, so
    # this isolates the one condition under test.
    anchor = Path(gone.anchor)
    monkeypatch.setattr(
        Path, "is_dir",
        lambda self: False if self == anchor else real_is_dir(self))
    assert projects._absence_confirmed(gone) is False


def test_a_pruned_entry_is_gone_from_the_registry_only(tmp_home, tmp_path):
    """Pruning edits `projects.json` and nothing else — the same contract
    `exptrack project forget` has. A project that still exists is untouched."""
    keep = tmp_path / "keep"
    _make_project(keep, _SCHEMA_VERSION)
    projects.register(keep)
    gone = tmp_path / "gone"
    _make_project(gone, _SCHEMA_VERSION)
    projects.register(gone)
    import shutil
    shutil.rmtree(gone)

    found = projects.discover()
    assert [e["path"] for e in found] == [str(keep.resolve())]
    assert [e["path"] for e in projects.registered()] == [str(keep.resolve())]
    assert (keep / ".exptrack" / "experiments.db").is_file()


def test_discover_marks_a_skewed_project_without_opening_it(tmp_home, tmp_path):
    old = tmp_path / "old"
    db = _make_project(old, _SCHEMA_VERSION - 1)
    projects.register(old)
    before = db.read_bytes()

    entry = projects.discover()[0]
    assert entry["status"] == projects.SCHEMA_OLD
    assert "exptrack upgrade" in entry["message"]
    assert db.read_bytes() == before


def test_discover_includes_git_worktrees(tmp_home, tmp_path, monkeypatch):
    """Worktrees come free — they are the case that motivated the release."""
    wt = tmp_path / "wt"
    _make_project(wt, _SCHEMA_VERSION)

    def fake_worktrees(root):
        return [wt]
    monkeypatch.setattr(projects, "_git_worktrees", fake_worktrees)

    ids = {e["path"] for e in projects.discover(current_root=tmp_path)}
    assert str(wt.resolve()) in ids


def test_discover_deduplicates_a_registered_worktree(tmp_home, tmp_path, monkeypatch):
    wt = tmp_path / "wt"
    _make_project(wt, _SCHEMA_VERSION)
    projects.register(wt)
    monkeypatch.setattr(projects, "_git_worktrees", lambda root: [wt])
    assert len(projects.discover(current_root=tmp_path)) == 1


def test_discover_skips_a_directory_with_no_exptrack(tmp_home, tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr(projects, "_git_worktrees", lambda root: [plain])
    assert projects.discover(current_root=tmp_path) == []


def test_git_worktrees_parses_real_porcelain_output(tmp_path):
    """The discover() tests above monkeypatch `_git_worktrees` itself, so the
    porcelain parsing in the function's own body had no coverage at all. This
    builds a real repo with a real second worktree and runs actual git."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    wt_dir = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", str(wt_dir), "-b", "wt-branch"],
                    cwd=repo, check=True)

    found = {p.resolve() for p in projects._git_worktrees(repo)}
    assert repo.resolve() in found
    assert wt_dir.resolve() in found


def test_git_worktrees_degrades_to_empty_when_not_a_repo(tmp_path):
    """Non-zero exit (no .git here) must degrade to [], never raise."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert projects._git_worktrees(plain) == []


def test_git_worktrees_degrades_to_empty_when_git_is_missing(tmp_path, monkeypatch):
    """A missing git binary raises FileNotFoundError from subprocess.run —
    the exact exception `_git_worktrees` must swallow, not re-raise."""
    def boom(*args, **kwargs):
        raise FileNotFoundError("git not found")
    monkeypatch.setattr(projects.subprocess, "run", boom)
    assert projects._git_worktrees(tmp_path) == []


# ── the cached discovery used on the dashboard's request path ───────────────

def test_a_slow_discovery_is_not_born_already_expired(tmp_home, monkeypatch):
    """The entry's life must be measured from *after* the discovery.

    Timed from before, a discovery that takes longer than the TTL stores an
    entry that expired before it was written — so the cache does nothing in
    exactly the slow-git case it exists for, and every request re-spawns git.
    """
    monkeypatch.setattr(projects, "_DISCOVERY_TTL_S", 0.3)
    calls = []
    real = projects.discover

    def slow(current_root=None, prune=True):
        calls.append(current_root)
        time.sleep(0.4)                       # longer than the TTL
        return real(current_root=current_root, prune=prune)

    monkeypatch.setattr(projects, "discover", slow)
    projects.invalidate_discovery_cache()
    projects.discover_cached()
    projects.discover_cached()
    assert len(calls) == 1
    projects.invalidate_discovery_cache()


def test_a_refresh_does_not_block_another_caller(tmp_home, monkeypatch):
    """`discover` spawns git (5s timeout) and opens a sqlite connection per
    candidate. Holding the map lock across that would serialize every
    project-named request in the process behind one slow subprocess — the
    blocking-operation-on-a-request-path hazard ThreadingHTTPServer exists to
    avoid. One thread refreshes; everyone else gets the previous answer.
    """
    monkeypatch.setattr(projects, "_DISCOVERY_TTL_S", 0.01)
    projects.invalidate_discovery_cache()
    projects.discover_cached()                # seed an entry, then let it age
    time.sleep(0.02)

    started, release = threading.Event(), threading.Event()
    real = projects.discover

    def blocking(current_root=None, prune=True):
        started.set()
        release.wait(10)
        return real(current_root=current_root, prune=prune)

    monkeypatch.setattr(projects, "discover", blocking)
    refresher = threading.Thread(target=projects.discover_cached, daemon=True)
    refresher.start()
    try:
        assert started.wait(5), "the refresher never got going"
        begin = time.monotonic()
        assert projects.discover_cached() is not None
        assert time.monotonic() - begin < 1.0
    finally:
        release.set()
        refresher.join(10)
        projects.invalidate_discovery_cache()


# ── Worktree grouping (display only) ────────────────────────────────────────
# Three checkouts of one repository are three projects with three databases,
# and they usually share a directory name — a flat switcher lists "exptrack,
# exptrack, exptrack" and the reader has to hover each row to find out which
# is which. The grouping is metadata on the listing and never decides which
# database a request reads.

def _repo_with_worktree(tmp_path):
    """A real repo plus a real linked worktree. Skips if git is unavailable."""
    main = tmp_path / "main"
    main.mkdir()

    def git(*args, cwd=main):
        return subprocess.run(["git", *args], cwd=str(cwd),
                              capture_output=True, text=True)

    if git("init", "-q", "-b", "trunk").returncode != 0:
        pytest.skip("git unavailable")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (main / "f.txt").write_text("x")
    git("add", "f.txt")
    git("commit", "-qm", "init")
    side = tmp_path / "side"
    if git("worktree", "add", "-q", "-b", "feat/x", str(side)).returncode != 0:
        pytest.skip("git worktree unavailable")
    return main, side


def test_worktree_rows_carry_the_branch(tmp_path):
    main, side = _repo_with_worktree(tmp_path)
    rows = {str(Path(r["path"]).resolve()): r["branch"]
            for r in projects._git_worktree_rows(main)}
    assert rows[str(main.resolve())] == "trunk"
    assert rows[str(side.resolve())] == "feat/x"


def test_siblings_of_one_repo_share_a_group(tmp_home, tmp_path):
    main, side = _repo_with_worktree(tmp_path)
    for root in (main, side):
        _make_project(root, _SCHEMA_VERSION)
        projects.register(root)

    entries = projects.annotate_worktree_groups(projects.discover())
    by_path = {e["path"]: e for e in entries}
    a, b = by_path[str(main.resolve())], by_path[str(side.resolve())]
    assert a["group"] and a["group"] == b["group"]
    # The repository's directory name, not the common dir's — a group headed
    # ".git" says nothing.
    assert a["group_name"] == "main"
    # The branch is the only thing that tells two same-named checkouts apart.
    assert {a["branch"], b["branch"]} == {"trunk", "feat/x"}


def test_a_lone_project_is_not_a_group_of_one(tmp_home, tmp_path):
    """Only the *main* checkout of a repo is registered, so it has no sibling
    in the list — a heading over a single row is noise, not structure."""
    main, _side = _repo_with_worktree(tmp_path)
    _make_project(main, _SCHEMA_VERSION)
    projects.register(main)
    other = tmp_path / "other"
    _make_project(other, _SCHEMA_VERSION)
    projects.register(other)

    for entry in projects.annotate_worktree_groups(projects.discover()):
        assert "group" not in entry


def test_grouping_degrades_to_a_flat_list_without_git(tmp_home, tmp_path,
                                                      monkeypatch):
    """No git, not a repo, an unreadable worktree list — the switcher renders
    exactly the flat list it always did rather than failing."""
    for name in ("a", "b"):
        root = tmp_path / name
        _make_project(root, _SCHEMA_VERSION)
        projects.register(root)
    monkeypatch.setattr(projects, "_run_git", lambda root, *args: None)

    entries = projects.annotate_worktree_groups(projects.discover())
    assert len(entries) == 2
    assert all("group" not in e for e in entries)


def test_grouping_is_skipped_past_the_probe_ceiling(monkeypatch):
    """One git subprocess per project is worth paying for three checkouts and
    not for thirty — a switcher with thirty projects is a different problem."""
    called = []
    monkeypatch.setattr(projects, "_run_git",
                        lambda root, *a: called.append(root) or None)
    entries = [{"path": f"/p{i}", "name": str(i)}
               for i in range(projects._GROUP_PROBE_MAX + 1)]
    projects.annotate_worktree_groups(entries)
    assert called == []


def test_the_request_path_never_writes_the_registry(tmp_home, tmp_path, monkeypatch):
    """`discover_cached` resolves a project id for every request that names
    one — including the 5s /api/metrics poll. Pruning there would make a
    user-global file a write on the dashboard's hot path, against the rule
    that only `exptrack init` and `exptrack ui start` write the registry."""
    gone = tmp_path / "gone"
    _make_project(gone, _SCHEMA_VERSION)
    projects.register(gone)
    import shutil
    shutil.rmtree(gone)
    writes = []
    monkeypatch.setattr(projects, "_write_registry",
                        lambda data: writes.append(data) or True)
    projects.invalidate_discovery_cache()

    # Hidden from the listing either way — the reader sees the same thing.
    assert projects.discover_cached() == []
    assert writes == [], "id resolution must not rewrite projects.json"

    # The surfaces that *show* the list are the ones that prune.
    assert projects.discover() == []
    assert writes and gone.name not in str(writes[-1])


def test_a_prune_does_not_throw_away_the_discovery_it_just_ran(tmp_home, tmp_path):
    """`_prune_registry` used to call `invalidate_discovery_cache()`, which
    bumps `_discovery_gen` — and `_finish_discovery` refuses to store a
    result whose generation moved, so the refresh that pruned was never
    cached. With a failed write (a read-only ~/.exptrack) that repeated on
    every single call, turning the 2s memo into no memo at all."""
    _make_project(tmp_path / "live", _SCHEMA_VERSION)
    projects.register(tmp_path / "live")
    gone = tmp_path / "gone"
    _make_project(gone, _SCHEMA_VERSION)
    projects.register(gone)
    import shutil
    shutil.rmtree(gone)
    projects.invalidate_discovery_cache()

    gen_before = projects._discovery_gen
    projects.discover()
    assert projects._discovery_gen == gen_before, "prune invalidated the cache"
