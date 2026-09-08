"""How Compare decides that two runs' images are the same plot.

Compare grouped images by ``label || basename``, which is exactly right when
both runs wrote ``loss.png`` and useless the moment the filename carries the
epoch, the step or a timestamp — ``loss_epoch10.png`` and ``loss_epoch12.png``
are the same plot and paired with nothing, so the grid showed each run's images
in a column of their own. "Sometimes they line up, sometimes they don't" is that
rule meeting two different naming habits.

And because artifacts are tracked by reference, two runs writing to the *same*
path share one file on disk: whatever is there now is whichever run wrote last.
Rendering it in both columns as though it were each run's own output is the one
outcome worse than not pairing at all, so it is stated.
"""
from __future__ import annotations

import pytest


def _conn():
    from exptrack.core.db import get_db
    return get_db()


def _run(name, files, tmp_project):
    from exptrack.core.experiment import Experiment
    exp = Experiment(name=name, script="train.py")
    for f in files:
        p = tmp_project / f
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(b"\x89PNG\r\n")
        exp.log_artifact(str(p))
    exp.finish()
    return exp


def _groups(runs):
    """{group: {exp_id: [paths]}} as the compare grid would build it."""
    out: dict = {}
    for r in runs:
        for img in r["images"]:
            out.setdefault(img["group"], {}).setdefault(r["id"], []).append(img)
    return out


# ---------------------------------------------------------------------------
# The normalization rule on its own
# ---------------------------------------------------------------------------

def test_normalized_stem_drops_digit_runs():
    from exptrack.core.queries import normalized_image_stem
    assert normalized_image_stem("loss_epoch10.png") == \
           normalized_image_stem("loss_epoch12.png")
    assert normalized_image_stem("cm_20260831_121500.png") == \
           normalized_image_stem("cm_20260101_000000.png")
    assert normalized_image_stem("loss.png") != normalized_image_stem("acc.png")


def test_normalization_is_case_and_separator_insensitive():
    from exptrack.core.queries import normalized_image_stem
    assert normalized_image_stem("Loss-Curve.png") == \
           normalized_image_stem("loss_curve.png")


# ---------------------------------------------------------------------------
# Pairing across runs
# ---------------------------------------------------------------------------

def test_identical_filenames_still_pair_exactly(tmp_project):
    """The rule that already worked must keep working, unchanged."""
    from exptrack.core.queries import get_multi_compare
    a = _run("a", ["outputs/a/loss.png"], tmp_project)
    b = _run("b", ["outputs/b/loss.png"], tmp_project)

    runs = get_multi_compare(_conn(), [a.id, b.id])
    groups = _groups(runs)
    assert len(groups) == 1
    assert set(next(iter(groups.values()))) == {a.id, b.id}
    assert next(iter(groups)) == "loss.png"


def test_step_suffixed_filenames_pair(tmp_project):
    """The reported case: same plot, filename carries the epoch."""
    from exptrack.core.queries import get_multi_compare
    a = _run("a", ["outputs/a/loss_epoch10.png"], tmp_project)
    b = _run("b", ["outputs/b/loss_epoch12.png"], tmp_project)

    groups = _groups(get_multi_compare(_conn(), [a.id, b.id]))
    assert len(groups) == 1, groups
    assert set(next(iter(groups.values()))) == {a.id, b.id}


def test_different_plots_are_not_merged(tmp_project):
    from exptrack.core.queries import get_multi_compare
    a = _run("a", ["outputs/a/loss.png", "outputs/a/confusion.png"], tmp_project)
    b = _run("b", ["outputs/b/loss.png", "outputs/b/confusion.png"], tmp_project)

    groups = _groups(get_multi_compare(_conn(), [a.id, b.id]))
    assert len(groups) == 2, groups


