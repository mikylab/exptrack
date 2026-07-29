"""Tests for orphan/hanging-artifact cleanup and its data-loss guards.

Covers four regressions found in the orphans & hanging-artifacts audit:

1. ``api_clean_db`` used to ``shutil.rmtree`` every unclaimed directory under
   ``outputs/`` (and ``unlink`` every loose file) with no confirmation, no
   preview, and no OS-Trash copy — destroying the outputs of any run
   permanently deleted with ``delete_files=False``.
2. The two reset paths carried separate hardcoded table lists that both omitted
   ``code_snapshots``, ``sessions`` and ``session_nodes``, so "delete
   everything, cannot be undone" left full script sources and every notebook
   cell body/output in the database.
3. ``delete_experiment`` never reclaimed the content-addressed blobs a deleted
   run was the last referrer of, and no sweeper knew about those tables — a
   permanently-deleted run's script source and entire working-tree diff stayed
   readable forever.
4. ``exptrack ui --token`` persisted the auth secret into
   ``.exptrack/config.json``, which ``exptrack init`` declares committable and
   leaves out of ``.gitignore``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run_with_blobs(conn, name="r1"):
    """A finished run owning one code snapshot and one referenced git diff."""
    from exptrack.core.db import get_db, store_code_snapshot, store_git_diff
    from exptrack.core.experiment import Experiment

    exp = Experiment(name=name, script="train.py")
    conn = get_db()
    snap_hash = store_code_snapshot(
        conn, f'API_KEY = "sk-secret-{name}"\n', "script", f"/tmp/{name}.py")
    exp.log_param("_code_snapshot",
                  [{"hash": snap_hash, "kind": "script", "path": f"/tmp/{name}.py"}])
    ref = store_git_diff(conn, f"diff --git a/x b/x\n+SECRET_{name}=hunter2\n")
    conn.execute("UPDATE experiments SET git_diff=? WHERE id=?", (ref, exp.id))
    conn.commit()
    exp.finish()
    # finish() closes the cached connection — hand back a live one.
    return exp.id, snap_hash, ref[len("[ref:sha256:"):-1], get_db()


def _seed_session(conn):
    """A session + one node holding cell source and output."""
    conn.execute(
        "INSERT INTO sessions (id,name,notebook,status,created_at) "
        "VALUES ('s1','sess','nb.ipynb','active',1.0)")
    conn.execute(
        "INSERT INTO session_nodes "
        "(id,session_id,parent_id,node_type,label,cell_source,cell_outputs,seq,created_at) "
        "VALUES ('n1','s1',NULL,'root','root','PASSWORD = \"p\"','out',0,1.0)")
    conn.commit()


def _clean_args(**kwargs):
    defaults = dict(orphans=True, reset=False, baselines=False,
                    older_than=None, all_statuses=False, dry_run=False)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# 1. Clean-database never destroys files, and reports before touching any
# ---------------------------------------------------------------------------

def test_clean_db_does_not_touch_files_without_opt_in(tmp_project, db_conn):
    """The default POST reports orphaned paths and leaves the disk alone."""
    from exptrack.dashboard.routes.write_routes import api_clean_db

    orphan = tmp_project / "outputs" / "orphan_run"
    orphan.mkdir(parents=True)
    (orphan / "model.pt").write_bytes(b"weights")

    res = api_clean_db(db_conn, {})

    assert res["ok"]
    names = {o["name"] for o in res["orphan_files"]}
    assert "orphan_run" in names
    # Nothing removed, and the report carries enough detail to confirm against.
    assert orphan.is_dir()
    assert (orphan / "model.pt").exists()
    entry = next(o for o in res["orphan_files"] if o["name"] == "orphan_run")
    assert entry["is_dir"] and entry["files"] == 1 and entry["bytes"] == 7
    assert "output_paths" not in res["details"]


def test_clean_db_opt_in_trashes_instead_of_rmtree(tmp_project, db_conn, monkeypatch):
    """With delete_files=True the path is moved via _trash_or_local, not deleted."""
    from exptrack.core import db as core_db
    from exptrack.dashboard.routes.write_routes import api_clean_db

    orphan = tmp_project / "outputs" / "orphan_run"
    orphan.mkdir(parents=True)
    (orphan / "model.pt").write_bytes(b"weights")

    trashed = []
    monkeypatch.setattr(core_db, "_send_to_os_trash", lambda p: False)  # force local
    real = core_db._trash_or_local

    def spy(path, label="file"):
        trashed.append(str(path))
        return real(path, label)
    monkeypatch.setattr(core_db, "_trash_or_local", spy)

    res = api_clean_db(db_conn, {"delete_files": True})

    assert res["details"].get("output_paths") == 1
    assert str(orphan) in trashed
    assert not orphan.exists()
    # Recoverable: it landed in the local trash fallback, not oblivion.
    recovered = list((tmp_project / ".exptrack" / "trash").glob("*orphan_run"))
    assert len(recovered) == 1
    assert (recovered[0] / "model.pt").read_bytes() == b"weights"


def test_clean_db_preserves_files_of_run_deleted_with_files_kept(tmp_project, db_conn):
    """The exact data-loss case: permanent delete with delete_files=False, then Clean.

    The run is gone from `experiments`, so its output dir now reads as an
    orphan — the old unconditional rmtree silently reversed the user's explicit
    "keep my files" choice.
    """
    from exptrack.core.db import delete_experiment, get_db
    from exptrack.core.experiment import Experiment
    from exptrack.dashboard.routes.write_routes import api_clean_db

    exp = Experiment(name="keepme", script="train.py")
    out = tmp_project / "outputs" / "keepme"
    out.mkdir(parents=True)
    (out / "model.pt").write_bytes(b"expensive")
    exp.finish()

    conn = get_db()
    delete_experiment(conn, exp.id, delete_files=False)
    conn.commit()
    assert (out / "model.pt").exists(), "delete_files=False must keep files"

    api_clean_db(conn, {})  # the unconfirmed default path

    assert (out / "model.pt").read_bytes() == b"expensive"


def test_clean_db_reports_loose_files_but_keeps_them(tmp_project, db_conn):
    """A hand-placed file under outputs/ is reported, never unlinked."""
    from exptrack.dashboard.routes.write_routes import api_clean_db

    (tmp_project / "outputs").mkdir(exist_ok=True)
    stray = tmp_project / "outputs" / "NOTES.md"
    stray.write_text("my notes")

    res = api_clean_db(db_conn, {})

    assert "NOTES.md" in {o["name"] for o in res["orphan_files"]}
    assert stray.read_text() == "my notes"


def test_clean_db_only_trashes_the_paths_the_confirm_listed(tmp_project, db_conn):
    """The confirm dialog is built by a *previous* request.

    Anything that appears under outputs/ between the two calls must not be
    trashed — the user never saw it.
    """
    from exptrack.dashboard.routes.write_routes import api_clean_db

    (tmp_project / "outputs").mkdir(exist_ok=True)
    shown = tmp_project / "outputs" / "old_orphan"
    shown.mkdir()
    (shown / "junk.txt").write_text("junk")

    listed = api_clean_db(db_conn, {})["orphan_files"]
    assert {o["name"] for o in listed} == {"old_orphan"}

    # ... and now something new lands while the dialog is open.
    fresh = tmp_project / "outputs" / "brand_new"
    fresh.mkdir()
    (fresh / "ckpt.pt").write_bytes(b"precious")

    res = api_clean_db(db_conn, {"delete_files": True,
                                 "paths": [o["path"] for o in listed]})

    assert not shown.exists(), "the confirmed orphan should be trashed"
    assert (fresh / "ckpt.pt").read_bytes() == b"precious"
    assert res["skipped_unconfirmed"] == 1


def test_clean_db_without_paths_keeps_legacy_behaviour(tmp_project, db_conn):
    """An older client that sends no `paths` still gets discover-and-act."""
    from exptrack.dashboard.routes.write_routes import api_clean_db

    orphan = tmp_project / "outputs" / "orphan"
    orphan.mkdir(parents=True)
    (orphan / "junk.txt").write_text("junk")

    res = api_clean_db(db_conn, {"delete_files": True})

    assert not orphan.exists()
    assert res["skipped_unconfirmed"] == 0


def test_cli_clean_orphans_trashes_recoverably(tmp_project, monkeypatch, capsys):
    """`exptrack clean --orphans` moves orphans to trash rather than rmtree."""
    from exptrack.cli.mutate_cmds import cmd_clean
    from exptrack.core import db as core_db

    orphan = tmp_project / "outputs" / "orphan_run"
    orphan.mkdir(parents=True)
    (orphan / "junk.txt").write_text("junk")

    monkeypatch.setattr(core_db, "_send_to_os_trash", lambda p: False)
    monkeypatch.setattr("builtins.input", lambda *_: "y")

    cmd_clean(_clean_args())

    assert not orphan.exists()
    recovered = list((tmp_project / ".exptrack" / "trash").glob("*orphan_run"))
    assert len(recovered) == 1
    assert (recovered[0] / "junk.txt").read_text() == "junk"


# ---------------------------------------------------------------------------
# 2. Reset really clears everything
# ---------------------------------------------------------------------------

def test_reset_all_tables_covers_snapshots_and_sessions(tmp_project, db_conn):
    """The shared reset list includes the tables both old lists forgot."""
    from exptrack.core.db import _RESET_TABLES

    for t in ("code_snapshots", "sessions", "session_nodes"):
        assert t in _RESET_TABLES, f"{t} missing from reset list"
    # session_nodes must precede sessions: FKs are ON, so the child goes first.
    assert _RESET_TABLES.index("session_nodes") < _RESET_TABLES.index("sessions")


def test_api_reset_db_leaves_no_source_behind(tmp_project, db_conn):
    """Reset erases code snapshots and whole session trees, not just runs."""
    from exptrack.core.db import get_db
    from exptrack.dashboard.routes.write_routes import api_reset_db

    _, _, _, conn = _make_run_with_blobs(db_conn)
    _seed_session(conn)
    assert conn.execute("SELECT COUNT(*) FROM code_snapshots").fetchone()[0] > 0

    res = api_reset_db(conn)
    assert res["ok"]

    conn = get_db()
    for table in ("experiments", "params", "metrics", "timeline",
                  "code_snapshots", "git_diffs", "sessions", "session_nodes"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert n == 0, f"{table} still holds {n} row(s) after reset"


def test_cli_reset_leaves_no_source_behind(tmp_project, db_conn, monkeypatch):
    """`exptrack clean --reset` clears the same tables as the dashboard."""
    from exptrack.cli.mutate_cmds import cmd_clean
    from exptrack.core.db import get_db

    _, _, _, conn = _make_run_with_blobs(db_conn)
    _seed_session(conn)

    monkeypatch.setattr("builtins.input", lambda *_: "y")
    monkeypatch.setattr("exptrack.core.db._send_to_os_trash", lambda p: False)
    cmd_clean(_clean_args(orphans=False, reset=True))

    conn = get_db()
    for table in ("experiments", "code_snapshots", "sessions", "session_nodes"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert n == 0, f"{table} still holds {n} row(s) after --reset"


def test_reset_trashes_outputs_recoverably(tmp_project, db_conn, monkeypatch):
    """A reset moves output dirs to Trash instead of rmtree-ing them."""
    from exptrack.dashboard.routes.write_routes import api_reset_db

    out = tmp_project / "outputs" / "run1"
    out.mkdir(parents=True)
    (out / "model.pt").write_bytes(b"weights")
    monkeypatch.setattr("exptrack.core.db._send_to_os_trash", lambda p: False)

    api_reset_db(db_conn)

    assert not out.exists()
    recovered = list((tmp_project / ".exptrack" / "trash").glob("*run1"))
    assert len(recovered) == 1
    assert (recovered[0] / "model.pt").read_bytes() == b"weights"


# ---------------------------------------------------------------------------
# 3. Content-addressed blobs are refcounted and reclaimed
# ---------------------------------------------------------------------------

def test_permanent_delete_reclaims_snapshot_and_diff(tmp_project, db_conn):
    """A deleted run's source snapshot and diff body do not survive it."""
    from exptrack.core.db import delete_experiment, get_db

    exp_id, snap_hash, diff_hash, conn = _make_run_with_blobs(db_conn)
    assert conn.execute("SELECT COUNT(*) FROM code_snapshots WHERE hash=?",
                        (snap_hash,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM git_diffs WHERE diff_hash=?",
                        (diff_hash,)).fetchone()[0] == 1

    delete_experiment(conn, exp_id, delete_files=False)
    conn.commit()

    conn = get_db()
    assert conn.execute("SELECT COUNT(*) FROM code_snapshots WHERE hash=?",
                        (snap_hash,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM git_diffs WHERE diff_hash=?",
                        (diff_hash,)).fetchone()[0] == 0


def test_soft_delete_keeps_blobs_so_restore_is_lossless(tmp_project, db_conn):
    """Trashing a run must not drop its blobs — Restore has to be lossless."""
    from exptrack.core.db import (
        get_db,
        restore_experiment,
        sweep_orphans,
        trash_experiment,
    )
    from exptrack.core.queries import _script_snapshot_source

    exp_id, snap_hash, diff_hash, conn = _make_run_with_blobs(db_conn)

    trash_experiment(conn, exp_id)
    conn.commit()
    sweep_orphans(conn)  # a sweep while trashed must not collect them

    conn = get_db()
    assert conn.execute("SELECT COUNT(*) FROM code_snapshots WHERE hash=?",
                        (snap_hash,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM git_diffs WHERE diff_hash=?",
                        (diff_hash,)).fetchone()[0] == 1

    restore_experiment(conn, exp_id)
    conn.commit()
    assert "sk-secret" in (_script_snapshot_source(conn, exp_id) or "")


def test_shared_blob_survives_while_another_run_refers_to_it(tmp_project, db_conn):
    """Content-addressed dedup: deleting one of two referrers keeps the blob."""
    from exptrack.core.db import delete_experiment, get_db, store_code_snapshot
    from exptrack.core.experiment import Experiment

    conn = db_conn
    shared = store_code_snapshot(conn, "shared source\n", "script", "/tmp/s.py")
    conn.commit()  # close the implicit txn before Experiment() BEGINs its own
    ids = []
    for name in ("a", "b"):
        exp = Experiment(name=name, script="train.py")
        exp.log_param("_code_snapshot",
                      [{"hash": shared, "kind": "script", "path": "/tmp/s.py"}])
        exp.finish()
        ids.append(exp.id)

    conn = get_db()
    delete_experiment(conn, ids[0], delete_files=False)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM code_snapshots WHERE hash=?",
                        (shared,)).fetchone()[0] == 1, "still referenced by run b"

    delete_experiment(conn, ids[1], delete_files=False)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM code_snapshots WHERE hash=?",
                        (shared,)).fetchone()[0] == 0, "last referrer gone"


def test_sweep_orphans_reclaims_stranded_blobs(tmp_project, db_conn):
    """The sweeper knows about both blob tables (it previously reported {})."""
    from exptrack.core.db import store_code_snapshot, store_git_diff, sweep_orphans

    conn = db_conn
    store_code_snapshot(conn, "stranded source\n", "script", "/tmp/x.py")
    store_git_diff(conn, "diff --git a/y b/y\n+stranded\n")
    conn.commit()

    counts = sweep_orphans(conn)

    assert counts.get("code_snapshots") == 1
    assert counts.get("git_diffs") == 1
    assert conn.execute("SELECT COUNT(*) FROM code_snapshots").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM git_diffs").fetchone()[0] == 0


def test_session_node_diff_ref_is_not_swept(tmp_project, db_conn):
    """A diff referenced only by a session node must survive the sweep."""
    from exptrack.core.db import store_git_diff, sweep_orphans

    conn = db_conn
    ref = store_git_diff(conn, "diff --git a/z b/z\n+node diff\n")
    _seed_session(conn)
    conn.execute("UPDATE session_nodes SET git_diff=? WHERE id='n1'", (ref,))
    conn.commit()

    sweep_orphans(conn)

    assert conn.execute("SELECT COUNT(*) FROM git_diffs").fetchone()[0] == 1


@pytest.mark.parametrize("value", [
    # Native list (script_tracking) …
    json.dumps([{"hash": "0123456789abcdef", "kind": "script", "path": "/a.py"}]),
    # … double-encoded legacy rows …
    json.dumps(json.dumps([{"hash": "0123456789abcdef", "kind": "script"}])),
    # … and the pipeline's pre-encoded string form.
    json.dumps([{"hash": "0123456789abcdef", "kind": "shellscript"}]),
])
def test_snapshot_refs_recognised_in_every_param_shape(tmp_project, db_conn, value):
    """Every historical `_code_snapshot` encoding must count as a reference.

    Under-retention here would destroy a run's only copy of its source, so the
    extractor has to recognise all three shapes this param has had.
    """
    from exptrack.core.db import _referenced_snapshot_hashes

    conn = db_conn
    conn.execute(
        "INSERT INTO experiments (id,name,created_at,updated_at) "
        "VALUES ('e1','shapes','2026-01-01T00:00:00','2026-01-01T00:00:00')")
    conn.execute(
        "INSERT INTO params (exp_id,key,value,source) VALUES ('e1','_code_snapshot',?,'auto')",
        (value,))
    conn.commit()

    assert "0123456789abcdef" in _referenced_snapshot_hashes(conn)


# ---------------------------------------------------------------------------
# 4. The dashboard token stays out of the committable config
# ---------------------------------------------------------------------------

def test_ui_token_written_to_gitignored_file_not_config(tmp_project):
    """`exptrack ui --token` writes .exptrack/dashboard_token, not config.json."""
    from exptrack import config as cfg
    from exptrack.cli.admin_cmds import cmd_ui
    from exptrack.config import token_file_path
    from exptrack.dashboard.handler import _get_auth_token

    args = SimpleNamespace(host="127.0.0.1", port=7331, no_auth=False,
                           token="s3cret-token", clear_token=False)
    # Stop before the blocking serve_forever() — only the token side effect matters.
    import exptrack.dashboard.app as app
    orig = app.main
    app.main = lambda **kw: None
    try:
        cmd_ui(args)
    finally:
        app.main = orig

    tf = token_file_path()
    assert tf.is_file()
    assert tf.read_text().strip() == "s3cret-token"
    assert "dashboard_token" not in cfg.reload()
    assert "dashboard_token" not in cfg.config_path().read_text()
    assert _get_auth_token() == "s3cret-token"


def test_token_file_is_gitignored_and_private(tmp_path, monkeypatch):
    """init's .gitignore covers the token file and the local trash dir."""
    import os
    import stat

    from exptrack import config as cfg
    from exptrack.config import token_file_path

    monkeypatch.setattr(cfg, "_root_cache", None, raising=False)
    monkeypatch.chdir(tmp_path)
    cfg.init(project_name="t", here=True)

    ignored = (tmp_path / ".gitignore").read_text()
    assert ".exptrack/dashboard_token" in ignored
    assert ".exptrack/trash/" in ignored

    import exptrack.dashboard.app as app
    from exptrack.cli.admin_cmds import cmd_ui
    orig, app.main = app.main, lambda **kw: None
    try:
        cmd_ui(SimpleNamespace(host="127.0.0.1", port=7331, no_auth=False,
                               token="abc", clear_token=False))
    finally:
        app.main = orig

    mode = stat.S_IMODE(os.stat(token_file_path()).st_mode)
    assert mode == 0o600, f"token file mode is {oct(mode)}, expected 0o600"


def test_legacy_config_token_still_honored_and_flagged(tmp_project, capsys):
    """An existing config.json token keeps working but is warned about."""
    from exptrack import config as cfg
    from exptrack.dashboard.app import _warn_if_token_in_config
    from exptrack.dashboard.handler import _get_auth_token

    conf = cfg.load()
    conf["dashboard_token"] = "legacy-token"
    cfg.save(conf)

    assert _get_auth_token() == "legacy-token"
    _warn_if_token_in_config()
    err = capsys.readouterr().err
    assert "committable" in err and "config.json" in err


def test_token_file_wins_over_legacy_config(tmp_project):
    """Precedence: the gitignored token file beats the legacy config key."""
    from exptrack import config as cfg
    from exptrack.config import token_file_path
    from exptrack.dashboard.handler import _get_auth_token

    conf = cfg.load()
    conf["dashboard_token"] = "legacy-token"
    cfg.save(conf)
    token_file_path().write_text("file-token\n")

    assert _get_auth_token() == "file-token"


def test_clear_token_removes_both_locations(tmp_project, capsys):
    """--clear-token clears the file *and* the legacy config key."""
    from exptrack import config as cfg
    from exptrack.cli.admin_cmds import cmd_ui
    from exptrack.config import token_file_path
    from exptrack.dashboard.handler import _get_auth_token

    conf = cfg.load()
    conf["dashboard_token"] = "legacy-token"
    cfg.save(conf)
    token_file_path().write_text("file-token\n")

    import exptrack.dashboard.app as app
    orig, app.main = app.main, lambda **kw: None
    try:
        cmd_ui(SimpleNamespace(host="127.0.0.1", port=7331, no_auth=False,
                               token=None, clear_token=True))
    finally:
        app.main = orig

    assert not token_file_path().exists()
    assert "dashboard_token" not in cfg.reload()
    assert _get_auth_token() == ""


# ---------------------------------------------------------------------------
# Sweep/reclaim contracts introduced by the cleanup refactor
# ---------------------------------------------------------------------------

def test_close_db_sweep_skips_the_expensive_blob_tables(tmp_project, db_conn):
    """The per-CLI-exit sweep must not pay for the refcounted blob scans.

    They can only go stale after a delete, and `delete_experiment` reclaims
    them inline — so scanning on every `exptrack` command exit bought a
    guaranteed zero result.
    """
    from exptrack.core.db import _sweep_orphans, store_code_snapshot, store_git_diff

    conn = db_conn
    h = store_code_snapshot(conn, "stranded\n", "script", "/tmp/x.py")
    store_git_diff(conn, "diff --git a/y b/y\n+stranded\n")
    conn.commit()

    _sweep_orphans(conn)  # the close_db path

    assert conn.execute("SELECT COUNT(*) FROM code_snapshots").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM git_diffs").fetchone()[0] == 1
    # ...while the explicit sweep still reclaims them.
    from exptrack.core.db import sweep_orphans
    assert sweep_orphans(conn).get("code_snapshots") == 1
    assert conn.execute("SELECT COUNT(*) FROM code_snapshots WHERE hash=?",
                        (h,)).fetchone()[0] == 0


def test_count_orphans_matches_what_the_sweep_removes(tmp_project, db_conn):
    """The dry-run preview and the deletion are built from the same specs."""
    from exptrack.core.db import count_orphans, store_code_snapshot, sweep_orphans

    conn = db_conn
    store_code_snapshot(conn, "stranded\n", "script", "/tmp/x.py")
    conn.commit()
    # An orphaned child row needs FKs off — that is exactly the state a
    # hand-edited DB or an older writer can leave behind.
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("INSERT INTO params (exp_id,key,value) VALUES ('ghost','lr','0.1')")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")

    preview = count_orphans(conn)
    assert preview.get("params") == 1
    assert preview.get("code_snapshots") == 1

    assert sweep_orphans(conn) == preview, "preview promised a different set"
    assert count_orphans(conn) == {}, "nothing left after the sweep"


def test_batched_delete_reclaims_blobs_once(tmp_project, db_conn):
    """reclaim_blobs=False defers to one sweep without leaking blobs."""
    from exptrack.core.db import _sweep_blobs, delete_experiment, get_db

    ids, hashes = [], []
    for name in ("a", "b"):
        eid, h, _, _ = _make_run_with_blobs(db_conn, name)
        ids.append(eid)
        hashes.append(h)

    conn = get_db()
    for eid in ids:
        delete_experiment(conn, eid, delete_files=False, reclaim_blobs=False)
    # Deferred: still present until the batch sweep runs.
    assert conn.execute("SELECT COUNT(*) FROM code_snapshots").fetchone()[0] == 2
    _sweep_blobs(conn)
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM code_snapshots").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM git_diffs").fetchone()[0] == 0


