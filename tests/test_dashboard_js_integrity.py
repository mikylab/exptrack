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


def test_every_private_helper_called_is_defined():
    """Every ``_helper(`` the bundle calls must be defined somewhere in it.

    ESLint runs per file with ``no-undef`` off (every name is a cross-file
    global), so a helper deleted in one edit while a caller survived shipped
    silently: ``_sharedImageNote`` vanished from compare.js while the image
    rows still called it, and every comparison of runs with images threw a
    ReferenceError before writing any HTML — the Compare button did nothing.
    The ``_`` prefix is the codebase's private-helper convention, so this
    covers the helpers without false positives from callback parameters.
    """
    js = get_all_js()
    called = set(re.findall(r'(?<![\w$.])(_[\w$]+)\s*\(', js))
    # `let _resolve;` assigned later (a Promise's resolver) is a definition too.
    declared = set(re.findall(r'\b(?:let|var)\s+([A-Za-z_$][\w$]*)\s*;', js))
    missing = sorted(called - _defined_names(js) - declared)
    assert not missing, f"Bundle calls undefined helpers: {missing}"


def test_cross_image_thumbs_quote_their_handler_arguments():
    """The compare image thumb's onclick quotes its string arguments.

    A mangled edit turned each ``\\'`` into ``' + E + '`` — a reference to an
    identifier that exists nowhere — so building the pair view's image columns
    threw and the whole comparison rendered nothing.
    """
    js = get_all_js()
    start = js.index("function _cmpImageCol(")
    body = js[start:js.index("\n}\n", start)]
    assert "' + E + '" not in body
    assert "selectCrossImg(\\''" in body


def test_boot_recovers_a_dead_project_before_loading_its_data():
    """A stored id the server does not know 400s every project-scoped load.

    The page used to fire them all anyway and recover afterwards, so a tab
    reopened after a project went away showed an empty table under a
    "Couldn't load data … 400 … /api/stats" banner until /api/projects came
    back. The auth probe carries the project and records what ping said about
    it; boot waits on loadProjects() when that was not 'ok'.
    """
    js = get_all_js()
    start = js.index("function _ping(")
    ping = js[start:js.index("\n}\n", start)]
    assert "X-Exptrack-Project" in ping and "_pingProjectState" in ping
    start = js.index("function _bootDashboard(")
    boot = js[start:js.index("\n}\n", start)]
    assert "_pingProjectState !== 'ok'" in boot
    assert "loadProjects().then(() => _bootProjectData())" in boot


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
    short response reads exactly like "that is all of them".

    The paging lives in `_loadProjectRuns`, which is where it moved when the
    cache became per-project: `_loadCmpExps` is now the page-project caller of
    it, so checking the loader covers both surfaces at once.
    """
    js = get_all_js()
    body = _js_function_body(js, "async function _loadProjectRuns(")
    assert "offset=' + rows.length" in body
    assert "limit=' + EXP_PAGE_SIZE" in body
    # The page's project is '' here, so the loader's own cache key is what
    # keeps the picker and the Compare filter box on one list.
    assert "_loadProjectRuns('" in _js_function_body(js, "async function _loadCmpExps(")


def test_detail_tabs_array_matches_the_button_row():
    """`switchDetailTab` pairs DETAIL_TABS[i] with the i-th #detail-tabs button.

    They are declared in two different files, and a mismatch does not error — it
    silently shows the wrong panel and marks the wrong tab active, which is the
    same shadowing hazard the GET-dispatch tables were restructured to remove.
    """
    import re
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "exptrack" / "dashboard" / "static" / "js"
    tabs_src = (static / "timeline.js").read_text(encoding="utf-8")
    detail_src = (static / "detail.js").read_text(encoding="utf-8")

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


def test_the_picker_and_the_compare_filter_share_one_run_cache_per_project():
    """Two caches would mean the picker and the filter box beside it could be
    searching different sets of runs, and "no match" would mean different things
    in each.

    Now one cache *per project*, for the mirror-image reason: a run list is
    entirely a property of the project it was paged from, so a single shared
    list would serve project A's runs — under bare ids that resolve against B —
    while the user browsed B. Both surfaces still reach it through the one
    loader, so they cannot end up describing different sets of the same
    project.
    """
    js = get_all_js()
    for fn in ("async function _rpLoad(", "async function _loadCmpExps("):
        assert "_loadProjectRuns(" in _js_function_body(js, fn), \
            f"{fn} does not go through the shared per-project loader"
    loader = _js_function_body(js, "async function _loadProjectRuns(")
    assert "_cmpCacheByProject[key]" in loader, "the loader does not cache per project"
    assert "_cmpCacheKey(projectId)" in loader, "the cache key ignores the project"
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
    # The wording covers the facet chips too — a pick hidden by a chip is just
    # as absent from the list as one hidden by the query.
    assert "hidden by the search or filters" in _js_function_body(
        js, "function _rpRenderFooter(")


def test_the_picker_states_both_reasons_the_list_is_partial():
    """Too many matched to paint and "the cache is one page of the project" lead
    to different actions — narrow the search vs. load the rest — so they are
    never collapsed into one notice."""
    js = get_all_js()
    body = _js_function_body(js, "function _rpNoticesHtml(")
    assert "RP_MAX_ROWS" in body and "narrow the search" in body
    assert "_rpHasMore" in body and "rpLoadAll()" in body


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
           "static" / "js" / "matrix.js").read_text(encoding="utf-8")
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
    assert "_restoreViewFromHash()" in _js_function_body(js, "async function _onPopView(")
    body = _js_function_body(js, "async function _restoreViewFromHash(")
    assert "restoreCompareFromUrl()" in body and "openParamMatrix()" in body
    assert "window.addEventListener('popstate', _onPopView);" in js


def test_a_run_has_an_address_a_reload_reopens():
    """Run detail had no hash, so reloading while reading a run — or Back out
    of a comparison opened from one — always landed on the experiments list.

    Entering a run writes `#run=<id>` (pushed, replaced on a lateral move), a
    tab switch replaces it with the tab, and boot restores through the same
    parser popstate uses — so a reload and the Back button cannot disagree.
    """
    js = get_all_js()
    detail = _js_function_body(js, "async function refreshDetail(")
    assert "_pushViewHash(_runViewHash(id, currentDetailTab), lateral)" in detail
    tabs = _js_function_body(js, "function switchDetailTab(")
    assert "_pushViewHash(_runViewHash(expId, tab), true)" in tabs
    restore = _js_function_body(js, "async function _restoreViewFromHash(")
    assert "_parseRunViewHash(hash)" in restore and "refreshDetail(run.id)" in restore
    start = js.index("function _bootProjectData(")
    assert "_restoreViewFromHash()" in js[start:js.index("\n}\n", start)]
    # Leaving to the list drops the address, or a reload would reopen the run.
    assert "h.startsWith('#run=')" in _js_function_body(js, "function _clearViewHash(")


def test_opening_a_run_leaves_the_rail_as_the_reader_left_it():
    """Opening a run forced the rail open, and returning to the list forced it
    shut — so the rail's state was never the reader's. Neither view switch may
    write the class; the list view re-applies the stored choice."""
    js = get_all_js()
    detail = _js_function_body(js, "async function refreshDetail(")
    assert "classList.remove('collapsed')" not in detail
    welcome = _js_function_body(js, "function showWelcome(")
    assert "classList.add('collapsed')" not in welcome
    assert "restoreSidebarState()" in welcome


def test_the_login_overlay_can_always_be_dismissed():
    """A 401 arrives on a background poll, not on anything the user just did,
    so the overlay must be dismissible and must say what to do. It had no
    Cancel, no Escape and no click-outside, so a stale token did not degrade
    the page — it locked it behind a dialog whose only exit was a token the
    user had to leave and find."""
    js = get_all_js()
    body = _js_function_body(js, "function _showLoginOverlay(")
    assert "function dismiss(" in body
    assert "ev.key === 'Escape'" in body
    assert "exptrack-login-dismiss" in body
    # And it names the way back, which "Invalid token" never did. Asserted on
    # the command rather than a sentence: this test used to pin the words
    # "mints a new token", which stopped being true when 1.9.0 persisted the
    # token, so the test was holding false copy in place.
    assert "exptrack ui status" in body
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


# ── picking a point in Compare Within ────────────────────────────────────────

def test_picking_a_timeline_point_does_not_rebuild_the_whole_tab():
    """Selecting A or B is a selection change, not a data change.

    It used to call `loadCompareWithin`, which re-requests the timeline and
    rewrites the tab's whole innerHTML — so the `.cw-timeline` list scrolled
    itself back to the top and `#main-content` collapsed and re-clamped,
    throwing the reader to the top of the page on every click. The one control
    whose job is "click the event you mean" moved the event out from under the
    cursor.
    """
    js = get_all_js()
    body = _js_function_body(js, "function selectWithinSeq(", strip_comments=True)
    assert "loadCompareWithin(" not in body, \
        "a selection must repaint in place, not refetch and rebuild the tab"
    assert "_cwRepaintSelection(" in body
    # Clear is the same kind of change and must take the same path.
    clear = _js_function_body(js, "function clearWithinSelection(", strip_comments=True)
    assert "loadCompareWithin(" not in clear
    assert "_cwRepaintSelection(" in clear


def test_the_in_place_repaint_holds_the_page_and_list_scroll():
    """Both scrollers: the page (`#main-content`, the pattern the detail refresh
    already follows) and the checkpoint list's own overflow box."""
    body = _js_function_body(get_all_js(), "function _cwRepaintSelection(",
                             strip_comments=True)
    assert "main-content" in body
    assert "scrollTop" in body


