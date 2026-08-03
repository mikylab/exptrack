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


# ── the live-run auto-refresh poll ──────────────────────────────────────────

def _poll_source() -> str:
    js = get_all_js()
    start = js.index("async function _autoRefreshPoll(")
    return js[start:js.index("\n}", start)]


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
    js = get_all_js()
    start = js.index("function _buildCodeSection(")
    return js[start:js.index("\n}", start)]


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
    assert js.count("_renderCompareCodeDiff(data.code_diff, data.exp1, data.exp2)") == 2


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