def test_clean_orphans_dry_run_reports_blobs_it_would_remove(tmp_project, db_conn,
                                                             capsys):
    """`--dry-run` must describe the blobs too, and must not delete them.

    The blob counts used to be discovered *after* the dry-run return and the
    confirm, so the preview described a different set than the run performed —
    and a project whose only orphans were blobs hit "No orphaned data found"
    and could never reclaim them.
    """
    from exptrack.cli.mutate_cmds import cmd_clean
    from exptrack.core.db import get_db, store_code_snapshot

    conn = db_conn
    store_code_snapshot(conn, "stranded\n", "script", "/tmp/x.py")
    conn.commit()

    cmd_clean(_clean_args(dry_run=True))
    err = capsys.readouterr().err
    assert "code_snapshots" in err
    assert "No orphaned data found" not in err
    assert get_db().execute("SELECT COUNT(*) FROM code_snapshots").fetchone()[0] == 1


def test_clean_orphans_reclaims_blob_only_orphans(tmp_project, db_conn, monkeypatch):
    """Confirming the prompt actually removes the previewed blobs."""
    from exptrack.cli.mutate_cmds import cmd_clean
    from exptrack.core.db import get_db, store_code_snapshot

    conn = db_conn
    store_code_snapshot(conn, "stranded\n", "script", "/tmp/x.py")
    conn.commit()
    monkeypatch.setattr("builtins.input", lambda *_: "y")

    cmd_clean(_clean_args())

    assert get_db().execute("SELECT COUNT(*) FROM code_snapshots").fetchone()[0] == 0


