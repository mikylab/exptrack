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
