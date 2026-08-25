"""Static integrity checks over the assembled dashboard JS/HTML bundle.

Pure-Python — no JS runtime needed. These guard against the class of bugs
where an inline event handler references a function that doesn't exist
(ReferenceError on click, e.g. the old ``editNotes`` bug) and against
regressions in the JS-string-context escaping introduced for stored-XSS
hardening (``escJs``).
"""
from __future__ import annotations

import re

from exptrack.dashboard.static import DASHBOARD_HTML
from exptrack.dashboard.static_parts.js import get_all_js

# Identifiers that are legal to call from an inline handler without a local
# definition: JS keywords/operators and browser globals. Member calls
# (``foo.bar()``) are excluded by the extraction lookbehind, so this only
# needs bare top-level names.
_ALLOWED_GLOBALS = {
    # keywords / operators that can precede "("
    "if", "for", "while", "return", "typeof", "new", "delete", "void", "in",
    "instanceof", "switch", "catch", "function", "await", "yield",
    # browser / built-in globals commonly called bare
    "event", "this", "alert", "confirm", "prompt", "document", "window",
    "navigator", "console", "setTimeout", "setInterval", "clearTimeout",
    "parseInt", "parseFloat", "encodeURIComponent", "decodeURIComponent",
    "Math", "JSON", "Object", "Array", "String", "Number", "Boolean", "Date",
    "isNaN", "isFinite", "fetch", "Promise", "requestAnimationFrame",
}

# Match a whole inline-handler attribute value: on<evt>="...". A generic
# on<lowercase>= covers every event type without hand-enumerating them (so a
# new handler kind can't slip past the check).
_HANDLER_RE = re.compile(r'\bon[a-z]+="([^"]*)"')
# A top-level function call inside a handler value: name( not preceded by a
# member access ('.') or another identifier char.
_CALL_RE = re.compile(r'(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(')


