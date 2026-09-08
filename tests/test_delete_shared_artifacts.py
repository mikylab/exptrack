"""A delete must not take a file another run still references.

Artifacts are tracked **by reference** — the path, never a copy — so two runs
that write to the same path (a `logs/<date>/` folder, a fixed `results.json`, a
rerun after cleaning the directory out) each own an artifact row pointing at the
same file. Deleting the first run trashed that file, and the surviving run's
outputs went with it.

The claim rule already existed for directories (``output_dirs_owned_by``,
``linked_dirs_owned_by``) — "no other run may claim it" — and was simply absent
from the per-file loop, which is the one that runs for every ordinary artifact.
The preview had the same gap, so the confirm dialog counted and sized files the
delete had no business removing.
"""
from __future__ import annotations

import pytest


def _run_with_artifact(path, name):
    """A finished run whose only artifact is *path*."""
    from exptrack.core.experiment import Experiment
    exp = Experiment(name=name, script="train.py")
    exp.log_artifact(str(path))
    exp.finish()
    return exp


def _conn():
    from exptrack.core.db import get_db
    return get_db()


@pytest.fixture()
def two_runs_one_file(tmp_project):
    """Two runs both pointing at ``logs/out.txt`` — the reported situation."""
    shared = tmp_project / "logs" / "out.txt"
    shared.parent.mkdir(parents=True)
    shared.write_text("run one\n")
    first = _run_with_artifact(shared, "first")
    shared.write_text("run two\n")
    second = _run_with_artifact(shared, "second")
    return shared, first, second


def test_deleting_the_first_run_leaves_the_shared_file(two_runs_one_file):
    from exptrack.core.db import delete_experiment
    shared, first, second = two_runs_one_file

    delete_experiment(_conn(), first.id, delete_files=True)

    assert shared.is_file(), "the surviving run's file was trashed"
    assert shared.read_text() == "run two\n"


def test_the_note_says_why_the_file_was_left(two_runs_one_file, capsys):
    from exptrack.core.db import delete_experiment
    shared, first, second = two_runs_one_file

    delete_experiment(_conn(), first.id, delete_files=True)

    err = capsys.readouterr().err
    # The note names the run the file was kept for: "another experiment" is a
    # fact the user cannot act on, and the whole point of keeping the file is
    # that some other run needs it — say which.
    assert "out.txt" in err and "also used by" in err
    assert second.id[:6] in err


def test_the_last_run_holding_the_file_may_delete_it(two_runs_one_file):
    """The guard protects a *survivor's* file, not the file forever."""
    from exptrack.core.db import delete_experiment
    shared, first, second = two_runs_one_file

    delete_experiment(_conn(), first.id, delete_files=True)
    delete_experiment(_conn(), second.id, delete_files=True)

    assert not shared.exists()


def test_a_trashed_run_still_counts_as_a_claim(tmp_project):
    """Restore has to stay lossless, so a soft-deleted run's files are held."""
    from exptrack.core.db import delete_experiment, trash_experiment
    shared = tmp_project / "logs" / "out.txt"
    shared.parent.mkdir(parents=True)
    shared.write_text("x\n")
    first = _run_with_artifact(shared, "first")
    second = _run_with_artifact(shared, "second")

    trash_experiment(_conn(), second.id)
    delete_experiment(_conn(), first.id, delete_files=True)

    assert shared.is_file()


def test_an_unshared_file_is_still_trashed(tmp_project):
    from exptrack.core.db import delete_experiment
    mine = tmp_project / "logs" / "mine.txt"
    mine.parent.mkdir(parents=True)
    mine.write_text("x\n")
    exp = _run_with_artifact(mine, "only")

    delete_experiment(_conn(), exp.id, delete_files=True)

    assert not mine.exists()


# ---------------------------------------------------------------------------
# The preview must describe the delete that follows it
# ---------------------------------------------------------------------------

def test_preview_marks_a_shared_file_and_excludes_its_bytes(two_runs_one_file):
    from exptrack.core.db import get_delete_preview
    shared, first, second = two_runs_one_file

    preview = get_delete_preview(_conn(), first.id)

    entry = next(a for a in preview["artifacts"] if a["path"] == str(shared))
    assert entry["shared"] is True
    assert preview["artifacts_shared"] == 1
    # Sizing a file the delete leaves alone overstates what is about to be lost.
    assert preview["artifacts_existing"] == 0
    assert preview["artifact_bytes"] == 0


def test_preview_of_an_unshared_file_is_unchanged(tmp_project):
    from exptrack.core.db import get_delete_preview
    mine = tmp_project / "logs" / "mine.txt"
    mine.parent.mkdir(parents=True)
    mine.write_text("hello\n")
    exp = _run_with_artifact(mine, "only")

    preview = get_delete_preview(_conn(), exp.id)

    entry = next(a for a in preview["artifacts"] if a["path"] == str(mine))
    assert entry["shared"] is False
    assert preview["artifacts_shared"] == 0
    assert preview["artifacts_existing"] == 1
    assert preview["artifact_bytes"] > 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
