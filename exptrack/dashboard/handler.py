"""
exptrack/dashboard/handler.py — DashboardHandler and API endpoints
"""
import json
import sys
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .static import DASHBOARD_HTML


def get_db():
    from exptrack.core import get_db as _get_db
    return _get_db()


def _delete_exp(conn, exp_id):
    from exptrack.core import delete_experiment
    delete_experiment(conn, exp_id)


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress request logs

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = dict(urllib.parse.parse_qsl(parsed.query))

        if path == "/" or path == "/index.html":
            self._html()
        elif path == "/api/stats":
            self._json_response(self._api_stats())
        elif path == "/api/experiments":
            self._json_response(self._api_experiments(qs))
        elif path.startswith("/api/experiment/"):
            exp_id = path.split("/")[-1]
            self._json_response(self._api_experiment(exp_id))
        elif path.startswith("/api/metrics/"):
            exp_id = path.split("/")[-1]
            self._json_response(self._api_metrics(exp_id))
        elif path.startswith("/api/diff/"):
            exp_id = path.split("/")[-1]
            self._json_response(self._api_diff(exp_id))
        elif path == "/api/compare":
            self._json_response(self._api_compare(qs))
        elif path.startswith("/api/timeline/"):
            exp_id = path.split("/")[-1]
            self._json_response(self._api_timeline(exp_id, qs))
        elif path.startswith("/api/vars-at/"):
            # /api/vars-at/<exp_id>?seq=N
            exp_id = path.split("/")[-1]
            self._json_response(self._api_vars_at(exp_id, qs))
        elif path.startswith("/api/cell-source/"):
            # /api/cell-source/<cell_hash>
            cell_hash = path.split("/")[-1]
            self._json_response(self._api_cell_source(cell_hash))
        elif path.startswith("/api/export/"):
            # /api/export/<exp_id>?format=json|markdown
            exp_id = path.split("/")[-1]
            self._json_response(self._api_export(exp_id, qs))
        elif path == "/api/all-tags":
            self._json_response(self._api_all_tags())
        elif path == "/api/config/timezone":
            self._json_response(self._api_get_timezone())
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get('Content-Length', 0))
        if content_len > 10 * 1024 * 1024:  # 10MB limit
            self.send_error(413, "Request body too large")
            return
        body = json.loads(self.rfile.read(content_len)) if content_len else {}

        if path.startswith("/api/experiment/") and path.endswith("/note"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_add_note(exp_id, body))
        elif path.startswith("/api/experiment/") and path.endswith("/tag"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_add_tag(exp_id, body))
        elif path.startswith("/api/experiment/") and path.endswith("/rename"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_rename(exp_id, body))
        elif path.startswith("/api/experiment/") and path.endswith("/delete"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_delete(exp_id))
        elif path.startswith("/api/experiment/") and path.endswith("/finish"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_finish(exp_id))
        elif path.startswith("/api/experiment/") and path.endswith("/artifact"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_add_artifact(exp_id, body))
        elif path.startswith("/api/experiment/") and path.endswith("/delete-tag"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_delete_tag(exp_id, body))
        elif path.startswith("/api/experiment/") and path.endswith("/edit-tag"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_edit_tag(exp_id, body))
        elif path.startswith("/api/experiment/") and path.endswith("/edit-notes"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_edit_notes(exp_id, body))
        elif path.startswith("/api/experiment/") and path.endswith("/delete-artifact"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_delete_artifact(exp_id, body))
        elif path.startswith("/api/experiment/") and path.endswith("/edit-artifact"):
            exp_id = path.split("/")[-2]
            self._json_response(self._api_edit_artifact(exp_id, body))
        elif path == "/api/bulk-delete":
            self._json_response(self._api_bulk_delete(body))
        elif path == "/api/bulk-export":
            self._json_response(self._api_bulk_export(body))
        elif path == "/api/config/timezone":
            self._json_response(self._api_set_timezone(body))
        else:
            self.send_error(404)

    def _html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DASHBOARD_HTML.encode())

    def _json_response(self, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _find_exp(self, exp_id, columns="id"):
        """Look up experiment by prefix match. Returns row or None."""
        conn = get_db()
        return conn.execute(f"SELECT {columns} FROM experiments WHERE id LIKE ?",
                            (exp_id + "%",)).fetchone()

    def _api_stats(self):
        conn = get_db()
        total = conn.execute("SELECT COUNT(*) as n FROM experiments").fetchone()["n"]
        done = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE status='done'").fetchone()["n"]
        failed = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE status='failed'").fetchone()["n"]
        running = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE status='running'").fetchone()["n"]
        avg_dur = conn.execute("SELECT AVG(duration_s) as v FROM experiments WHERE duration_s IS NOT NULL").fetchone()["v"]
        longest = conn.execute("SELECT MAX(duration_s) as v FROM experiments WHERE duration_s IS NOT NULL").fetchone()["v"]
        most_recent = conn.execute("SELECT created_at FROM experiments ORDER BY created_at DESC LIMIT 1").fetchone()
        # Count unique tags
        tag_rows = conn.execute("SELECT tags FROM experiments WHERE tags IS NOT NULL AND tags != '[]'").fetchall()
        all_tags = set()
        for r in tag_rows:
            try:
                for t in json.loads(r["tags"] or "[]"):
                    all_tags.add(t)
            except Exception:
                pass
        # Count artifacts
        try:
            total_artifacts = conn.execute("SELECT COUNT(*) as n FROM artifacts").fetchone()["n"]
        except Exception:
            total_artifacts = 0
        # Count unique branches
        unique_branches = conn.execute("SELECT COUNT(DISTINCT git_branch) as n FROM experiments WHERE git_branch IS NOT NULL AND git_branch != ''").fetchone()["n"]
        return {
            "total": total,
            "done": done,
            "failed": failed,
            "running": running,
            "success_rate": round(done / total * 100, 1) if total else 0,
            "avg_duration_s": round(avg_dur or 0, 1),
            "longest_run_s": round(longest or 0, 1),
            "most_recent": most_recent["created_at"] if most_recent else None,
            "unique_tags": len(all_tags),
            "total_artifacts": total_artifacts,
            "unique_branches": unique_branches,
        }

    def _api_experiments(self, qs):
        conn = get_db()
        limit = int(qs.get("limit", 50))
        status = qs.get("status", "")
        where = "WHERE status=?" if status else ""
        params = (status, limit) if status else (limit,)
        query = f"""
            SELECT id, project, name, status, created_at, duration_s,
                   git_branch, git_commit, tags, notes, output_dir
            FROM experiments {where}
            ORDER BY created_at DESC LIMIT ?
        """
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            # Get last metrics
            metrics = conn.execute("""
                SELECT key, value FROM metrics WHERE exp_id=?
                GROUP BY key HAVING MAX(COALESCE(step, 0))
            """, (r["id"],)).fetchall()
            # Get params
            ps = conn.execute("SELECT key, value FROM params WHERE exp_id=?",
                              (r["id"],)).fetchall()
            result.append({
                "id": r["id"],
                "name": r["name"],
                "status": r["status"],
                "created_at": r["created_at"],
                "duration_s": r["duration_s"],
                "git_branch": r["git_branch"],
                "git_commit": r["git_commit"],
                "tags": json.loads(r["tags"] or "[]"),
                "notes": r["notes"] or "",
                "output_dir": r["output_dir"] or "",
                "metrics": {m["key"]: m["value"] for m in metrics},
                "params": {p["key"]: json.loads(p["value"]) for p in ps},
            })
        return result

    def _api_experiment(self, exp_id):
        conn = get_db()
        exp = conn.execute("SELECT * FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
        if not exp:
            return {"error": "not found"}
        params = conn.execute("SELECT key, value FROM params WHERE exp_id=? ORDER BY key",
                              (exp["id"],)).fetchall()
        metrics = conn.execute("""
            SELECT key,
                   MIN(value) as min_v, MAX(value) as max_v, COUNT(*) as n,
                   (SELECT value FROM metrics m2 WHERE m2.exp_id=metrics.exp_id
                    AND m2.key=metrics.key ORDER BY COALESCE(step,0) DESC LIMIT 1) as last_v
            FROM metrics WHERE exp_id=? GROUP BY key ORDER BY key
        """, (exp["id"],)).fetchall()
        artifacts = conn.execute("SELECT label, path, created_at FROM artifacts WHERE exp_id=?",
                                 (exp["id"],)).fetchall()
        return {
            "id": exp["id"],
            "name": exp["name"],
            "project": exp["project"],
            "status": exp["status"],
            "created_at": exp["created_at"],
            "updated_at": exp["updated_at"],
            "duration_s": exp["duration_s"],
            "script": exp["script"],
            "command": exp["command"],
            "git_branch": exp["git_branch"],
            "git_commit": exp["git_commit"],
            "diff_lines": len((exp["git_diff"] or "").splitlines()),
            "hostname": exp["hostname"],
            "python_ver": exp["python_ver"],
            "notes": exp["notes"],
            "tags": json.loads(exp["tags"] or "[]"),
            "output_dir": exp["output_dir"] or "",
            "params": {p["key"]: json.loads(p["value"]) for p in params},
            "metrics": [{
                "key": m["key"], "last": m["last_v"],
                "min": m["min_v"], "max": m["max_v"], "n": m["n"]
            } for m in metrics],
            "artifacts": [{"label": a["label"], "path": a["path"]} for a in artifacts],
        }

    def _api_metrics(self, exp_id):
        conn = get_db()
        exp = conn.execute("SELECT id FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
        if not exp:
            return {"error": "not found"}
        rows = conn.execute("""
            SELECT key, value, step, ts FROM metrics
            WHERE exp_id=? ORDER BY key, COALESCE(step, 0)
        """, (exp["id"],)).fetchall()
        by_key = {}
        for r in rows:
            by_key.setdefault(r["key"], []).append({
                "value": r["value"], "step": r["step"], "ts": r["ts"]
            })
        return by_key

    def _api_diff(self, exp_id):
        conn = get_db()
        exp = conn.execute("SELECT git_diff, git_branch, git_commit FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
        if not exp:
            return {"error": "not found"}
        return {
            "diff": exp["git_diff"] or "",
            "branch": exp["git_branch"],
            "commit": exp["git_commit"],
        }

    def _api_compare(self, qs):
        id1, id2 = qs.get("id1", ""), qs.get("id2", "")
        if not id1 or not id2:
            return {"error": "provide id1 and id2"}
        return {
            "exp1": self._api_experiment(id1),
            "exp2": self._api_experiment(id2),
        }

    def _api_add_note(self, exp_id, body):
        conn = get_db()
        exp = self._find_exp(exp_id, "id, notes")
        if not exp:
            return {"error": "not found"}
        text = body.get("note", "").strip()
        if not text:
            return {"error": "empty note"}
        existing = exp["notes"] or ""
        new_notes = (existing + "\n" + text).strip() if existing else text
        conn.execute("UPDATE experiments SET notes=?, updated_at=? WHERE id=?",
                     (new_notes, datetime.now(timezone.utc).isoformat(), exp["id"]))
        conn.commit()
        return {"ok": True, "notes": new_notes}

    def _api_add_tag(self, exp_id, body):
        conn = get_db()
        exp = self._find_exp(exp_id, "id, tags")
        if not exp:
            return {"error": "not found"}
        tag = body.get("tag", "").strip()
        if not tag:
            return {"error": "empty tag"}
        tags = json.loads(exp["tags"] or "[]")
        if tag not in tags:
            tags.append(tag)
        conn.execute("UPDATE experiments SET tags=?, updated_at=? WHERE id=?",
                     (json.dumps(tags), datetime.now(timezone.utc).isoformat(), exp["id"]))
        conn.commit()
        return {"ok": True, "tags": tags}

    def _api_rename(self, exp_id, body):
        conn = get_db()
        exp = self._find_exp(exp_id, "id, name")
        if not exp:
            return {"error": "not found"}
        new_name = body.get("name", "").strip()
        if not new_name:
            return {"error": "empty name"}
        old_name = exp["name"]
        conn.execute("UPDATE experiments SET name=?, updated_at=? WHERE id=?",
                     (new_name, datetime.now(timezone.utc).isoformat(), exp["id"]))
        from exptrack.core.db import rename_output_folder
        rename_output_folder(conn, exp["id"], old_name, new_name)
        conn.commit()
        return {"ok": True, "name": new_name}

    def _api_delete(self, exp_id):
        conn = get_db()
        exp = self._find_exp(exp_id)
        if not exp:
            return {"error": "not found"}
        _delete_exp(conn, exp["id"])
        conn.commit()
        return {"ok": True}


    def _api_finish(self, exp_id):
        """Manually mark an experiment as done."""
        conn = get_db()
        exp = conn.execute(
            "SELECT id, status, created_at FROM experiments WHERE id LIKE ?",
            (exp_id + "%",)
        ).fetchone()
        if not exp:
            return {"error": "not found"}
        if exp["status"] == "done":
            return {"ok": True, "status": "done", "message": "already done"}
        now = datetime.now(timezone.utc).isoformat()
        duration = (datetime.fromisoformat(now) -
                    datetime.fromisoformat(exp["created_at"])).total_seconds()
        conn.execute("""
            UPDATE experiments SET status='done', updated_at=?, duration_s=? WHERE id=?
        """, (now, duration, exp["id"]))
        conn.commit()
        return {"ok": True, "status": "done", "duration_s": duration}

    def _api_add_artifact(self, exp_id, body):
        conn = get_db()
        exp = self._find_exp(exp_id)
        if not exp:
            return {"error": "not found"}
        label = body.get("label", "").strip()
        path = body.get("path", "").strip()
        if not label and not path:
            return {"error": "provide label or path"}
        if not label:
            label = Path(path).name
        ts = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO artifacts (exp_id, label, path, created_at) VALUES (?,?,?,?)",
            (exp["id"], label, path, ts)
        )
        conn.commit()
        return {"ok": True, "label": label, "path": path}

    def _api_delete_tag(self, exp_id, body):
        conn = get_db()
        exp = self._find_exp(exp_id, "id, tags")
        if not exp:
            return {"error": "not found"}
        tag = body.get("tag", "").strip()
        if not tag:
            return {"error": "empty tag"}
        tags = json.loads(exp["tags"] or "[]")
        tags = [t for t in tags if t != tag]
        conn.execute("UPDATE experiments SET tags=?, updated_at=? WHERE id=?",
                     (json.dumps(tags), datetime.now(timezone.utc).isoformat(), exp["id"]))
        conn.commit()
        return {"ok": True, "tags": tags}

    def _api_edit_tag(self, exp_id, body):
        conn = get_db()
        exp = self._find_exp(exp_id, "id, tags")
        if not exp:
            return {"error": "not found"}
        old_tag = body.get("old_tag", "").strip()
        new_tag = body.get("new_tag", "").strip()
        if not old_tag or not new_tag:
            return {"error": "provide old_tag and new_tag"}
        tags = json.loads(exp["tags"] or "[]")
        tags = [new_tag if t == old_tag else t for t in tags]
        conn.execute("UPDATE experiments SET tags=?, updated_at=? WHERE id=?",
                     (json.dumps(tags), datetime.now(timezone.utc).isoformat(), exp["id"]))
        conn.commit()
        return {"ok": True, "tags": tags}

    def _api_edit_notes(self, exp_id, body):
        conn = get_db()
        exp = self._find_exp(exp_id)
        if not exp:
            return {"error": "not found"}
        notes = body.get("notes", "")
        conn.execute("UPDATE experiments SET notes=?, updated_at=? WHERE id=?",
                     (notes, datetime.now(timezone.utc).isoformat(), exp["id"]))
        conn.commit()
        return {"ok": True, "notes": notes}

    def _api_delete_artifact(self, exp_id, body):
        conn = get_db()
        exp = self._find_exp(exp_id)
        if not exp:
            return {"error": "not found"}
        label = body.get("label", "")
        path = body.get("path", "")
        if not label and not path:
            return {"error": "provide label or path"}
        if label and path:
            conn.execute("DELETE FROM artifacts WHERE exp_id=? AND label=? AND path=?",
                         (exp["id"], label, path))
        elif label:
            conn.execute("DELETE FROM artifacts WHERE exp_id=? AND label=?",
                         (exp["id"], label))
        else:
            conn.execute("DELETE FROM artifacts WHERE exp_id=? AND path=?",
                         (exp["id"], path))
        conn.commit()
        return {"ok": True}

    def _api_edit_artifact(self, exp_id, body):
        conn = get_db()
        exp = self._find_exp(exp_id)
        if not exp:
            return {"error": "not found"}
        old_label = body.get("old_label", "")
        old_path = body.get("old_path", "")
        new_label = body.get("new_label", "")
        new_path = body.get("new_path", "")
        if not old_label and not old_path:
            return {"error": "provide old_label or old_path"}
        if old_label and old_path:
            conn.execute("UPDATE artifacts SET label=?, path=? WHERE exp_id=? AND label=? AND path=?",
                         (new_label or old_label, new_path or old_path, exp["id"], old_label, old_path))
        elif old_label:
            conn.execute("UPDATE artifacts SET label=?, path=? WHERE exp_id=? AND label=?",
                         (new_label or old_label, new_path or old_path, exp["id"], old_label))
        else:
            conn.execute("UPDATE artifacts SET label=?, path=? WHERE exp_id=? AND path=?",
                         (new_label or old_label, new_path or old_path, exp["id"], old_path))
        conn.commit()
        return {"ok": True}

    def _api_bulk_delete(self, body):
        ids = body.get("ids", [])
        if not ids:
            return {"error": "no ids provided"}
        conn = get_db()
        deleted = 0
        for exp_id in ids:
            exp = self._find_exp(exp_id)
            if exp:
                _delete_exp(conn, exp["id"])
                deleted += 1
        conn.commit()
        return {"ok": True, "deleted": deleted}

    def _api_bulk_export(self, body):
        ids = body.get("ids", [])
        fmt = body.get("format", "json")
        if not ids:
            return {"error": "no ids provided"}
        results = []
        for exp_id in ids:
            data = self._api_export(exp_id, {"format": fmt})
            if not data.get("error"):
                results.append(data)
        return results

    def _api_all_tags(self):
        conn = get_db()
        rows = conn.execute("SELECT tags FROM experiments WHERE tags IS NOT NULL AND tags != '[]'").fetchall()
        all_tags = {}
        for r in rows:
            try:
                for t in json.loads(r["tags"] or "[]"):
                    all_tags[t] = all_tags.get(t, 0) + 1
            except Exception:
                pass
        return {"tags": [{"name": t, "count": c} for t, c in sorted(all_tags.items(), key=lambda x: -x[1])]}

    def _api_get_timezone(self):
        from exptrack import config as cfg
        conf = cfg.load()
        return {"timezone": conf.get("timezone", "")}

    _VALID_TIMEZONES = {
        "", "UTC", "America/New_York", "America/Chicago", "America/Denver",
        "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Europe/Paris",
        "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata", "Australia/Sydney",
    }

    def _api_set_timezone(self, body):
        from exptrack import config as cfg
        tz = body.get("timezone", "").strip()
        if tz not in self._VALID_TIMEZONES:
            return {"error": "invalid timezone"}
        conf = cfg.load()
        conf["timezone"] = tz
        cfg.save(conf)
        return {"ok": True, "timezone": tz}

    def _api_timeline(self, exp_id, qs):
        conn = get_db()
        exp = conn.execute("SELECT id FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
        if not exp:
            return {"error": "not found"}
        event_type = qs.get("type", "")
        where = "WHERE exp_id=?"
        params = [exp["id"]]
        if event_type:
            where += " AND event_type=?"
            params.append(event_type)
        rows = conn.execute(
            f"""SELECT seq, event_type, cell_hash, cell_pos, key, value,
                       prev_value, source_diff, ts
                FROM timeline {where} ORDER BY seq""",
            params
        ).fetchall()
        return [{
            "seq": r["seq"],
            "event_type": r["event_type"],
            "cell_hash": r["cell_hash"],
            "cell_pos": r["cell_pos"],
            "key": r["key"],
            "value": json.loads(r["value"]) if r["value"] else None,
            "prev_value": json.loads(r["prev_value"]) if r["prev_value"] else None,
            "source_diff": json.loads(r["source_diff"]) if r["source_diff"] else None,
            "ts": r["ts"],
        } for r in rows]

    def _api_vars_at(self, exp_id, qs):
        """Get variable state at a specific timeline seq point."""
        conn = get_db()
        exp = conn.execute("SELECT id FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
        if not exp:
            return {"error": "not found"}
        seq = int(qs.get("seq", 999999))
        rows = conn.execute("""
            SELECT key, value FROM timeline
            WHERE exp_id=? AND event_type='var_set' AND seq <= ?
            ORDER BY seq DESC
        """, (exp["id"], seq)).fetchall()
        ctx = {}
        for r in rows:
            if r["key"] not in ctx:
                try:
                    ctx[r["key"]] = json.loads(r["value"]) if r["value"] else None
                except Exception:
                    ctx[r["key"]] = r["value"]
        return ctx


    def _api_cell_source(self, cell_hash):
        """Return full source code for a cell by its content hash."""
        conn = get_db()
        row = conn.execute(
            "SELECT source, parent_hash, notebook, created_at FROM cell_lineage WHERE cell_hash=?",
            (cell_hash,)
        ).fetchone()
        if not row:
            return {"error": "cell not found", "cell_hash": cell_hash}
        # Also get parent source if available
        parent_source = None
        if row["parent_hash"]:
            parent = conn.execute(
                "SELECT source FROM cell_lineage WHERE cell_hash=?",
                (row["parent_hash"],)
            ).fetchone()
            if parent:
                parent_source = parent["source"]
        return {
            "cell_hash": cell_hash,
            "source": row["source"],
            "parent_hash": row["parent_hash"],
            "parent_source": parent_source,
            "notebook": row["notebook"],
            "created_at": row["created_at"],
        }

    def _api_export(self, exp_id, qs):
        """Export experiment data as structured JSON or markdown for workflow integration."""
        conn = get_db()
        exp = conn.execute("SELECT * FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
        if not exp:
            return {"error": "not found"}
        fmt = qs.get("format", "json")
        params = conn.execute("SELECT key, value FROM params WHERE exp_id=? ORDER BY key",
                              (exp["id"],)).fetchall()
        metrics = conn.execute("""
            SELECT key, value, step, ts FROM metrics WHERE exp_id=?
            ORDER BY key, COALESCE(step, 0)
        """, (exp["id"],)).fetchall()
        artifacts = conn.execute("SELECT label, path, created_at FROM artifacts WHERE exp_id=?",
                                 (exp["id"],)).fetchall()
        timeline = conn.execute("""
            SELECT seq, event_type, key, value, ts FROM timeline WHERE exp_id=?
            ORDER BY seq
        """, (exp["id"],)).fetchall()

        # Separate internal params into categories
        all_params = {p["key"]: json.loads(p["value"]) for p in params}
        user_params = {k: v for k, v in all_params.items() if not k.startswith("_")}
        variables = {k[5:]: v for k, v in all_params.items() if k.startswith("_var/")}
        code_changes = {k[13:]: v for k, v in all_params.items() if k.startswith("_code_change/")}

        data = {
            "id": exp["id"],
            "name": exp["name"],
            "project": exp["project"],
            "status": exp["status"],
            "created_at": exp["created_at"],
            "duration_s": exp["duration_s"],
            "script": exp["script"],
            "command": exp["command"],
            "python_ver": exp["python_ver"],
            "git_branch": exp["git_branch"],
            "git_commit": exp["git_commit"],
            "hostname": exp["hostname"],
            "tags": json.loads(exp["tags"] or "[]"),
            "notes": exp["notes"],
            "output_dir": exp["output_dir"] or "",
            "params": user_params,
            "variables": variables,
            "code_changes": code_changes,
            "metrics_series": {},
            "artifacts": [{"label": a["label"], "path": a["path"]} for a in artifacts],
            "timeline_summary": {
                "total_events": len(timeline),
                "cell_executions": sum(1 for t in timeline if t["event_type"] == "cell_exec"),
                "variable_sets": sum(1 for t in timeline if t["event_type"] == "var_set"),
                "artifact_events": sum(1 for t in timeline if t["event_type"] == "artifact"),
            },
        }
        for m in metrics:
            data["metrics_series"].setdefault(m["key"], []).append({
                "value": m["value"], "step": m["step"]
            })
        if fmt == "markdown":
            md = self._export_markdown(data)
            return {"markdown": md, "data": data}
        return data

    def _export_markdown(self, data):
        """Generate a markdown summary of an experiment."""
        lines = [
            f"# {data['name']}",
            f"",
            f"**ID:** {data['id']}  ",
            f"**Status:** {data['status']}  ",
            f"**Created:** {data['created_at']}  ",
            f"**Duration:** {data['duration_s']}s  " if data.get('duration_s') else "",
            f"**Script:** `{data['script']}`  " if data.get('script') else "",
            f"**Command:** `{data['command']}`  " if data.get('command') else "",
            f"**Python:** {data['python_ver']}  " if data.get('python_ver') else "",
            f"**Git:** {data['git_branch']} @ {data['git_commit']}  " if data.get('git_branch') else "",
            f"**Hostname:** {data['hostname']}  " if data.get('hostname') else "",
            f"**Tags:** {', '.join(data['tags'])}  " if data.get('tags') else "",
            f"",
        ]
        if data.get("notes"):
            lines += [f"## Notes", f"", data["notes"], f""]
        # Params
        if data.get("params"):
            lines += [f"## Parameters", f"", "| Key | Value |", "| --- | --- |"]
            for k, v in data["params"].items():
                lines.append(f"| {k} | {json.dumps(v)} |")
            lines.append("")
        # Variables
        if data.get("variables"):
            lines += [f"## Variables", f"", "| Name | Value |", "| --- | --- |"]
            for k, v in data["variables"].items():
                lines.append(f"| {k} | {json.dumps(v)} |")
            lines.append("")
        # Metrics
        if data.get("metrics_series"):
            lines += [f"## Metrics", f"", "| Key | Last | Steps |", "| --- | --- | --- |"]
            for k, pts in data["metrics_series"].items():
                last = pts[-1]["value"] if pts else "--"
                lines.append(f"| {k} | {last} | {len(pts)} |")
            lines.append("")
        # Artifacts
        if data.get("artifacts"):
            lines += [f"## Artifacts", f""]
            for a in data["artifacts"]:
                lines.append(f"- **{a['label']}**: `{a['path']}`")
            lines.append("")
        # Code Changes
        if data.get("code_changes"):
            lines += [f"## Code Changes", f""]
            for name, diff in data["code_changes"].items():
                lines.append(f"### {name}")
                lines.append("```diff")
                lines.append(str(diff))
                lines.append("```")
                lines.append("")
        # Timeline summary
        ts = data.get("timeline_summary", {})
        if ts.get("total_events"):
            lines += [
                f"## Timeline Summary",
                f"",
                f"- Total events: {ts['total_events']}",
                f"- Cell executions: {ts['cell_executions']}",
                f"- Variable changes: {ts['variable_sets']}",
                f"- Artifacts saved: {ts['artifact_events']}",
            ]
        return "\n".join(lines)