def test_gitignore_rules_established_when_the_token_is_written(tmp_path, monkeypatch):
    """A project initialized before the token moved must still get the rule.

    `write_token` claims the file is gitignored, so it has to establish that
    rule rather than rely on `init` having written it.
    """
    from exptrack import config as cfg

    monkeypatch.setattr(cfg, "_root_cache", None, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".exptrack").mkdir()
    cfg.save(dict(cfg.DEFAULTS))
    # An old .gitignore with only the pre-token rules.
    (tmp_path / ".gitignore").write_text(".exptrack/experiments.db\n")

    cfg.write_token("abc")

    ignored = (tmp_path / ".gitignore").read_text()
    assert ".exptrack/dashboard_token" in ignored
    assert ".exptrack/trash/" in ignored
    # Additive only — the pre-existing rule survives, and re-running is a no-op.
    assert ".exptrack/experiments.db" in ignored
    assert cfg.ensure_gitignore_rules() is False


# ---------------------------------------------------------------------------
# 5. A permanent delete never removes another run's output directory
# ---------------------------------------------------------------------------

def _rename(conn, exp_id, new_name):
    """The dashboard rename path: update the row + move the folder."""
    from exptrack.core.db import rename_output_folder
    old = conn.execute("SELECT name FROM experiments WHERE id=?",
                       (exp_id,)).fetchone()["name"]
    conn.execute("UPDATE experiments SET name=? WHERE id=?", (new_name, exp_id))
    rename_output_folder(conn, exp_id, old, new_name)
    conn.commit()