def test_a_stale_within_comparison_is_cleared_not_left_standing():
    """The result panel answers one pair of points. Changing either point makes
    it an answer to a question no longer on screen."""
    body = _js_function_body(get_all_js(), "function _cwRepaintSelection(",
                             strip_comments=True)
    assert "within-compare-result" in body


# ── narrowing the run picker ─────────────────────────────────────────────────

def test_the_picker_can_be_narrowed_without_typing():
    """A text box can only be used by someone who remembers what to type. With
    twenty-odd runs listed, narrowing to "the failed cnn runs" meant guessing a
    substring; the facet chips make each value the runs actually hold a click."""
    js = get_all_js()
    for name in ("_rpFacetGroups", "rpToggleFacet", "rpClearFacets", "_rpFacetSel"):
        assert name in js, f"the picker needs {name}"
    body = _js_function_body(js, "function _rpFiltered(", strip_comments=True)
    assert "_rpMatchesFacets" in body, "the facets have to actually filter the list"


def test_facet_values_within_a_group_are_an_or_and_groups_are_an_and():
    """status=failed OR running, *and* script=train.py — the reading every
    faceted list uses. An AND inside a group can only ever match nothing."""
    body = _js_function_body(get_all_js(), "function _rpMatchesFacets(",
                             strip_comments=True)
    assert "return false" in body, "a group with no matching value rejects the run"


def test_a_facet_count_is_what_clicking_it_would_leave():
    """Counting against the unfiltered set promises rows that are not there:
    with `script=eval.py` already on, a `status=failed` chip reading 14 must not
    mean fourteen runs of which two are eval's. Counted against everything else
    currently applied — the chip's own group excluded, or turning a second value
    on in it would always read zero."""
    body = _js_function_body(get_all_js(), "function _rpFacetGroups(",
                             strip_comments=True)
    assert "_rpMatchesFacets" in body or "except" in body


def test_the_picks_and_the_filters_are_cleared_separately():
    """Two different things to undo: the runs chosen, and the narrowing that
    decided which runs were offered. One button for both would make dropping a
    stray chip throw away a selection assembled across four searches."""
    js = get_all_js()
    picks = _js_function_body(js, "function rpClearSelection(", strip_comments=True)
    assert "_rpFacetSel" not in picks, "clearing the picks must not drop the filters"
    facets = _js_function_body(js, "function rpClearFacets(", strip_comments=True)
    assert "_rpSelected" not in facets, "clearing the filters must not drop the picks"
    assert "_rpFacetSel = {}" in facets
    assert 'onclick="rpClearFacets()"' in js, "the facet bar needs its own clear"


def test_the_picker_states_how_many_facets_are_narrowing_it():
    """A list that is short because of a chip scrolled out of view is
    indistinguishable from a project with four runs in it."""
    js = get_all_js()
    assert "_rpActiveFacetCount(" in js
    bar = _js_function_body(js, "function _rpFacetBarHtml(", strip_comments=True)
    assert "_rpActiveFacetCount(" in bar


