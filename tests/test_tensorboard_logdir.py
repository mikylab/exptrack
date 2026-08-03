"""TensorBoard log directories are recorded, and cleaned up with the run.

`SummaryWriter()` with no `log_dir` creates `runs/<timestamp>_<hostname>/`
itself — a directory named and created entirely by PyTorch. exptrack mirrored
the *values* written to it but never recorded *where*, so those trees were
invisible to every storage report and untouched by every delete, and a project
accumulated one per run with nothing anywhere accounting for them.

Removing a whole directory is far less forgiving than removing a file, so the
ownership guards below are the point of this file.
"""
import pytest

from exptrack.capture.tensorboard_patch import (
    _TB_DIR_LABEL,
    _record_log_dir,
    _writer_log_dir,
)
from exptrack.core.db import get_db, get_delete_preview, linked_dirs_owned_by


class _Writer:
    """Stand-in for SummaryWriter — the real one needs torch."""
    def __init__(self, log_dir):
        self.log_dir = str(log_dir)


class _WriterX:
    """tensorboardX has carried `logdir` and `get_logdir()` across versions."""
    def __init__(self, logdir):
        self.logdir = str(logdir)


class _WriterGetter:
    def __init__(self, d):
        self._d = str(d)

    def get_logdir(self):
        return self._d


