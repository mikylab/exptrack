"""Tests for image rendering — ensure artifact paths are served correctly.

Covers the full pipeline from artifact storage (absolute paths) through
API responses (relative paths) to the /api/file/ serving endpoint.

The root cause of the image rendering bug was that artifact paths are stored
as absolute in the DB (via Path.resolve() in log_artifact), but the dashboard
/api/file/ endpoint expects relative paths from the project root.  Without
conversion, the browser would request /api/file//absolute/path/to/image.png
which fails the security check in _serve_file.
"""
from __future__ import annotations

import io
import json
import os
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock


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


# ── HTTP file serving (_serve_file) ──────────────────────────────────────────

def _make_mock_handler(tmp_project):
    """Create a mock DashboardHandler with enough wiring to test _serve_file."""
    from exptrack.dashboard.handler import DashboardHandler

    handler = object.__new__(DashboardHandler)
    handler.wfile = io.BytesIO()
    handler._headers_buffer = []
    handler.responses = {}

    # Track what was sent
    sent = {"status": None, "headers": {}, "data": None, "error": None}

    def mock_send_response(code):
        sent["status"] = code

    def mock_send_header(key, value):
        sent["headers"][key] = value

    def mock_end_headers():
        pass

    def mock_send_error(code, msg=""):
        sent["error"] = code

    handler.send_response = mock_send_response
    handler.send_header = mock_send_header
    handler.end_headers = mock_end_headers
    handler.send_error = mock_send_error

    return handler, sent


def test_serve_file_with_relative_path(tmp_project):
    """_serve_file correctly serves a file given a relative path."""
    from exptrack.dashboard.handler import DashboardHandler

    # Create a test image
    img_dir = tmp_project / "outputs" / "exp1"
    img_dir.mkdir(parents=True)
    img_file = img_dir / "test.png"
    img_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    img_file.write_bytes(img_data)

    handler, sent = _make_mock_handler(tmp_project)
    handler._serve_file("outputs/exp1/test.png")

    assert sent["status"] == 200, f"Expected 200, got {sent['status']} (error: {sent['error']})"
    assert sent["headers"]["Content-Type"] == "image/png"
    assert int(sent["headers"]["Content-Length"]) == len(img_data)


def test_serve_file_rejects_absolute_path(tmp_project):
    """_serve_file rejects absolute paths that escape project root."""
    handler, sent = _make_mock_handler(tmp_project)
    handler._serve_file("/etc/passwd")

    assert sent["error"] in (403, 404), (
        f"Should reject absolute path outside root, got status={sent['status']}, error={sent['error']}"
    )


def test_serve_file_rejects_path_traversal(tmp_project):
    """_serve_file rejects path traversal attempts."""
    handler, sent = _make_mock_handler(tmp_project)
    handler._serve_file("../../../etc/passwd")

    assert sent["error"] in (403, 404), (
        f"Should reject traversal, got status={sent['status']}, error={sent['error']}"
    )


def test_serve_file_404_for_missing(tmp_project):
    """_serve_file returns 404 for nonexistent files."""
    handler, sent = _make_mock_handler(tmp_project)
    handler._serve_file("outputs/nonexistent.png")

    assert sent["error"] == 404


def test_serve_file_rejects_disallowed_extension(tmp_project):
    """_serve_file rejects file types not in the allowed list."""
    # Create a .py file (not in allowed types)
    py_file = tmp_project / "script.py"
    py_file.write_text("print('hello')")

    handler, sent = _make_mock_handler(tmp_project)
    handler._serve_file("script.py")

    assert sent["error"] == 403


# ── Full pipeline: artifact → API → URL → serve ─────────────────────────────

