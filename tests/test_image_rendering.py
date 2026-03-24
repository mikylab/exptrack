"""Tests for image rendering — ensure artifact paths are served correctly.

Covers the full pipeline from artifact storage (absolute paths) through
API responses (relative paths) to the /api/file/ serving endpoint.
"""
from __future__ import annotations

import os
from pathlib import Path


# ── _rel_path helper ─────────────────────────────────────────────────────────

def test_rel_path_converts_absolute(tmp_project):
    """_rel_path converts absolute artifact paths to relative from project root."""
    from exptrack.core.queries import _rel_path

    root = str(tmp_project)
    abs_path = os.path.join(root, "outputs", "exp1", "test.png")
    result = _rel_path(abs_path)
    # Should be relative, like "outputs/exp1/test.png"
    assert not os.path.isabs(result)
    assert result == os.path.join("outputs", "exp1", "test.png")


def test_rel_path_passthrough_relative(tmp_project):
    """_rel_path passes through already-relative paths unchanged."""
    from exptrack.core.queries import _rel_path

    result = _rel_path("outputs/test.png")
    assert result == "outputs/test.png"


def test_rel_path_empty_string(tmp_project):
    """_rel_path handles empty string gracefully."""
    from exptrack.core.queries import _rel_path

    assert _rel_path("") == ""


def test_rel_path_none(tmp_project):
    """_rel_path handles None gracefully."""
    from exptrack.core.queries import _rel_path

    assert _rel_path(None) is None


# ── Artifact paths in experiment detail API ──────────────────────────────────

def test_detail_artifact_paths_are_relative(tmp_project):
    """get_experiment_detail returns relative artifact paths, not absolute."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_experiment_detail

    # Create an experiment with an image artifact
    exp = Experiment(script="train.py")
    art_path = tmp_project / "outputs" / exp.name / "plot.png"
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_bytes(b"\x89PNG fake image data")
    exp.log_artifact(str(art_path), label="plot")
    exp.finish()

    # The artifact path in DB should be absolute (this is how log_artifact works)
    conn = get_db()
    row = conn.execute(
        "SELECT path FROM artifacts WHERE exp_id=? AND label='plot'", (exp.id,)
    ).fetchone()
    assert os.path.isabs(row["path"]), "DB should store absolute paths"

    # But the API response should convert to relative
    detail = get_experiment_detail(conn, exp.id)
    assert detail is not None
    # Find the plot artifact (finish() may also add output_dir as artifact)
    art = next(a for a in detail["artifacts"] if a["label"] == "plot")
    assert not os.path.isabs(art["path"]), (
        f"API should return relative path, got: {art['path']}"
    )
    assert art["path"].endswith("plot.png")


def test_detail_artifact_path_usable_for_serving(tmp_project):
    """The relative artifact path should resolve correctly from project root."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_experiment_detail

    exp = Experiment(script="train.py")
    art_path = tmp_project / "outputs" / exp.name / "result.png"
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_bytes(b"\x89PNG fake data")
    exp.log_artifact(str(art_path), label="result")
    exp.finish()

    conn = get_db()
    detail = get_experiment_detail(conn, exp.id)
    art = next(a for a in detail["artifacts"] if a["label"] == "result")
    rel = art["path"]

    # Reconstruct the absolute path the way _serve_file would
    reconstructed = os.path.realpath(os.path.join(str(tmp_project), rel))
    assert os.path.isfile(reconstructed), (
        f"Reconstructed path should exist: {reconstructed}"
    )


# ── Multi-compare image paths ───────────────────────────────────────────────

def test_multi_compare_image_paths_are_relative(tmp_project):
    """get_multi_compare returns relative image artifact paths."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_multi_compare

    # Create two experiments with image artifacts
    ids = []
    for i in range(2):
        exp = Experiment(script=f"train{i}.py")
        art_path = tmp_project / "outputs" / exp.name / f"fig{i}.png"
        art_path.parent.mkdir(parents=True, exist_ok=True)
        art_path.write_bytes(b"\x89PNG fake")
        exp.log_artifact(str(art_path), label=f"fig{i}")
        exp.finish()
        ids.append(exp.id)

    conn = get_db()
    results = get_multi_compare(conn, ids)
    assert len(results) == 2
    for r in results:
        assert len(r["images"]) == 1
        img = r["images"][0]
        assert not os.path.isabs(img["path"]), (
            f"Multi-compare should return relative path, got: {img['path']}"
        )
        # Path should resolve to an existing file
        full = os.path.join(str(tmp_project), img["path"])
        assert os.path.isfile(full)


# ── Images API includes artifact images ──────────────────────────────────────

def test_images_api_includes_artifact_images(tmp_project):
    """api_list_images returns artifact_images from the artifacts table."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.dashboard.routes.read_routes import api_list_images

    exp = Experiment(script="train.py")
    art_path = tmp_project / "outputs" / exp.name / "loss_curve.png"
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_bytes(b"\x89PNG fake chart")
    exp.log_artifact(str(art_path), label="loss_curve")
    exp.finish()

    conn = get_db()
    result = api_list_images(conn, exp.id)

    assert "artifact_images" in result
    assert len(result["artifact_images"]) == 1
    ai = result["artifact_images"][0]
    assert ai["name"] == "loss_curve.png"
    assert ai["label"] == "loss_curve"
    assert not os.path.isabs(ai["path"]), (
        f"artifact_images path should be relative, got: {ai['path']}"
    )
    # Path should be servable
    full = os.path.join(str(tmp_project), ai["path"])
    assert os.path.isfile(full)


def test_images_api_artifact_path_matches_dir_scan_format(tmp_project):
    """Artifact image paths use the same relative format as directory scan paths."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.dashboard.routes.read_routes import api_list_images

    exp = Experiment(script="train.py")
    art_path = tmp_project / "outputs" / exp.name / "plot.png"
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_bytes(b"\x89PNG data")
    exp.log_artifact(str(art_path), label="plot")
    exp.finish()

    conn = get_db()
    result = api_list_images(conn, exp.id)
    art_images = result["artifact_images"]
    assert len(art_images) >= 1

    # The artifact path should be relative from project root
    ai = next(i for i in art_images if i["name"] == "plot.png")
    assert not os.path.isabs(ai["path"])
    # And it should start with the outputs directory prefix
    assert ai["path"].replace("\\", "/").startswith("outputs/")
