"""Dashboard security hardening: Host-header validation, vendored Chart.js,
malformed-input handling, and /api/file scoping.

Drives DashboardHandler.do_GET / do_POST directly with a mock socket so the
top-of-request checks (Host, auth-exempt vendor route, JSON body parse) are
exercised the way a real request would hit them.
"""
from __future__ import annotations

import io

from exptrack.dashboard.handler import DashboardHandler


class _FakeServer:
    def __init__(self, allowed_host=""):
        self.allowed_host = allowed_host


def _make_handler(tmp_project=None, host="127.0.0.1", allowed_host="",
                  path="/", body=b""):
    """Build a DashboardHandler with enough wiring to run do_GET/do_POST."""
    h = object.__new__(DashboardHandler)
    h.path = path
    h.server = _FakeServer(allowed_host)
    h.rfile = io.BytesIO(body)
    h.wfile = io.BytesIO()
    h.headers = {"Host": host}
    if body:
        h.headers["Content-Length"] = str(len(body))

    sent = {"status": None, "headers": {}, "error": None, "error_msg": None,
            "body": b""}

    def send_response(code):
        sent["status"] = code

    def send_header(k, v):
        sent["headers"][k] = v

    def end_headers(csp=None):   # real end_headers takes an optional CSP
        pass

    def send_error(code, msg=""):
        sent["error"] = code
        sent["error_msg"] = msg

    def write(data):
        sent["body"] += data

    h.send_response = send_response
    h.send_header = send_header
    h.end_headers = end_headers
    h.send_error = send_error
    h.wfile.write = write
    return h, sent


# ── F11: Host-header validation ──────────────────────────────────────────────

def test_bad_host_rejected_get(tmp_project):
    h, sent = _make_handler(tmp_project, host="evil.example", path="/api/stats")
    h.do_GET()
    assert sent["error"] == 403
    assert sent["status"] is None  # never reached the route


def test_localhost_host_allowed(tmp_project):
    h, sent = _make_handler(tmp_project, host="localhost", path="/")
    h.do_GET()
    assert sent["error"] is None
    assert sent["status"] == 200  # HTML shell served


def test_loopback_host_with_port_allowed(tmp_project):
    h, sent = _make_handler(tmp_project, host="127.0.0.1:7331", path="/")
    h.do_GET()
    assert sent["error"] is None
    assert sent["status"] == 200


def test_ipv6_loopback_host_allowed(tmp_project):
    h, sent = _make_handler(tmp_project, host="[::1]:7331", path="/")
    h.do_GET()
    assert sent["error"] is None
    assert sent["status"] == 200


def test_bound_host_allowed(tmp_project):
    # A non-local bind (app.main sets server.allowed_host) must be accepted.
    h, sent = _make_handler(tmp_project, host="myhost.local",
                            allowed_host="myhost.local", path="/")
    h.do_GET()
    assert sent["error"] is None
    assert sent["status"] == 200


def test_wildcard_bind_accepts_any_host(tmp_project):
    # `exptrack ui --host 0.0.0.0` (app.main sets allowed_host="*") must accept
    # whatever name/IP the client reached the machine under — a LAN client
    # sends e.g. Host: 192.168.1.50:7331, never "0.0.0.0".
    h, sent = _make_handler(tmp_project, host="192.168.1.50:7331",
                            allowed_host="*", path="/")
    h.do_GET()
    assert sent["error"] is None
    assert sent["status"] == 200


def test_wildcard_bind_maps_to_star():
    # app.main must translate wildcard binds to the "*" sentinel and keep
    # specific binds strict.
    from exptrack.dashboard.app import _allowed_host_for_bind
    for bind, expected in (("0.0.0.0", "*"), ("::", "*"), ("[::]", "*"),
                           ("192.168.1.50", "192.168.1.50"),
                           ("MyHost.Local", "myhost.local")):
        assert _allowed_host_for_bind(bind) == expected


def test_localhost_bind_still_rejects_foreign_host(tmp_project):
    # The default localhost bind keeps the full DNS-rebinding defense.
    h, sent = _make_handler(tmp_project, host="evil.example",
                            allowed_host="127.0.0.1", path="/")
    h.do_GET()
    assert sent["error"] == 403


def test_bad_host_rejected_post(tmp_project):
    h, sent = _make_handler(tmp_project, host="evil.example",
                            path="/api/clean-db", body=b"{}")
    h.do_POST()
    assert sent["error"] == 403


# ── F12: vendored Chart.js ───────────────────────────────────────────────────

def test_vendor_chart_served_without_auth(tmp_project):
    h, sent = _make_handler(tmp_project, path="/vendor/chart.umd.min.js")
    h.do_GET()
    assert sent["status"] == 200
    assert sent["headers"]["Content-Type"] == "application/javascript"
    assert len(sent["body"]) > 100_000  # the real UMD build


def test_dashboard_html_has_no_cdn():
    from exptrack.dashboard.static import DASHBOARD_HTML
    assert "cdn.jsdelivr" not in DASHBOARD_HTML
    assert "/vendor/chart.umd.min.js" in DASHBOARD_HTML


# ── F13: malformed input → 400/200, not 500 ──────────────────────────────────

def test_invalid_json_body_400(tmp_project):
    h, sent = _make_handler(tmp_project, path="/api/clean-db", body=b"not-json")
    h.do_POST()
    assert sent["error"] == 400


def test_bad_limit_query_defaults(db_conn):
    from exptrack.dashboard.routes.read_routes import api_experiments
    # ?limit=abc must not raise; falls back to the default.
    result = api_experiments(db_conn, {"limit": "abc"})
    assert isinstance(result, list)


def test_bad_seq_query_defaults(sample_experiment):
    from exptrack.core import get_db
    from exptrack.dashboard.routes.read_routes import api_vars_at
    conn = get_db()
    result = api_vars_at(conn, sample_experiment.id, {"seq": "abc"})
    assert isinstance(result, dict)
    assert "error" not in result


# ── F14: /api/file scoped away from .exptrack/ ───────────────────────────────

def test_serve_file_blocks_exptrack_config(tmp_project):
    # config.json holds the dashboard token — must never be served.
    (tmp_project / ".exptrack" / "config.json").write_text('{"dashboard_token": "s3cret"}')
    h, sent = _make_handler(tmp_project)
    h._serve_file(".exptrack/config.json")
    assert sent["error"] == 403
    assert b"s3cret" not in sent["body"]


def test_serve_file_allows_outputs(tmp_project):
    log_dir = tmp_project / "outputs" / "exp1"
    log_dir.mkdir(parents=True)
    (log_dir / "run.log").write_text("training started\n")
    h, sent = _make_handler(tmp_project)
    h._serve_file("outputs/exp1/run.log")
    assert sent["error"] is None
    assert sent["status"] == 200
    assert b"training started" in sent["body"]


def test_serve_file_blocks_traversal(tmp_project):
    h, sent = _make_handler(tmp_project)
    h._serve_file("../../etc/passwd")
    assert sent["error"] in (403, 404)