def test_full_pipeline_artifact_to_serving(tmp_project):
    """End-to-end: log artifact → detail API → construct URL → serve file."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_experiment_detail

    # 1. Create experiment with image artifact
    exp = Experiment(script="train.py")
    art_path = tmp_project / "outputs" / exp.name / "confusion_matrix.png"
    art_path.parent.mkdir(parents=True, exist_ok=True)
    img_data = b"\x89PNG\r\n\x1a\n" + b"fake confusion matrix image" * 10
    art_path.write_bytes(img_data)
    exp.log_artifact(str(art_path), label="confusion_matrix")
    exp.finish()

    # 2. Get artifact path from API
    conn = get_db()
    detail = get_experiment_detail(conn, exp.id)
    art = next(a for a in detail["artifacts"] if a["label"] == "confusion_matrix")
    rel_path = art["path"]

    # Verify path is relative
    assert not os.path.isabs(rel_path), f"Path should be relative, got: {rel_path}"

    # 3. Simulate JS URL construction:
    #    const src = '/api/file/' + encodeURIComponent(a.path).replace(/%2F/g, '/');
    encoded = urllib.parse.quote(rel_path, safe='/')
    url_path = f"/api/file/{encoded}"

    # 4. Simulate handler's URL parsing:
    #    file_path = "/".join(path.split("/")[3:])
    #    file_path = urllib.parse.unquote(file_path)
    parts = url_path.split("/")
    extracted = "/".join(parts[3:])
    decoded = urllib.parse.unquote(extracted)

    # 5. Verify the decoded path matches what we started with
    assert decoded == rel_path, f"URL round-trip failed: {decoded!r} != {rel_path!r}"

    # 6. Serve the file
    handler, sent = _make_mock_handler(tmp_project)
    handler._serve_file(decoded)

    assert sent["status"] == 200, (
        f"Failed to serve file, status={sent['status']}, error={sent['error']}"
    )
    assert sent["headers"]["Content-Type"] == "image/png"


def test_full_pipeline_images_api_to_serving(tmp_project):
    """End-to-end: artifact images from /api/images → URL → serve file."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.dashboard.routes.read_routes import api_list_images

    # 1. Create experiment with image artifact
    exp = Experiment(script="eval.py")
    art_path = tmp_project / "outputs" / exp.name / "roc_curve.jpg"
    art_path.parent.mkdir(parents=True, exist_ok=True)
    img_data = b"\xff\xd8\xff\xe0" + b"fake JPEG data" * 5
    art_path.write_bytes(img_data)
    exp.log_artifact(str(art_path), label="roc")
    exp.finish()

    # 2. Get from images API
    conn = get_db()
    result = api_list_images(conn, exp.id)
    art_imgs = result["artifact_images"]
    assert len(art_imgs) >= 1
    ai = next(i for i in art_imgs if i["name"] == "roc_curve.jpg")

    # 3. Simulate JS URL construction and handler parsing
    rel_path = ai["path"]
    assert not os.path.isabs(rel_path)
    encoded = urllib.parse.quote(rel_path, safe='/')
    url_path = f"/api/file/{encoded}"
    extracted = "/".join(url_path.split("/")[3:])
    decoded = urllib.parse.unquote(extracted)

    # 4. Serve
    handler, sent = _make_mock_handler(tmp_project)
    handler._serve_file(decoded)
    assert sent["status"] == 200, (
        f"Failed to serve artifact image, error={sent['error']}"
    )
    assert sent["headers"]["Content-Type"] == "image/jpeg"


