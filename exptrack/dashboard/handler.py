"""
exptrack/dashboard/handler.py — DashboardHandler: HTTP routing + JSON responses

Route logic is delegated to routes/read_routes.py and routes/write_routes.py.
This file handles HTTP parsing, routing dispatch, and response formatting.
"""
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler

from .static import DASHBOARD_HTML
from .routes import read_routes, write_routes


def get_db():
    from exptrack.core import get_db as _get_db
    return _get_db()


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress request logs

    # ── GET routing ──────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = dict(urllib.parse.parse_qsl(parsed.query))
        conn = get_db()

        if path == "/" or path == "/index.html":
            self._html()
        elif path == "/api/stats":
            self._json(read_routes.api_stats(conn))
        elif path == "/api/experiments":
            self._json(read_routes.api_experiments(conn, qs))
        elif path.startswith("/api/experiment/"):
            self._json(read_routes.api_experiment(conn, path.split("/")[-1]))
        elif path.startswith("/api/metrics/"):
            self._json(read_routes.api_metrics(conn, path.split("/")[-1]))
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
        elif path == "/api/result-types":
            self._json(read_routes.api_result_types())
        elif path == "/api/studies":
            self._json(read_routes.api_studies(conn))
        elif path == "/api/multi-compare":
            self._json(read_routes.api_multi_compare(conn, qs))
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
                "delete-result":   lambda: write_routes.api_delete_result(conn, exp_id, body),
                "edit-result":     lambda: write_routes.api_edit_result(conn, exp_id, body),
            }
            handler = dispatch.get(action)
            if handler:
                self._json(handler())
                return

        # Global mutations
        global_dispatch = {
            "/api/delete-tag-global":    lambda: write_routes.api_delete_tag_global(conn, body),
            "/api/bulk-delete":          lambda: write_routes.api_bulk_delete(conn, body),
            "/api/bulk-export":          lambda: write_routes.api_bulk_export(conn, body),
            "/api/config/timezone":      lambda: write_routes.api_set_timezone(body),
            "/api/studies/create":       lambda: write_routes.api_create_study(conn, body),
            "/api/studies/add":          lambda: write_routes.api_add_to_study(conn, body),
            "/api/studies/remove":       lambda: write_routes.api_remove_from_study(conn, body),
            "/api/studies/delete":       lambda: write_routes.api_delete_study(conn, body),
            "/api/all-studies":          lambda: write_routes.api_all_studies(conn),
            "/api/bulk-add-to-study":    lambda: write_routes.api_bulk_add_to_study(conn, body),
            "/api/result-types":         lambda: write_routes.api_manage_result_types(body),
        }
        handler = global_dispatch.get(path)
        if handler:
            self._json(handler())
        else:
            self.send_error(404)

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
        abs_path = os.path.normpath(os.path.join(root, rel_path))
        # Security: ensure path is within project root
        if not abs_path.startswith(os.path.normpath(root)):
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
            '.err': 'text/plain', '.csv': 'text/csv', '.json': 'application/json',
            '.jsonl': 'application/json',
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