def test_permanent_delete_spares_a_duplicate_named_runs_outputs(tmp_project, db_conn):
    """Names are not unique, so `outputs/<name>` may belong to a different run.

    `rename_output_folder` refuses to move onto an existing directory, so after
    renaming A to B's name only B owns `outputs/<name>` — deleting A used to
    trash it anyway.
    """
    from exptrack.core.db import delete_experiment, get_db
    from exptrack.core.experiment import Experiment

    keeper = Experiment(name="baseline", script="train.py")
    keep_dir = tmp_project / "outputs" / "baseline"
    keep_dir.mkdir(parents=True, exist_ok=True)
    (keep_dir / "model.pt").write_bytes(b"expensive")
    keeper.finish()

    doomed = Experiment(name="scratch", script="train.py")
    doomed_dir = tmp_project / "outputs" / "scratch"
    doomed_dir.mkdir(parents=True, exist_ok=True)
    (doomed_dir / "tmp.pt").write_bytes(b"junk")
    doomed.finish()

    conn = get_db()
    _rename(conn, doomed.id, "baseline")  # collides; the folder does not move

    stats = delete_experiment(conn, doomed.id, delete_files=True)
    conn.commit()

    assert (keep_dir / "model.pt").read_bytes() == b"expensive", \
        "deleting one run must not trash another run's output directory"
    assert not doomed_dir.exists(), "the run's own output dir should still go"
    assert stats["os_trash"] + stats["local_trash"] >= 1


