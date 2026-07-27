"""
exptrack/dashboard/handler.py — DashboardHandler: HTTP routing + JSON responses

Route logic is delegated to routes/read_routes.py and routes/write_routes.py.
This file handles HTTP parsing, routing dispatch, and response formatting.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .routes import read_routes, write_routes
from .static import DASHBOARD_CSS, DASHBOARD_HTML, DASHBOARD_JS

# The assembled JS/CSS bundles, served at /static/dashboard.{js,css} (auth-
# exempt, Host-gated) and referenced from the HTML by hash-versioned URL. Bytes
# built once at import; the ?v=<hash> query busts the browser cache on change.
_STATIC_BUNDLES = {
    "dashboard.css": (DASHBOARD_CSS.encode("utf-8"), "text/css; charset=utf-8"),
    "dashboard.js": (DASHBOARD_JS.encode("utf-8"), "application/javascript; charset=utf-8"),
}

# Vendored static assets served at /vendor/<name> (auth-exempt, Host-gated).
# The bytes are pinned build artifacts, so read each once and cache.
_VENDOR_DIR = Path(__file__).parent / "vendor"
_VENDOR_ALLOWED = {"chart.umd.min.js"}
_vendor_cache: dict = {}

# ── Security headers ────────────────────────────────────────────────────────
# Sent on every response by _send_bytes. `nosniff` stops a browser from
# re-typing a served .txt/.log as HTML; `no-referrer` matters specifically
# because fileUrl() puts the auth token in the query string (?token=…), so
# without it every outbound link would leak the token in the Referer header.
_SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
)

# CSP for the dashboard HTML shell. `'unsafe-inline'` on script-src is
# required — the UI is built on inline on* handlers throughout (see the
# escJsAttr rule in CLAUDE.md), so this policy is not an XSS backstop. What it
# does buy: no external origin can be contacted (blocking exfiltration of the
# token or run data), the page cannot be framed, and <base>/<object>/<form>
# hijacking is off.
_CSP_HTML = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

# CSP for user files served from /api/file/. `sandbox` (with no
# allow-scripts / allow-same-origin) is the load-bearing token: an SVG is a
# live document, and artifacts are user-supplied files that a project can pick
# up from a cloned repo or a shared dataset. Without this, opening a hostile
# .svg artifact would run script on the dashboard's own origin with the auth
# token sitting in location.search. The sandbox disables scripting and drops
# the document into an opaque origin, so it can neither execute nor read the
# dashboard's storage. Images still render normally; style-src keeps inline
# <style> inside plot SVGs working.
_CSP_FILE = (
    "default-src 'none'; "
    "img-src 'self' data:; "
    "style-src 'unsafe-inline'; "
    "sandbox"
)

# CSP for everything else (JSON APIs, JS/CSS bundles, vendored assets). These
# are never rendered as documents, so nothing needs to be allowed.
_CSP_STRICT = "default-src 'none'; frame-ancestors 'none'"


# ── GET routing tables ──────────────────────────────────────────────────────
# Split in two so ordering only has to be reasoned about where it can actually
# bite. Every handler takes (conn, qs, path) and returns a JSON-able payload.

def _seg(path: str, i: int) -> str:
    """Path segment `i`, counting the empty string before the leading '/'.

    So /api/experiment/<id>/delete-preview has the id at index 3.
    """
    parts = path.split("/")
    return parts[i] if len(parts) > i else ""


def _last(path: str) -> str:
    """Trailing path segment."""
    return path.rsplit("/", 1)[-1]


# Exact-path routes. A dict lookup cannot be shadowed by a sibling entry, so
# any route whose full path is known belongs here and needs no ordering
# thought whatsoever.
_GET_EXACT = {
    "/api/stats":            lambda conn, qs, p: read_routes.api_stats(conn),
    "/api/experiments":      lambda conn, qs, p: read_routes.api_experiments(conn, qs),
    "/api/compare":          lambda conn, qs, p: read_routes.api_compare(conn, qs),
    "/api/multi-compare":    lambda conn, qs, p: read_routes.api_multi_compare(conn, qs),
    "/api/all-tags":         lambda conn, qs, p: read_routes.api_all_tags(conn),
    "/api/config/timezone":  lambda conn, qs, p: read_routes.api_get_timezone(),
    "/api/config/metrics":   lambda conn, qs, p: read_routes.api_get_metric_settings(),
    "/api/config/capture":   lambda conn, qs, p: read_routes.api_get_capture_settings(),
    "/api/result-types":     lambda conn, qs, p: read_routes.api_result_types(),
    "/api/studies":          lambda conn, qs, p: read_routes.api_studies(conn),
    "/api/todos":            lambda conn, qs, p: read_routes.api_get_todos(),
    "/api/commands":         lambda conn, qs, p: read_routes.api_get_commands(),
    "/api/trash":            lambda conn, qs, p: read_routes.api_trash(conn),
    "/api/sessions":         lambda conn, qs, p: read_routes.api_sessions(conn),
    "/api/all-studies":      lambda conn, qs, p: write_routes.api_all_studies(conn),
}

# Routes carrying an id in the path, as (prefix, suffix, handler) — an empty
# suffix means "prefix only".
#
# Order within this table does not matter: _match_prefixed_get tries every
# suffixed entry before any bare-prefix one, so a specific route can never be
# shadowed by the generic route sharing its prefix. That shadowing is the
# failure this table is shaped to prevent, and it is silent rather than loud —
# /api/experiment/<id>/delete-preview would otherwise resolve to the generic
# /api/experiment/ handler with "delete-preview" as the experiment id, giving
# the client a 200 with the wrong body. Grouping below is for reading only.
_GET_PREFIXED = (
    ("/api/experiment/", "/delete-preview",
     lambda conn, qs, p: read_routes.api_delete_preview(conn, _seg(p, 3))),
    ("/api/experiment/", "/prev-by-script",
     lambda conn, qs, p: read_routes.api_prev_by_script(conn, _seg(p, 3))),
    ("/api/experiment/", "",
     lambda conn, qs, p: read_routes.api_experiment(conn, _last(p))),

    ("/api/session/", "/nodes",
     lambda conn, qs, p: read_routes.api_session_nodes(conn, _seg(p, 3))),
    ("/api/session/", "/trash",
     lambda conn, qs, p: read_routes.api_session_trash(conn, _seg(p, 3))),
    ("/api/session/", "/finalize-preview",
     lambda conn, qs, p: read_routes.api_session_finalize_preview(conn, _seg(p, 3))),
    ("/api/session/", "",
     lambda conn, qs, p: read_routes.api_session_tree(conn, _last(p))),

    ("/api/run-delta/", "", lambda conn, qs, p: read_routes.api_run_delta(conn, _last(p))),
    ("/api/metrics/", "", lambda conn, qs, p: read_routes.api_metrics(conn, _last(p), qs)),
    ("/api/diff/", "", lambda conn, qs, p: read_routes.api_diff(conn, _last(p))),
    ("/api/timeline/", "", lambda conn, qs, p: read_routes.api_timeline(conn, _last(p), qs)),
    ("/api/vars-at/", "", lambda conn, qs, p: read_routes.api_vars_at(conn, _last(p), qs)),
    ("/api/cell-source/", "", lambda conn, qs, p: read_routes.api_cell_source(conn, _last(p))),
    ("/api/export/", "", lambda conn, qs, p: read_routes.api_export(conn, _last(p), qs)),
    ("/api/confusion/", "", lambda conn, qs, p: read_routes.api_list_confusion(conn, _last(p))),
    # These two read segment 3 rather than the last segment, so a trailing
    # extra segment is ignored instead of being taken as the id.
    ("/api/logs/", "", lambda conn, qs, p: read_routes.api_list_logs(conn, _seg(p, 3))),
    ("/api/images/", "", lambda conn, qs, p: read_routes.api_list_images(conn, _seg(p, 3))),
)


def get_db():
    from exptrack.core import get_db as _get_db
    return _get_db()


_session_token: str = ""


def set_session_token(token: str) -> None:
    """Install an in-memory token for the running dashboard process.

    Lives only for this process — not persisted to config and not exported
    to the environment, so it cannot leak to child processes.
    """
    global _session_token
    _session_token = token


def _read_token_file() -> str:
    """Read the token from ``.exptrack/dashboard_token`` (see config.token_file_path)."""
    try:
        from exptrack.config import token_file_path
        p = token_file_path()
        return p.read_text().strip() if p.is_file() else ""
    except Exception:
        return ""


def _get_auth_token() -> str:
    """Return the dashboard auth token from the session, env, or disk.

    Precedence: explicit env var > token file > legacy config key >
    in-process session token. A deliberately-set token always wins over the
    auto-generated one; the ``config.json`` key is still read so existing
    setups keep working, but `exptrack ui --token` no longer writes there
    (and warns when it finds one).
    """
    token = os.environ.get("EXPTRACK_DASHBOARD_TOKEN", "")
    if not token:
        token = _read_token_file()
    if not token:
        try:
            from exptrack import config as _cfg
            conf = _cfg.load()
            token = conf.get("dashboard_token", "")
        except Exception:
            pass
    if not token:
        token = _session_token
    return token


class DashboardHandler(BaseHTTPRequestHandler):
    # Set once a response has started, so the 500 handler knows whether it is
    # still safe to send one.
    _responded: bool = False

    # Drop a connection that opens but never sends a request line. Tunnels and
    # browsers both pre-open sockets they may never use; with a thread per
    # connection those would otherwise sit in readline() for the lifetime of
    # the process, one parked thread each. StreamRequestHandler.setup() applies
    # this to the socket and http.server turns the resulting timeout into a
    # clean close (its log_error routes through the suppressed log_message, so
    # a reaped idle socket stays silent).
    timeout = 30

    def log_message(self, fmt, *args):
        pass  # suppress request logs

    def end_headers(self, csp: str = _CSP_STRICT):
        """Attach the security headers to *every* response, then flush.

        Hooked here rather than in _send_bytes because send_error writes HTML
        error pages without going through it — this is the one point every
        response passes, which also makes it the right place to record that a
        response has started.

        ``csp`` defaults to the strict policy, so a caller that forgets to
        pass one (including send_error's own internal no-arg call) fails
        closed rather than open. _send_bytes passes a looser policy for the
        two response kinds a browser actually renders as documents.
        """
        for name, value in _SECURITY_HEADERS:
            self.send_header(name, value)
        self.send_header("Content-Security-Policy", csp)
        self._responded = True
        super().end_headers()

    def _server_error(self):
        """Turn an unhandled route exception into a readable 500.

        Without this the exception escapes the handler, BaseHTTPRequestHandler
        closes the connection with no response written at all, and the caller
        sees a dropped socket. The dashboard's own error bar cannot say
        anything useful about that, and neither can curl. A route bug should
        be a status code you can read, not a disconnect.

        The traceback goes to the console the user started `exptrack ui` in —
        this is a local, single-user tool, so that is where they will look.
        """
        traceback.print_exc(file=sys.stderr)
        if self._responded:
            return  # body already going out; nothing safe to append
        try:
            self.send_error(500, "Internal server error - see the exptrack console")
        except Exception:
            pass

    def handle_one_request(self):
        """The one point every request passes through — so the error boundary
        lives here rather than being wired per verb.

        Wrapping do_GET/do_POST individually would mean a do_HEAD or do_PUT
        added later silently reverts to the old failure mode (exception
        escapes, connection closed with no response) and no test would notice.
        """
        self._responded = False
        try:
            super().handle_one_request()
        except BrokenPipeError:
            pass  # browser closed connection early — harmless
        except Exception:
            self._server_error()

    def _host_allowed(self) -> bool:
        """Reject requests whose Host header isn't a local name we bound to.

        Guards against DNS-rebinding: a remote page that resolves its own
        hostname to 127.0.0.1 would otherwise reach the dashboard same-origin.
        Handles ``host:port`` and bracketed IPv6 (``[::1]:7331``).

        A wildcard bind (``--host 0.0.0.0`` / ``::``) sets ``allowed_host``
        to ``"*"`` — clients then reach us under the machine's real name/IP,
        which can't be predicted here, and the user explicitly opted into
        network exposure, so any Host is accepted. The DNS-rebinding defense
        matters for (and is kept on) the default localhost bind.
        """
        allowed_host = getattr(self.server, "allowed_host", "")
        if allowed_host == "*":
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        allowed = {"127.0.0.1", "localhost", "::1", allowed_host}
        return host in allowed

    def _check_auth(self) -> bool:
        """Check Bearer token auth if a dashboard_token is configured.
        Returns True if authorized, False if rejected (error already sent)."""
        token = _get_auth_token()
        if not token:
            return True  # no auth configured
        # Constant-time compare guards against timing-based token enumeration
        # on network-exposed dashboards.
        auth_header = self.headers.get("Authorization", "")
        presented = auth_header[7:] if auth_header.startswith("Bearer ") else ""
        if not presented:
            parsed = urllib.parse.urlparse(self.path)
            qs = dict(urllib.parse.parse_qsl(parsed.query))
            presented = qs.get("token", "")
        if presented and secrets.compare_digest(presented, token):
            return True
        self.send_error(401, "Unauthorized - set Authorization: Bearer <token> header "
                        "or ?token=<token> query param")
        return False

    # ── GET routing ──────────────────────────────────────────────────────────

    def do_GET(self):
        if not self._host_allowed():
            self.send_error(403, "Forbidden: bad Host header")
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Serve the HTML shell without auth so the browser can show a login prompt
        if path == "/" or path == "/index.html":
            self._html()
            return

        # Vendored Chart.js — served without auth (a <script src> tag cannot
        # carry the Bearer token), same as the HTML shell. Still Host-gated above.
        if path == "/vendor/chart.umd.min.js":
            self._serve_vendor("chart.umd.min.js")
            return

        # Assembled dashboard JS/CSS bundles — auth-exempt (a <link>/<script src>
        # can't carry the token) and Host-gated, like the shell. The ?v=<hash>
        # query is ignored here (matched on the path); it only busts the cache.
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
            return

        if not self._check_auth():
            return

        # Lightweight auth probe — used by the login overlay to validate a
        # candidate token without touching the DB.
        if path == "/api/ping":
            self._json({"ok": True})
            return

        qs = dict(urllib.parse.parse_qsl(parsed.query))
        conn = get_db()

        # Checkpoint WAL on every API request.  External CLI commands
        # (run-start, run-finish, clean --reset) cannot truncate the WAL
        # while the dashboard holds a connection — only we can do it.
        # wal_checkpoint(TRUNCATE) is a no-op (<1ms) when the WAL is empty.
        self._wal_checkpoint(conn)

        handler = _GET_EXACT.get(path)
        if handler is None:
            handler = self._match_prefixed_get(path)

        if handler is not None:
            self._json(handler(conn, qs, path))
        elif path.startswith("/api/file/"):
            # The one GET that serves bytes rather than JSON, so it sits
            # outside the tables. Nothing else matches this prefix.
            file_path = "/".join(path.split("/")[3:])
            self._serve_file(urllib.parse.unquote(file_path))
        else:
            self.send_error(404)

    @staticmethod
    def _match_prefixed_get(path: str):
        """Match _GET_PREFIXED, specific routes before generic ones.

        Two passes rather than one, so table order carries no meaning: every
        prefix+suffix entry is tried before any bare-prefix entry. A new
        sub-action can therefore be appended anywhere — including directly
        below the generic route it shares a prefix with, which is the natural
        place to put it and would silently make it dead code under
        first-match-wins.
        """
        for prefix, suffix, fn in _GET_PREFIXED:
            if suffix and path.startswith(prefix) and path.endswith(suffix):
                return fn
        for prefix, suffix, fn in _GET_PREFIXED:
            if not suffix and path.startswith(prefix):
                return fn
        return None

    # ── POST routing ─────────────────────────────────────────────────────────

    def do_POST(self):
        if not self._host_allowed():
            self.send_error(403, "Forbidden: bad Host header")
            return
        if not self._check_auth():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get('Content-Length', 0))
        if content_len > 10 * 1024 * 1024:  # 10MB limit
            self.send_error(413, "Request body too large")
            return
        try:
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
        except (ValueError, UnicodeDecodeError):
            self.send_error(400, "Invalid JSON body")
            return
        conn = get_db()

        # Experiment-scoped mutations: /api/experiment/<id>/<action>
        if path.startswith("/api/experiment/"):
            parts = path.split("/")
            exp_id = parts[-2] if len(parts) >= 4 else ""
            action = parts[-1] if len(parts) >= 4 else ""

            dispatch = {
                "note":            lambda: write_routes.api_add_note(conn, exp_id, body),
                "tag":             lambda: write_routes.api_add_tag(conn, exp_id, body),
                "rename":          lambda: write_routes.api_rename(conn, exp_id, body),
                "delete":          lambda: write_routes.api_delete(conn, exp_id),
                "restore":         lambda: write_routes.api_restore(conn, exp_id),
                "delete-permanent": lambda: write_routes.api_delete_permanent(conn, exp_id, body),
                "finish":          lambda: write_routes.api_finish(conn, exp_id),
                "artifact":        lambda: write_routes.api_add_artifact(conn, exp_id, body),
                "delete-tag":      lambda: write_routes.api_delete_tag(conn, exp_id, body),
                "edit-tag":        lambda: write_routes.api_edit_tag(conn, exp_id, body),
                "edit-notes":      lambda: write_routes.api_edit_notes(conn, exp_id, body),
                "delete-artifact": lambda: write_routes.api_delete_artifact(conn, exp_id, body),
                "edit-artifact":   lambda: write_routes.api_edit_artifact(conn, exp_id, body),
                "study":           lambda: write_routes.api_add_study(conn, exp_id, body),
                "delete-study":    lambda: write_routes.api_delete_exp_study(conn, exp_id, body),
                "stage":           lambda: write_routes.api_set_stage(conn, exp_id, body),
                "image-path":      lambda: write_routes.api_image_path(conn, exp_id, body),
                "log-path":        lambda: write_routes.api_log_path(conn, exp_id, body),
                "log-result":      lambda: write_routes.api_log_result(conn, exp_id, body),
                "log-metric":      lambda: write_routes.api_log_metric(conn, exp_id, body),
                "delete-result":   lambda: write_routes.api_delete_result(conn, exp_id, body),
                "delete-metric":   lambda: write_routes.api_delete_metric(conn, exp_id, body),
                "rename-metric":   lambda: write_routes.api_rename_metric(conn, exp_id, body),
                "edit-result":     lambda: write_routes.api_edit_result(conn, exp_id, body),
                "add-param":       lambda: write_routes.api_add_param(conn, exp_id, body),
                "edit-param":      lambda: write_routes.api_edit_param(conn, exp_id, body),
                "delete-param":    lambda: write_routes.api_delete_param(conn, exp_id, body),
                "rename-param":    lambda: write_routes.api_rename_param(conn, exp_id, body),
                "edit-script":     lambda: write_routes.api_edit_script(conn, exp_id, body),
                "save-confusion":  lambda: write_routes.api_save_confusion(conn, exp_id, body),
                "edit-command":    lambda: write_routes.api_edit_command(conn, exp_id, body),
                "export-diff":     lambda: write_routes.api_export_diff(conn, exp_id),
            }
            handler = dispatch.get(action)
            if handler:
                self._json(handler())
                self._wal_checkpoint(conn)
                return

        # Session-scoped mutations: /api/session/<id>/<action>
        if path.startswith("/api/session/"):
            parts = path.split("/")
            if len(parts) >= 5:
                sid = parts[-2]
                action = parts[-1]
                sess_dispatch = {
                    "note-node":            lambda: write_routes.api_session_note_node(conn, sid, body),
                    "rename-node":          lambda: write_routes.api_session_rename_node(conn, sid, body),
                    "end":                  lambda: write_routes.api_session_end(conn, sid, body),
                    "delete":               lambda: write_routes.api_session_delete(conn, sid, body),
                    "restore":              lambda: write_routes.api_session_restore(conn, sid, body),
                    "purge":                lambda: write_routes.api_session_purge(conn, sid, body),
                    "finalize":             lambda: write_routes.api_session_finalize(conn, sid, body),
                    "delete-node":          lambda: write_routes.api_session_delete_node(conn, sid, body),
                    "delete-node-preview":  lambda: write_routes.api_session_preview_delete_node(conn, sid, body),
                    "restore-node":         lambda: write_routes.api_session_restore_node(conn, sid, body),
                    "promote-to-checkpoint": lambda: write_routes.api_session_promote_to_checkpoint(conn, sid, body),
                    "materialize-experiment": lambda: write_routes.api_session_materialize_experiment(conn, sid, body),
                    "link-experiment":      lambda: write_routes.api_session_link_experiment(conn, sid, body),
                    "purge-node":           lambda: write_routes.api_session_purge_node(conn, sid, body),
                    "empty-trash":          lambda: write_routes.api_session_empty_trash(conn, sid, body),
                }
                handler = sess_dispatch.get(action)
                if handler:
                    self._json(handler())
                    self._wal_checkpoint(conn)
                    return

        # Global mutations
        global_dispatch = {
            "/api/delete-tag-global":    lambda: write_routes.api_delete_tag_global(conn, body),
            "/api/bulk-delete":          lambda: write_routes.api_bulk_delete(conn, body),
            "/api/bulk-restore":         lambda: write_routes.api_bulk_restore(conn, body),
            "/api/bulk-delete-permanent": lambda: write_routes.api_bulk_delete_permanent(conn, body),
            "/api/bulk-delete-preview":  lambda: write_routes.api_bulk_delete_preview(conn, body),
            "/api/bulk-compact":         lambda: write_routes.api_compact(conn, body),
            "/api/bulk-export":          lambda: write_routes.api_bulk_export(conn, body),
            "/api/config/timezone":      lambda: write_routes.api_set_timezone(body),
            "/api/config/metrics":       lambda: write_routes.api_set_metric_settings(body),
            "/api/config/capture":       lambda: write_routes.api_set_capture_settings(body),
            "/api/studies/create":       lambda: write_routes.api_create_study(conn, body),
            "/api/studies/add":          lambda: write_routes.api_add_to_study(conn, body),
            "/api/studies/remove":       lambda: write_routes.api_remove_from_study(conn, body),
            "/api/studies/delete":       lambda: write_routes.api_delete_study(conn, body),
            "/api/all-studies":          lambda: write_routes.api_all_studies(conn),
            "/api/bulk-add-to-study":    lambda: write_routes.api_bulk_add_to_study(conn, body),
            "/api/result-types":         lambda: write_routes.api_manage_result_types(body),
            "/api/experiments/create":   lambda: write_routes.api_create_experiment(conn, body),
            "/api/clean-db":             lambda: write_routes.api_clean_db(conn, body),
            "/api/vacuum-db":            lambda: write_routes.api_vacuum_db(conn),
            "/api/reset-db":             lambda: write_routes.api_reset_db(conn),
            "/api/todos/add":            lambda: write_routes.api_add_todo(body),
            "/api/todos/update":         lambda: write_routes.api_update_todo(body),
            "/api/todos/delete":         lambda: write_routes.api_delete_todo(body),
            "/api/commands/add":         lambda: write_routes.api_add_command(body),
            "/api/commands/update":      lambda: write_routes.api_update_command(body),
            "/api/commands/delete":      lambda: write_routes.api_delete_command(body),
            "/api/commands/reorder":     lambda: write_routes.api_reorder_commands(body),
            "/api/storage-info":         lambda: write_routes.api_storage_info(conn),
            "/api/propagate-tag-rename": lambda: write_routes.api_propagate_tag_rename(body),
            "/api/propagate-study-rename": lambda: write_routes.api_propagate_study_rename(body),
            "/api/save-export":          lambda: write_routes.api_save_export(body),
        }
        handler = global_dispatch.get(path)
        if handler:
            self._json(handler())
            self._wal_checkpoint(conn)
        else:
            self.send_error(404)

    # ── WAL maintenance ─────────────────────────────────────────────────────

    @staticmethod
    def _wal_checkpoint(conn):
        """Checkpoint and truncate the WAL after writes.

        TRUNCATE flushes all WAL pages back to the DB and then truncates
        the WAL file to zero bytes.  The dashboard is the only long-lived
        connection, so this is safe and keeps the WAL from growing unbounded.
        """
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass

    # ── Response helpers ─────────────────────────────────────────────────────

    def _send_bytes(self, data: bytes, ctype: str, cache_control: str | None = None,
                    csp: str = _CSP_STRICT):
        """Write a 200 response body with the standard header tail.

        The shared shape (status + Content-Type + Content-Length + optional
        Cache-Control + security headers + body) behind every static/JSON/HTML
        response, so a future header change (ETag, a new policy) is made in one
        place. ``csp`` defaults to the strict no-op policy — a caller serving
        something the browser will actually render as a document (the HTML
        shell, a user file) passes its own.
        """
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers(csp)  # also emits the security headers
        self.wfile.write(data)

    def _html(self):
        self._send_bytes(DASHBOARD_HTML.encode(), "text/html; charset=utf-8",
                         csp=_CSP_HTML)

    def _json(self, data):
        self._send_bytes(json.dumps(data, default=str).encode(), "application/json")

    def _serve_static(self, name: str):
        """Serve an assembled dashboard bundle from /static/dashboard.{js,css}.

        Auth-exempt (a <link>/<script src> can't carry the Bearer token) but
        Host-gated, same as the HTML shell and the vendored Chart.js. The URL
        is hash-versioned, so the response is immutable and can cache hard.
        """
        entry = _STATIC_BUNDLES.get(name)
        if entry is None:
            self.send_error(404, "Not found")
            return
        data, ctype = entry
        self._send_bytes(data, ctype, "max-age=31536000, immutable")

    def _serve_vendor(self, name: str):
        """Serve a vendored static asset from exptrack/dashboard/vendor/.

        Auth-exempt (see do_GET) but Host-gated. Only a fixed allow-list of
        filenames is served, so the name can't be used for traversal. Bytes are
        cached after the first read — these are pinned build artifacts.
        """
        if name not in _VENDOR_ALLOWED:
            self.send_error(404, "Not found")
            return
        data = _vendor_cache.get(name)
        if data is None:
            path = _VENDOR_DIR / name
            if not path.is_file():
                self.send_error(404, "Not found")
                return
            data = _vendor_cache[name] = path.read_bytes()
        self._send_bytes(data, "application/javascript", "max-age=86400")

    def _serve_file(self, rel_path: str):
        """Serve a file from the project root (images only, with path validation)."""
        import os

        from exptrack.config import project_root
        root = str(project_root())
        if not root:
            self.send_error(404, "No project root")
            return
        real_root = os.path.realpath(root)
        abs_path = os.path.realpath(os.path.join(root, rel_path))
        # Security: ensure path is within project root (realpath resolves symlinks)
        if not abs_path.startswith(real_root + os.sep) and abs_path != real_root:
            self.send_error(403, "Access denied")
            return
        # Never serve exptrack's own internals (.exptrack/ holds config.json with
        # the dashboard token, the DB, notebook history). Legitimate assets live
        # under outputs/ and the project tree, not here.
        exptrack_dir = os.path.realpath(os.path.join(real_root, ".exptrack"))
        if abs_path == exptrack_dir or abs_path.startswith(exptrack_dir + os.sep):
            self.send_error(403, "Access denied")
            return
        if not os.path.isfile(abs_path):
            self.send_error(404, "File not found")
            return
        # Serve image and text file types
        ext = os.path.splitext(abs_path)[1].lower()
        mime_types = {
            '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.gif': 'image/gif', '.bmp': 'image/bmp', '.svg': 'image/svg+xml',
            '.tiff': 'image/tiff', '.webp': 'image/webp',
            '.log': 'text/plain', '.txt': 'text/plain', '.out': 'text/plain',
            '.err': 'text/plain', '.csv': 'text/csv', '.tsv': 'text/tab-separated-values',
            '.json': 'application/json', '.jsonl': 'application/json',
        }
        content_type = mime_types.get(ext)
        if not content_type:
            self.send_error(403, "File type not allowed")
            return
        with open(abs_path, 'rb') as f:
            data = f.read()
        # _CSP_FILE sandboxes the response — see the constant for why an SVG
        # artifact would otherwise be script execution on the dashboard origin.
        self._send_bytes(data, content_type, "max-age=60", csp=_CSP_FILE)
