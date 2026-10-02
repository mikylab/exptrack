"""Tests for image comparison features in the dashboard.

Verifies that:
1. JS_IMAGE_COMPARE constant exists and contains expected functions
2. CSS_IMAGE_COMPARE constant exists and contains expected classes
3. get_all_js() includes image comparison code
4. get_all_css() includes image comparison styles
5. Cross-run compare (doCompare) includes image fetching code
6. Intra-run compare (loadImages) includes compare toggle
"""
import os
import sys


def test_js_image_compare_functions():
    """JS_IMAGE_COMPARE contains all required comparison functions."""
    from exptrack.dashboard.static_parts.scripts import JS_IMAGE_COMPARE

    required_functions = [
        'openCompareModal',
        'closeCompareModal',
        'setCompareMode',
        'renderCompareBody',
        'selectCrossImg',
        'doCrossCompare',
        'clearCrossCompare',
        'toggleImgCompare',
        'selectImgCompare',
        'doIntraCompare',
        'clearIntraCompare',
    ]
    for fn in required_functions:
        assert fn in JS_IMAGE_COMPARE, f"Function '{fn}' not found in JS_IMAGE_COMPARE"

    print("  [PASS] test_js_image_compare_functions")


def test_js_image_compare_modes():
    """JS_IMAGE_COMPARE supports side-by-side, overlay, and swipe modes."""
    from exptrack.dashboard.static_parts.scripts import JS_IMAGE_COMPARE

    assert "'side'" in JS_IMAGE_COMPARE, "Side-by-side mode not found"
    assert "'overlay'" in JS_IMAGE_COMPARE, "Overlay mode not found"
    assert "'swipe'" in JS_IMAGE_COMPARE, "Swipe mode not found"

    # Swipe uses clip-path
    assert 'clipPath' in JS_IMAGE_COMPARE or 'clip-path' in JS_IMAGE_COMPARE, \
        "Swipe mode should use clip-path"

    # Overlay uses opacity slider
    assert 'opacity' in JS_IMAGE_COMPARE, "Overlay mode should use opacity"

    print("  [PASS] test_js_image_compare_modes")


def test_css_image_compare_classes():
    """CSS_IMAGE_COMPARE contains all required style classes."""
    from exptrack.dashboard.static_parts.styles import CSS_IMAGE_COMPARE

    required_classes = [
        '.img-cmp-overlay',
        '.img-cmp-header',
        '.img-cmp-modes',
        '.img-cmp-body',
        '.img-cmp-side',
        '.img-cmp-stack',
        '.img-cmp-swipe',
        '.img-cmp-divider',
        '.compare-images-section',
        '.compare-images-cols',
        '.cmp-img-thumb',
        '.cmp-img-thumb.selected',
        '.compare-select-bar',
        '.img-compare-toggle',
        '.img-compare-toggle.active',
        '.img-card.compare-sel',
        '.img-cmp-floating-bar',
        '.img-cmp-badge',
    ]
    for cls in required_classes:
        assert cls in CSS_IMAGE_COMPARE, f"CSS class '{cls}' not found in CSS_IMAGE_COMPARE"

    print("  [PASS] test_css_image_compare_classes")


def test_get_all_js_includes_image_compare():
    """get_all_js() output includes image comparison code."""
    from exptrack.dashboard.static_parts.scripts import get_all_js

    all_js = get_all_js()
    assert 'openCompareModal' in all_js, "get_all_js() should include openCompareModal"
    assert 'toggleImgCompare' in all_js, "get_all_js() should include toggleImgCompare"
    assert 'selectCrossImg' in all_js, "get_all_js() should include selectCrossImg"

    print("  [PASS] test_get_all_js_includes_image_compare")


def test_get_all_css_includes_image_compare():
    """get_all_css() output includes image comparison styles."""
    from exptrack.dashboard.static_parts.styles import get_all_css

    all_css = get_all_css()
    assert '.img-cmp-overlay' in all_css, "get_all_css() should include .img-cmp-overlay"
    assert '.img-cmp-swipe' in all_css, "get_all_css() should include .img-cmp-swipe"

    print("  [PASS] test_get_all_css_includes_image_compare")