def test_delete_preview_sizes_only_the_dirs_the_delete_will_take(tmp_project, db_conn):
    """The dialog must not quote bytes belonging to a run it will not touch."""
    from exptrack.core.db import get_db, get_delete_preview
    from exptrack.core.experiment import Experiment

    keeper = Experiment(name="baseline", script="train.py")
    keep_dir = tmp_project / "outputs" / "baseline"
    keep_dir.mkdir(parents=True, exist_ok=True)
    (keep_dir / "model.pt").write_bytes(b"x" * 5000)
    keeper.finish()

    doomed = Experiment(name="scratch", script="train.py")
    doomed.finish()

    conn = get_db()
    conn.execute("UPDATE experiments SET name='baseline', output_dir=NULL WHERE id=?",
                 (doomed.id,))
    conn.commit()

    prev = get_delete_preview(conn, doomed.id)

    assert prev["output_dir_bytes"] == 0
    assert prev["output_dir_files"] == 0


def test_a_trashed_runs_outputs_still_count_as_claimed(tmp_project, db_conn):
    """Restore has to stay lossless, so a soft-deleted run keeps its claim."""
    from exptrack.core.db import (
        delete_experiment,
        get_db,
        output_dirs_owned_by,
        trash_experiment,
    )
    from exptrack.core.experiment import Experiment

    keeper = Experiment(name="baseline", script="train.py")
    keep_dir = tmp_project / "outputs" / "baseline"
    keep_dir.mkdir(parents=True, exist_ok=True)
    (keep_dir / "model.pt").write_bytes(b"expensive")
    keeper.finish()

    doomed = Experiment(name="scratch", script="train.py")
    doomed.finish()

    conn = get_db()
    trash_experiment(conn, keeper.id)
    conn.execute("UPDATE experiments SET name='baseline', output_dir=NULL WHERE id=?",
                 (doomed.id,))
    conn.commit()

    assert output_dirs_owned_by(conn, doomed.id, "baseline", None) == []

    delete_experiment(conn, doomed.id, delete_files=True)
    conn.commit()
    assert (keep_dir / "model.pt").read_bytes() == b"expensive"