# ── taking the charts out of the page ────────────────────────────────────────

def test_show_all_charts_can_be_taken_as_one_image():
    """Nine downloads is not a figure. `Show All` is the view that answers "how
    did every metric move" and the only way out of it was one PNG per canvas,
    to be reassembled by hand in something else."""
    js = get_all_js()
    assert "function _chartsSheetCanvas(" in js
    body = _js_function_body(js, "function _chartsSheetCanvas(", strip_comments=True)
    assert "drawImage" in body
    assert "chart-download-sheet" in js, "the sheet needs its own control"


def test_a_chart_can_be_copied_not_only_downloaded():
    """Pasting into a lab notebook or a message should not require finding the
    file the browser just saved."""
    js = get_all_js()
    body = _js_function_body(js, "function copyChartsPng(", strip_comments=True)
    assert "_copyCanvasPng(" in body
    # The clipboard holds one image, so several charts go as the sheet — copying
    # them one at a time would keep only the last.
    assert "_chartsSheetCanvas(" in body
    assert "chart-copy-png" in js


def test_the_clipboard_path_says_why_it_is_unavailable():
    """Writing an image to the clipboard needs a secure context: localhost is
    one, a plain-http tunnel is not. A button that silently does nothing there
    reads as a broken button."""
    body = _js_function_body(get_all_js(), "function _copyCanvasPng(",
                             strip_comments=True)
    assert "ClipboardItem" in body
    assert "owlSay" in body


def test_every_chart_export_control_is_wired():
    """The toolbar is built as a string and the listeners are attached
    afterwards — a control with no addEventListener is a button that does
    nothing at all."""
    body = _js_function_body(get_all_js(), "function initChartsTab(")
    for cid in ("chart-download-png", "chart-download-sheet", "chart-copy-png"):
        assert cid in body, f"{cid} is never wired up"


# ── taking the code diff out of the page ─────────────────────────────────────

def test_the_code_diff_can_be_copied_not_only_exported():
    js = get_all_js()
    assert "async function copyDiff(" in js
    body = _js_function_body(js, "async function copyDiff(", strip_comments=True)
    assert "export-diff" in body, "same payload as the export, not a second render"
    assert "copyRich(d.markdown, d.html" in body


def test_every_markdown_copy_carries_its_html_rendering():
    """OneNote, Word and Outlook do not render markdown — a markdown copy
    pasted there as pipes and dashes. Every markdown copy goes through
    copyRich with the server's HTML beside the text, and copyRich writes both
    flavours to one ClipboardItem."""
    js = get_all_js()
    rich = _js_function_body(js, "async function copyRich(")
    assert "'text/html'" in rich and "'text/plain'" in rich
    assert "_selectionCopy(" in rich, "plain-http fallback, or a tunnelled Copy fails"
    assert "copyRich(d.text, d.html" in _js_function_body(js, "async function copyExportFmt(")
    assert "copyRich(" in _js_function_body(js, "async function sidebarCopyFmt(")
    assert "copyRich(d.markdown, d.html" in _js_function_body(
        js, "async function copyComparisonDocument(")


def test_plain_text_is_rendered_by_the_server_not_the_browser():
    """The browser built its own plain-text layout, so the CLI had none and
    each code change came out JSON-escaped on one line. The server's
    renderer (core/export_render.py) is now the only one."""
    js = get_all_js()
    assert "function _formatExpPlainText(" not in js
    assert "fmt === 'plain' ? 'text'" in _js_function_body(js, "async function _fetchExportText(")


def test_every_diff_panel_offers_the_raw_patch_and_links_the_commit():
    """The markdown diff is for reading; `git apply` needs the raw patch, and
    the header's commit hash should open the commit on the hosted repo."""
    js = get_all_js()
    assert "exportPatch(" in _js_function_body(js, "function _diffActionsHtml(")
    body = _js_function_body(js, "async function exportPatch(")
    assert "d.patch" in body and "saveOrDownload(" in body
    link = _js_function_body(js, "function _commitHtml(")
    assert "git_commit_url" in link and "^https:" in link and "noopener" in link


def test_compare_has_copy_and_markdown_export_beside_csv():
    assert 'onclick="copyComparisonDocument()"' in DASHBOARD_HTML
    assert 'onclick="exportComparisonMarkdown()"' in DASHBOARD_HTML
    body = _js_function_body(get_all_js(), "async function _comparisonDocument(")
    assert "document: true" in body and "metricPolarityGoals()" in body


def test_every_diff_export_button_has_a_copy_beside_it():
    """Export and copy answer the same need at different distances; a panel
    offering only the download makes pasting a two-step detour through the
    filesystem."""
    js = get_all_js()
    assert js.count("exportDiff(") == js.count("copyDiff("), \
        "every exportDiff( site should have a copyDiff( beside it"


# ── opening an image must not move the page under it ─────────────────────────

def test_a_compare_image_reserves_its_box_before_it_loads():
    """`.multi-compare-image-cell img` had `width: 100%` and no height, so the
    cell's height came entirely from the decoded image's aspect ratio: zero
    before the load, and zero again whenever the browser drops the decode for an
    offscreen image (which opening a full-size PNG in the modal is a good way to
    provoke). Every other image grid in the dashboard already reserves its box —
    `.img-thumb` and `.cmp-img-thumb` both carry `aspect-ratio` — and this one,
    inside the scroller, was the outlier: when it collapses, `#main-content`
    clamps its own scrollTop and the page jumps to the top."""
    from exptrack.dashboard.static import DASHBOARD_CSS
    block = DASHBOARD_CSS[DASHBOARD_CSS.index(".multi-compare-image-cell img {"):]
    block = block[:block.index("}")]
    assert "aspect-ratio" in block, "the cell must not size itself from the decode"
    # A reserved box that crops would make the pairing grid lie about the plots.
    assert "object-fit: contain" in block


def test_opening_an_image_holds_the_page_scroll():
    """Both image modals are fixed overlays appended to `document.body`, so
    neither *should* move the scroller — but the grid they are opened from can
    collapse under them, and the page position is the reader's place in a
    comparison. Held explicitly, the same way the detail refresh does it."""
    js = get_all_js()
    assert "function _holdMainScroll(" in js
    hold = _js_function_body(js, "function _holdMainScroll(", strip_comments=True)
    assert "main-content" in hold and "scrollTop" in hold
    for opener in ("function openImageModal(", "function openCompareModal("):
        body = _js_function_body(js, opener, strip_comments=True)
        assert "_holdMainScroll()" in body, f"{opener} does not hold the scroll"