def test_a_run_with_several_images_in_one_family_is_not_collapsed(tmp_project):
    """Merging here would hide images: a per-epoch filmstrip is many plots, and
    the grid shows one cell per (run, group)."""
    from exptrack.core.queries import get_multi_compare
    a = _run("a", ["outputs/a/loss_epoch1.png", "outputs/a/loss_epoch2.png"],
             tmp_project)
    b = _run("b", ["outputs/b/loss_epoch1.png"], tmp_project)

    groups = _groups(get_multi_compare(_conn(), [a.id, b.id]))
    for g, by_exp in groups.items():
        for exp_id, imgs in by_exp.items():
            assert len(imgs) == 1, (g, exp_id, imgs)


def test_an_exact_match_wins_over_a_normalized_one(tmp_project):
    """A filename both runs share is never merged into a fuzzy family."""
    from exptrack.core.queries import get_multi_compare
    a = _run("a", ["outputs/a/loss.png", "outputs/a/loss_epoch9.png"], tmp_project)
    b = _run("b", ["outputs/b/loss.png"], tmp_project)

    groups = _groups(get_multi_compare(_conn(), [a.id, b.id]))
    assert "loss.png" in groups
    assert set(groups["loss.png"]) == {a.id, b.id}


# ---------------------------------------------------------------------------
# Two runs, one file
# ---------------------------------------------------------------------------

def test_a_path_two_runs_share_is_marked_shared(tmp_project):
    from exptrack.core.queries import get_multi_compare
    shared = "logs/plot.png"
    a = _run("a", [shared], tmp_project)
    b = _run("b", [shared], tmp_project)

    runs = get_multi_compare(_conn(), [a.id, b.id])
    for r in runs:
        assert r["images"][0]["shared"] is True


def test_a_run_owned_path_is_not_marked_shared(tmp_project):
    from exptrack.core.queries import get_multi_compare
    a = _run("a", ["outputs/a/loss.png"], tmp_project)
    b = _run("b", ["outputs/b/loss.png"], tmp_project)

    for r in get_multi_compare(_conn(), [a.id, b.id]):
        assert r["images"][0]["shared"] is False


def test_shared_is_scoped_to_the_compared_set(tmp_project):
    """A third run outside the comparison must not make the pair look shared."""
    from exptrack.core.queries import get_multi_compare
    shared = "logs/plot.png"
    a = _run("a", [shared], tmp_project)
    b = _run("b", ["outputs/b/loss.png"], tmp_project)
    _run("c", [shared], tmp_project)

    for r in get_multi_compare(_conn(), [a.id, b.id]):
        assert r["images"][0]["shared"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_the_group_is_named_by_the_file_not_the_artifact_label(tmp_project):
    """The matplotlib capture labels an artifact from the figure's title, which
    varies with the run's own parameters — so pairing on the label failed and the
    heading that survived was a mangled title rather than a file name."""
    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment
    from exptrack.core.queries import get_multi_compare

    ids = []
    for name, scale, epoch in (("a", "2.0", 10), ("b", "5.0", 12)):
        p = tmp_project / "plots" / f"loss_epoch{epoch}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n")
        exp = Experiment(name=name, script="train.py")
        exp.log_artifact(str(p), label=f"loss scale={scale} (loss_epoch{epoch})")
        exp.finish()
        ids.append(exp.id)

    runs = get_multi_compare(get_db(), ids)
    groups = {img["group"] for r in runs for img in r["images"]}
    assert groups == {"loss-epoch#"}, groups


def test_same_filename_in_two_directories_stays_two_groups(tmp_project):
    """One cell per (run, group), so a colliding key would drop an image."""
    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment
    from exptrack.core.queries import get_multi_compare

    ids = []
    for name in ("a", "b"):
        exp = Experiment(name=name, script="train.py")
        for sub in ("train", "val"):
            p = tmp_project / "plots" / sub / "loss.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\x89PNG\r\n")
            exp.log_artifact(str(p))
        exp.finish()
        ids.append(exp.id)

    runs = get_multi_compare(get_db(), ids)
    for r in runs:
        assert len({img["group"] for img in r["images"]}) == 2, r["images"]