def test_the_only_claimant_still_gets_its_outputs_deleted(tmp_project, db_conn):
    """The guard must not turn every delete into a no-op."""
    from exptrack.core.db import delete_experiment, get_db
    from exptrack.core.experiment import Experiment

    exp = Experiment(name="solo", script="train.py")
    out = tmp_project / "outputs" / "solo"
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.pt").write_bytes(b"junk")
    exp.finish()

    conn = get_db()
    conn.execute("UPDATE experiments SET output_dir=NULL WHERE id=?", (exp.id,))
    conn.commit()

    delete_experiment(conn, exp.id, delete_files=True)
    conn.commit()

    assert not out.exists(), "the name-derived dir is still ours when nobody else claims it"


def test_a_dir_the_delete_protects_is_not_reported_as_an_orphan(tmp_project, db_conn):
    """One claim rule, or the guarantee is undone one button over.

    `output_dirs_owned_by` refuses to trash a directory another run claims; if
    `find_orphan_output_paths` used a different rule and called that same
    directory debris, the next Clean click would trash it anyway.
    """
    from exptrack.core.db import (
        find_orphan_output_paths,
        get_db,
        output_dirs_owned_by,
    )
    from exptrack.core.experiment import Experiment

    keeper = Experiment(name="baseline", script="train.py")
    keep_dir = tmp_project / "outputs" / "baseline"
    keep_dir.mkdir(parents=True, exist_ok=True)
    (keep_dir / "model.pt").write_bytes(b"expensive")
    keeper.finish()

    doomed = Experiment(name="scratch", script="train.py")
    doomed.finish()

    conn = get_db()
    conn.execute("UPDATE experiments SET name='baseline', output_dir=NULL WHERE id=?",
                 (doomed.id,))
    conn.commit()

    protected = output_dirs_owned_by(conn, doomed.id, "baseline", None)
    orphans = {str(p) for p in find_orphan_output_paths(conn)}

    assert protected == [], "another run claims it, so the delete must skip it"
    assert str(keep_dir) not in orphans, "…and Clean must not call it debris"