def test_every_way_of_closing_an_image_modal_is_the_same_way():
    """The overlay closed by three routes — the backdrop, the × and Escape — and
    two of them inlined `.remove()`, so the keydown listener leaked on both and
    any restore-on-close would have had to be written three times (or, as
    happened here, in none of them)."""
    js = get_all_js()
    assert "function closeImageModal(" in js
    body = _js_function_body(js, "function closeImageModal(", strip_comments=True)
    assert "removeEventListener" in body, "the Escape handler has to come off too"
    opener = _js_function_body(js, "function openImageModal(", strip_comments=True)
    assert opener.count(".remove()") == 0, "every close path goes through closeImageModal"


# ── picking the two images to compare, in a run's Images tab ─────────────────

def test_picking_an_image_to_compare_does_not_reload_the_gallery():
    """Images tab → Compare → click an image. `selectImgCompare` called
    `loadImages(expId)`, which re-requests `/api/images/<id>` and rewrites the
    whole tab's innerHTML — for an A/B badge. The gallery is up to 200 thumbnails
    tall, so emptying it collapses `#main-content` and the browser clamps the
    scroll to 0: the click threw the reader to the top of the page, and the
    thumbnail they were aiming at moved. Same failure as the Compare Within tab
    (`_cwRepaintSelection`), same fix."""
    js = get_all_js()
    for fn in ("function selectImgCompare(", "function clearIntraCompare("):
        body = _js_function_body(js, fn, strip_comments=True)
        assert "loadImages(" not in body, f"{fn} must repaint, not reload"
        assert "_imgCmpRepaint()" in body


def test_the_image_compare_repaint_touches_only_the_selection():
    """The badge, the selected class and the bar that names the two picks —
    nothing else, and no request."""
    body = _js_function_body(get_all_js(), "function _imgCmpRepaint(", strip_comments=True)
    assert "img-cmp-badge" in body
    assert "compare-sel" in body
    assert "img-cmp-bar" in body
    assert "api(" not in body, "a selection change is not a fetch"


def test_the_gallery_cards_carry_their_source():
    """A surgical repaint has to find the card for an image; matching on the
    inline handler's text would tie the repaint to how the handler is spelled."""
    js = get_all_js()
    gallery = _js_function_body(js, "function _renderImages(")
    assert "data-src=" in gallery


def test_rebuilding_the_images_tab_holds_the_page_scroll():
    """Entering compare mode and Refresh do legitimately rebuild the tab. That
    still must not move the reader."""
    body = _js_function_body(get_all_js(), "function _renderImages(", strip_comments=True)
    assert "_holdMainScroll()" in body


def test_a_view_change_in_the_images_tab_does_not_refetch_or_blank_the_tab():
    """`loadImages` blanked the tab with a Loading placeholder before its
    request. Typing one character into the search box therefore destroyed the
    box mid-keystroke (focus gone, the character lost) and collapsed
    `#main-content`, so the scroller clamped the reader to the top — reported
    as "the page refreshes and I can't type". Search, sort, folder filter,
    limit and compare mode now repaint from the payload already fetched, and
    the placeholder only appears when there is nothing on screen yet."""
    js = get_all_js()
    load = _js_function_body(js, "async function loadImages(", strip_comments=True)
    assert "if (!container.firstChild)" in load, (
        "the Loading placeholder must not wipe a tab that already has content")

    repaint = _js_function_body(js, "function repaintImages(", strip_comments=True)
    assert "_renderImages(" in repaint and "_imgDataCache" in repaint

    render = _js_function_body(js, "function _renderImages(", strip_comments=True)
    assert "api(" not in render, "a repaint is not a fetch"
    assert "img-search-input" in render, "the search box must survive its own repaint"


def test_the_scan_path_editor_fills_its_row():
    """The editor sets `width: 100%` inline and borrows `.name-edit-input`, whose
    shared rule caps it at 300px — a cap that exists for the experiments table,
    where the input sits in a fixed-width column. In a scan-path row, which is as
    wide as the panel, that left a third-width box inside a full-width bar, on
    the one value most likely to be longer than the box: a path. `max-width`
    beats an inline `width`, so it has to be lifted for these rows."""
    from exptrack.dashboard.static import DASHBOARD_CSS
    assert ".name-edit-input {" in DASHBOARD_CSS
    assert "max-width: 300px" in DASHBOARD_CSS, "the table's cap is still wanted there"
    block = DASHBOARD_CSS[DASHBOARD_CSS.index(".img-path-row .name-edit-input {"):]
    assert "max-width: none" in block[:block.index("}")]



def test_every_delete_confirm_asks_the_shared_question_separately():
    """The delete dialog's two answers must stay two, in every caller.

    A shared file is only taken when the *shared* box is ticked as well as the
    files box, and each ``onPermanent`` has to forward that second answer to
    the server. A caller that forwards only the first one silently reverts to
    "one yes deletes another run's results".
    """
    js = get_all_js()
    # Both modal renderers pass two answers, and the second is gated on the first.
    gated = js.count("opts.onPermanent(cb && cb.checked, "
                     "!!(cb && cb.checked && sh && sh.checked))")
    assert gated == 2, f"expected both modal renderers to gate it, found {gated}"
    # No caller may take the single-argument shape any more.
    assert "opts.onPermanent(cb && cb.checked);" not in js
    # Every permanent-delete POST forwards it.
    posts = re.findall(r"delete_files: !!deleteFiles([^}]*)\}", js)
    assert posts, "no permanent-delete POST bodies found"
    for tail in posts:
        assert "delete_shared_files" in tail, \
            f"a permanent-delete POST omits delete_shared_files: {tail!r}"


def test_the_shared_block_names_the_runs_and_escapes_them():
    """The list is built from run names, which are user-controlled."""
    js = get_all_js()
    body = _js_function_body(js, "function _sharedFilesHtml(files)")
    assert "esc(a.path" in body and "esc((h.id" in body
    assert "modified after this run ended" in body


