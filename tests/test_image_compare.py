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


def test_overlay_range_slider():
    """Overlay mode has a range slider for opacity control."""
    from exptrack.dashboard.static_parts.scripts import JS_IMAGE_COMPARE

    assert 'type="range"' in JS_IMAGE_COMPARE, "Overlay should have range input"
    assert 'min="0"' in JS_IMAGE_COMPARE, "Range should start at 0"
    assert 'max="100"' in JS_IMAGE_COMPARE, "Range should go to 100"

    print("  [PASS] test_overlay_range_slider")


def test_escape_closes_modal():
    """Compare modal closes on Escape key."""
    from exptrack.dashboard.static_parts.scripts import JS_IMAGE_COMPARE

    assert 'Escape' in JS_IMAGE_COMPARE, "Modal should listen for Escape key"
    assert 'closeCompareModal' in JS_IMAGE_COMPARE, "Should call closeCompareModal"

    print("  [PASS] test_escape_closes_modal")


def test_dashboard_html_contains_image_compare():
    """Final DASHBOARD_HTML includes image comparison code."""
    from exptrack.dashboard.static import DASHBOARD_HTML

    assert 'openCompareModal' in DASHBOARD_HTML, "DASHBOARD_HTML should contain openCompareModal"
    assert '.img-cmp-overlay' in DASHBOARD_HTML, "DASHBOARD_HTML should contain image compare CSS"

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