def test_cross_run_compare_fetches_images():
    """doCompare() in JS_COMPARE fetches images from both experiments."""
    from exptrack.dashboard.static_parts.scripts import JS_COMPARE

    assert "/api/images/" in JS_COMPARE, "doCompare should fetch images via /api/images/"
    assert "crossCmpA" in JS_COMPARE, "doCompare should reset crossCmpA"
    assert "compare-images-section" in JS_COMPARE, "doCompare should render images section"
    assert "selectCrossImg" in JS_COMPARE, "doCompare should wire up selectCrossImg on thumbnails"

    print("  [PASS] test_cross_run_compare_fetches_images")


def test_intra_run_compare_in_load_images():
    """loadImages() in JS_TIMELINE includes compare toggle and selection mode."""
    from exptrack.dashboard.static_parts.scripts import JS_TIMELINE

    assert "img-compare-toggle" in JS_TIMELINE, "loadImages should render compare toggle button"
    assert "toggleImgCompare" in JS_TIMELINE, "loadImages should call toggleImgCompare"
    assert "selectImgCompare" in JS_TIMELINE, "loadImages should call selectImgCompare in compare mode"
    assert "img-cmp-badge" in JS_TIMELINE, "loadImages should render A/B badges"
    assert "img-cmp-floating-bar" in JS_TIMELINE, "loadImages should render floating compare bar"

    print("  [PASS] test_intra_run_compare_in_load_images")


def test_swipe_pointer_events():
    """Swipe mode uses pointer events for dragging."""
    from exptrack.dashboard.static_parts.scripts import JS_IMAGE_COMPARE

    assert 'pointerdown' in JS_IMAGE_COMPARE, "Swipe should use pointerdown"
    assert 'pointermove' in JS_IMAGE_COMPARE, "Swipe should use pointermove"
    assert 'pointerup' in JS_IMAGE_COMPARE, "Swipe should use pointerup"
    assert 'setPointerCapture' in JS_IMAGE_COMPARE, "Swipe should capture pointer"

    print("  [PASS] test_swipe_pointer_events")


def test_side_by_side_names_the_run_each_image_came_from():
    """Both runs usually write the same file name, so a cross-run overlay that
    labelled each panel with the file name alone said nothing about which side
    was which."""
    from exptrack.dashboard.static_parts.scripts import JS_COMPARE, JS_IMAGE_COMPARE
    from exptrack.dashboard.static_parts.styles import CSS_IMAGE_COMPARE

    assert "function openCompareModal(src1, name1, src2, name2, run1, run2, opts)" in (
        JS_IMAGE_COMPARE), "the modal must accept the run each image is from"
    assert "_imgCmpPanel" in JS_IMAGE_COMPARE
    assert "img-cmp-run" in JS_IMAGE_COMPARE
    assert "img-cmp-run" in CSS_IMAGE_COMPARE
    assert "crossCmpA.run" in JS_IMAGE_COMPARE, (
        "doCrossCompare must pass the run names through")
    assert "selectCrossImg" in JS_COMPARE
    assert "escJsAttr(name)" in JS_COMPARE, (
        "the compare grid must tell selectCrossImg which run a thumbnail is from")

    print("  [PASS] test_side_by_side_names_the_run_each_image_came_from")


def test_the_modal_can_flip_through_a_runs_images():
    """Picking two of 900 images by closing the modal, scrolling and picking
    again is the cost this removes: each side steps through its own list, and
    a name query jumps straight to one."""
    from exptrack.dashboard.static_parts.scripts import JS_IMAGE_COMPARE, JS_TIMELINE
    from exptrack.dashboard.static_parts.styles import CSS_IMAGE_COMPARE

    for fn in ("function stepCompareImage(", "function jumpCompareImage(",
               "function _renderCmpNav("):
        assert fn in JS_IMAGE_COMPARE, fn
    assert "ArrowLeft" in JS_IMAGE_COMPARE and "ArrowRight" in JS_IMAGE_COMPARE, (
        "arrow keys must step the sides")
    assert "img-cmp-nav" in CSS_IMAGE_COMPARE
    assert "_intraImgList" in JS_TIMELINE, (
        "the Images tab must hand the modal the gallery it is showing")

    print("  [PASS] test_the_modal_can_flip_through_a_runs_images")


def test_both_image_pickers_can_be_searched_by_name():
    from exptrack.dashboard.static_parts.scripts import JS_COMPARE, JS_TIMELINE
    from exptrack.dashboard.static_parts.styles import CSS_IMAGE_COMPARE, CSS_IMAGES

    assert "_onCmpImgSearch" in JS_COMPARE and "cmp-img-search" in JS_COMPARE
    assert "cmp-img-search" in CSS_IMAGE_COMPARE
    assert "_onImageSearch" in JS_TIMELINE and "img-search-input" in JS_TIMELINE
    assert "img-search-input" in CSS_IMAGES

    print("  [PASS] test_both_image_pickers_can_be_searched_by_name")


