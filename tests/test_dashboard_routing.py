"""GET route dispatch — which handler each path reaches, and with what args.

This is a characterization test: it pins the routing table's observable
behaviour (handler + extracted id) so the dispatch implementation can be
restructured without silently redirecting or dropping a route. Several routes
are ordering-sensitive in the original if/elif form — /api/experiment/<id>
would shadow /api/experiment/<id>/delete-preview if it came first — and the
specificity cases below are what catch that class of regression.

Note the deliberate asymmetry the routes have always had: /api/logs/ and
/api/images/ take path segment 3, so a trailing extra segment is ignored,
while the others take the last segment.
"""
from __future__ import annotations

import io
import pathlib

import pytest

from exptrack.dashboard import handler as H
from exptrack.dashboard.handler import DashboardHandler


class _FakeServer:
    allowed_host = "127.0.0.1"


@pytest.fixture
def route_probe(tmp_project, monkeypatch):
    """Replace every route function with a recorder; return the call log."""
    calls = []

    def recorder(name):
        def fn(*args, **kwargs):
            # drop the leading sqlite connection, keep the routing-relevant args
            rest = [a for a in args if not hasattr(a, "execute")]
            calls.append((name, tuple(rest)))
            return {"ok": name}
        return fn

    for mod in (H.read_routes, H.write_routes):
        for attr in dir(mod):
            if attr.startswith("api_"):
                monkeypatch.setattr(mod, attr, recorder(attr))
    monkeypatch.setattr(H, "get_db", lambda: _FakeConn())
    return calls


class _FakeConn:
    def execute(self, *a, **k):
        return self


def _make_handler(path, state):
    """A DashboardHandler wired with just enough to run do_GET."""
    h = object.__new__(DashboardHandler)
    h.path = path
    h.server = _FakeServer()
    h.rfile = io.BytesIO(b"")
    h.wfile = io.BytesIO()
    h.headers = {"Host": "127.0.0.1"}
    h.send_response = lambda code: state.__setitem__("status", code)
    h.send_header = lambda k, v: None
    h.end_headers = lambda csp=None: None
    h.send_error = lambda code, msg="": state.__setitem__("error", code)
    h.wfile.write = lambda data: None
    return h


def _dispatch(path, serve_file=None):
    """Run do_GET for `path`; return {status, error}.

    `serve_file` replaces _serve_file so the /api/file/ route can be observed
    without touching disk.
    """
    state = {"error": None, "status": None}
    h = _make_handler(path, state)
    if serve_file is not None:
        h._serve_file = serve_file
    h.do_GET()
    return state


# ── exact-path routes ───────────────────────────────────────────────────────

EXACT = [
    ("/api/stats", "api_stats"),
    ("/api/experiments", "api_experiments"),
    ("/api/compare", "api_compare"),
    ("/api/all-tags", "api_all_tags"),
    ("/api/config/timezone", "api_get_timezone"),
    ("/api/config/metrics", "api_get_metric_settings"),
    ("/api/config/capture", "api_get_capture_settings"),
    ("/api/result-types", "api_result_types"),
    ("/api/studies", "api_studies"),
    ("/api/multi-compare", "api_multi_compare"),
    ("/api/todos", "api_get_todos"),
    ("/api/commands", "api_get_commands"),
    ("/api/all-studies", "api_all_studies"),
    ("/api/trash", "api_trash"),
    ("/api/sessions", "api_sessions"),
]


@pytest.mark.parametrize("path,expected", EXACT)
def test_exact_routes(route_probe, path, expected):
    _dispatch(path)
    assert [c[0] for c in route_probe] == [expected]


# ── id-bearing routes: handler *and* the id it extracts ─────────────────────

IDENT = [
    ("/api/experiment/abc123", "api_experiment", "abc123"),
    ("/api/run-delta/abc123", "api_run_delta", "abc123"),
    ("/api/metrics/abc123", "api_metrics", "abc123"),
    ("/api/diff/abc123", "api_diff", "abc123"),
    ("/api/timeline/abc123", "api_timeline", "abc123"),
    ("/api/vars-at/abc123", "api_vars_at", "abc123"),
    ("/api/cell-source/deadbeef", "api_cell_source", "deadbeef"),
    ("/api/export/abc123", "api_export", "abc123"),
    ("/api/logs/abc123", "api_list_logs", "abc123"),
    ("/api/confusion/abc123", "api_list_confusion", "abc123"),
    ("/api/images/abc123", "api_list_images", "abc123"),
    ("/api/session/sess1", "api_session_tree", "sess1"),
]


@pytest.mark.parametrize("path,expected,ident", IDENT)
def test_ident_routes(route_probe, path, expected, ident):
    _dispatch(path)
    assert len(route_probe) == 1, f"{path} hit {[c[0] for c in route_probe]}"
    name, args = route_probe[0]
    assert name == expected
    assert args[0] == ident


# ── specificity: a sub-action must never be swallowed by its parent ─────────

SPECIFIC = [
    ("/api/experiment/abc123/delete-preview", "api_delete_preview", "abc123"),
    ("/api/experiment/abc123/prev-by-script", "api_prev_by_script", "abc123"),
    ("/api/session/sess1/nodes", "api_session_nodes", "sess1"),
    ("/api/session/sess1/trash", "api_session_trash", "sess1"),
    ("/api/session/sess1/finalize-preview", "api_session_finalize_preview", "sess1"),
]


@pytest.mark.parametrize("path,expected,ident", SPECIFIC)
def test_specific_routes_beat_generic(route_probe, path, expected, ident):
    """The regression this guards: reordering makes these silently dead code."""
    _dispatch(path)
    assert len(route_probe) == 1, f"{path} hit {[c[0] for c in route_probe]}"
    name, args = route_probe[0]
    assert name == expected, f"{path} was swallowed by {name}"
    assert args[0] == ident