def test_full_pipeline_compare_images_to_serving(tmp_project):
    """End-to-end: multi-compare images → URL → serve file."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_multi_compare

    ids = []
    img_paths = []
    for i in range(2):
        exp = Experiment(script=f"run{i}.py")
        art_path = tmp_project / "outputs" / exp.name / f"sample_{i}.png"
        art_path.parent.mkdir(parents=True, exist_ok=True)
        art_path.write_bytes(b"\x89PNG" + bytes([i]) * 50)
        exp.log_artifact(str(art_path), label=f"sample_{i}")
        exp.finish()
        ids.append(exp.id)
        img_paths.append(art_path)

    conn = get_db()
    results = get_multi_compare(conn, ids)

    for r in results:
        for img in r["images"]:
            rel_path = img["path"]
            assert not os.path.isabs(rel_path)

            # Simulate JS + handler
            encoded = urllib.parse.quote(rel_path, safe='/')
            extracted = "/".join(f"/api/file/{encoded}".split("/")[3:])
            decoded = urllib.parse.unquote(extracted)

            handler, sent = _make_mock_handler(tmp_project)
            handler._serve_file(decoded)
            assert sent["status"] == 200, (
                f"Failed to serve compare image {rel_path}, error={sent['error']}"
            )


# ── JS HTML generation checks ────────────────────────────────────────────────

def test_detail_js_generates_img_tags_for_artifacts():
    """The detail overview does NOT render image thumbnails (images only in Images tab)."""
    from exptrack.dashboard.static_parts.js.detail import JS_DETAIL

    assert "isImage" not in JS_DETAIL, "Detail overview should not detect image artifacts (moved to Images tab)"
    assert "artifact-thumb" not in JS_DETAIL, "Detail overview should not render artifact thumbnails"
    assert "artifactTypeBadge" in JS_DETAIL, "Detail JS should still render artifact type badges"


def test_images_tab_js_generates_img_tags():
    """The images tab JS produces <img> tags with correct src attributes."""
    from exptrack.dashboard.static_parts.js.timeline import JS_TIMELINE

    assert "img-gallery" in JS_TIMELINE, "Images tab should render gallery"
    assert "img-thumb" in JS_TIMELINE, "Images tab should render thumbnails"
    assert "fileUrl(img.path)" in JS_TIMELINE, "Images tab should use fileUrl() helper"


def test_compare_js_generates_img_tags():
    """The compare view JS produces <img> tags for cross-experiment comparison."""
    from exptrack.dashboard.static_parts.js.compare import JS_COMPARE

    assert "cmp-img-grid" in JS_COMPARE, "Compare should render image grid"
    assert "cmp-img-thumb" in JS_COMPARE, "Compare should render thumbnails"
    assert "fileUrl(img.path)" in JS_COMPARE, "Compare should use fileUrl() helper"


# ── Auth token forwarding for image URLs ─────────────────────────────────────

def test_fileurl_helper_exists():
    """fileUrl() helper is defined in core JS and handles auth + encoding."""
    from exptrack.dashboard.static_parts.js.core import JS_CORE

    assert "function fileUrl(path)" in JS_CORE, "Core JS should define fileUrl() helper"
    assert "_authUrl" in JS_CORE.split("function fileUrl")[1].split("\n")[0:3].__repr__(), (
        "fileUrl() should use _authUrl internally"
    )


def test_merge_artifact_images_helper_exists():
    """mergeArtifactImages() helper is defined in core JS."""
    from exptrack.dashboard.static_parts.js.core import JS_CORE

    assert "function mergeArtifactImages(" in JS_CORE


def test_all_file_urls_use_helper():
    """All /api/file/ references should go through fileUrl() or its definition."""
    from exptrack.dashboard.static_parts.scripts import get_all_js

    all_js = get_all_js()
    lines = all_js.split('\n')
    bare_urls = []
    for i, line in enumerate(lines, 1):
        if '/api/file/' in line:
            stripped = line.strip()
            if stripped.startswith('//') or stripped.startswith('*'):
                continue
            # Allow the fileUrl definition itself
            if 'function fileUrl' in stripped or "return _authUrl('/api/file/'" in stripped:
                continue
            bare_urls.append(f"  line {i}: {stripped[:100]}")

    assert not bare_urls, (
        "Found /api/file/ URLs not going through fileUrl() helper:\n" + "\n".join(bare_urls)
    )


def test_compare_js_merges_artifact_images():
    """The compare view JS uses mergeArtifactImages helper."""
    from exptrack.dashboard.static_parts.js.compare import JS_COMPARE

    assert "mergeArtifactImages(" in JS_COMPARE, (
        "Compare should use mergeArtifactImages() helper"
    )


def test_images_tab_js_merges_artifact_images():
    """The images tab JS uses mergeArtifactImages helper."""
    from exptrack.dashboard.static_parts.js.timeline import JS_TIMELINE

    assert "mergeArtifactImages(" in JS_TIMELINE, (
        "Images tab should use mergeArtifactImages() helper"
    )


# ── Paths with special characters ────────────────────────────────────────────

def test_path_with_spaces(tmp_project):
    """Artifact paths with spaces are handled correctly through the pipeline."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_experiment_detail

    exp = Experiment(script="train.py")
    art_path = tmp_project / "outputs" / exp.name / "my plot.png"
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_bytes(b"\x89PNG space test")
    exp.log_artifact(str(art_path), label="spaced")
    exp.finish()

    conn = get_db()
    detail = get_experiment_detail(conn, exp.id)
    art = next(a for a in detail["artifacts"] if a["label"] == "spaced")
    rel_path = art["path"]
    assert not os.path.isabs(rel_path)
    assert "my plot.png" in rel_path

    # Simulate JS encoding: encodeURIComponent encodes spaces as %20
    encoded = urllib.parse.quote(rel_path, safe='/')
    assert "%20" in encoded or " " not in encoded

    # Handler decodes it back
    extracted = "/".join(f"/api/file/{encoded}".split("/")[3:])
    decoded = urllib.parse.unquote(extracted)
    assert decoded == rel_path

    # Serve the file
    handler, sent = _make_mock_handler(tmp_project)
    handler._serve_file(decoded)
    assert sent["status"] == 200, f"Spaces in path failed, error={sent['error']}"