def test_a_small_image_is_enlarged_by_the_modal_not_shrunk():
    """`max-width`/`max-height` only shrink, so a 128x128 image rendered at
    128px inside a full-screen overlay while the gallery thumb upscaled it to
    the cell width — clicking to enlarge made it smaller. Both modals scale a
    small image up to the space they have, and every image in one modal takes
    the same scale so an overlay compare still aligns."""
    from exptrack.dashboard.static_parts.scripts import JS_CORE, JS_IMAGE_COMPARE, JS_TIMELINE

    assert "function fitModalImages(" in JS_CORE
    assert "MODAL_IMAGE_MAX_UPSCALE" in JS_CORE, (
        "an upscale has to be capped, or a tiny icon becomes a wall of blur")
    assert "pixelated" in JS_CORE, (
        "past 2x a smooth upscale reads as out of focus, not as pixels")
    assert "MODAL_IMAGE_MIN_UPSCALE" in JS_CORE, (
        "an image already near the window size must be left alone")
    assert "fitModalImages(" in JS_TIMELINE, "the single-image modal must fit"
    assert "_fitCompareBody" in JS_IMAGE_COMPARE, "the compare modal must fit"
    assert "_imgCmpAvail" in JS_IMAGE_COMPARE, (
        "side-by-side splits the window, overlay and swipe do not")

    print("  [PASS] test_a_small_image_is_enlarged_by_the_modal_not_shrunk")


def test_the_image_modals_offer_more_than_one_backdrop():
    """Dark suits a matplotlib plot and fights a dark mask or a light-on-white
    sample. The default is unchanged; the alternatives are one click away, the
    choice is remembered, and the modal chrome takes its colour from the same
    tokens so a light backdrop is not white text on white."""
    from exptrack.dashboard.static_parts.scripts import (
        JS_CORE,
        JS_IMAGE_COMPARE,
        JS_TIMELINE,
    )
    from exptrack.dashboard.static_parts.styles import CSS_IMAGE_COMPARE, CSS_IMAGES

    assert "MODAL_BACKDROPS" in JS_CORE
    for preset in ("'dark'", "'light'", "'grey'", "'checker'"):
        assert preset in JS_CORE, preset
    assert "exptrack-modal-backdrop" in JS_CORE, "the choice must be remembered"
    assert "function setModalBackdrop(" in JS_CORE
    assert "function applyModalBackdrop(" in JS_CORE
    assert "escJsAttr(b.id)" in JS_CORE, (
        "the swatch writes an inline handler, so the value must be escaped for one")
    assert "modalBackdropPickerHtml()" in JS_TIMELINE, "single-image modal"
    assert "modalBackdropPickerHtml()" in JS_IMAGE_COMPARE, "comparison modal"
    assert "applyModalBackdrop()" in JS_TIMELINE and "applyModalBackdrop()" in (
        JS_IMAGE_COMPARE), "a modal must open on the backdrop already chosen"

    assert "--modal-bg" in CSS_IMAGE_COMPARE and "--modal-fg" in CSS_IMAGE_COMPARE
    assert 'data-backdrop="checker"' in CSS_IMAGE_COMPARE
    assert "var(--modal-bg)" in CSS_IMAGES, (
        "the single-image modal must use the shared backdrop token too")
    assert "#fff" not in CSS_IMAGES.split(".img-modal-header")[1].split("}")[0], (
        "modal chrome must not hardcode white, or a light backdrop is unreadable")

    print("  [PASS] test_the_image_modals_offer_more_than_one_backdrop")


def test_overlay_range_slider():
    """Overlay mode has a range slider for opacity control."""
    from exptrack.dashboard.static_parts.scripts import JS_IMAGE_COMPARE

    assert 'type="range"' in JS_IMAGE_COMPARE, "Overlay should have range input"
    assert 'min="0"' in JS_IMAGE_COMPARE, "Range should start at 0"
    assert 'max="100"' in JS_IMAGE_COMPARE, "Range should go to 100"

    print("  [PASS] test_overlay_range_slider")


