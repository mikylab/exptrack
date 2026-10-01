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


# ---------------------------------------------------------------------------
# The savefig copy and the file the script wrote are one image
# ---------------------------------------------------------------------------

def _run_with_protected_copy(name, filename, body, tmp_project):
    """A run holding both the file the script wrote and its outputs/ copy.

    Exactly what the savefig patch plus the finish-time output scan leave
    behind: the patch copies the figure to ``outputs/<run>/`` and registers the
    copy, the scan then registers the original.
    """
    import shutil

    from exptrack.core.experiment import Experiment
    orig = tmp_project / "figs" / filename
    orig.parent.mkdir(parents=True, exist_ok=True)
    orig.write_bytes(body)
    copy = tmp_project / "outputs" / name / filename
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(orig), str(copy))

    exp = Experiment(name=name, script="train.py")
    exp.log_artifact(str(copy))
    exp.log_artifact(str(orig))
    exp.finish()
    return exp.id


def test_a_figure_and_its_outputs_copy_are_one_image(tmp_project):
    """Two rows for one image put two same-named images inside a single run,
    which forced the full-path keying and left every run's images in a column
    of their own — the "nothing lines up" report."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_multi_compare

    ids = [_run_with_protected_copy(n, "loss.png", b"\x89PNG\r\n" + n.encode(),
                                    tmp_project)
           for n in ("a", "b")]

    runs = get_multi_compare(get_db(), ids)
    for r in runs:
        assert len(r["images"]) == 1, r["images"]
        # The copy is what survives: it is the run's own protected file.
        assert "outputs" in r["images"][0]["path"]
    groups = _groups(runs)
    assert list(groups) == ["loss.png"]
    assert len(groups["loss.png"]) == 2


def test_identical_bytes_outside_outputs_are_still_two_images(tmp_project):
    """Only the copy shape collapses. Two plots that merely hash alike are two
    images, and hiding one of them is worse than showing a duplicate."""
    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment
    from exptrack.core.queries import get_multi_compare

    exp = Experiment(name="a", script="train.py")
    for sub in ("train", "val"):
        p = tmp_project / "plots" / sub / "loss.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n")
        exp.log_artifact(str(p))
    exp.finish()

    runs = get_multi_compare(get_db(), [exp.id])
    assert len(runs[0]["images"]) == 2, runs[0]["images"]


def _copy_pair_run(name, orig_rel, tmp_project, hashed=True):
    """A run holding the savefig copy at outputs/<name>/ and one original."""
    import shutil

    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment
    orig = tmp_project / orig_rel
    orig.parent.mkdir(parents=True, exist_ok=True)
    orig.write_bytes(b"\x89PNG " + name.encode())
    copy = tmp_project / "outputs" / name / orig.name
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(orig), str(copy))

    exp = Experiment(name=name, script="train.py")
    exp.log_artifact(str(copy))
    exp.log_artifact(str(orig))
    exp.finish()
    if not hashed:
        # Runs recorded before artifacts were hashed: the content rule has
        # nothing to compare, so only the copy address can pair them.
        conn = get_db()
        conn.execute("UPDATE artifacts SET content_hash=NULL, size_bytes=NULL "
                     "WHERE exp_id=?", (exp.id,))
        conn.commit()
    return exp.id


def test_the_copy_pairs_when_the_script_also_wrote_into_outputs(tmp_project):
    """Both rows under `outputs/` — the shape a script with its own output dir
    produces. "Some inside, some outside" never fired for it, and the grid
    headed the row with a full path and said *No image* in the other column."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_multi_compare

    ids = [_copy_pair_run(n, f"outputs/raw/{n}/pred.png", tmp_project)
           for n in ("a", "b")]

    runs = get_multi_compare(get_db(), ids)
    for r in runs:
        assert len(r["images"]) == 1, r["images"]
    groups = _groups(runs)
    assert list(groups) == ["pred.png"], groups
    assert len(groups["pred.png"]) == 2


def test_the_copy_pairs_for_runs_recorded_before_artifacts_were_hashed(tmp_project):
    """`content_hash` NULL is the normal state of an old run, and the content
    rule cannot see those at all."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_multi_compare

    ids = [_copy_pair_run(n, "figs/pred.png", tmp_project, hashed=False)
           for n in ("a", "b")]

    runs = get_multi_compare(get_db(), ids)
    for r in runs:
        assert len(r["images"]) == 1, r["images"]
    assert list(_groups(runs)) == ["pred.png"]


def test_a_same_named_file_of_a_different_size_is_not_the_copy(tmp_project):
    """The copy address is strong evidence, not a licence: where both sizes
    are recorded they still have to agree."""
    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment
    from exptrack.core.queries import get_multi_compare

    exp = Experiment(name="a", script="train.py")
    copy = tmp_project / "outputs" / "a" / "pred.png"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(b"\x89PNG one")
    other = tmp_project / "figs" / "pred.png"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(b"\x89PNG a different picture entirely")
    exp.log_artifact(str(copy))
    exp.log_artifact(str(other))
    exp.finish()

    runs = get_multi_compare(get_db(), [exp.id])
    assert len(runs[0]["images"]) == 2, runs[0]["images"]


def test_the_copy_still_pairs_after_the_run_is_renamed(tmp_project):
    """The copy's address is `outputs/<name at the time>/`, and a rename does
    not move the file — so the address rule alone would stop recognising it."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_multi_compare

    ids = [_copy_pair_run(n, "figs/pred.png", tmp_project) for n in ("a", "b")]
    conn = get_db()
    conn.execute("UPDATE experiments SET name='a-renamed' WHERE id=?", (ids[0],))
    conn.commit()

    runs = get_multi_compare(get_db(), ids)
    for r in runs:
        assert len(r["images"]) == 1, r["images"]
    assert list(_groups(runs)) == ["pred.png"]