def _defined_names(js: str) -> set:
    """Names defined in the bundle as functions or (const|let|var) bindings."""
    names = set(re.findall(r'\bfunction\s+([A-Za-z_$][\w$]*)\s*\(', js))
    names |= set(re.findall(r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=', js))
    return names


def test_all_inline_handlers_are_defined():
    """Every function invoked from an inline handler must exist in the bundle.

    This would have failed on the old undefined ``editNotes`` reference.
    """
    js = get_all_js()
    defined = _defined_names(js) | _ALLOWED_GLOBALS
    called = set()
    for value in _HANDLER_RE.findall(DASHBOARD_HTML):
        called |= set(_CALL_RE.findall(value))
    missing = sorted(n for n in called if n not in defined)
    assert not missing, f"Inline handlers call undefined functions: {missing}"


def test_escjs_defined_once():
    """escJs — the JS-string-context escaper — is defined exactly once."""
    js = get_all_js()
    assert js.count("function escJs(") == 1


def test_no_raw_esc_in_handler_strings():
    """User data placed in a JS string inside an inline handler must be
    JS-escaped (escJs) before HTML-escaping (esc), not esc()/escapeHtml() alone.

    Scoped to the on*="..." attribute value (so text-content esc() around the
    handler is not flagged). ``esc(escJs(x))`` / ``escapeHtml(escJs(x))`` pass.
    """
    offenders = []
    for value in _HANDLER_RE.findall(get_all_js()):
        if re.search(r'\b(?:esc|escapeHtml)\((?!escJs)', value):
            offenders.append(value.strip()[:140])
    assert not offenders, (
        "esc()/escapeHtml() without escJs() inside an inline-handler JS string:\n"
        + "\n".join(offenders)
    )


def _js_function_body(js: str, decl: str, strip_comments: bool = False) -> str:
    """Source of the function opened by `decl`, up to its closing brace.

    `strip_comments` drops `//` lines, for assertions that must see the *code* —
    a rule named in a comment explaining it must not satisfy a check for the
    rule being followed.
    """
    assert decl in js, f"no function declared as {decl!r}"
    start = js.index(decl)
    body = js[start:js.index("\n}", start)]
    if strip_comments:
        body = "\n".join(ln for ln in body.splitlines()
                          if not ln.lstrip().startswith("//"))
    return body


# ── the live-run auto-refresh poll ──────────────────────────────────────────

def _poll_source() -> str:
    return _js_function_body(get_all_js(), "async function _autoRefreshPoll(")


def test_auto_refresh_poll_guards_against_stacking():
    """The poll fires every 5s and a request can take longer than that.

    Without an in-flight guard the requests pile up, each re-rendering the
    detail panel underneath the last.
    """
    js = get_all_js()
    assert "_autoRefreshInFlight" in js
    body = _poll_source()
    assert "if (_autoRefreshInFlight) return;" in body
    assert "_autoRefreshInFlight = true;" in body
    assert "finally" in body and "_autoRefreshInFlight = false;" in body


def test_poll_captures_the_run_id_before_stopping_auto_refresh():
    """stopAutoRefresh() nulls _autoRefreshExpId; reading it afterwards
    refreshed with null — the panel became an "Experiment not found" card the
    moment a watched run finished."""
    body = _poll_source()
    assert "const finishedId = _autoRefreshExpId;" in body
    assert "refreshDetail(finishedId)" in body
    # The broken ordering must not come back.
    assert not re.search(
        r"stopAutoRefresh\(\);\s*\n\s*await refreshDetail\(_autoRefreshExpId\)",
        body)


def test_prune_confirm_round_trips_the_preview_token():
    """The confirmed prune must delete the set the dialog described, not a
    fresh selection that also takes points logged while it was open."""
    js = get_all_js()
    assert "preview_token: pre.preview_token" in js


def _code_section_source():
    return _js_function_body(get_all_js(), "function _buildCodeSection(")


def test_code_panel_needs_a_captured_script_before_claiming_clean():
    """A notebook run must not be told its script matched the commit.

    `git_commit` is captured for *every* run inside a repo, script or not, so
    an ``exp.git_commit`` branch reached before the no-script guard fires for a
    notebook and states — confidently and falsely — that a script the run never
    had was clean. That is the exact failure the empty states exist to kill:
    an unconditional "no changes" for something git never compared.

    The server states the fact (`has_script_capture`); the client must consult it
    before saying anything about "this run's script".
    """
    body = _code_section_source()
    assert "exp.has_script_capture" in body
    # Every path that can claim something about a script is gated on `captured`,
    # and the commit claim itself lives behind it in _scriptStatusNote.
    assert "} else if (captured) {" in body
    assert "captured && !parts.scriptFiles" in body
    assert "exp.git_commit" not in body, (
        "the commit claim belongs in _scriptStatusNote, behind the captured gate")


def test_the_working_tree_diff_is_rendered_exactly_once():
    """One panel, not two renderings of the same lines against the same commit.

    The detail view used to carry a script-scoped `Script diff vs. last commit`
    panel directly above a repository-wide `Uncommitted Changes` panel — same
    baseline, same file in any single-script project, so the identical edit was
    drawn twice (one of them a lossier summary of the other).
    """
    js = get_all_js()
    assert js.count("_splitDiffByScript(") == 2       # definition + its one call
    # Comments explain the history on purpose; the check is about emitted markup.
    code = "\n".join(ln for ln in js.splitlines()
                     if not ln.lstrip().startswith("//"))
    # The second panel and its builder are gone, not merely hidden.
    assert "diffHtml" not in code
    assert "Uncommitted Changes (" not in code
    assert "Script diff vs. last commit" not in code


def test_the_merged_panel_keeps_the_script_scoped_answer():
    """Merging must not cost the question the script panel existed to answer.

    A run whose own script was clean or untracked usually sits in a repo that is
    dirty *somewhere*, so without a script-scoped note the panel would show a
    wall of unrelated files and never say anything about this run's code.
    """
    body = _code_section_source()
    assert "_scriptStatusNote(" in body
    # One fold label for both run types, not one per branch.
    js_others = get_all_js()
    others = js_others[js_others.index("function _otherFilesHtml("):]
    others = others[:others.index("\n}")]
    assert others.count("in the working tree") == 1
    assert "uncommitted when this run started" not in others
    js = get_all_js()
    note = js[js.index("function _scriptStatusNote("):]
    note = note[:note.index("\n}")]
    # Apostrophes are backslash-escaped inside the single-quoted JS strings.
    assert "had no uncommitted changes" in note
    assert "tracked by git" in note
    assert "a git repository" in note


def test_compare_does_not_claim_no_code_change_when_a_helper_moved():
    """"No code change" was only ever true of the run's *own* source.

    Run `train.py`, tweak `helper.py`, run again: the runs differ by a real code
    edit, captured in each run's working-tree diff — but it isn't either run's
    own script, so the panel found nothing and stated the opposite of what
    happened, on the one screen built to answer the question.
    """
    js = get_all_js()
    src = js[js.index("function _renderCompareCodeDiff("):]
    src = src[:src.index("\n}\n")]
    # The no-change claim must be reached only after the working tree is checked.
    assert src.index("_cmpWorkingTreeFiles(") < src.index("no code change between these runs")
    # Both callers pass the two runs, or the check has nothing to compare.
    assert "_renderCompareCodeDiff(pair.cmp.code_diff, pair.cmp.exp1, pair.cmp.exp2)" in js
    assert "_renderCompareCodeDiff(data.code_diff, data.exp1, data.exp2)" in js


def test_auto_refresh_poll_survives_a_failed_request():
    """api() returns null on failure, so `exp.error` threw into the poll's own
    catch — making one bad poll indistinguishable from a healthy one."""
    body = _poll_source()
    assert "if (!exp || exp.error) return;" in body
    assert "exp.metrics || []" in body


def test_compare_picker_pages_instead_of_asking_for_one_huge_limit():
    """The server caps `limit`, so an over-large ask comes back short — and a
    short response reads exactly like "that is all of them"."""
    js = get_all_js()
    start = js.index("async function _loadCmpExps(")
    body = js[start:js.index("\n}", start)]
    assert "offset=' + rows.length" in body
    assert "limit=' + EXP_PAGE_SIZE" in body


def test_detail_tabs_array_matches_the_button_row():
    """`switchDetailTab` pairs DETAIL_TABS[i] with the i-th #detail-tabs button.

    They are declared in two different files, and a mismatch does not error — it
    silently shows the wrong panel and marks the wrong tab active, which is the
    same shadowing hazard the GET-dispatch tables were restructured to remove.
    """
    import re
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "exptrack" / "dashboard" / "static" / "js"
    tabs_src = (static / "timeline.js").read_text()
    detail_src = (static / "detail.js").read_text()

    arr = re.search(r"const DETAIL_TABS = \[(.*?)\];", tabs_src).group(1)
    declared = [t.strip().strip("'\"") for t in arr.split(",") if t.strip()]
    buttons = re.findall(r"switchDetailTab\('([a-z-]+)','\$\{exp\.id\}'\)", detail_src)

    assert declared == buttons, (
        f"DETAIL_TABS {declared} is out of step with the button row {buttons}"
    )
    # Every tab needs a container to show/hide, or switching to it blanks the view.
    for t in declared:
        assert f'id="detail-tab-{t}"' in detail_src or t == "overview", \
            f"no #detail-tab-{t} container"


def test_a_compacted_summary_is_not_drawn_as_diff_content():
    """`compact --code-changes` replaces the summary with a `[compacted…]`
    marker. Handing that to the diff-fragment renderer drew a status string as
    diff content, split across lines on its `; ` separator — a sentinel is a
    status, never diff text."""
    js = get_all_js()
    body = js[js.index("function _diffSentinelBody("):]
    body = body[:body.index("\n}")]
    assert "startsWith('[compacted')" in body
    assert "haveSummary ?" in body


# ── Compare-mode interactions ───────────────────────────────────────────────
# Three separate surfaces let the user assemble a set of runs (or nodes) and
# compare them, and each one used to reach outside itself to do it. The rules
# below are structural: none of these failures raises, so nothing but a check
# like this notices when one comes back.


def test_every_canvas_switcher_releases_the_canvas_first():
    """The full-canvas views are siblings and two of them suppress the others
    from CSS with `!important`, so raising one means putting *all* the rest
    down. Each switcher used to hide an ad-hoc subset — `showCompareView` hid
    the two oldest only, so "Compare (N)" pressed while the Sessions tab, the
    Trash or the parameter matrix held the canvas silently did nothing.
    """
    js = get_all_js()
    for decl in ("function showCompareView(", "function showDetailView(",
                 "function showWelcome(", "function openParamMatrix(",
                 "function openTrashView(", "function toggleSessionsTab(",
                 "function closeParamMatrix("):
        body = _js_function_body(js, decl, strip_comments=True)
        assert "releaseCanvas()" in body, \
            f"{decl} does not release the canvas before raising its own view"

    # The teardown has to cover every view, or the ones it misses are exactly
    # the ones that go on hiding the view being raised. `matrix-bar` is in the
    # list because it is laid out outside `#matrix-view`.
    decls = js[js.index("const CANVAS_VIEWS"):js.index("function releaseCanvas(")]
    for view in ("welcome-state", "detail-view", "compare-view", "matrix-view",
                 "trash-view", "sessions-tab", "matrix-bar"):
        assert f"'{view}'" in decls, f"{view} is not in CANVAS_VIEWS"
    for cls in ("sessions-active", "matrix-active", "trash-active"):
        assert f"'{cls}'" in decls, f"{cls} is not in CANVAS_CLASSES"
    body = _js_function_body(js, "function releaseCanvas(")
    assert "CANVAS_VIEWS" in body and "CANVAS_CLASSES" in body


def test_matrix_compare_does_not_rewrite_the_table_selection():
    """The matrix's picks are the matrix's. Handing them to the compare flow by
    assigning the global `selectedIds` silently discarded whatever the user had
    ticked in the experiments table — a selection they may have been staging for
    a bulk delete — and left the table's action bar describing the matrix's runs.
    """
    js = get_all_js()
    body = _js_function_body(js, "function compareMatrixSelection(",
                             strip_comments=True)
    assert re.search(r"\bcompareRuns\(", body)
    assert "selectedIds" not in body, \
        "compareMatrixSelection must not touch the table's selection"
    # compareRuns takes the ids; compareSelected is the thin table-side caller.
    assert "async function compareRuns(" in js
    assert "selectedIds" in _js_function_body(js, "async function compareSelected(")


def test_closing_a_session_comparison_keeps_the_picks():
    """Dismissing the result panel is not discarding the selection behind it —
    the picks are several deliberate clicks on a tree of any size, and wanting
    the columns off screen is not wanting to start over."""
    js = get_all_js()
    # The rendered comparison's Close is wired to the panel-only close, not to
    # Clear. (The "nothing left to compare" branch does offer Clear, correctly —
    # so scope this to the head that renders actual columns.)
    run = _js_function_body(js, "function runCompare(")
    head = run.split("Comparing ")[-1]
    assert "_closeCompareResult()" in head
    assert "clearCompare()" not in head, \
        "the result panel's Close must not clear the picks"
    body = _js_function_body(js, "function _closeCompareResult(")
    assert "_compareNodes" not in body, "closing the result must not clear picks"
    # Clear still clears, and still closes the result it produced.
    assert "_closeCompareResult()" in _js_function_body(js, "function clearCompare(")


def test_clearing_the_staged_runs_discards_the_comparison_they_produced():
    """Clear emptied the chips and left the whole rendered comparison standing
    under a bar reading "No runs chosen yet" — the one thing still on screen was
    the thing Clear was pressed to remove, so the button read as broken. The
    token bump is part of the teardown: without it a comparison already in
    flight lands afterwards and repaints what was just cleared."""
    js = get_all_js()
    assert "_discardComparison()" in _js_function_body(js, "function clearMultiPicked(")
    body = _js_function_body(js, "function _discardComparison(")
    assert "_multiCmpToken++" in body, \
        "an in-flight comparison must not land after a clear"
    assert "multiCharts = {}" in body
    assert "_lastComparison = null" in body
    assert "multi-compare-result" in body
    assert "_clearCompareHash()" in body, \
        "a cleared page must not keep an address naming the comparison"


def test_session_compare_states_picks_it_could_not_resolve():
    """A pick can stop resolving between the click and the compare (trashed in
    another tab). Dropping those silently rendered three columns for four picks
    with the bar still saying four. Both result heads report it the same way."""
    js = get_all_js()
    run = _js_function_body(js, "function runCompare(")
    # Both the success head and the "nothing left" head render the same chip.
    assert run.count("_missingPicksHtml(") == 2
    assert "cmp-missing" in _js_function_body(js, "function _missingPicksHtml(")


def test_matrix_selection_is_pruned_to_the_set_on_screen():
    """The selection survives closing the view, but the set analysed is whatever
    the list is filtered to — so a pick could name a run with no row to un-tick
    it on, which the bar still counted and Compare would still have opened."""
    js = get_all_js()
    assert re.search(r"_pruneMatrixSelection\(",
                     _js_function_body(js, "async function loadParamMatrix("))
    body = _js_function_body(js, "function _pruneMatrixSelection(")
    assert "_matrixSelected" in body and "present" in body


# ── Compare surfaces (1.4 audit) ────────────────────────────────────────────

def test_compare_chart_canvas_ids_are_positional():
    """`val/acc` and `val_acc` both sanitize to `val_acc`; a duplicate canvas id
    makes the second `new Chart(...)` throw, and the unhandled rejection killed
    every later chart while the table above still rendered."""
    js = get_all_js()
    assert "function multiChartId(" in js
    # No caller reconstructs an id from a sanitized key any more.
    assert "'cmp-chart-' + k.replace" not in js
    assert "'multi-chart-' + k.replace" not in js
    assert "'multi-curve-' + i" in js


def test_multi_compare_tints_by_polarity_not_by_size():
    """Tinting max=green/min=red highlighted the *worst* run on loss/latency —
    against the project's "green means better, not bigger" rule and against the
    pair view's Delta column one panel over.

    The rule lives in `_multiMetricRowHtml` because the metric table now has two
    callers — Multi Compare and the matrix's inline comparison — and a second
    copy of it is a second place for the tint to come back inverted.
    """
    js = get_all_js()
    body = _js_function_body(js, "function _multiMetricRowHtml(")
    assert "metricGoodDirection(" in body
    assert "metricMoved(" in body, "the tint needs the same epsilon the cells print at"
    for fn in ("function _renderMultiComparison(", "function renderMatrixInlineCompare("):
        assert "_multiMetricTableHtml(" in _js_function_body(js, fn), \
            f"{fn} builds its own metric table instead of the shared one"


def test_multi_compare_posts_its_id_set_and_reports_missing_picks():
    js = get_all_js()
    fetch = _js_function_body(js, "async function doMultiCompare(")
    assert "postApi('/api/multi-compare'" in fetch
    render = _js_function_body(js, "function _renderMultiComparison(")
    assert "unknown_ids" in render and "cmp-missing" in render


def test_polarity_toggle_repaints_without_refetching():
    """Flipping which direction is better changes a tint, not the data. Re-running
    the comparison meant a POST plus one /api/metrics call per run — 21 requests
    for a 20-run comparison — to recolour one column."""
    js = get_all_js()
    body = _js_function_body(js, "function toggleMetricPolarity(")
    assert "_repaintComparison()" in body
    repaint = _js_function_body(js, "function _repaintComparison(")
    assert "_renderMultiComparison(" in repaint
    assert "postApi(" not in repaint and "doMultiCompare(" not in repaint


def test_multi_compare_sends_the_readers_polarity_overrides():
    """`rank_by=best` is resolved server-side. Without the overrides it picked the
    best point by the name heuristic while the cell beside it was tinted by the
    user's override, so one row disagreed with itself about who won."""
    js = get_all_js()
    body = _js_function_body(js, "async function doMultiCompare(")
    assert "metric_goals" in body and "metricPolarityGoals()" in body


def test_compare_config_table_uses_the_servers_varying_set():
    """`JSON.stringify` equality called `0.01` and `"0.01"` two settings — the
    same param captured by argparse and by the pipeline CLI — so Compare showed
    a row the matrix, the CLI and duplicate detection all called constant."""
    js = get_all_js()
    body = _js_function_body(js, "function _multiConfigTable(")
    assert "JSON.stringify" not in body
    render = _js_function_body(js, "function _renderMultiComparison(")
    assert "data.varying_params" in render


def test_both_compare_surfaces_guard_against_a_superseded_request():
    """Two rapid clicks interleave; the older result could land last, painting a
    comparison the user is no longer looking at."""
    js = get_all_js()
    body = _js_function_body(js, "async function doMultiCompare(")
    assert "Token" in body, "the comparison has no request token"
    # The pair panels are fetched inside the same guarded window.
    assert body.index("_fetchPairExtras(") < body.index("_renderMultiComparison(data, ids, token)")


def test_the_merged_compare_keeps_every_pair_only_panel():
    """Compare had two tabs answering the same question at different arities.
    Three of the four things only the pair tab could do — the code diff between
    two attempts, the notebook variable table, the A/B image overlay — were
    absent from the multi view, so a three-run comparison could not reach them
    and getting there meant re-picking both runs in a different picker. Merging
    the tabs must not quietly drop any of them."""
    js = get_all_js()
    extras = _js_function_body(js, "function _pairExtrasHtml(")
    for fn in ("_pairParamsHtml(", "_renderCompareCodeDiff(", "_pairVariablesHtml(",
               "_pairImagesHtml("):
        assert fn in extras, f"the merged view lost {fn}"
    # The A/B overlay bar and its handlers, which only exist for two runs.
    imgs = _js_function_body(js, "function _pairImagesHtml(")
    assert "cross-cmp-bar" in imgs and "doCrossCompare()" in imgs
    # The delta column, which is only defined between two runs.
    table = _js_function_body(js, "function _multiMetricTableHtml(")
    assert "exps.length === 2" in table and "Delta" in table
    assert "metricDelta(" in _js_function_body(js, "function _multiMetricRowHtml(")
    # And the tab chrome is gone rather than hidden.
    assert "compare-pair-content" not in DASHBOARD_HTML
    assert "Pair Compare" not in DASHBOARD_HTML


def test_bulk_export_does_not_download_an_error_payload():
    """A 500 downloaded a `.csv` containing {"error":...} under a success toast."""
    js = get_all_js()
    assert "function _exportText(" in js
    for fn in ("async function sidebarExportFmt(", "async function sidebarCopyFmt("):
        assert "_exportText(" in _js_function_body(js, fn)


# ── Choosing runs ───────────────────────────────────────────────────────────
# Every surface that asks "which runs?" goes through one picker over one cache.
# The failure these guard is a quiet one: a picker searching a narrower set than
# the user thinks reports "no match" for a run that exists.


def test_every_run_picking_surface_uses_the_shared_picker():
    """Three surfaces ask which runs, and each used to ask with a native
    <select> — one line per run, searchable only by a name the user may never
    have seen. A second picker built for one of them would drift from the other
    two, which is how the old list box ended up the only one without a filter."""
    js = get_all_js()
    assert "async function openRunPicker(" in js
    for fn in ("function openMultiRunPicker(", "function openMatrixRunPicker("):
        assert "openRunPicker(" in _js_function_body(js, fn), \
            f"{fn} does not open the shared run picker"


def test_the_picker_and_the_compare_filter_share_one_run_cache():
    """Two caches would mean the picker and the filter box beside it could be
    searching different sets of runs, and "no match" would mean different things
    in each."""
    js = get_all_js()
    body = _js_function_body(js, "async function openRunPicker(")
    assert "_loadCmpExps(" in body
    # The picker reads whole runs, so the cache has to carry them.
    entries = _js_function_body(js, "function _cmpEntries(")
    assert "e: e" in entries and "hay:" in entries


def test_a_run_is_searchable_by_params_the_label_does_not_print():
    """The option label shows three params because a dropdown line has room for
    three. Matching only what was printed made a run identified by its fourth
    parameter unfindable — with the picker reporting "no match" for a run in the
    list it had just searched."""
    js = get_all_js()
    body = _js_function_body(js, "function _cmpHaystack(")
    assert "e.params" in body and "isUserParamKey(" in body
    assert "e.script" in body


def test_the_pickers_search_can_actually_narrow_the_list():
    """Selected runs were briefly force-included past the query so a pick could
    always be un-ticked. The matrix opens the dialog with its *entire* analysed
    set preselected, so every row was exempt and typing narrowed nothing — a
    search box that cannot narrow is worse than none, because it looks like it
    worked. Picks the query hides are counted in the footer instead."""
    js = get_all_js()
    body = _js_function_body(js, "function _rpFiltered(")
    assert "_rpSelected" not in body
    assert "not matching this search" in _js_function_body(js, "function _rpRenderFooter(")


def test_the_picker_states_both_reasons_the_list_is_partial():
    """Too many matched to paint and "the cache is one page of the project" lead
    to different actions — narrow the search vs. load the rest — so they are
    never collapsed into one notice."""
    js = get_all_js()
    body = _js_function_body(js, "function _rpNoticesHtml(")
    assert "RP_MAX_ROWS" in body and "narrow the search" in body
    assert "_cmpHasMore" in body and "rpLoadAll()" in body


def test_a_matrix_run_choice_is_a_set_not_a_search():
    """The analysed set was whatever the experiment list was filtered to, so
    narrowing it meant leaving the view to rewrite a search box — and "these
    five runs" was not expressible at all unless their names shared a
    substring."""
    js = get_all_js()
    body = _js_function_body(js, "function _matrixIds(", strip_comments=True)
    assert "_matrixIdSet" in body
    # An empty pick returns to the filter rather than analysing nothing, which
    # would be a dead view whose only escape is the control that emptied it.
    pick = _js_function_body(js, "function openMatrixRunPicker(")
    assert "ids.length ? new Set(ids) : null" in pick
    assert "function clearMatrixRunChoice(" in js


def test_multi_compare_holds_its_picks_outside_a_select():
    """The `<select multiple>` needed Ctrl/Cmd-click for a second run — stated in
    fine print under it — so one plain click silently replaced the whole
    selection."""
    js = get_all_js()
    assert 'id="cmp-multi-select"' not in DASHBOARD_HTML
    body = _js_function_body(js, "function doMultiCompareFromSelector(")
    assert "_multiPicked" in body
    # Staging the table's selection is a copy: editing the comparison must not
    # reach back into what the table has ticked.
    assert "selectedIds" not in _js_function_body(js, "function unpickMultiRun(")


def test_the_config_panel_renders_even_when_nothing_varies():
    """It used to return an empty string, so the one panel built to answer "what
    changed" answered by showing nothing — indistinguishable from the panel
    being missing or from the comparison failing to load it."""
    js = get_all_js()
    body = _js_function_body(js, "function _multiConfigTable(")
    assert "return ''" not in body
    assert "identical across these runs" in body
    # Internal `_`-prefixed bookkeeping differs on nearly every run and is not a
    # setting anyone chose — it would be the loudest row here saying nothing.
    assert "isUserParamKey" in body


def test_chart_series_are_labelled_by_what_differs():
    """Every chart in Multi Compare labelled its series with the run's *name*.
    For a sweep those are auto-generated and near-identical, so a five-run legend
    read as five copies of one string and the charts could not answer the only
    question they were opened for: which line is which setting."""
    js = get_all_js()
    body = _js_function_body(js, "function _multiSeriesLabel(")
    assert "e.params" in body
    # A run missing every label key still has to be tellable from the others.
    assert "e.name" in body
    # Both chart kinds use it, and the keys come from the server's varying set.
    curves = _js_function_body(js, "async function _renderMultiCurves(")
    assert "labelOf(e)" in curves
    assert "_multiSeriesLabel(e, labelKeys)" in js
    assert "varying_params" in _js_function_body(js, "function _multiLabelKeys(")
    # Relabelling is a repaint, not a re-request.
    setter = _js_function_body(js, "function setMultiLabelBy(")
    assert "_repaintComparison()" in setter and "postApi(" not in setter


def test_the_matrix_says_in_words_what_it_is_showing():
    """The view opened onto a wide table and four collapsible analyses and never
    stated what any of it amounted to, so the first job on arrival was to read a
    grid and work out which columns mattered and which row won."""
    js = get_all_js()
    body = _js_function_body(js, "function _matrixSummaryHtml(")
    assert "varied" in body and "_bestRowId()" in body
    assert "_matrixSummaryHtml(d)" in _js_function_body(js, "function renderParamMatrix(")
    # Each collapsed section says what it will show before it is opened.
    for key in ("desc: 'the best runs", "desc: 'whether the best result",
                "desc: 'runs not beaten", "desc: 'what each parameter"):
        assert key in js, f"missing section description: {key}"
    assert "sec.desc" in _js_function_body(js, "function _mxSectionToggleHtml(")


def test_identifying_a_chart_point_does_not_leave_the_analysis():
    """Clicking a dot opened that run's detail page, which put the whole
    analysis down: the one gesture for "which run is this?" cost the comparison
    it was asked from, and getting back meant reopening Analyze and rebuilding
    the set."""
    js = get_all_js()
    draw = _js_function_body(js, "function _drawEffectChart(")
    assert "pickEffectPoint(p.key, pt._id)" in draw
    assert "openFromMatrix(pt._id)" not in draw
    # The tooltip names the run, and covers exactly one point.
    assert "_fxRunName(raw._id)" in draw
    assert "intersect: true" in draw
    # The card is repainted alone — rebuilding the section would destroy and
    # recreate every live Chart.js instance in it.
    body = _js_function_body(js, "function _renderEffectPick(")
    assert "renderParamEffects()" not in body and "loadMxSection(" not in body


def test_the_colour_by_picker_can_show_its_own_value():
    """The server built the option list with the selected key removed, so the
    `selected` match had nothing to attach to and the <select> fell back to its
    first entry: picking `model` coloured the points and then displayed "—"."""
    js = get_all_js()
    body = _js_function_body(js, "function renderParamEffects(")
    # Marked from the client's own state, not from the server's echo.
    assert "g.key === _effectsGroupBy" in body
    # The per-panel rule lives in the panel it applies to.
    draw = _js_function_body(js, "function _drawEffectChart(")
    assert "_effectsGroupBy !== p.key" in draw
    # A grouping that separates nothing says so rather than looking inert.
    note = _js_function_body(js, "function _effectsGroupNoteHtml(")
    assert "separates nothing" in note


def test_changing_the_colour_grouping_is_a_repaint_not_a_request():
    """It called `loadMxSection`, which blanks the section to "Summarizing…",
    re-POSTs the whole analysis and rebuilds it — so choosing a colour read as
    the page reloading, for a change that only decides which points share one.
    The payload carries every grouping's value per run, so the answer is already
    on the client."""
    js = get_all_js()
    body = _js_function_body(js, "function setEffectsGroupBy(")
    assert "renderParamEffects()" in body
    assert "loadMxSection(" not in body
    assert "run_groups" in _js_function_body(js, "function _fxGroupOf(")


def test_a_chart_never_silently_drops_the_groups_it_cannot_colour():
    """`groups.slice(0, N)` built the datasets from the first few groups only,
    so with more groups than colours — "colour by run", or any sweep over a
    many-valued parameter — the extra runs vanished from the chart entirely: a
    scatter quietly missing most of its points, with nothing saying so."""
    js = get_all_js()
    body = _js_function_body(js, "function _drawEffectChart(")
    assert "const overflow = groups.slice(_FX_MAX_GROUPS);" in body
    assert "more (uncoloured)" in body


def test_a_run_can_be_found_on_the_charts_not_only_hovered():
    """Hover answered "which run is this point?" and was the only direction that
    worked. The points of a sweep overlap, so finding one specific run meant
    hovering each in turn and reading a long auto-generated name off a tooltip
    that moves with the cursor."""
    js = get_all_js()
    body = _js_function_body(js, "function _fxHighlightSet(")
    assert "_matrixSelected" in body and "_fxPicked" in body
    # Ticking a row repaints the highlight, without rebuilding the charts.
    assert "_refreshEffectHighlights()" in _js_function_body(js, "function toggleMatrixSelect(")
    refresh = _js_function_body(js, "function _refreshEffectHighlights(")
    assert "update('none')" in refresh and "loadMxSection(" not in refresh
    # With nothing selected nothing is dimmed — an always-on highlight is a
    # filter, and this view already has one.
    style = _js_function_body(js, "function _fxPointStyle(")
    assert "hi.size" in style


def test_the_colour_key_does_not_depend_on_there_being_charts():
    """It was rendered above the charts, so a comparison with no shared
    multi-point metric — two different models, a run that logged only final
    values — got no key at all, which is the case where knowing which run is
    which matters most."""
    js = get_all_js()
    body = _js_function_body(js, "function _renderMultiComparison(")
    assert "_multiSeriesKeyHtml(exps, labelKeys)" in body
    # …emitted with the tables, not inside the branch that needs metrics.
    assert body.index("_multiSeriesKeyHtml(") < body.index("if (keys.length)")


def test_compare_columns_keep_the_end_of_a_run_name():
    """Auto-generated names differ in their tail, so head-truncating them to 17
    characters rendered a table whose every column read `Aug12_train__lr0…` — a
    comparison you cannot tell apart by the thing being compared. `midEllipsis`
    is the existing answer; the compare surfaces just weren't using it."""
    js = get_all_js()
    src = js[js.index("// ── Compare ──"):]
    assert "e.name.slice(0, 17)" not in src and "e.name.slice(0,17)" not in src
    assert "function _cmpColName(" in js and "midEllipsis(" in js


def test_the_config_panel_keeps_the_constants_it_folds():
    """"What did these runs have in common" is what the differences are read
    against — routinely the thing that explains the result."""
    js = get_all_js()
    body = _js_function_body(js, "function _multiConstantsHtml(")
    assert "isUserParamKey(" in body and "varySet" in body


def test_the_small_button_classes_are_actually_styled():
    """`.btn-sm`/`.btn-ghost` were used by the matrix header, its selection bar
    and the toolbar's Analyze button and styled nowhere, so each rendered as a
    raw platform default button on a page with one button look."""
    from exptrack.dashboard.static import DASHBOARD_CSS
    assert ".btn-sm {" in DASHBOARD_CSS
    assert ".btn-ghost {" in DASHBOARD_CSS


def test_every_select_in_the_matrix_view_carries_a_style_class():
    """A bare `<select>` does not fall back to the page's look — it falls back to
    the *operating system's*, ignoring the theme (and dark mode) entirely. The
    matrix emitted five of them (Rank by, Show, the two Pareto axes, Colour by)
    among themed controls. `.select-sm` is the shared toolbar select.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "exptrack" / "dashboard" /
           "static" / "js" / "matrix.js").read_text()
    bare = [m for m in re.findall(r"<select[^>]*>", src) if "class=" not in m]
    assert not bare, f"unstyled <select> in the matrix view: {bare}"
    from exptrack.dashboard.static import DASHBOARD_CSS
    assert ".select-sm {" in DASHBOARD_CSS or ".select-sm," in DASHBOARD_CSS


def test_the_matrix_header_is_the_shared_view_header():
    """An `<h2>` here inherits the table stylesheet's section-heading treatment —
    uppercase, letter-spaced, muted — a style no other full-canvas view title
    uses."""
    js = get_all_js()
    body = _js_function_body(js, "function _matrixShell(")
    assert "<h2>" not in body
    assert "back-link" in body and "compare-header" in body


# ── Getting back out of a view ──────────────────────────────────────────────


def test_compare_goes_back_to_the_view_it_was_opened_from():
    """Compare is a full-canvas view that puts down whatever raised it, and its
    Back was hardwired to the experiments list — so comparing runs picked in the
    parameter matrix cost you the table you had assembled them in, with no way
    back but re-opening Analyze and re-ticking every row."""
    js = get_all_js()
    assert 'onclick="closeCompareView()"' in DASHBOARD_HTML
    body = _js_function_body(js, "function closeCompareView(")
    assert "openParamMatrix({replaceHash: true})" in body and "showWelcome()" in body
    # The origin travels with the request to compare, not as a global the
    # matrix writes and Compare reads back.
    assert "compareRuns(ids, 'matrix')" in js


def test_the_two_addressable_views_push_a_history_entry():
    """`replaceState` gave a comparison an address but no *position*: no in-app
    navigation left an entry, so the browser Back button did not go back a view,
    it left the dashboard — landing on a URL with no `?token=`, which works only
    while localStorage still holds one."""
    js = get_all_js()
    assert "window.history.pushState(" in _js_function_body(js, "function _pushViewHash(")
    assert "_pushViewHash('#matrix', opts && opts.replaceHash)" in js
    assert "_pushViewHash('#compare=" in js
    # popstate restores the named view through the one hash parser.
    body = _js_function_body(js, "async function _onPopView(")
    assert "restoreCompareFromUrl()" in body and "openParamMatrix()" in body
    assert "window.addEventListener('popstate', _onPopView);" in js


def test_the_login_overlay_can_always_be_dismissed():
    """`exptrack ui` mints a random token per session, so restarting it
    invalidates the one the browser stored and the next background poll 401s.
    The overlay had no Cancel, no Escape and no click-outside, so a stale token
    did not degrade the page — it locked it behind a dialog whose only exit was
    a token the user had to leave and find."""
    js = get_all_js()
    body = _js_function_body(js, "function _showLoginOverlay(")
    assert "function dismiss(" in body
    assert "ev.key === 'Escape'" in body
    assert "exptrack-login-dismiss" in body
    # And it names the reason, which "Invalid token" never did.
    assert "mints a new token" in body
    # A dismissal with no token leaves every request failing; say so.
    assert "_showAuthBanner()" in body
    # Logging back in reloads the data the 401'd request never returned.
    assert "loadExperiments()" in body


def test_a_dismissed_login_prompt_does_not_ambush_the_next_click():
    """Making the modal dismissible fixed the lock-out and created a subtler
    failure: a stale-token session renders, reads as working, and then raises
    the full-screen prompt again at the first thing you click — "the home page
    is fine but Compare demands a token". One dismissal is one decision."""
    js = get_all_js()
    body = _js_function_body(js, "function _showLoginOverlay(")
    assert "if (_authDismissed && !force) { _showAuthBanner(); return; }" in body
    # The banner is the one control that reopens it, deliberately.
    assert "function openLoginPrompt(" in js
    assert "_showLoginOverlay(true)" in js
    from exptrack.dashboard.static import DASHBOARD_CSS
    assert ".auth-banner {" in DASHBOARD_CSS


def test_comparing_from_the_matrix_does_not_require_leaving_it():
    """The full Compare view is still there for curves and images, but the two
    tables that answer most of "what do these differ by" now render under the
    rows the runs were picked in — so the selection, the parameters and the
    numbers are on screen together."""
    js = get_all_js()
    body = _js_function_body(js, "async function compareMatrixInline(")
    assert "postApi('/api/multi-compare'" in body
    assert "_mxCmpToken" in body, "the inline comparison needs the same staleness guard"
    render = _js_function_body(js, "function renderMatrixInlineCompare(")
    assert "_multiConfigTable(" in render
    # Comparing four runs and rendering three has to be stated here too.
    assert "could not be found" in render


def test_no_raw_nul_byte_in_the_bundle():
    """A literal NUL makes grep/ripgrep treat a file as binary and stop reading
    it mid-file — a trap for any grep-based check like the ones in this file."""
    assert "\x00" not in get_all_js()