def test_overlay_can_tint_each_side_so_differences_show():
    """A 50% crossfade answers "are these different?" only when the difference
    is large: both images are half-drawn, so a shifted boundary or a handful of
    wrong pixels is invisible. Tinting each side and adding them makes
    agreement neutral and disagreement coloured."""
    from exptrack.dashboard.static_parts.scripts import JS_IMAGE_COMPARE
    from exptrack.dashboard.static_parts.styles import CSS_IMAGE_COMPARE

    assert "IMG_CMP_TINTS" in JS_IMAGE_COMPARE
    for t in ("'none'", "'yellowblue'", "'redcyan'", "'difference'"):
        assert t in JS_IMAGE_COMPARE, t
    assert "function setOverlayTint(" in JS_IMAGE_COMPARE
    assert "exptrack-overlay-tint" in JS_IMAGE_COMPARE, "the choice must persist"
    assert "_tintSvgDefs" in JS_IMAGE_COMPARE and "feColorMatrix" in JS_IMAGE_COMPARE, (
        "the tints must be exact channel projections — a sepia+hue-rotate chain "
        "lands near a hue, and near-yellow plus near-blue sums to pink, which "
        "makes an identical pair look like a difference")
    assert "url(#imgCmpTintYellow)" in CSS_IMAGE_COMPARE
    assert "mix-blend-mode: screen" in CSS_IMAGE_COMPARE, (
        "the tinted pair is added, not faded")
    assert "mix-blend-mode: difference" in CSS_IMAGE_COMPARE
    assert "isolation: isolate" in CSS_IMAGE_COMPARE, (
        "the blend must not reach past the stack into the chosen backdrop")
    assert "tinted ? '1' : '0.5'" in JS_IMAGE_COMPARE, (
        "a tinted top image is drawn at full strength; half of each sums to mud")
    assert "img-cmp-tint-help" in JS_IMAGE_COMPARE, (
        "an unexplained colour scheme is just a strangely coloured image")

    print("  [PASS] test_overlay_can_tint_each_side_so_differences_show")


def test_escape_closes_modal():
    """Compare modal closes on Escape key."""
    from exptrack.dashboard.static_parts.scripts import JS_IMAGE_COMPARE

    assert 'Escape' in JS_IMAGE_COMPARE, "Modal should listen for Escape key"
    assert 'closeCompareModal' in JS_IMAGE_COMPARE, "Should call closeCompareModal"

    print("  [PASS] test_escape_closes_modal")


def test_dashboard_html_contains_image_compare():
    """The assembled JS/CSS bundles include image comparison code.

    JS/CSS are now served as external /static/dashboard.{js,css} bundles
    rather than inlined into DASHBOARD_HTML, so assert against the bundles the
    page references (DASHBOARD_JS / DASHBOARD_CSS) — and confirm the HTML
    actually references them."""
    from exptrack.dashboard.static import (
        DASHBOARD_CSS,
        DASHBOARD_HTML,
        DASHBOARD_JS,
    )

    assert 'openCompareModal' in DASHBOARD_JS, "DASHBOARD_JS should contain openCompareModal"
    assert '.img-cmp-overlay' in DASHBOARD_CSS, "DASHBOARD_CSS should contain image compare CSS"
    assert '/static/dashboard.js' in DASHBOARD_HTML
    assert '/static/dashboard.css' in DASHBOARD_HTML

    print("  [PASS] test_dashboard_html_contains_image_compare")


if __name__ == "__main__":
    saved_cwd = os.getcwd()
    tests = [
        test_js_image_compare_functions,
        test_js_image_compare_modes,
        test_css_image_compare_classes,
        test_get_all_js_includes_image_compare,
        test_get_all_css_includes_image_compare,
        test_cross_run_compare_fetches_images,
        test_intra_run_compare_in_load_images,
        test_swipe_pointer_events,
        test_overlay_range_slider,
        test_the_image_modals_offer_more_than_one_backdrop,
        test_a_small_image_is_enlarged_by_the_modal_not_shrunk,
        test_side_by_side_names_the_run_each_image_came_from,
        test_the_modal_can_flip_through_a_runs_images,
        test_both_image_pickers_can_be_searched_by_name,
        test_overlay_can_tint_each_side_so_differences_show,
        test_escape_closes_modal,
        test_dashboard_html_contains_image_compare,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            os.chdir(saved_cwd)
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            failed += 1

    os.chdir(saved_cwd)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