# ── the two routes that read segment 3 rather than the last segment ─────────

def test_logs_and_images_use_segment_three(route_probe):
    """Long-standing asymmetry: a trailing segment is ignored, not treated as the id."""
    _dispatch("/api/logs/abc123/extra")
    _dispatch("/api/images/abc123/extra")
    assert [c[0] for c in route_probe] == ["api_list_logs", "api_list_images"]
    assert route_probe[0][1][0] == "abc123"
    assert route_probe[1][1][0] == "abc123"


# ── non-API routes and the fallthrough ──────────────────────────────────────

def test_html_shell(tmp_project):
    assert _dispatch("/")["status"] == 200
    assert _dispatch("/index.html")["status"] == 200


def test_static_and_vendor(tmp_project):
    assert _dispatch("/static/dashboard.js")["status"] == 200
    assert _dispatch("/static/dashboard.css")["status"] == 200
    assert _dispatch("/vendor/chart.umd.min.js")["status"] == 200


def test_ping_does_not_touch_db(tmp_project):
    assert _dispatch("/api/ping")["status"] == 200


def test_unknown_route_404(route_probe):
    assert _dispatch("/api/does-not-exist")["error"] == 404
    assert route_probe == []


def test_file_route_joins_remaining_segments(tmp_project):
    """/api/file/<a>/<b> must serve "a/b", not just the last segment."""
    served = []
    _dispatch("/api/file/outputs/nested/plot.png", serve_file=served.append)
    assert served == ["outputs/nested/plot.png"]


# ── every dispatch entry must resolve to a real route function ──────────────

def test_post_dispatch_targets_all_exist(tmp_project):
    """POST routes are lambdas, so a missing function only fails at request time.

    write_routes is a package of ten submodules re-exported through its
    __init__; forgetting to re-export one would leave the endpoint dead until
    somebody clicked it. This walks the dispatch tables in do_POST and checks
    each target resolves now.
    """
    import re

    source = pathlib.Path(H.__file__).read_text()
    refs = set(re.findall(r"\b(write_routes|read_routes)\.(api_\w+)", source))
    assert refs, "found no route references — the scrape is broken, not the code"
    missing = [f"{mod}.{fn}" for mod, fn in sorted(refs)
               if not hasattr(getattr(H, mod), fn)]
    assert not missing, f"handler references nonexistent route functions: {missing}"


def test_no_route_strips_a_raw_body_value():
    """Every body field read as a string must go through body_str().

    A raw `body.get("k", "").strip()` (or `(body.get("k") or "").strip()`)
    raises AttributeError on a JSON number, because the dashboard's own JS is
    the only client that guarantees strings. The first sweep pattern-matched
    one spelling and left nine sites of the other, so the rule is enforced
    here rather than by remembering.
    """
    import re

    pkg = pathlib.Path(H.write_routes.__file__).parent
    offenders = []
    for f in sorted(pkg.glob("*.py")):
        if f.name == "_shared.py":
            continue  # defines body_str; its docstring quotes the bad form
        for i, line in enumerate(f.read_text().split("\n"), 1):
            if re.search(r"body\.get\(.*\)\s*(or\s*[\"'][\"']\s*\))?\.strip\(\)", line):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, (
        "read these through body_str(body, key) instead — .strip() on a raw "
        "body value raises on a JSON number:\n  " + "\n  ".join(offenders)
    )


def test_write_routes_reexports_its_whole_surface():
    """__all__ and the actual module surface must agree."""
    from exptrack.dashboard.routes import write_routes
    for name in write_routes.__all__:
        assert hasattr(write_routes, name), f"{name} in __all__ but not exported"
    public = {n for n in dir(write_routes)
              if n.startswith("api_") and callable(getattr(write_routes, n))}
    assert public == set(write_routes.__all__), (
        f"surface drift: {public ^ set(write_routes.__all__)}"
    )


# ── structural guard on the ordered table ───────────────────────────────────

def test_route_table_order_does_not_matter(monkeypatch):
    """Reversing _GET_PREFIXED must not change where any route resolves.

    Stronger than asserting the table is currently ordered correctly: it
    asserts ordering cannot matter at all, which is what the two-pass matcher
    buys. A regression to first-match-wins fails here even if the committed
    table happens to be in a working order.
    """
    before = {p: H.DashboardHandler._match_prefixed_get(p)
              for p, _, _ in SPECIFIC + IDENT}
    monkeypatch.setattr(H, "_GET_PREFIXED", tuple(reversed(H._GET_PREFIXED)))
    after = {p: H.DashboardHandler._match_prefixed_get(p)
             for p, _, _ in SPECIFIC + IDENT}
    assert before == after, (
        "reversing the route table changed dispatch — ordering is load-bearing "
        f"again for: {[k for k in before if before[k] is not after[k]]}"
    )


def test_exact_routes_are_not_shadowed_by_a_prefix():
    """Exact paths are matched first, but a collision would still be a trap."""
    for path in H._GET_EXACT:
        for prefix, suffix, _ in H._GET_PREFIXED:
            if path.startswith(prefix) and (not suffix or path.endswith(suffix)):
                raise AssertionError(
                    f"exact route '{path}' also matches prefix '{prefix}' — "
                    f"the two tables overlap, which makes dispatch order matter "
                    f"where it currently does not."
                )


def test_file_route_percent_decodes(tmp_project):
    served = []
    _dispatch("/api/file/outputs/my%20plot.png", serve_file=served.append)
    assert served == ["outputs/my plot.png"]