def test_the_shared_choice_is_two_named_outcomes_with_the_safe_one_default():
    """A tick-box makes the safe outcome "the thing you didn't do". The dialog
    offers both outcomes by name instead, and the one that cannot destroy
    another run's results is the one already selected."""
    js = get_all_js()
    body = _js_function_body(js, "function _sharedCheckboxHtml(count, bytes)")
    assert "Unlink and delete this experiment" in body
    assert "Delete both" in body
    # The keep option is preselected, and the delete option is the id the
    # button handler reads — so an untouched dialog can only keep.
    assert 'value="keep" checked' in body
    assert 'value="delete" ' in body and 'id="dc-shared-checkbox"' in body
    assert body.index('value="keep" checked') < body.index('value="delete" ')


def test_the_artifact_row_offers_unlink_and_says_what_else_holds_the_file():
    js = get_all_js()
    assert 'unlinkArtifact(' in js
    # The action says what it does not do — the old wording ("del") read as a
    # file delete, which is the one thing it never was.
    unlink = _js_function_body(js, "async function unlinkArtifact(id, label, path)")
    assert "not touched" in unlink
    badge = _js_function_body(js, "function _artifactLinkBadge(a)")
    assert "linked_by" in badge and "also in" in badge


def test_a_stored_project_id_that_stops_resolving_is_recovered_not_replayed():
    """A stale/unknown localStorage project id must not leave the switcher —
    the one recovery surface — permanently failing.

    /api/projects reports `current` as the default project's id whenever the
    requested id didn't resolve (server-side, see handler.py's exemption and
    read_routes.api_projects). loadProjects() has to notice that mismatch,
    drop the dead id from localStorage, and adopt the server's answer, or the
    dashboard keeps sending the same dead id on every subsequent request.
    """
    js = get_all_js()
    body = _js_function_body(js, "async function loadProjects()")
    # The null-response path (api() failing outright) also clears the stored
    # id, so a reload gets a clean shot instead of repeating the same failure.
    assert "if (!data) {" in body
    assert "_storageDel(_PROJECT_KEY)" in body
    # The mismatch-detection path: current from the server disagreeing with
    # what we stored is the signal the stored id no longer resolves.
    assert "data.current !== _activeProjectId" in body
    assert "_storageSet(_PROJECT_KEY, data.current)" in body
    # The user is told the view moved, not left to discover it silently.
    assert "project-problem" in body and "no longer available" in body


# ── Cross-project Compare (client side) ──────────────────────────────────────
# Compare is the only surface that may span projects. None of the failures
# below raises: a bare id that should have been qualified resolves against the
# wrong database and still looks like a perfectly good run, and a fetch sent
# with the page's project instead of the run's comes back empty rather than
# wrong. A structural check is the only thing that notices.

def test_the_picker_qualifies_only_runs_outside_the_pages_project():
    """A bare id means "the current project", and every existing caller,
    bookmark and saved URL passes one — so the picker must leave them bare and
    qualify only what it browsed elsewhere."""
    js = get_all_js()
    body = _js_function_body(js, "function _rpQualify(")
    # '' (the page's project) returns the id untouched; anything else prefixes.
    assert "_rpProject ?" in body and "':' + id" in body
    # The row's identity — what gets ticked and what gets handed back — is the
    # qualified id, not the bare one: two projects can hold the same id and
    # they must not tick each other.
    row = _js_function_body(js, "function _rpRowHtml(")
    assert "_rpQualify(entry.id)" in row
    assert "escJsAttr(qid)" in row, "the handed-back id must be escaped in the handler"
    assert "_rpSelected.has(qid)" in row
    assert "_rpQualify(" in _js_function_body(js, "function rpSelectAllShown(")


def test_the_project_selector_is_opt_in_and_only_compare_opts_in():
    """Every other view reads a *set* whose members must share a parameter
    space, so a cross-project matrix, leaderboard or merged list is a non-goal.
    The matrix's picker must not grow a project selector by inheritance."""
    js = get_all_js()
    assert "crossProject: true" in _js_function_body(js, "function openMultiRunPicker(")
    assert "crossProject" not in _js_function_body(js, "function openMatrixRunPicker("), \
        "the matrix picker must stay single-project"
    body = _js_function_body(js, "async function openRunPicker(")
    assert "_rpCross = !!o.crossProject" in body
    assert "if (_rpCross) await _rpLoadProjects()" in body
    # A picker that reopened on the project last browsed would hand back
    # qualified ids for runs the user believes are local.
    assert "_rpProject = ''" in body


def test_a_projects_listing_that_fails_leaves_a_working_picker():
    """api() returns null on failure and has already reported it; a dialog that
    refuses to open because the *optional* selector could not be built is worse
    than one with no selector."""
    js = get_all_js()
    body = _js_function_body(js, "async function _rpLoadProjects(")
    assert "if (!data || !Array.isArray(data.projects)) return;" in body


def test_a_run_outside_the_page_is_fetched_against_its_own_project():
    """The per-run fetches carry the PAGE's project by default, so a foreign
    run's metrics came back empty — drawn as a run that logged nothing rather
    than one we asked the wrong database about."""
    js = get_all_js()
    curves = _js_function_body(js, "async function _renderMultiCurves(")
    assert "api('/api/metrics/' + e.id, e.project_id)" in curves
    # An <img src> carries no headers at all, which is why the token already
    # rides in the query for /api/file/ — the project travels the same way.
    fu = _js_function_body(js, "function fileUrl(")
    assert "project=" in fu and "projectId" in fu
    cell = _js_function_body(js, "function _imageCellHtml(")
    assert "fileUrl(img.path, img._project)" in cell
    # ...and the optional project argument is what makes every existing
    # one-argument call unchanged.
    assert "async function api(path, projectId)" in js
    assert "_projectHeaders(projectId)" in _js_function_body(js, "async function api(")


def test_a_cross_project_pair_says_the_pair_panels_are_unavailable():
    """The pair-only endpoints each read one project's database per request. A
    cross-project pair silently losing four panels reads as a comparison that
    half-failed, with no way to tell which half."""
    js = get_all_js()
    fetch = _js_function_body(js, "async function doMultiCompare(")
    assert "_cmpSpansProjects(data.experiments)" in fetch
    assert "data._pairCrossProject = true" in fetch
    render = _js_function_body(js, "function _renderMultiComparison(")
    assert "_pairCrossProjectNoteHtml(" in render
    note = _js_function_body(js, "function _pairCrossProjectNoteHtml(")
    assert "different projects" in note and "cmp-missing" in note