# ── Multiple image formats ───────────────────────────────────────────────────

def test_all_image_formats_servable(tmp_project):
    """All supported image extensions are recognized by _serve_file."""
    formats = {
        "test.png": ("image/png", b"\x89PNG"),
        "test.jpg": ("image/jpeg", b"\xff\xd8\xff"),
        "test.jpeg": ("image/jpeg", b"\xff\xd8\xff"),
        "test.gif": ("image/gif", b"GIF89a"),
        "test.bmp": ("image/bmp", b"BM"),
        "test.svg": ("image/svg+xml", b"<svg></svg>"),
        "test.webp": ("image/webp", b"RIFF"),
    }

    for filename, (expected_mime, data) in formats.items():
        img_file = tmp_project / filename
        img_file.write_bytes(data)

        handler, sent = _make_mock_handler(tmp_project)
        handler._serve_file(filename)
        assert sent["status"] == 200, f"{filename}: expected 200, got error={sent['error']}"
        assert sent["headers"]["Content-Type"] == expected_mime, (
            f"{filename}: expected {expected_mime}, got {sent['headers'].get('Content-Type')}"
        )


# ── Non-image artifacts should not break ─────────────────────────────────────

def test_non_image_artifacts_excluded_from_images_api(tmp_project):
    """Non-image artifacts (model files, etc.) are excluded from artifact_images."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.dashboard.routes.read_routes import api_list_images

    exp = Experiment(script="train.py")
    # Log a model file (not an image)
    model_path = tmp_project / "outputs" / exp.name / "model.pt"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"fake model")
    exp.log_artifact(str(model_path), label="model")
    # Also log an image
    img_path = tmp_project / "outputs" / exp.name / "chart.png"
    img_path.write_bytes(b"\x89PNG chart")
    exp.log_artifact(str(img_path), label="chart")
    exp.finish()

    conn = get_db()
    result = api_list_images(conn, exp.id)
    art_imgs = result["artifact_images"]

    # Only the .png should appear
    names = [ai["name"] for ai in art_imgs]
    assert "chart.png" in names
    assert "model.pt" not in names