# ---------------------------------------------------------------------------
# A numbered series is one row, not one row per member
# ---------------------------------------------------------------------------

def _series_run(name, indices, tmp_project, prefix="test_ISIC_", suffix="_output"):
    from exptrack.core.experiment import Experiment
    exp = Experiment(name=name, script="train.py")
    for i in indices:
        p = tmp_project / "outputs" / name / f"{prefix}{i:07d}{suffix}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG " + f"{name}{i}".encode())
        exp.log_artifact(str(p))
    exp.finish()
    return exp.id


def test_a_per_sample_series_is_one_row_even_when_the_names_differ(tmp_project):
    """Two runs scoring different samples share no file name, so per-file rows
    gave a page of singles reading *No image* opposite each one."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_multi_compare

    ids = [_series_run("a", range(0, 6), tmp_project),
           _series_run("b", range(100, 106), tmp_project)]

    runs = get_multi_compare(get_db(), ids)
    groups = _groups(runs)
    assert len(groups) == 1, list(groups)
    (only,) = groups.values()
    assert len(only) == 2, "both runs must be in the row"
    assert all(len(v) == 6 for v in only.values())
    assert all(img.get("family") for r in runs for img in r["images"])


def test_a_series_stays_one_row_when_both_runs_wrote_the_same_names(tmp_project):
    """The exact-filename rule would give 200 correctly-paired rows, which is
    still a page nobody can read."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_multi_compare

    ids = [_series_run(n, range(0, 5), tmp_project) for n in ("a", "b")]

    runs = get_multi_compare(get_db(), ids)
    assert len(_groups(runs)) == 1


def test_two_plots_are_still_two_rows(tmp_project):
    """Below the series threshold nothing changes: `loss.png` and `acc.png` are
    two plots and pair per file."""
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_multi_compare

    ids = []
    for name in ("a", "b"):
        exp_id = None
        from exptrack.core.experiment import Experiment
        exp = Experiment(name=name, script="train.py")
        for fn in ("loss.png", "acc.png"):
            p = tmp_project / "outputs" / name / fn
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\x89PNG " + name.encode())
            exp.log_artifact(str(p))
        exp.finish()
        exp_id = exp.id
        ids.append(exp_id)

    runs = get_multi_compare(get_db(), ids)
    groups = _groups(runs)
    assert set(groups) == {"loss.png", "acc.png"}, list(groups)
    assert all(len(v) == 2 for v in groups.values())


def test_a_short_epoch_filmstrip_still_keeps_its_exact_names(tmp_project):
    """Three per run is not a series: the old rule (keep exact filenames when a
    merge would hide a member) still applies below the threshold."""
    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment
    from exptrack.core.queries import get_multi_compare

    ids = []
    for name in ("a", "b"):
        exp = Experiment(name=name, script="train.py")
        for ep in (1, 2, 3):
            p = tmp_project / "outputs" / name / f"loss_epoch{ep}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\x89PNG " + f"{name}{ep}".encode())
            exp.log_artifact(str(p))
        exp.finish()
        ids.append(exp.id)

    runs = get_multi_compare(get_db(), ids)
    groups = _groups(runs)
    assert set(groups) == {"loss_epoch1.png", "loss_epoch2.png", "loss_epoch3.png"}


def test_same_named_hashless_files_in_two_directories_both_survive(tmp_project):
    """A run that writes one `pred.png` per subdirectory, recorded before
    artifacts were hashed, collapsed to a single image: nothing recorded said
    they differed, and the dedupe assumed they matched. It measures the files
    instead, and a pair it cannot measure is left alone."""
    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment
    from exptrack.core.queries import get_multi_compare

    exp = Experiment(name="a", script="train.py")
    for i, sub in enumerate(("epoch1", "epoch2", "epoch3")):
        p = tmp_project / "outputs" / "a" / sub / "pred.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG" + bytes([i]) * (40 + i))
        exp.log_artifact(str(p))
    top = tmp_project / "outputs" / "a" / "pred.png"
    top.write_bytes(b"\x89PNG top")
    exp.log_artifact(str(top))
    exp.finish()

    conn = get_db()
    conn.execute("UPDATE artifacts SET content_hash=NULL, size_bytes=NULL "
                 "WHERE exp_id=?", (exp.id,))
    conn.commit()

    runs = get_multi_compare(get_db(), [exp.id])
    assert len(runs[0]["images"]) == 4, runs[0]["images"]