def test_a_compare_column_names_the_project_only_when_the_set_spans_them():
    """Two projects can hold runs with the same name — auto-generated names come
    from one shared vocabulary, so that is the ordinary case. On a
    single-project comparison the tag would sit on every column saying the same
    thing on each, which is noise."""
    js = get_all_js()
    spans = _js_function_body(js, "function _cmpSpansProjects(")
    assert "project_id" in spans and "size > 1" in spans
    label = _js_function_body(js, "function _cmpRunLabel(")
    # Middle-ellipsis, never a head truncation: auto-named runs differ in the
    # tail, which is exactly what a head cut would hide.
    assert "_cmpColName(" in label and "project_name" in label
    assert "midEllipsis(" in _js_function_body(js, "function _cmpColName(")
    # The chips naming staged runs resolve a qualified id in its own project's
    # cache rather than failing to find it in the page's.
    chip = _js_function_body(js, "function _cmpLabelFor(")
    assert "splitQualifiedRunId(" in chip and "projectName(" in chip


def test_the_switcher_has_a_dismiss_control_reachable_from_a_project_row():
    """Spec rule: "The switcher's dismiss control calls the same code path as
    `forget`." forgetProject() is that control — it must POST to the
    /api/project/forget endpoint, guard postApi()'s possible null, and never
    silently reload out from under an unrelated selection.
    """
    js = get_all_js()
    forget = _js_function_body(js, "async function forgetProject(id, name)")
    assert "/api/project/forget" in forget
    assert "postApi(" in forget
    assert "if (!res) return;" in forget
    # Confirmed first: a dismiss must not fire on the same misclick that would
    # hit the switcher itself.
    assert "confirm(" in forget
    # Dismissing the project currently being viewed must not leave the
    # switcher pointing at an id the server no longer recognizes.
    assert "_activeProjectId === id" in forget
    assert "_storageDel(_PROJECT_KEY)" in forget


def test_every_project_row_carries_its_own_forget_control():
    """A <select><option> can't host a button, so the dismiss affordance lives
    in a rendered row list — one row, one forget button, escaped the same way
    every other user-controlled value in an inline handler is."""
    js = get_all_js()
    body = _js_function_body(js, "async function loadProjects()")
    assert "forgetProject(" in body
    assert "escJsAttr(p.id)" in body and "escJsAttr(p.name)" in body
    # The manage panel is reached through its own toggle, not folded into the
    # picker itself.
    assert "toggleProjectManage" in body


# ── The final-review fix wave (B1, B2, N1, N2, N4, N6) ───────────────────────

def test_a_foreign_projects_truncated_run_list_says_it_is_truncated():
    """`hasMore` is "the last page came back full", and nothing else.

    It briefly read `lastPageFull && total > rows.length`. For a foreign
    project `total` *is* `rows.length` (the page's own `expTotal` counts the
    page's project, so it cannot be claimed for another one), so that second
    clause pinned `hasMore` to false there: a foreign project with more than
    one page of runs rendered neither the "searching the N most recent runs"
    notice nor the Load-all button, and `_rpFiltered` answered "No run
    matches" for a run that exists. A wrong answer with no error is the worst
    failure this surface has.
    """
    js = get_all_js()
    loader = _js_function_body(js, "async function _loadProjectRuns(",
                               strip_comments=True)
    assert "hasMore: lastPageFull" in loader
    assert "total > rows.length" not in loader, (
        "hasMore is gated on a total that a foreign project cannot have"
    )
    # And the notice it feeds is still the one that offers loading the rest.
    notices = _js_function_body(js, "function _rpNoticesHtml(")
    assert "_rpHasMore" in notices and "rpLoadAll()" in notices


def test_a_cross_project_comparisons_link_carries_qualified_ids():
    """The hash is the comparison's address: `copyComparisonLink` shares it,
    and `restoreCompareFromUrl` / `_onPopView` post the ids back. A bare id
    resolves against the *current* project only, so writing bare ids meant a
    cross-project comparison reopened from its own link — a reload, a shared
    URL, or the browser Back button — came back with its foreign runs in
    `unknown_ids`."""
    js = get_all_js()
    assert "_writeCompareHash('multi', exps.map(e => e.qualified_id || e.id))" in js
    assert "_writeCompareHash('multi', exps.map(e => e.id))" not in js, (
        "a comparison still writes bare ids into its own link"
    )
    # The reader takes the ids as given — qualification is resolved server-side.
    restore = _js_function_body(js, "async function restoreCompareFromUrl(")
    assert "doMultiCompare(ids)" in restore


def test_boot_reruns_the_project_scoped_loads_after_a_dead_id_is_recovered():
    """Only /api/projects is exempt from project activation, so with a dead
    stored id every other boot-time load 400s. loadProjects() recovers the id
    and the switcher says "switched to X" — over an empty list, empty stats and
    an empty table, until the user reloaded by hand."""
    js = get_all_js()
    boot = _js_function_body(js, "function _bootDashboard(", strip_comments=True)
    assert "_bootProjectData()" in boot
    assert "recovered" in boot, "the boot never asks whether the id was recovered"
    data = _js_function_body(js, "function _bootProjectData(")
    for fn in ("loadStats()", "loadExperiments()", "loadAllTags()"):
        assert fn in data, f"{fn} is not in the re-runnable half of the boot"
    # loadProjects has to report it, not just apply it.
    loader = _js_function_body(js, "async function loadProjects(")
    assert "return {recovered: recovered" in loader


def test_forgetting_a_worktree_discovered_project_says_what_happened():
    """`projects.forget` only edits the registry, so it returns ok=false for a
    project that was discovered as a worktree and never registered — the user
    confirmed a destructive-sounding dialog and nothing visibly happened. And
    a *successful* forget of a project that is still a worktree of this
    repository leaves it in the list, which reads exactly like a failure."""
    js = get_all_js()
    forget = _js_function_body(js, "async function forgetProject(id, name)",
                               strip_comments=True)
    assert "if (!res.ok)" in forget, "the {'ok': false} outcome is unhandled"
    assert forget.count("owlSay(") >= 2, "only one of the outcomes is reported"
    assert "worktree" in forget, "neither message names the reason"