def _exp(conn, exp_id):
    conn.execute(
        "INSERT INTO experiments (id, name, status, created_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (exp_id, exp_id, "done", "2026-08-01T00:00:00", "2026-08-01T00:00:00"))
    conn.commit()
    return exp_id


def _link(conn, exp_id, path):
    conn.execute(
        "INSERT INTO artifacts (exp_id, label, path, created_at) VALUES (?,?,?,?)",
        (exp_id, _TB_DIR_LABEL, str(path), "2026-08-01T00:00:00"))
    conn.commit()


@pytest.fixture
def conn(tmp_project):
    return get_db()


# ── Finding the writer's directory ───────────────────────────────────────────

def test_log_dir_read_from_every_writer_dialect():
    """torch exposes log_dir, tensorboardX has carried logdir and get_logdir()."""
    assert _writer_log_dir(_Writer("runs/a")) == "runs/a"
    assert _writer_log_dir(_WriterX("runs/b")) == "runs/b"
    assert _writer_log_dir(_WriterGetter("runs/c")) == "runs/c"
    assert _writer_log_dir(object()) is None


def test_writer_construction_records_the_dir(tmp_project, conn, monkeypatch):
    from exptrack.capture import tensorboard_patch as tbp
    from exptrack.core import Experiment
    d = tmp_project / "runs" / "Aug01_12-00-00_host"
    d.mkdir(parents=True)
    exp = Experiment(name="tb")
    monkeypatch.setattr(tbp, "_active_exp", exp)      # what patch_tensorboard sets
    _record_log_dir(_Writer(d))
    row = conn.execute(
        "SELECT label, path FROM artifacts WHERE exp_id=? AND label=?",
        (exp.id, _TB_DIR_LABEL)).fetchone()
    assert row is not None
    assert row["path"] == str(d.resolve())


def test_recording_is_deduped_and_needs_no_active_run(tmp_project, conn, monkeypatch):
    """Reopening a writer on one dir records it once; no run ⇒ silent no-op."""
    from exptrack.capture import tensorboard_patch as tbp
    from exptrack.core import Experiment
    d = tmp_project / "runs" / "same"
    d.mkdir(parents=True)
    exp = Experiment(name="dedup")
    monkeypatch.setattr(tbp, "_active_exp", exp)
    _record_log_dir(_Writer(d))
    _record_log_dir(_Writer(d))
    n = conn.execute(
        "SELECT COUNT(*) FROM artifacts WHERE exp_id=? AND label=?",
        (exp.id, _TB_DIR_LABEL)).fetchone()[0]
    assert n == 1

    # No active run: nothing is recorded, and nothing raises.
    monkeypatch.setattr(tbp, "_active_exp", None)
    _record_log_dir(_Writer(tmp_project / "runs" / "orphan"))


# ── Ownership: what a delete may actually remove ─────────────────────────────

def test_a_linked_dir_is_owned_and_removable(tmp_project, conn):
    _exp(conn, "solo")
    d = tmp_project / "runs" / "solo_logs"
    d.mkdir(parents=True)
    _link(conn, "solo", d)
    assert [str(p) for p in linked_dirs_owned_by(conn, "solo")] == [str(d)]


def test_a_dir_another_run_links_is_left_alone(tmp_project, conn):
    """`SummaryWriter("runs/sweep")` in a loop is normal — trashing it with the
    first delete would take the surviving runs' logs."""
    _exp(conn, "one")
    _exp(conn, "two")
    shared = tmp_project / "runs" / "sweep"
    shared.mkdir(parents=True)
    _link(conn, "one", shared)
    _link(conn, "two", shared)
    assert linked_dirs_owned_by(conn, "one") == []
    assert linked_dirs_owned_by(conn, "two") == []


def test_a_dir_outside_the_project_is_never_removed(tmp_project, conn, tmp_path):
    """A shared ~/tb-logs belongs to the user, not to this project."""
    _exp(conn, "outside")
    # tmp_project IS tmp_path, so go up a level for a genuinely outside tree.
    far = tmp_path.parent / "elsewhere_tb_logs"
    far.mkdir(parents=True, exist_ok=True)
    _link(conn, "outside", far)
    assert linked_dirs_owned_by(conn, "outside") == []


def test_the_project_root_itself_is_never_removed(tmp_project, conn):
    """A stray SummaryWriter(log_dir=".") records the project directory —
    nothing exptrack does may trash a user's whole project."""
    _exp(conn, "root")
    _link(conn, "root", tmp_project)
    assert linked_dirs_owned_by(conn, "root") == []
    _exp(conn, "above")
    _link(conn, "above", tmp_project.parent)
    assert linked_dirs_owned_by(conn, "above") == []


# ── The confirm dialog describes the delete ──────────────────────────────────

def test_delete_preview_names_and_sizes_the_linked_dir(tmp_project, conn):
    """The preview and the delete share linked_dirs_owned_by, so the dialog can
    never size a directory the delete leaves alone (or the reverse)."""
    _exp(conn, "prev")
    d = tmp_project / "runs" / "prev_logs"
    d.mkdir(parents=True)
    (d / "events.out.tfevents.1").write_text("x" * 100)
    _link(conn, "prev", d)
    p = get_delete_preview(conn, "prev")
    assert [x["path"] for x in p["linked_dirs"]] == [str(d)]
    assert p["linked_dir_files"] == 1
    assert p["linked_dir_bytes"] == 100
    # Not folded into the output-dir total, which would double-count it.
    assert p["output_dir_bytes"] == 0


def test_preview_omits_a_dir_the_delete_will_not_touch(tmp_project, conn):
    _exp(conn, "a")
    _exp(conn, "b")
    shared = tmp_project / "runs" / "shared"
    shared.mkdir(parents=True)
    (shared / "f").write_text("data")
    _link(conn, "a", shared)
    _link(conn, "b", shared)
    assert get_delete_preview(conn, "a")["linked_dirs"] == []


def test_delete_trashes_the_linked_dir(tmp_project, conn):
    from exptrack.core.db import delete_experiment
    _exp(conn, "gone")
    d = tmp_project / "runs" / "gone_logs"
    d.mkdir(parents=True)
    (d / "events").write_text("x")
    _link(conn, "gone", d)
    delete_experiment(conn, "gone", delete_files=True)
    conn.commit()
    assert not d.exists()


def test_soft_delete_leaves_the_linked_dir_in_place(tmp_project, conn):
    """Restore has to stay lossless."""
    from exptrack.core.db import trash_experiment
    _exp(conn, "soft")
    d = tmp_project / "runs" / "soft_logs"
    d.mkdir(parents=True)
    _link(conn, "soft", d)
    trash_experiment(conn, "soft")
    conn.commit()
    assert d.is_dir()
