"""
exptrack/dashboard/handler.py — DashboardHandler: HTTP routing + JSON responses

Route logic is delegated to routes/read_routes.py and routes/write_routes.py.
This file handles HTTP parsing, routing dispatch, and response formatting.
"""
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler

from .routes import read_routes, write_routes
from .static import DASHBOARD_HTML


def get_db():
    from exptrack.core import get_db as _get_db
    return _get_db()


def _get_auth_token() -> str:
    """Return the dashboard auth token from config or env, or empty string if none."""
    token = os.environ.get("EXPTRACK_DASHBOARD_TOKEN", "")
    if not token:
        try:
            from exptrack import config as _cfg
            conf = _cfg.load()
            token = conf.get("dashboard_token", "")
        except Exception:
            pass
    return token


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress request logs

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except BrokenPipeError:
            pass  # browser closed connection early — harmless

    def _check_auth(self) -> bool:
        """Check Bearer token auth if a dashboard_token is configured.
        Returns True if authorized, False if rejected (error already sent)."""
        token = _get_auth_token()
        if not token:
            return True  # no auth configured
        auth_header = self.headers.get("Authorization", "")
        # Allow token via query param for browser access
        parsed = urllib.parse.urlparse(self.path)
        qs = dict(urllib.parse.parse_qsl(parsed.query))
        if auth_header == f"Bearer {token}" or qs.get("token") == token:
            return True
        self.send_error(401, "Unauthorized - set Authorization: Bearer <token> header "
                        "or ?token=<token> query param")
        return False

    # ── GET routing ──────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Serve the HTML shell without auth so the browser can show a login prompt
        if path == "/" or path == "/index.html":
            self._html()
            return

        if not self._check_auth():
            return
        qs = dict(urllib.parse.parse_qsl(parsed.query))
        conn = get_db()

        # Checkpoint WAL on every API request.  External CLI commands
        # (run-start, run-finish, clean --reset) cannot truncate the WAL
        # while the dashboard holds a connection — only we can do it.
        # wal_checkpoint(TRUNCATE) is a no-op (<1ms) when the WAL is empty.
        self._wal_checkpoint(conn)

        if False:
            pass  # placeholder — removed the duplicate "/" branch above
        elif path == "/api/stats":
            self._json(read_routes.api_stats(conn))
        elif path == "/api/experiments":
            self._json(read_routes.api_experiments(conn, qs))
        elif path.startswith("/api/experiment/"):
            self._json(read_routes.api_experiment(conn, path.split("/")[-1]))
        elif path.startswith("/api/metrics/"):
            self._json(read_routes.api_metrics(conn, path.split("/")[-1], qs))
        elif path.startswith("/api/diff/"):
            self._json(read_routes.api_diff(conn, path.split("/")[-1]))
        elif path == "/api/compare":
            self._json(read_routes.api_compare(conn, qs))
        elif path.startswith("/api/timeline/"):
            self._json(read_routes.api_timeline(conn, path.split("/")[-1], qs))
        elif path.startswith("/api/vars-at/"):
            self._json(read_routes.api_vars_at(conn, path.split("/")[-1], qs))
        elif path.startswith("/api/cell-source/"):
            self._json(read_routes.api_cell_source(conn, path.split("/")[-1]))
        elif path.startswith("/api/export/"):
            self._json(read_routes.api_export(conn, path.split("/")[-1], qs))
        elif path == "/api/all-tags":
            self._json(read_routes.api_all_tags(conn))
        elif path == "/api/config/timezone":
            self._json(read_routes.api_get_timezone())
        elif path == "/api/config/metrics":
            self._json(read_routes.api_get_metric_settings())
        elif path == "/api/result-types":
            self._json(read_routes.api_result_types())
        elif path == "/api/studies":
            self._json(read_routes.api_studies(conn))
        elif path == "/api/multi-compare":
            self._json(read_routes.api_multi_compare(conn, qs))
        elif path == "/api/todos":
            self._json(read_routes.api_get_todos())
        elif path == "/api/commands":
            self._json(read_routes.api_get_commands())
        elif path == "/api/all-studies":
            self._json(write_routes.api_all_studies(conn))
        elif path.startswith("/api/logs/"):
            exp_id = path.split("/")[3] if len(path.split("/")) >= 4 else ""
            self._json(read_routes.api_list_logs(conn, exp_id))
        elif path.startswith("/api/images/"):
            exp_id = path.split("/")[3] if len(path.split("/")) >= 4 else ""
            self._json(read_routes.api_list_images(conn, exp_id))
        elif path.startswith("/api/file/"):
            # Serve a file from the project root (for image viewing)
            file_path = "/".join(path.split("/")[3:])
            file_path = urllib.parse.unquote(file_path)
            self._serve_file(file_path)
        else:
            self.send_error(404)

    # ── POST routing ─────────────────────────────────────────────────────────

    def do_POST(self):
        if not self._check_auth():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get('Content-Length', 0))
        if content_len > 10 * 1024 * 1024:  # 10MB limit
            self.send_error(413, "Request body too large")
            return
        body = json.loads(self.rfile.read(content_len)) if content_len else {}
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
                "edit-script":     lambda: write_routes.api_edit_script(conn, exp_id, body),
                "edit-command":    lambda: write_routes.api_edit_command(conn, exp_id, body),
                "export-diff":     lambda: write_routes.api_export_diff(conn, exp_id),
            }
            handler = dispatch.get(action)
            if handler:
                self._json(handler())
                self._wal_checkpoint(conn)
                return

        # Global mutations
        global_dispatch = {
            "/api/delete-tag-global":    lambda: write_routes.api_delete_tag_global(conn, body),
            "/api/bulk-delete":          lambda: write_routes.api_bulk_delete(conn, body),
            "/api/bulk-compact":         lambda: write_routes.api_compact(conn, body),
            "/api/bulk-export":          lambda: write_routes.api_bulk_export(conn, body),
            "/api/config/timezone":      lambda: write_routes.api_set_timezone(body),
            "/api/config/metrics":       lambda: write_routes.api_set_metric_settings(body),
            "/api/studies/create":       lambda: write_routes.api_create_study(conn, body),
            "/api/studies/add":          lambda: write_routes.api_add_to_study(conn, body),
            "/api/studies/remove":       lambda: write_routes.api_remove_from_study(conn, body),
            "/api/studies/delete":       lambda: write_routes.api_delete_study(conn, body),
            "/api/all-studies":          lambda: write_routes.api_all_studies(conn),
            "/api/bulk-add-to-study":    lambda: write_routes.api_bulk_add_to_study(conn, body),
            "/api/result-types":         lambda: write_routes.api_manage_result_types(body),
            "/api/experiments/create":   lambda: write_routes.api_create_experiment(conn, body),
            "/api/clean-db":             lambda: write_routes.api_clean_db(conn),
            "/api/vacuum-db":            lambda: write_routes.api_vacuum_db(conn),
            "/api/reset-db":             lambda: write_routes.api_reset_db(conn),
            "/api/todos/add":            lambda: write_routes.api_add_todo(body),
            "/api/todos/update":         lambda: write_routes.api_update_todo(body),
            "/api/todos/delete":         lambda: write_routes.api_delete_todo(body),
            "/api/commands/add":         lambda: write_routes.api_add_command(body),
            "/api/commands/update":      lambda: write_routes.api_update_command(body),
            "/api/commands/delete":      lambda: write_routes.api_delete_command(body),
            "/api/storage-info":         lambda: write_routes.api_storage_info(conn),
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

    def _html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DASHBOARD_HTML.encode())

    def _json(self, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, rel_path: str):
        """Serve a file from the project root (images only, with path validation)."""
        import os

        from exptrack.config import project_root
        root = str(project_root())
        if not root:
            self.send_error(404, "No project root")
            return
        abs_path = os.path.realpath(os.path.join(root, rel_path))
        # Security: ensure path is within project root (realpath resolves symlinks)
        if not abs_path.startswith(os.path.realpath(root) + os.sep) and abs_path != os.path.realpath(root):
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
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=60")
        self.end_headers()
        self.wfile.write(data)