def test_a_cross_project_export_names_the_project_each_run_came_from():
    """Two projects can hold runs with the same auto-generated name, which is
    the argument `_cmpRunLabel` already makes for the on-screen column. Off the
    page the CSV has nothing else to go on, so it carries the project too —
    and only when the set actually spans projects, so a single-project export
    does not gain a column that says the same thing on every row."""
    js = get_all_js()
    body = _js_function_body(js, "function exportComparison(", strip_comments=True)
    assert "_cmpSpansProjects(exps)" in body
    assert "'project'" in body and "project_name" in body


def test_the_functions_these_checks_read_are_declared_once():
    """`_js_function_body` resolves to the FIRST definition in the bundle.

    That is fine for every function declared once, and silently wrong for one
    declared twice: the assertion passes or fails against source the browser
    never runs. Three of compare.js's functions are in that state, so the
    cross-project checks over them prove nothing about the live code.
    """
    js = get_all_js()
    dupes = {}
    for decl in ("function _multiMetricTableHtml(",
                 "function _renderMultiComparison(",
                 "async function doMultiCompare("):
        n = js.count("\n" + decl)
        if n != 1:
            dupes[decl] = n
    assert not dupes, (
        "declared more than once, so _js_function_body() reads a dead copy: "
        + ", ".join(f"{d.strip()} x{n}" for d, n in dupes.items())
    )


# ── the collapsed rail and the header project switcher ──────────────────────

def test_the_rail_ships_collapsed_and_reads_its_state_through_the_helpers():
    """The sidebar's default is collapsed in the *markup*, not only in JS.

    Two failures, both silent. `restoreSidebarState()` is the first call in
    init.js, and a bare `localStorage.getItem` THROWS in a private window or
    with site data blocked — taking the whole boot sequence with it, so the
    page rendered nothing and said nothing. `_storageGet`/`_storageSet`
    swallow that and return '', which lands on the collapsed default. And
    without `class="collapsed"` in the markup the rail painted open and
    snapped shut when the script ran, on every first visit.
    """
    assert '<div id="exp-sidebar" class="collapsed">' in DASHBOARD_HTML
    js = get_all_js()
    restore = _js_function_body(js, "function restoreSidebarState()",
                                strip_comments=True)
    assert "_storageGet(_SIDEBAR_KEY)" in restore
    assert "localStorage" not in restore, "a raw storage read can throw the boot"
    toggle = _js_function_body(js, "function toggleSidebar()", strip_comments=True)
    assert "_storageSet(_SIDEBAR_KEY" in toggle
    assert "localStorage" not in toggle


def test_a_collapsed_rail_still_names_its_own_opener():
    """Collapsed must not mean unreachable: the 44px strip is the only way
    back in, so it carries a label and a title rather than a bare chevron —
    and every class it uses is styled, or it renders as an OS default."""
    assert 'class="collapse-strip"' in DASHBOARD_HTML
    assert "Show the run list" in DASHBOARD_HTML
    assert "collapse-strip-label" in DASHBOARD_HTML
    from exptrack.dashboard.static_parts.css import get_all_css
    css = get_all_css()
    for cls in ("collapse-strip-icon", "collapse-strip-label", "collapse-strip-count",
                "header-project-label", "header-project-problem"):
        assert "." + cls in css, f"{cls} is used in markup but styled nowhere"


def test_the_header_switcher_shares_one_switch_path_with_the_rail():
    """Two switchers, one implementation. A second copy of the picker markup
    is a second place for "stale entries are shown, not hidden" to be
    forgotten — so both go through `_projectSelectHtml`, which is the only
    thing that writes `switchProject(` from a picker, keeps a non-`ok`
    project in the list with its status, and marks it `disabled`."""
    js = get_all_js()
    assert '<div id="header-project-switcher"' in DASHBOARD_HTML
    picker = _js_function_body(js, "function _projectSelectHtml(")
    assert "switchProject(this.value)" in picker
    # The <option> itself is rendered by one helper, shared by the grouped
    # (worktree <optgroup>) and ungrouped paths — the rules below would
    # otherwise have to hold in two loops instead of one.
    assert js.count("function _projectOptionHtml(") == 1
    assert "_projectOptionHtml(p, current" in picker
    option = _js_function_body(js, "function _projectOptionHtml(")
    assert "escJsAttr(p.id)" in option, "a project id is user-controlled"
    assert "' disabled'" in option and "p.status !== 'ok'" in option
    # The rail and the header both render through it, and neither writes its
    # own <option> loop.
    loader = _js_function_body(js, "async function loadProjects()")
    assert "_projectSelectHtml(data.projects, current, 'project-select')" in loader
    assert "renderHeaderProjectSwitcher(data.projects, current, note)" in loader
    header = _js_function_body(js, "function renderHeaderProjectSwitcher(")
    assert "_projectSelectHtml(projects, current, 'header-project-select')" in header
    assert js.count("onchange=\"switchProject(this.value)\"") == 1, (
        "a second picker writes its own switch handler"
    )
    # The dismiss/forget control is not duplicated into the header.
    assert "forgetProject(" not in header


def test_the_header_switcher_states_a_dead_or_unreadable_project():
    """The reason is computed once and given to both switchers, so the header
    can never be quieter than the rail about a project it cannot read — and
    the rail is the one that ships collapsed."""
    js = get_all_js()
    loader = _js_function_body(js, "async function loadProjects()")
    assert "renderHeaderProjectSwitcher(data.projects, current, note)" in loader
    header = _js_function_body(js, "function renderHeaderProjectSwitcher(")
    assert "header-project-problem" in header and "esc(note)" in header


def test_failed_runs_are_listed_by_default():
    """A failed run is a result, not noise — the same rule `_BASELINE_WHERE`
    applies server-side — so the list shows them unless the reader says
    otherwise, and the group bar's control reads "Hide failed" at rest.

    The state also reads a *new* storage key: `exptrack-show-failed` was
    written under the opposite default, so a stored value there says nothing
    about what the reader wants under this one."""
    js = get_all_js()
    assert "let showFailed = _storageGet('exptrack-hide-failed') !== '1';" in js
    assert "localStorage.getItem('exptrack-show-failed')" not in js, (
        "the old key's values were written under the old default"
    )
    assert "localStorage.removeItem('exptrack-show-failed')" in js
    assert '>Hide failed</button>' in DASHBOARD_HTML
    assert 'id="show-failed-toggle"' in DASHBOARD_HTML
    assert 'onclick="toggleShowFailed()"' in DASHBOARD_HTML


def test_the_hidden_state_says_how_many_runs_it_is_withholding():
    """A filter withholding rows has to say how many, counted against the view
    as it actually stands — so the count comes from the same
    `getFilteredExperiments` the table renders, with only this filter lifted,
    never from a raw scan of `allExperiments` (which would ignore the search,
    the date range and every other filter in effect)."""
    js = get_all_js()
    body = _js_function_body(js, "function updateFailedCount(")
    assert "getFilteredExperiments({includeFailed: true})" in body
    assert "e.status === 'failed'" in body
    assert "'Show failed (' + n + ')'" in body
    assert "'Hide failed'" in body


def test_the_failed_control_defers_to_the_failed_status_chip():
    """`getFilteredExperiments` lifts this filter while the Failed status chip
    is on (else the chip would show nothing), so the button cannot be true
    there — it is disabled and names the control that won, rather than
    offering an action that does nothing or a count that is a lie."""
    js = get_all_js()
    body = _js_function_body(js, "function updateFailedCount(")
    assert "currentFilter === 'failed'" in body
    assert "btn.disabled = true" in body
    tbl = _js_function_body(js, "function getFilteredExperiments(")
    assert "!showFailed && currentFilter !== 'failed'" in tbl


def test_the_withheld_count_tracks_every_other_filter():
    """The number depends on the rest of the view, so it is recomputed on the
    shared re-render — not only when the list is re-fetched. Without this, a
    search or a date-range change left a stale count on screen."""
    js = get_all_js()
    body = _js_function_body(js, "function rerender(")
    assert "updateFailedCount()" in body


def test_compare_picker_cannot_confirm_fewer_than_two_runs():
    """Compare's picker greys out its confirm below two picks and says why.

    It used to accept one run, stage it, and then do nothing — the cross-project
    case most of all, where the first pick is out of sight in another project's
    list — which read as a Compare button that was broken.
    """
    js = get_all_js()
    footer = _js_function_body(js, "function _rpRenderFooter(")
    assert "go.disabled = _rpShort()" in footer
    assert "_rpMinReason" in footer
    assert "_rpSelected.size < _rpMinPicks" in _js_function_body(js, "function _rpShort(")
    assert "if (_rpShort()) return" in _js_function_body(js, "function rpConfirm(")
    assert "minPicks: 2" in _js_function_body(js, "function openMultiRunPicker(")


def test_a_failed_comparison_says_so_and_why():
    """Every way doMultiCompare can give up renders a reason in the result area."""
    js = get_all_js()
    body = _js_function_body(js, "async function doMultiCompare(", strip_comments=True)
    assert body.count("_showCompareFailure(") == 2
    assert "Couldn" in _js_function_body(js, "function _showCompareFailure(")


# ── Charts: overlay view ────────────────────────────────────────────────────

def _run_js(src: str):
    """Evaluate *src* with node and return its JSON output, or skip without node.

    The overlay's pair matcher and axis rule are pure functions, and a static
    string check cannot say whether `val_loss` is actually paired with `loss`.
    """
    import json
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run([node, "-e", src], capture_output=True, text=True,
                         timeout=30, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _overlay_helpers() -> str:
    js = get_all_js()
    return "\n".join(_js_function_body(js, decl) + "\n}" for decl in (
        "function _overlayBaseName(",
        "function _overlayDefaultKeys(",
        "function _overlaySpan(",
        "function _overlayAxisGroups(",
    ))


def test_overlay_defaults_to_the_train_val_pair_of_the_primary_metric():
    got = _run_js(_overlay_helpers() + """
      const keys = ['acc', 'loss', 'lr', 'val_acc', 'val_loss'];
      console.log(JSON.stringify([
        _overlayDefaultKeys(keys, 'loss'),
        _overlayDefaultKeys(keys, 'val_acc'),
        _overlayDefaultKeys(['train_loss', 'lr', 'valid_loss'], null),
        _overlayDefaultKeys(['train/loss', 'eval/loss', 'x'], null),
        _overlayDefaultKeys(['a', 'b', 'c'], 'b'),
        _overlayDefaultKeys(['only'], null),
      ]));""")
    assert got[0] == ["loss", "val_loss"]
    assert got[1] == ["acc", "val_acc"]
    assert got[2] == ["train_loss", "valid_loss"]
    assert got[3] == ["train/loss", "eval/loss"]
    assert got[4] == ["b", "a"]          # no pair: primary plus the next one
    assert got[5] == ["only"]


def test_overlay_shares_an_axis_unless_the_scales_differ_tenfold():
    got = _run_js(_overlay_helpers() + """
      const p = vs => vs.map((v, i) => ({step: i, value: v}));
      const data = {
        loss: p([2.0, 1.0, 0.4]), val_loss: p([2.2, 1.3, 0.6]),
        acc: p([0.1, 0.5, 0.9]), lr: p([0.001, 0.0005, 0.0001]),
        steps: p([10, 5000, 90000]),
      };
      console.log(JSON.stringify([
        _overlayAxisGroups(['loss', 'val_loss'], data),
        _overlayAxisGroups(['loss', 'acc'], data),
        _overlayAxisGroups(['loss', 'lr'], data),
        _overlayAxisGroups(['loss', 'val_loss', 'steps'], data),
      ]));""")
    assert got[0] == {"left": ["loss", "val_loss"], "right": []}
    assert got[1] == {"left": ["loss", "acc"], "right": []}   # 2.2 vs 0.9: shared
    assert got[2] == {"left": ["loss"], "right": ["lr"]}
    assert got[3] == {"left": ["loss", "val_loss"], "right": ["steps"]}


def test_overlay_keeps_its_picks_across_a_live_refresh():
    """The 5s poll must update the overlay in place, never re-pick its series."""
    js = get_all_js()
    body = _js_function_body(js, "function updateChartsInPlace(")
    assert "mode === 'overlay'" in body
    assert "_applyOverlayPoints(" in body
    assert "_overlayPicks" in _js_function_body(js, "function _overlayInitialPicks(")
