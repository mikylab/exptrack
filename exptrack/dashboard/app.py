"""
exptrack/dashboard/app.py — Web dashboard (stdlib only, no Flask needed)

Serves a single-page app with:
  - Stats cards (total runs, success rate, etc.)
  - Experiment list with status filters
  - Experiment detail with metric plots (Chart.js from CDN)
  - Git diff viewer
  - Compare view

Usage: python -m exptrack.dashboard.app [port]
       exptrack ui [--port 7331]
"""
import json
import os
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Add parent to path so we can import exptrack
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def get_db():
    from exptrack.core import get_db as _get_db
    return _get_db()


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
                   git_branch, git_commit, tags, notes
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
        exp = conn.execute("SELECT id, notes FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
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
        exp = conn.execute("SELECT id, tags FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
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
        exp = conn.execute("SELECT id FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
        if not exp:
            return {"error": "not found"}
        new_name = body.get("name", "").strip()
        if not new_name:
            return {"error": "empty name"}
        conn.execute("UPDATE experiments SET name=?, updated_at=? WHERE id=?",
                     (new_name, datetime.now(timezone.utc).isoformat(), exp["id"]))
        conn.commit()
        return {"ok": True, "name": new_name}

    def _api_delete(self, exp_id):
        conn = get_db()
        exp = conn.execute("SELECT id FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
        if not exp:
            return {"error": "not found"}
        eid = exp["id"]
        conn.execute("DELETE FROM metrics WHERE exp_id=?", (eid,))
        conn.execute("DELETE FROM params WHERE exp_id=?", (eid,))
        conn.execute("DELETE FROM artifacts WHERE exp_id=?", (eid,))
        conn.execute("DELETE FROM timeline WHERE exp_id=?", (eid,))
        conn.execute("DELETE FROM experiments WHERE id=?", (eid,))
        conn.commit()
        return {"ok": True}


    def _api_add_artifact(self, exp_id, body):
        conn = get_db()
        exp = conn.execute("SELECT id FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
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
        exp = conn.execute("SELECT id, tags FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
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
        exp = conn.execute("SELECT id, tags FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
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
        exp = conn.execute("SELECT id FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
        if not exp:
            return {"error": "not found"}
        notes = body.get("notes", "")
        conn.execute("UPDATE experiments SET notes=?, updated_at=? WHERE id=?",
                     (notes, datetime.now(timezone.utc).isoformat(), exp["id"]))
        conn.commit()
        return {"ok": True, "notes": notes}

    def _api_delete_artifact(self, exp_id, body):
        conn = get_db()
        exp = conn.execute("SELECT id FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
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
        exp = conn.execute("SELECT id FROM experiments WHERE id LIKE ?",
                           (exp_id + "%",)).fetchone()
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
            exp = conn.execute("SELECT id FROM experiments WHERE id LIKE ?",
                               (exp_id + "%",)).fetchone()
            if exp:
                eid = exp["id"]
                conn.execute("DELETE FROM metrics WHERE exp_id=?", (eid,))
                conn.execute("DELETE FROM params WHERE exp_id=?", (eid,))
                conn.execute("DELETE FROM artifacts WHERE exp_id=?", (eid,))
                conn.execute("DELETE FROM timeline WHERE exp_id=?", (eid,))
                conn.execute("DELETE FROM experiments WHERE id=?", (eid,))
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

    def _api_set_timezone(self, body):
        from exptrack import config as cfg
        tz = body.get("timezone", "").strip()
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


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>exptrack</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --bg: #faf9f7; --fg: #1a1a1a; --muted: #777; --border: #d0d0d0;
    --green: #2d7d46; --red: #c0392b; --yellow: #b8860b; --blue: #2c5aa0;
    --purple: #7c3aed; --card-bg: #fff; --code-bg: #f5f3f0;
    --tl-cell: #2c5aa0; --tl-var: #7c3aed; --tl-artifact: #2d7d46;
    --tl-metric: #d4820f; --tl-obs: #999;
  }
  body.dark {
    --bg: #1a1a1a; --fg: #e0e0e0; --muted: #999; --border: #444;
    --green: #4caf50; --red: #ef5350; --yellow: #ffc107; --blue: #5c9ce6;
    --purple: #b388ff; --card-bg: #252525; --code-bg: #2d2d2d;
    --tl-cell: #5c9ce6; --tl-var: #b388ff; --tl-artifact: #4caf50;
    --tl-metric: #ffc107; --tl-obs: #777;
  }
  body {
    font-family: 'IBM Plex Mono', monospace;
    background: var(--bg); color: var(--fg);
    margin: 0; padding: 0;
    font-size: 15px; line-height: 1.6;
    overflow: hidden; height: 100vh;
  }
  /* Header bar */
  .header { display: flex; justify-content: space-between; align-items: center; padding: 10px 24px; border-bottom: 1px solid var(--border); background: var(--card-bg); flex-shrink: 0; height: 64px; }
  .header h1 { font-size: 24px; font-weight: 600; letter-spacing: -0.5px; margin: 0; cursor: pointer; }
  .header h1:hover { color: var(--blue); }
  .header-actions { display: flex; gap: 10px; align-items: center; }
  /* IDE layout */
  #app-layout { display: flex; height: calc(100vh - 64px); overflow: hidden; }
  #exp-sidebar {
    width: 280px; min-width: 280px; border-right: 1px solid var(--border);
    display: flex; flex-direction: column; overflow: hidden;
    transition: width 0.2s ease, min-width 0.2s ease; flex-shrink: 0;
    background: var(--card-bg);
  }
  #exp-sidebar.collapsed { width: 44px; min-width: 44px; }
  #exp-sidebar.collapsed .sidebar-content { display: none; }
  #exp-sidebar.collapsed .collapse-strip { display: flex; }
  .sidebar-content { display: flex; flex-direction: column; height: 100%; overflow: hidden; }
  .sidebar-header { display: flex; gap: 6px; padding: 10px 12px 6px; align-items: center; }
  .sidebar-header input { flex: 1; font-family: inherit; font-size: 13px; border: 1px solid var(--border); padding: 5px 8px; border-radius: 3px; background: var(--bg); min-width: 0; }
  .collapse-btn { font-family: inherit; font-size: 16px; background: none; border: 1px solid var(--border); padding: 2px 8px; cursor: pointer; border-radius: 3px; color: var(--muted); flex-shrink: 0; }
  .collapse-btn:hover { background: var(--code-bg); color: var(--fg); }
  .collapse-strip { display: none; flex-direction: column; align-items: center; padding-top: 12px; cursor: pointer; width: 44px; height: 100%; }
  .collapse-strip:hover { background: var(--code-bg); }
  .status-chips { display: flex; gap: 4px; padding: 4px 12px 8px; flex-wrap: wrap; }
  .status-chips button { font-family: inherit; font-size: 11px; background: var(--bg); border: 1px solid var(--border); padding: 2px 8px; cursor: pointer; border-radius: 3px; color: var(--muted); }
  .status-chips button:hover { background: var(--code-bg); color: var(--fg); }
  .status-chips button.active { background: var(--fg); color: var(--bg); }
  #exp-list { flex: 1; overflow-y: auto; padding: 0 8px 8px; }
  .exp-card { padding: 8px 10px; border-radius: 4px; cursor: pointer; margin-bottom: 2px; border: 1px solid transparent; }
  .exp-card:hover { background: var(--code-bg); }
  .exp-card.active { background: rgba(44,90,160,0.08); border-color: var(--blue); }
  .exp-card-row1 { display: flex; align-items: center; gap: 6px; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .status-dot.status-done { background: var(--green); }
  .status-dot.status-failed { background: var(--red); }
  .status-dot.status-running { background: var(--yellow); }
  .exp-card-name { font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .exp-card-meta { font-size: 11px; color: var(--muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .exp-card-metrics { font-size: 11px; color: var(--blue); margin-top: 1px; }
  .exp-card-tags { font-size: 10px; color: var(--muted); margin-top: 1px; }
  .exp-card-tags .tag { font-size: 10px; padding: 0 4px; margin-left: 0; margin-right: 3px; }
  .exp-card-cb { margin-right: 4px; cursor: pointer; }
  .sidebar-actions-bar { padding: 8px 12px; border-top: 1px solid var(--border); background: var(--code-bg); display: flex; flex-direction: column; gap: 4px; }
  .sidebar-actions-bar button { font-family: inherit; font-size: 12px; border: none; padding: 5px 12px; cursor: pointer; border-radius: 3px; width: 100%; }
  .sidebar-actions-bar button.primary { background: var(--blue); color: #fff; }
  .sidebar-actions-bar button.export-btn { background: var(--card-bg); border: 1px solid var(--border); color: var(--fg); }
  .sidebar-actions-bar button.export-btn:hover { background: var(--border); }
  .sidebar-actions-bar button.danger { background: var(--card-bg); border: 1px solid var(--red); color: var(--red); }
  .sidebar-actions-bar button.danger:hover { background: var(--red); color: #fff; }
  .sidebar-actions-bar .action-count { font-size: 11px; color: var(--muted); text-align: center; }
  #main-content { flex: 1; overflow-y: auto; min-width: 0; padding: 20px 28px; }
  /* Detail summary bar */
  .detail-summary { display: flex; gap: 16px; flex-wrap: wrap; padding: 10px 16px; background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px; margin-bottom: 16px; align-items: center; }
  .detail-summary .sum-item { font-size: 13px; color: var(--muted); }
  .detail-summary .sum-item strong { color: var(--fg); }
  .detail-summary .sum-sep { color: var(--border); }
  /* Two-column detail grid */
  .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .detail-grid > div { }
  .detail-grid-full { grid-column: 1 / -1; }
  @media (max-width: 900px) {
    .detail-grid { grid-template-columns: 1fr; }
    #exp-sidebar { display: none; }
  }
  .help-btn {
    font-family: inherit; font-size: 15px; background: var(--code-bg);
    border: 1px solid var(--border); padding: 8px 16px; cursor: pointer;
    border-radius: 4px; color: var(--muted);
  }
  .help-btn:hover { background: var(--border); color: var(--fg); }
  .theme-btn { font-family: inherit; font-size: 20px; background: var(--code-bg); border: 1px solid var(--border); padding: 6px 14px; cursor: pointer; border-radius: 4px; color: var(--muted); line-height: 1; }
  .theme-btn:hover { background: var(--border); color: var(--fg); }
  h2 { font-size: 16px; font-weight: 600; margin: 24px 0 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); }
  h2 .help-icon { font-size: 13px; cursor: help; color: var(--blue); margin-left: 6px; font-weight: normal; text-transform: none; letter-spacing: 0; }
  /* Stats cards */
  .stats { margin-bottom: 20px; }
  .stats-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 6px; font-weight: 600; }
  .stats-row { display: grid; gap: 12px; margin-bottom: 12px; }
  .stats-row.runs { grid-template-columns: repeat(4, 1fr); }
  .stats-row.additional { grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
  .stat {
    background: var(--card-bg); border: 1px solid var(--border);
    padding: 20px; text-align: center; border-radius: 4px;
    position: relative;
  }
  .stat .num { font-size: 34px; font-weight: 600; }
  .stat .label { color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }
  .stat .stat-hint { display: none; position: absolute; bottom: -30px; left: 50%; transform: translateX(-50%); background: var(--fg); color: var(--bg); padding: 4px 10px; border-radius: 3px; font-size: 11px; white-space: nowrap; z-index: 10; }
  .stat:hover .stat-hint { display: block; }
  /* Filters */
  .filters { margin-bottom: 18px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .filters button {
    font-family: inherit; font-size: 14px;
    background: var(--card-bg); border: 1px solid var(--border);
    padding: 6px 16px; cursor: pointer; border-radius: 3px;
  }
  .filters button:hover { background: var(--code-bg); }
  .filters button.active { background: var(--fg); color: var(--bg); }
  .filters .compare-selected {
    margin-left: auto; background: var(--blue); color: #fff; border: none;
    padding: 6px 16px; font-family: inherit; font-size: 14px; cursor: pointer;
    display: none; border-radius: 3px;
  }
  .filters .compare-selected.visible { display: inline-block; }
  .filters .search-box {
    font-family: inherit; font-size: 14px; border: 1px solid var(--border);
    padding: 6px 12px; border-radius: 3px; background: var(--card-bg); min-width: 200px;
  }
  /* Table toolbar */
  .table-toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
  .main-search-input {
    font-family: inherit; font-size: 14px; border: 1px solid var(--border);
    padding: 8px 14px; border-radius: 4px; background: var(--card-bg); min-width: 260px; color: var(--fg);
  }
  .main-search-input:focus { outline: none; border-color: var(--blue); }
  .table-actions-bar {
    display: flex; gap: 8px; align-items: center; padding: 8px 12px; margin-bottom: 8px;
    background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px;
  }
  .table-actions-bar .sel-count { font-size: 13px; color: var(--muted); margin-right: 8px; }
  .table-actions-bar button {
    font-family: inherit; font-size: 12px; border: 1px solid var(--border); padding: 5px 14px;
    cursor: pointer; border-radius: 3px; background: var(--card-bg); color: var(--fg);
  }
  .table-actions-bar button:hover { background: var(--code-bg); }
  .table-actions-bar button.danger { background: var(--red); color: #fff; border-color: var(--red); }
  .table-actions-bar button.danger:hover { opacity: 0.85; }
  .table-actions-bar button.primary { background: var(--blue); color: #fff; border-color: var(--blue); }
  .table-actions-bar button.primary:hover { opacity: 0.85; }
  /* Table */
  .cb-col { width: 36px; text-align: center; }
  .cb-col input { cursor: pointer; width: 16px; height: 16px; }
  table { width: 100%; border-collapse: collapse; background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px; }
  th { text-align: left; padding: 12px 16px; border-bottom: 2px solid var(--fg); font-size: 13px; text-transform: uppercase; letter-spacing: 1px; user-select: none; }
  th.sortable { cursor: pointer; }
  th.sortable:hover { color: var(--blue); }
  th .sort-arrow { font-size: 10px; margin-left: 4px; opacity: 0.3; }
  th.sort-active .sort-arrow { opacity: 1; color: var(--blue); }
  td { padding: 10px 16px; border-bottom: 1px solid var(--border); font-size: 14px; }
  tr:hover { background: var(--code-bg); }
  tr.selected-row { background: rgba(44,90,160,0.08); }
  .status-done { color: var(--green); font-weight: 500; }
  .status-failed { color: var(--red); font-weight: 500; }
  .status-running { color: var(--yellow); font-weight: 500; }
  .tag { background: var(--code-bg); padding: 2px 8px; font-size: 12px; margin-left: 6px; border-radius: 3px; }
  .exp-metrics-preview { font-size: 12px; color: var(--muted); margin-top: 2px; }
  /* Detail panel */
  .detail { background: var(--card-bg); border: 1px solid var(--border); padding: 28px; margin-top: 20px; border-radius: 4px; }
  .detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; gap: 12px; flex-wrap: wrap; }
  .detail-export-bar { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
  .detail-header h2 { margin: 0; font-size: 18px; color: var(--fg); text-transform: none; letter-spacing: 0; }
  .detail-actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .detail-actions button, .action-btn {
    font-family: inherit; font-size: 13px;
    background: var(--code-bg); border: 1px solid var(--border);
    padding: 5px 14px; cursor: pointer; border-radius: 3px;
  }
  .detail-actions button:hover, .action-btn:hover { background: var(--border); }
  .action-btn.danger { color: var(--red); border-color: var(--red); }
  .action-btn.danger:hover { background: var(--red); color: #fff; }
  .action-btn.primary { background: var(--blue); color: #fff; border-color: var(--blue); }
  .action-btn.primary:hover { opacity: 0.9; }
  .close-btn { cursor: pointer; font-size: 20px; background: none; border: none; font-family: inherit; padding: 4px 8px; }
  .close-btn:hover { background: var(--code-bg); border-radius: 3px; }
  .info-grid { display: grid; grid-template-columns: 150px 1fr; gap: 6px 20px; margin-bottom: 20px; font-size: 14px; }
  .info-grid .label { color: var(--muted); font-weight: 500; }
  .params-table, .metrics-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
  .params-table td, .metrics-table td { padding: 6px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
  .params-table th, .metrics-table th { padding: 8px 12px; font-size: 13px; text-align: left; border-bottom: 2px solid var(--border); }
  /* Diff view */
  .diff-view {
    background: var(--code-bg); padding: 16px; font-size: 13px;
    overflow-x: auto; max-height: 500px; overflow-y: auto;
    white-space: pre; border: 1px solid var(--border); border-radius: 4px;
  }
  .diff-add { color: var(--green); }
  .diff-del { color: var(--red); }
  .diff-hunk { color: var(--blue); font-weight: 600; }
  /* Code changes */
  .code-changes { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; margin-bottom: 20px; font-size: 13px; border-radius: 4px; }
  .code-changes .change-item { margin-bottom: 10px; }
  .code-changes .change-label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .code-changes .change-diff { white-space: pre-wrap; }
  /* Variables */
  .var-changes { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; margin-bottom: 20px; font-size: 13px; border-radius: 4px; }
  .var-changes table { width: 100%; table-layout: fixed; }
  .var-changes td { padding: 4px 8px; border-bottom: 1px solid var(--border); vertical-align: top; word-break: break-word; }
  .var-changes td:first-child { width: 30%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .var-changes .var-name { color: var(--blue); font-weight: 500; }
  .var-changes .var-type { color: var(--muted); font-size: 12px; }
  .var-section-title { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin: 10px 0 6px; }
  .chart-container { max-width: 700px; margin: 20px 0; }
  /* Artifacts */
  .artifact-row { display: flex; align-items: center; gap: 8px; }
  .artifact-type-badge { font-size: 11px; padding: 1px 6px; border-radius: 3px; background: var(--code-bg); color: var(--muted); }
  .artifact-type-badge.img { background: #d4edda; color: #155724; }
  .artifact-type-badge.model { background: #cce5ff; color: #004085; }
  .artifact-type-badge.data { background: #fff3cd; color: #856404; }
  /* Timeline styles */
  .timeline { padding: 0; margin: 16px 0; }
  .tl-event { display: flex; gap: 12px; padding: 8px 12px; border-left: 3px solid var(--border); margin-left: 8px; font-size: 13px; position: relative; }
  .tl-event:hover { background: var(--code-bg); }
  .tl-event.tl-cell_exec { border-left-color: var(--blue); }
  .tl-event.tl-var_set { border-left-color: var(--purple); }
  .tl-event.tl-artifact { border-left-color: var(--green); }
  .tl-event.tl-metric { border-left-color: var(--yellow); }
  .tl-event.tl-observational { border-left-color: var(--border); opacity: 0.7; }
  .tl-seq { color: var(--muted); min-width: 40px; font-size: 12px; }
  .tl-icon { min-width: 20px; text-align: center; font-weight: 600; }
  .tl-body { flex: 1; }
  .tl-code-preview { color: var(--muted); font-size: 12px; margin-top: 2px; white-space: pre-wrap; }
  .tl-diff { margin-top: 4px; font-size: 12px; }
  .tl-diff .diff-add { color: var(--green); }
  .tl-diff .diff-del { color: var(--red); }
  .tl-badge { display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 3px; margin-left: 6px; }
  .tl-badge-new { background: #d4edda; color: #155724; }
  .tl-badge-edited { background: #fff3cd; color: #856404; }
  .tl-badge-rerun { background: var(--code-bg); color: var(--muted); }
  .tl-badge-output { background: #cce5ff; color: #004085; }
  .tl-var-arrow { color: var(--muted); }
  .tl-context { font-size: 11px; color: var(--muted); margin-top: 3px; }
  .tl-filters { display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }
  .tl-filters button { font-family: inherit; font-size: 12px; background: var(--card-bg); border: 1px solid var(--border); padding: 3px 10px; cursor: pointer; border-radius: 3px; }
  .tl-filters button:hover { background: var(--code-bg); }
  .tl-filters button.active { background: var(--fg); color: var(--bg); }
  .tl-compare-bar { background: var(--code-bg); padding: 10px 14px; margin-bottom: 12px; border-radius: 4px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 13px; }
  .tl-compare-bar button { font-family: inherit; font-size: 12px; background: var(--blue); color: #fff; border: none; padding: 4px 12px; cursor: pointer; border-radius: 3px; }
  .tl-seq-select { cursor: pointer; }
  .tl-seq-select:hover { background: rgba(44,90,160,0.1); }
  .tl-seq-select.selected { background: rgba(44,90,160,0.15); outline: 2px solid var(--blue); }
  .within-compare { background: var(--card-bg); border: 1px solid var(--border); padding: 20px; border-radius: 4px; margin-top: 16px; }
  .within-compare h3 { font-size: 14px; margin-bottom: 12px; }
  /* Source viewer */
  .source-view { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; font-size: 13px; border-radius: 4px; white-space: pre-wrap; max-height: 500px; overflow-y: auto; margin-top: 6px; }
  .source-view .line-num { color: var(--muted); display: inline-block; min-width: 30px; text-align: right; margin-right: 12px; user-select: none; }
  .view-source-btn { font-family: inherit; font-size: 11px; padding: 1px 8px; border: 1px solid var(--border); background: var(--card-bg); cursor: pointer; border-radius: 3px; margin-left: 6px; color: var(--blue); }
  .view-source-btn:hover { background: var(--code-bg); }
  /* Compare */
  .compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  .compare-input { display: flex; gap: 10px; margin-bottom: 20px; align-items: center; flex-wrap: wrap; }
  .compare-input select, .compare-input input {
    font-family: inherit; font-size: 14px;
    border: 1px solid var(--border); padding: 6px 12px; min-width: 260px;
    background: var(--card-bg); border-radius: 3px;
  }
  .compare-input button {
    font-family: inherit; font-size: 14px;
    background: var(--fg); color: var(--bg); border: none;
    padding: 6px 16px; cursor: pointer; border-radius: 3px;
  }
  .compare-input .vs-label { font-weight: 600; color: var(--muted); }
  .differs { color: var(--yellow); font-weight: 600; }
  .only-differs-toggle { font-family: inherit; font-size: 12px; margin-left: 12px; cursor: pointer; }
  /* Tabs */
  .tabs { display: flex; gap: 0; margin-bottom: 20px; border-bottom: 2px solid var(--border); }
  .tab {
    font-family: inherit; font-size: 14px;
    background: none; border: none; padding: 10px 20px;
    cursor: pointer; text-transform: uppercase; letter-spacing: 1px;
    border-bottom: 2px solid transparent; margin-bottom: -2px;
  }
  .tab:hover { background: var(--code-bg); }
  .tab.active { border-bottom-color: var(--fg); font-weight: 600; }
  #view { min-height: 200px; }
  /* Inline forms */
  .inline-form { display: inline-flex; gap: 6px; align-items: center; margin-left: 8px; }
  .inline-form input {
    font-family: inherit; font-size: 13px; border: 1px solid var(--border);
    padding: 3px 8px; border-radius: 3px; background: var(--card-bg);
  }
  .inline-form button {
    font-family: inherit; font-size: 12px; padding: 3px 10px;
    border: 1px solid var(--border); background: var(--code-bg);
    cursor: pointer; border-radius: 3px;
  }
  .inline-form button:hover { background: var(--border); }
  .notes-display { white-space: pre-wrap; background: var(--code-bg); padding: 10px; border-radius: 4px; margin: 4px 0; font-size: 13px; }
  .tag-list { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .tag-removable { background: var(--code-bg); padding: 3px 10px; font-size: 13px; border-radius: 3px; display: inline-flex; align-items: center; gap: 4px; cursor: default; }
  .tag-removable .tag-delete { cursor: pointer; color: var(--muted); font-size: 14px; margin-left: 2px; line-height: 1; }
  .tag-removable .tag-delete:hover { color: var(--red); }
  .tag-removable .tag-edit { cursor: pointer; color: var(--muted); font-size: 11px; }
  .tag-removable .tag-edit:hover { color: var(--blue); }
  .notes-display { position: relative; }
  .notes-edit-btn { position: absolute; top: 4px; right: 4px; font-size: 11px; cursor: pointer; color: var(--muted); background: var(--card-bg); border: 1px solid var(--border); padding: 1px 6px; border-radius: 3px; }
  .notes-edit-btn:hover { color: var(--blue); border-color: var(--blue); }
  .notes-edit-area { width: 100%; font-family: inherit; font-size: 13px; border: 1px solid var(--blue); padding: 8px; border-radius: 4px; background: var(--card-bg); min-height: 80px; resize: vertical; }
  .artifact-actions { display: flex; gap: 4px; }
  .artifact-actions button { font-family: inherit; font-size: 11px; padding: 1px 6px; border: 1px solid var(--border); background: var(--card-bg); cursor: pointer; border-radius: 3px; color: var(--muted); }
  .artifact-actions button:hover { color: var(--fg); border-color: var(--fg); }
  .artifact-actions button.art-del:hover { color: var(--red); border-color: var(--red); }
  .home-btn { font-family: inherit; font-size: 13px; background: var(--code-bg); border: 1px solid var(--border); padding: 5px 12px; cursor: pointer; border-radius: 3px; color: var(--muted); }
  .home-btn:hover { background: var(--border); color: var(--fg); }
  /* Help/docs panel */
  .help-panel { display: none; background: var(--card-bg); border: 1px solid var(--border); padding: 24px; border-radius: 4px; margin-bottom: 20px; }
  .help-panel.visible { display: block; }
  .help-panel h3 { font-size: 15px; margin: 16px 0 8px; }
  .help-panel h3:first-child { margin-top: 0; }
  .help-panel p { color: var(--muted); font-size: 13px; margin-bottom: 8px; line-height: 1.5; }
  .help-panel .help-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 12px 0; }
  .help-panel .help-item { background: var(--code-bg); padding: 12px; border-radius: 4px; }
  .help-panel .help-item strong { display: block; margin-bottom: 4px; font-size: 13px; }
  .help-panel .help-item span { font-size: 12px; color: var(--muted); }
  .help-close { float: right; cursor: pointer; font-size: 18px; background: none; border: none; font-family: inherit; color: var(--muted); }
  .help-close:hover { color: var(--fg); }
  /* Export panel */
  .export-panel { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; border-radius: 4px; margin-top: 16px; }
  .export-panel pre { white-space: pre-wrap; font-size: 12px; max-height: 400px; overflow-y: auto; }
  .export-panel .export-actions { display: flex; gap: 8px; margin-bottom: 12px; }
  /* Summary section */
  .summary-card { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; border-radius: 4px; margin-bottom: 20px; }
  .summary-card .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
  .summary-card .summary-item { text-align: center; }
  .summary-card .summary-item .val { font-size: 20px; font-weight: 600; }
  .summary-card .summary-item .lbl { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
  /* Tooltip */
  .tooltip { position: relative; display: inline-block; }
  .tooltip .tooltip-text {
    visibility: hidden; background: var(--fg); color: var(--bg);
    text-align: center; border-radius: 3px; padding: 5px 10px;
    position: absolute; z-index: 1; bottom: 125%; left: 50%;
    transform: translateX(-50%); font-size: 11px; white-space: nowrap;
  }
  .tooltip:hover .tooltip-text { visibility: visible; }
  /* Legacy side panel (kept for compat) */
  .layout-mode-btn { font-family: inherit; font-size: 12px; background: var(--code-bg); border: 1px solid var(--border); padding: 4px 10px; cursor: pointer; border-radius: 3px; color: var(--muted); }
  .layout-mode-btn:hover { background: var(--border); color: var(--fg); }
  .layout-mode-btn.active { background: var(--fg); color: var(--bg); }
  /* Select mode / bulk actions */
  .bulk-bar { display: flex; gap: 8px; align-items: center; padding: 8px 16px; background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px; margin-bottom: 12px; }
  .bulk-bar .bulk-count { font-weight: 600; }
  .bulk-bar button { font-family: inherit; font-size: 13px; border: 1px solid var(--border); padding: 4px 12px; cursor: pointer; border-radius: 3px; background: var(--card-bg); }
  .bulk-bar button.danger { color: var(--red); border-color: var(--red); }
  .bulk-bar button.danger:hover { background: var(--red); color: #fff; }
  /* Collapsible sections */
  .section-toggle {
    cursor: pointer; user-select: none; display: flex; align-items: center; gap: 8px;
    padding: 6px 0; border-radius: 3px;
  }
  .section-toggle:hover { color: var(--blue); }
  .section-toggle::before {
    content: '\25BC'; font-size: 10px; transition: transform 0.15s; display: inline-block; width: 14px; text-align: center;
  }
  .section-toggle.collapsed::before { transform: rotate(-90deg); }
  .section-body { transition: max-height 0.2s ease; }
  .section-toggle.collapsed + .section-body { display: none; }
  /* Editable name */
  .editable-name { cursor: default; padding: 2px 4px; border-radius: 3px; }
  .editable-name:hover { background: rgba(44,90,160,0.08); }
  .name-edit-input { font-family: inherit; font-size: 14px; border: 1px solid var(--blue); padding: 2px 6px; border-radius: 3px; background: var(--card-bg); width: 100%; max-width: 300px; }
  /* Tag/note columns */
  .notes-cell { max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--muted); }
  .tags-cell .tag { font-size: 11px; padding: 1px 6px; }
  /* Timeline enhanced colors */
  .tl-event.tl-cell_exec { border-left-color: var(--tl-cell); border-left-width: 4px; }
  .tl-event.tl-var_set { border-left-color: var(--tl-var); border-left-width: 4px; }
  .tl-event.tl-artifact { border-left-color: var(--tl-artifact); border-left-width: 4px; background: rgba(45,125,70,0.03); }
  .tl-event.tl-metric { border-left-color: var(--tl-metric); border-left-width: 4px; }
  .tl-event.tl-observational { border-left-color: var(--tl-obs); border-left-width: 2px; opacity: 0.6; }
  .tl-type-label { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 3px; margin-right: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
  .tl-type-label.tl-type-cell_exec { background: rgba(44,90,160,0.12); color: var(--tl-cell); }
  .tl-type-label.tl-type-var_set { background: rgba(124,58,237,0.12); color: var(--tl-var); }
  .tl-type-label.tl-type-artifact { background: rgba(45,125,70,0.12); color: var(--tl-artifact); }
  .tl-type-label.tl-type-metric { background: rgba(212,130,15,0.12); color: var(--tl-metric); }
  .tl-type-label.tl-type-observational { background: rgba(153,153,153,0.12); color: var(--tl-obs); }
  /* Artifact add form */
  .artifact-add-form { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
  .artifact-add-form input { font-family: inherit; font-size: 13px; border: 1px solid var(--border); padding: 4px 8px; border-radius: 3px; background: var(--card-bg); }
  .artifact-add-form button { font-family: inherit; font-size: 12px; padding: 4px 12px; border: 1px solid var(--border); background: var(--code-bg); cursor: pointer; border-radius: 3px; }
  /* Pinned experiments */
  .pin-btn { cursor: pointer; font-size: 14px; background: none; border: none; color: var(--muted); padding: 0 2px; }
  .pin-btn:hover { color: var(--yellow); }
  .pin-btn.pinned { color: var(--yellow); }
  .pinned-row { background: rgba(184,134,11,0.05); }
  .pinned-row:hover { background: rgba(184,134,11,0.1); }
  /* Table row clickable */
  #exp-body tr { cursor: pointer; }
  #exp-body tr:hover { background: var(--code-bg); }
  /* Tag filter bar */
  .tag-filter-bar { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 10px; align-items: center; }
  .tag-filter-bar .tag-chip { font-family: inherit; font-size: 11px; background: var(--code-bg); border: 1px solid var(--border); padding: 2px 8px; cursor: pointer; border-radius: 3px; color: var(--muted); }
  .tag-filter-bar .tag-chip:hover { background: var(--border); color: var(--fg); }
  .tag-filter-bar .tag-chip.active { background: var(--fg); color: var(--bg); }
  .group-bar { display: flex; gap: 4px; align-items: center; margin-bottom: 10px; font-size: 12px; color: var(--muted); }
  .group-bar button { font-family: inherit; font-size: 11px; background: var(--code-bg); border: 1px solid var(--border); padding: 2px 8px; cursor: pointer; border-radius: 3px; color: var(--muted); }
  .group-bar button:hover { background: var(--border); color: var(--fg); }
  .group-bar button.active { background: var(--fg); color: var(--bg); }
  .group-header td { background: var(--code-bg); font-size: 12px; font-weight: 600; padding: 8px 16px; cursor: pointer; user-select: none; border-bottom: 2px solid var(--border); }
  .group-header td:hover { background: var(--border); }
  .group-header .group-label { color: var(--fg); }
  .group-header .group-meta { color: var(--muted); font-weight: 400; margin-left: 8px; }
  .group-header .group-toggle { float: right; color: var(--muted); font-size: 10px; }
  /* Code changes column */
  .code-stat { font-size: 11px; color: var(--muted); }
  .code-stat .lines-added { color: var(--green); }
  .code-stat .lines-removed { color: var(--red); }
  /* Notes cell expanded */
  .notes-cell-expanded { max-width: 250px; font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  /* Detail name hover */
  #detail-name { cursor: default; padding: 2px 6px; border-radius: 3px; }
  #detail-name:hover { background: rgba(44,90,160,0.08); }
  /* Tag autocomplete dropdown */
  .tag-autocomplete { position: relative; display: inline-block; }
  .tag-autocomplete-list {
    position: absolute; top: 100%; left: 0; z-index: 50;
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px;
    max-height: 180px; overflow-y: auto; min-width: 160px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }
  .tag-autocomplete-item {
    padding: 4px 10px; cursor: pointer; font-size: 12px; display: flex; justify-content: space-between;
  }
  .tag-autocomplete-item:hover, .tag-autocomplete-item.active { background: var(--code-bg); color: var(--blue); }
  .tag-autocomplete-item .tag-count { color: var(--muted); font-size: 11px; }
  .tag-autocomplete-new { color: var(--green); font-style: italic; }
  /* Inline editable hints */
  .editable-hint { border-bottom: 1px dashed transparent; transition: border-color 0.15s; }
  .editable-hint:hover { border-bottom-color: var(--blue); }
  /* Detail inline tag area */
  .detail-tags-inline { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .detail-tags-inline .tag-input-area { display: inline-flex; align-items: center; }
  /* Detail inline notes */
  .detail-notes-inline { cursor: text; min-height: 24px; padding: 4px; border-radius: 3px; }
  .detail-notes-inline:hover { background: rgba(44,90,160,0.05); }
  /* Owl mascot */
  .owl-mascot { cursor: pointer; transition: transform 0.2s; display: inline-block; }
  .owl-mascot:hover { transform: scale(1.15); }
  .owl-mascot.owl-blink svg rect.owl-eye-white { animation: owlBlink 3s infinite; }
  @keyframes owlBlink { 0%,92%,100% { height: 1; } 94%,98% { height: 0; } }
  .owl-speech { position: absolute; background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 11px; color: var(--fg); white-space: nowrap; box-shadow: 0 2px 8px rgba(0,0,0,0.1); z-index: 100; bottom: 44px; left: 50%; transform: translateX(-50%); pointer-events: none; opacity: 0; transition: opacity 0.3s; }
  .owl-speech.visible { opacity: 1; }
  .owl-speech::after { content: ''; position: absolute; top: 100%; left: 50%; margin-left: -5px; border: 5px solid transparent; border-top-color: var(--border); }
  .owl-container { position: relative; display: inline-block; }
  /* Timezone setting */
  .tz-setting { display: inline-flex; align-items: center; gap: 6px; margin-left: 12px; }
  .tz-setting select { font-family: inherit; font-size: 11px; border: 1px solid var(--border); padding: 2px 6px; border-radius: 3px; background: var(--card-bg); color: var(--fg); }
</style>
</head>
<body>

<div class="header">
  <h1 onclick="showWelcome()" title="Back to dashboard home"><span class="owl-container" id="header-owl"><span class="owl-speech" id="owl-speech"></span><span class="owl-mascot owl-blink" onclick="event.stopPropagation();owlSpeak()"><svg width="32" height="32" viewBox="0 0 16 16" style="vertical-align:middle;margin-right:8px;image-rendering:pixelated"><!-- Pixel owl: ear tufts --><rect x="4" y="1" width="1" height="1" fill="#7c3aed"/><rect x="11" y="1" width="1" height="1" fill="#7c3aed"/><rect x="4" y="2" width="1" height="1" fill="#7c3aed"/><rect x="11" y="2" width="1" height="1" fill="#7c3aed"/><!-- Head --><rect x="5" y="2" width="6" height="1" fill="#2c5aa0"/><rect x="4" y="3" width="8" height="1" fill="#2c5aa0"/><rect x="4" y="4" width="8" height="1" fill="#2c5aa0"/><!-- Eyes (white circles with dark pupils) --><rect class="owl-eye-white" x="5" y="4" width="2" height="1" fill="#fff"/><rect class="owl-eye-white" x="9" y="4" width="2" height="1" fill="#fff"/><rect x="6" y="4" width="1" height="1" fill="#1a1a1a"/><rect x="10" y="4" width="1" height="1" fill="#1a1a1a"/><!-- Beak --><rect x="7" y="5" width="2" height="1" fill="#ffc107"/><!-- Body --><rect x="4" y="5" width="3" height="1" fill="#2c5aa0"/><rect x="9" y="5" width="3" height="1" fill="#2c5aa0"/><rect x="4" y="6" width="8" height="1" fill="#2c5aa0"/><rect x="5" y="7" width="6" height="1" fill="#2c5aa0"/><!-- Belly --><rect x="6" y="7" width="4" height="1" fill="#5c9ce6"/><rect x="5" y="8" width="6" height="1" fill="#2c5aa0"/><rect x="6" y="8" width="4" height="1" fill="#5c9ce6"/><!-- Wings --><rect x="3" y="6" width="1" height="2" fill="#7c3aed"/><rect x="12" y="6" width="1" height="2" fill="#7c3aed"/><!-- Feet --><rect x="6" y="9" width="1" height="1" fill="#ffc107"/><rect x="9" y="9" width="1" height="1" fill="#ffc107"/></svg></span></span>exptrack</h1>
  <div class="header-actions">
    <span class="tz-setting" title="Set timezone for displaying timestamps">
      <span style="font-size:12px;color:var(--muted)">TZ:</span>
      <select id="tz-select" onchange="setTimezone(this.value)">
        <option value="">Browser local</option>
        <option value="UTC">UTC</option>
        <option value="America/New_York">US Eastern</option>
        <option value="America/Chicago">US Central</option>
        <option value="America/Denver">US Mountain</option>
        <option value="America/Los_Angeles">US Pacific</option>
        <option value="Europe/London">London</option>
        <option value="Europe/Berlin">Berlin</option>
        <option value="Europe/Paris">Paris</option>
        <option value="Asia/Tokyo">Tokyo</option>
        <option value="Asia/Shanghai">Shanghai</option>
        <option value="Asia/Kolkata">India</option>
        <option value="Australia/Sydney">Sydney</option>
      </select>
    </span>
    <button class="theme-btn" id="theme-toggle" onclick="toggleTheme()" title="Toggle dark mode">&#9790;</button>
    <button class="help-btn" onclick="toggleHelp()">? Docs</button>
  </div>
</div>

<div class="help-panel" id="help-panel">
  <button class="help-close" onclick="toggleHelp()">&times;</button>
  <h3>What is exptrack?</h3>
  <p>A zero-friction experiment tracker for ML workflows. It captures parameters, metrics, variables, code changes, and artifacts automatically — no code changes needed.</p>

  <h3>Key Concepts</h3>
  <div class="help-grid">
    <div class="help-item">
      <strong>Params</strong>
      <span>Hyperparameters and config values captured from argparse, CLI flags, or notebook variables (lr, batch_size, etc). These define WHAT you ran.</span>
    </div>
    <div class="help-item">
      <strong>Metrics</strong>
      <span>Numeric values logged during training (loss, accuracy, etc). Tracked per step with min/max/last. These measure HOW it performed.</span>
    </div>
    <div class="help-item">
      <strong>Variables</strong>
      <span>All notebook variable values captured automatically — scalars, arrays, DataFrames, tensors. Prefixed with _var/ in params. Shows the full state of your experiment.</span>
    </div>
    <div class="help-item">
      <strong>Artifacts</strong>
      <span>Output files (plots, models, CSVs) auto-captured via plt.savefig() or manually via exptrack.notebook.out(). Linked to the experiment timeline.</span>
    </div>
    <div class="help-item">
      <strong>Code Changes</strong>
      <span>Diffs of your code vs. the last git commit (scripts) or previous cell version (notebooks). Only changed lines are stored. Prefixed with _code_change/.</span>
    </div>
    <div class="help-item">
      <strong>Timeline</strong>
      <span>Ordered log of every cell execution, variable change, and artifact save. Each event has a sequence number (seq) so you can reconstruct the full execution history.</span>
    </div>
    <div class="help-item">
      <strong>Tags &amp; Notes</strong>
      <span>Manual labels (tags) and free-text annotations (notes) you add to organize experiments. Use tags like "baseline", "best", "ablation".</span>
    </div>
    <div class="help-item">
      <strong>Compare</strong>
      <span>Side-by-side comparison of two experiments (params, variables, metrics) or two points within the same experiment (variable state at different timeline positions).</span>
    </div>
  </div>

  <h3>Dashboard Views</h3>
  <p><strong>Experiment list:</strong> Collapsible sidebar on the left. Click any experiment to see details. Use checkboxes to select 2 experiments for comparison.</p>
  <p><strong>Detail view:</strong> Shows full experiment info in the main area. Tabs: Overview, Timeline, Compare Within.</p>
  <p><strong>Compare:</strong> Select two experiments via checkboxes in the sidebar, then click Compare.</p>
  <p><strong>Export:</strong> Use the Export button on any experiment to get JSON, Markdown, or Plain Text.</p>
</div>

<div id="app-layout">
  <!-- Left: Collapsible experiment list -->
  <div id="exp-sidebar">
    <div class="sidebar-content">
      <div class="sidebar-header">
        <input type="text" id="search-input" placeholder="Search..." oninput="searchQuery=this.value;renderExpList()">
        <button class="collapse-btn" onclick="toggleSidebar()" title="Collapse sidebar">&#8249;</button>
      </div>
      <div class="status-chips" id="status-chips"></div>
      <div id="exp-list"></div>
      <div id="sidebar-actions-bar"></div>
    </div>
    <div class="collapse-strip" onclick="toggleSidebar()">
      <span style="font-size:18px;color:var(--muted)">&#8250;</span>
      <span id="sidebar-count" style="font-size:11px;color:var(--muted);margin-top:8px;writing-mode:vertical-rl"></span>
    </div>
  </div>

  <!-- Center: Main content -->
  <div id="main-content">
    <!-- Welcome state: shown when no experiment selected -->
    <div id="welcome-state">
      <div class="stats" id="stats"></div>
      <div class="table-toolbar">
        <input type="text" id="main-search" class="main-search-input" placeholder="Search experiments..." oninput="searchQuery=this.value;renderExperiments();renderExpList()">
        <div class="tag-filter-bar" id="tag-filter-bar" style="display:inline"></div>
      </div>
      <div class="group-bar" id="group-bar">
        <span>Group by:</span>
        <button data-group="git_commit" onclick="setGroup('git_commit')" class="active">Git Commit</button>
        <button data-group="git_branch" onclick="setGroup('git_branch')">Branch</button>
        <button data-group="status" onclick="setGroup('status')">Status</button>
        <button data-group="" onclick="setGroup('')">None</button>
      </div>
      <div id="table-actions-bar" class="table-actions-bar" style="display:none"></div>
      <table id="exp-table"><thead><tr>
        <th style="width:28px"></th><th class="cb-col"><input type="checkbox" onclick="selectAllVisible()" title="Select all"></th><th class="sortable" onclick="toggleSort('id')">ID<span class="sort-arrow"></span></th><th class="sortable" onclick="toggleSort('name')">Name<span class="sort-arrow"></span></th><th class="sortable" onclick="toggleSort('status')">Status<span class="sort-arrow"></span></th><th class="sortable" onclick="toggleSort('tags')">Tags<span class="sort-arrow"></span></th><th>Notes</th><th>Key Metrics</th><th>Changes</th><th class="sortable" onclick="toggleSort('created_at')">Started<span class="sort-arrow"></span></th>
      </tr></thead><tbody id="exp-body"></tbody></table>
    </div>

    <!-- Detail state: shown when an experiment is selected -->
    <div id="detail-view" style="display:none">
      <div id="detail-panel"></div>
    </div>

    <!-- Compare state -->
    <div id="compare-view" style="display:none">
      <div class="compare-input">
        <select id="cmp-id1"><option value="">-- Select experiment 1 --</option></select>
        <span class="vs-label">vs</span>
        <select id="cmp-id2"><option value="">-- Select experiment 2 --</option></select>
        <button onclick="doCompare()">Compare</button>
      </div>
      <div id="compare-result"></div>
    </div>
  </div>
</div>

<script>
let currentFilter = '';
let searchQuery = '';
let tagFilter = '';
let charts = {};
let selectedIds = new Set();
let pinnedIds = new Set(JSON.parse(localStorage.getItem('exptrack-pinned') || '[]'));
let allExperiments = [];
let currentDetailId = '';
let sortCol = 'created_at';
let sortDir = 'desc';
let groupBy = 'git_commit';
let collapsedGroups = new Set();
let clickTimer = null;
let currentTimezone = localStorage.getItem('exptrack-tz') || '';
let allKnownTags = []; // {name, count}[]

// Dark mode
function toggleTheme() {
  document.body.classList.toggle('dark');
  const isDark = document.body.classList.contains('dark');
  localStorage.setItem('exptrack-theme', isDark ? 'dark' : 'light');
  document.getElementById('theme-toggle').innerHTML = isDark ? '&#9788;' : '&#9790;';
}
if (localStorage.getItem('exptrack-theme') === 'dark') {
  document.body.classList.add('dark');
  document.getElementById('theme-toggle').innerHTML = '&#9788;';
}

function togglePin(id) {
  if (pinnedIds.has(id)) pinnedIds.delete(id);
  else pinnedIds.add(id);
  localStorage.setItem('exptrack-pinned', JSON.stringify([...pinnedIds]));
  renderExperiments();
}

function renderTagFilterBar() {
  const bar = document.getElementById('tag-filter-bar');
  if (!bar) return;
  const allTags = new Set();
  allExperiments.forEach(e => (e.tags||[]).forEach(t => allTags.add(t)));
  if (allTags.size === 0) { bar.innerHTML = ''; return; }
  let html = '<span style="font-size:11px;color:var(--muted);margin-right:4px">Filter:</span>';
  html += '<span class="tag-chip' + (tagFilter===''?' active':'') + '" onclick="tagFilter=\'\';renderExperiments();renderExpList();renderTagFilterBar()">All</span>';
  for (const t of [...allTags].sort()) {
    html += '<span class="tag-chip' + (tagFilter===t?' active':'') + '" onclick="tagFilter=\'' + esc(t).replace(/'/g,"\\'") + '\';renderExperiments();renderExpList();renderTagFilterBar()">#' + esc(t) + '</span>';
  }
  bar.innerHTML = html;
}

async function api(path) {
  const r = await fetch(path);
  return r.json();
}

function fmtDur(s) {
  if (!s) return '--';
  if (s >= 3600) return Math.floor(s/3600) + 'h' + Math.floor((s%3600)/60) + 'm';
  if (s >= 60) return Math.floor(s/60) + 'm' + Math.floor(s%60) + 's';
  return s.toFixed(1) + 's';
}

function fmtTimeAgo(iso) {
  if (!iso) return '--';
  const now = new Date();
  const then = new Date(iso);
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return diff + 's ago';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
}

function fmtDt(iso) {
  if (!iso) return '--';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  if (currentTimezone) {
    try {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: currentTimezone, month: 'numeric', day: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: false
      }).formatToParts(d);
      const get = type => (parts.find(p => p.type === type) || {}).value || '';
      return get('month') + '/' + get('day') + ' ' + get('hour') + ':' + get('minute');
    } catch(e) {}
  }
  return (d.getMonth()+1) + '/' + d.getDate() + ' ' +
         String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}

function fmtDtFull(iso) {
  if (!iso) return '--';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  const opts = { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
  if (currentTimezone) opts.timeZone = currentTimezone;
  try { return d.toLocaleString('en-US', opts); } catch(e) {}
  return d.toLocaleString();
}

async function setTimezone(tz) {
  currentTimezone = tz;
  localStorage.setItem('exptrack-tz', tz);
  try { await fetch('/api/config/timezone', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({timezone: tz}) }); } catch(e) {}
  renderExperiments();
  renderExpList();
  if (currentDetailId) showDetail(currentDetailId);
  owlSay(tz ? 'Timezone set to ' + tz + '!' : 'Using your browser timezone!');
}

async function loadTimezoneConfig() {
  try {
    const data = await api('/api/config/timezone');
    if (data.timezone) {
      currentTimezone = data.timezone;
      localStorage.setItem('exptrack-tz', data.timezone);
    }
  } catch(e) {}
  const sel = document.getElementById('tz-select');
  if (sel) sel.value = currentTimezone;
}

async function loadAllTags() {
  try {
    const data = await api('/api/all-tags');
    allKnownTags = data.tags || [];
  } catch(e) { allKnownTags = []; }
}

function toggleHelp() {
  document.getElementById('help-panel').classList.toggle('visible');
}

// ── Owl mascot ──────────────────────────────────────────────────────────────
const owlPhrases = [
  'Hoo hoo! Track all the things!',
  'Another experiment? Wise choice.',
  'Remember to tag your best runs!',
  'I never forget a metric.',
  'Did you try a lower learning rate?',
  'Diff your code, diff your life.',
  'Compare runs to find the signal.',
  'Notes help future-you understand past-you.',
  'Zero dependencies, infinite wisdom.',
  'Local-first, always.',
  'Reproducibility is a superpower!',
  'Git diff captured. You\'re welcome.',
  'Have you tried turning it off and on again?',
];
const owlContextPhrases = {
  delete: ['Are you sure? I\'ll miss that one...', 'Cleaning house? Smart owl.'],
  compare: ['Let\'s see who wins!', 'Side by side, insight arrives.'],
  export: ['Sharing is caring!', 'Data to go!'],
  tag: ['Good labeling, wise human!', 'Tags make finding things a hoot!'],
  empty: ['No experiments yet? Go run something!', 'An empty lab is full of potential.'],
  welcome: ['Welcome back! What shall we track today?', 'Hoo! Good to see you!'],
};
let owlSpeechTimer = null;

function owlSay(msg) {
  const el = document.getElementById('owl-speech');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('visible');
  if (owlSpeechTimer) clearTimeout(owlSpeechTimer);
  owlSpeechTimer = setTimeout(() => el.classList.remove('visible'), 3000);
}

function owlSpeak(context) {
  const phrases = context && owlContextPhrases[context] ? owlContextPhrases[context] : owlPhrases;
  owlSay(phrases[Math.floor(Math.random() * phrases.length)]);
}

// ── Sidebar ──────────────────────────────────────────────────────────────────
function toggleSidebar() {
  const sb = document.getElementById('exp-sidebar');
  sb.classList.toggle('collapsed');
  localStorage.setItem('exptrack-sidebar', sb.classList.contains('collapsed') ? 'collapsed' : 'open');
  const countEl = document.getElementById('sidebar-count');
  if (countEl) countEl.textContent = allExperiments.length + ' experiments';
}

function renderStatusChips() {
  const el = document.getElementById('status-chips');
  if (!el) return;
  const chips = [
    {label: 'All', val: ''},
    {label: 'Done', val: 'done'},
    {label: 'Failed', val: 'failed'},
    {label: 'Running', val: 'running'}
  ];
  el.innerHTML = chips.map(c =>
    '<button class="' + (currentFilter===c.val?'active':'') + '" onclick="filterExps(\'' + c.val + '\')">' + c.label + '</button>'
  ).join('');
}

function renderExpList() {
  const list = document.getElementById('exp-list');
  if (!list) return;
  const filtered = getFilteredExperiments();
  list.innerHTML = filtered.map(e => {
    const active = currentDetailId === e.id ? ' active' : '';
    const statusCls = 'status-' + e.status;
    const metrics = Object.entries(e.metrics || {}).slice(0, 2)
      .map(([k,v]) => k.split('/').pop() + '=' + (typeof v === 'number' ? v.toFixed(3) : v)).join('  ');
    const isSelected = selectedIds.has(e.id);
    const cbHtml = '<input type="checkbox" class="exp-card-cb" ' + (isSelected?'checked':'') +
      ' onclick="event.stopPropagation();toggleSelection(\'' + e.id + '\')" title="Select">';
    const tagsHtml = (e.tags||[]).length ? '<div class="exp-card-tags">' + (e.tags||[]).map(t=>'<span class="tag">#'+esc(t)+'</span>').join('') + '</div>' : '';
    return '<div class="exp-card' + active + '" onclick="showDetail(\'' + e.id + '\')">' +
      '<div class="exp-card-row1">' + cbHtml +
      '<span class="status-dot ' + statusCls + '"></span>' +
      '<span class="exp-card-name" ondblclick="event.stopPropagation();startInlineRename(\'' + e.id + '\',this)">' + esc(e.name) + '</span></div>' +
      '<div class="exp-card-meta">' +
        esc(e.git_branch || '') + ' &middot; ' + fmtDur(e.duration_s) + ' &middot; ' + fmtDt(e.created_at) +
      '</div>' +
      (metrics ? '<div class="exp-card-metrics">' + esc(metrics) + '</div>' : '') +
      tagsHtml +
    '</div>';
  }).join('');

  // Update sidebar count
  const countEl = document.getElementById('sidebar-count');
  if (countEl) countEl.textContent = filtered.length + ' exp';

  // Render sidebar actions bar
  renderSidebarActionsBar();
}

function renderSidebarActionsBar() {
  const bar = document.getElementById('sidebar-actions-bar');
  if (!bar) return;
  const n = selectedIds.size;
  if (n === 0) {
    bar.innerHTML = '';
    return;
  }
  let html = '<div class="sidebar-actions-bar">';
  html += '<div class="action-count">' + n + ' selected</div>';
  if (n === 2) {
    html += '<button class="primary" onclick="compareSelected()">Compare (2)</button>';
  } else if (n === 1) {
    html += '<button class="primary" style="opacity:0.5" disabled title="Select 2 to compare">Compare (need 2)</button>';
  }
  html += '<button class="export-btn" onclick="sidebarExport()">Export (' + n + ')</button>';
  html += '<button class="export-btn" onclick="sidebarCopyText()">Copy as Text</button>';
  html += '<button class="danger" onclick="sidebarBulkDelete()">Delete (' + n + ')</button>';
  html += '<button class="export-btn" onclick="selectedIds.clear();renderExpList();renderExperiments()">Clear Selection</button>';
  html += '</div>';
  bar.innerHTML = html;
}

// ── View switching ───────────────────────────────────────────────────────────
function showWelcome() {
  currentDetailId = '';
  document.getElementById('welcome-state').style.display = '';
  document.getElementById('detail-view').style.display = 'none';
  document.getElementById('compare-view').style.display = 'none';
  document.getElementById('exp-sidebar').classList.add('collapsed');
  renderExpList();
  if (allExperiments.length === 0) owlSpeak('empty');
}

function showCompareView() {
  document.getElementById('welcome-state').style.display = 'none';
  document.getElementById('detail-view').style.display = 'none';
  document.getElementById('compare-view').style.display = '';
  populateCompareDropdowns();
}

function showDetailView() {
  document.getElementById('welcome-state').style.display = 'none';
  document.getElementById('detail-view').style.display = '';
  document.getElementById('compare-view').style.display = 'none';
}

// ── Unified selection ─────────────────────────────────────────────────────────
function toggleSelection(id) {
  if (selectedIds.has(id)) selectedIds.delete(id);
  else selectedIds.add(id);
  renderExpList();
  renderExperiments();
}

function selectAllVisible() {
  const visibleExps = getFilteredExperiments();
  if (selectedIds.size === visibleExps.length) {
    selectedIds.clear();
  } else {
    visibleExps.forEach(e => selectedIds.add(e.id));
  }
  renderExpList();
  renderExperiments();
}

function renderTableActionsBar() {
  const bar = document.getElementById('table-actions-bar');
  if (!bar) return;
  const n = selectedIds.size;
  if (n === 0) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = 'flex';
  let html = '<span class="sel-count">' + n + ' selected</span>';
  html += '<button class="danger" onclick="sidebarBulkDelete()">Delete (' + n + ')</button>';
  html += '<button onclick="sidebarExport()">Export JSON (' + n + ')</button>';
  html += '<button onclick="sidebarCopyText()">Copy Text (' + n + ')</button>';
  if (n === 2) {
    html += '<button class="primary" onclick="compareSelected()">Compare</button>';
  }
  html += '<button onclick="selectedIds.clear();renderExpList();renderExperiments()">Clear</button>';
  bar.innerHTML = html;
}

async function sidebarBulkDelete() {
  owlSpeak('delete');
  if (!confirm('Delete ' + selectedIds.size + ' experiments? This cannot be undone.')) return;
  const ids = [...selectedIds];
  const r = await fetch('/api/bulk-delete', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ids})
  });
  const d = await r.json();
  if (d.ok) {
    selectedIds.clear();
    showWelcome();
    loadStats();
    loadExperiments();
  } else alert(d.error || 'Failed');
}

async function sidebarExport() {
  owlSpeak('export');
  const ids = [...selectedIds];
  const r = await fetch('/api/bulk-export', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ids, format: 'json'})
  });
  const data = await r.json();
  const text = JSON.stringify(data, null, 2);
  await navigator.clipboard.writeText(text);
  alert('Exported ' + data.length + ' experiments to clipboard (JSON)');
}

async function sidebarCopyText() {
  const ids = [...selectedIds];
  const exps = allExperiments.filter(e => ids.includes(e.id));
  let lines = [];
  for (const e of exps) {
    lines.push(e.name + ' (' + e.id.slice(0,6) + ') [' + e.status + ']');
    lines.push('  ID: ' + e.id);
    lines.push('  Status: ' + e.status);
    if (e.created_at) lines.push('  Started: ' + fmtDtFull(e.created_at));
    if (e.duration_s) lines.push('  Duration: ' + fmtDur(e.duration_s));
    if (e.git_branch) lines.push('  Branch: ' + e.git_branch + (e.git_commit ? ' @ ' + e.git_commit : ''));
    const params = Object.entries(e.params || {}).filter(([k]) => !k.startsWith('_'));
    if (params.length) {
      lines.push('  Parameters:');
      params.forEach(([k,v]) => lines.push('    ' + k + ' = ' + JSON.stringify(v)));
    }
    const metrics = Object.entries(e.metrics || {});
    if (metrics.length) {
      lines.push('  Metrics:');
      metrics.forEach(([k,v]) => lines.push('    ' + k + ' = ' + (typeof v === 'number' ? v.toFixed(4) : v)));
    }
    if (e.tags && e.tags.length) lines.push('  Tags: ' + e.tags.map(t => '#' + t).join(', '));
    if (e.notes) {
      lines.push('  Notes:');
      e.notes.split('\n').forEach(l => lines.push('    ' + l));
    }
    lines.push('');
  }
  await navigator.clipboard.writeText(lines.join('\n'));
  owlSay('Copied ' + exps.length + ' experiment(s) to clipboard!');
  alert('Copied ' + exps.length + ' experiments to clipboard (plain text)');
}

function setGroup(field) {
  groupBy = field;
  collapsedGroups.clear();
  document.querySelectorAll('#group-bar button').forEach(b => {
    const val = b.getAttribute('data-group');
    b.classList.toggle('active', val === field);
  });
  renderExperiments();
}

function toggleGroup(key) {
  if (collapsedGroups.has(key)) collapsedGroups.delete(key);
  else collapsedGroups.add(key);
  renderExperiments();
}

function toggleSort(col) {
  if (sortCol === col) {
    sortDir = sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    sortCol = col;
    sortDir = (col === 'name' || col === 'status' || col === 'id') ? 'asc' : 'desc';
  }
  renderExperiments();
  updateSortHeaders();
}

function updateSortHeaders() {
  document.querySelectorAll('#exp-table th.sortable').forEach(th => {
    const col = th.getAttribute('onclick').match(/toggleSort\('(\w+)'\)/)?.[1];
    th.classList.toggle('sort-active', col === sortCol);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = col === sortCol ? (sortDir === 'asc' ? '\u25B2' : '\u25BC') : '';
  });
}

function getFilteredExperiments() {
  let exps = allExperiments;
  if (tagFilter) {
    exps = exps.filter(e => (e.tags || []).includes(tagFilter));
  }
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    exps = exps.filter(e =>
      e.name.toLowerCase().includes(q) ||
      e.id.toLowerCase().includes(q) ||
      (e.tags || []).some(t => t.toLowerCase().includes(q)) ||
      Object.keys(e.params || {}).some(k => k.toLowerCase().includes(q)) ||
      (e.git_branch || '').toLowerCase().includes(q) ||
      (e.notes || '').toLowerCase().includes(q)
    );
  }
  // Sort: pinned first, then by sort column
  exps = [...exps].sort((a, b) => {
    const ap = pinnedIds.has(a.id) ? 0 : 1;
    const bp = pinnedIds.has(b.id) ? 0 : 1;
    if (ap !== bp) return ap - bp;
    let av, bv;
    switch (sortCol) {
      case 'name': av = a.name.toLowerCase(); bv = b.name.toLowerCase(); break;
      case 'status': av = a.status; bv = b.status; break;
      case 'id': av = a.id; bv = b.id; break;
      case 'tags': av = (a.tags||[]).length; bv = (b.tags||[]).length; break;
      case 'created_at': default: av = a.created_at||''; bv = b.created_at||''; break;
    }
    let cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortDir === 'desc' ? -cmp : cmp;
  });
  return exps;
}

async function loadStats() {
  const s = await api('/api/stats');
  const statsEl = document.getElementById('stats');
  if (statsEl) {
    const timeAgo = s.most_recent ? fmtTimeAgo(s.most_recent) : '--';
    statsEl.innerHTML = `
      <div class="stats-label">Runs</div>
      <div class="stats-row runs">
        <div class="stat"><div class="num">${s.total}</div><div class="label">Total Runs</div><div class="stat-hint">All experiments tracked in this project</div></div>
        <div class="stat"><div class="num status-done">${s.done}</div><div class="label">Done</div><div class="stat-hint">Completed successfully</div></div>
        <div class="stat"><div class="num status-failed">${s.failed}</div><div class="label">Failed</div><div class="stat-hint">Ended with an error</div></div>
        <div class="stat"><div class="num status-running">${s.running}</div><div class="label">Running</div><div class="stat-hint">Currently in progress</div></div>
      </div>
      <div class="stats-label">Additional Stats</div>
      <div class="stats-row additional">
        <div class="stat"><div class="num">${s.success_rate}%</div><div class="label">Success Rate</div><div class="stat-hint">done / total</div></div>
        <div class="stat"><div class="num">${fmtDur(s.avg_duration_s)}</div><div class="label">Avg Duration</div><div class="stat-hint">Mean run time (completed only)</div></div>
        <div class="stat"><div class="num">${timeAgo}</div><div class="label">Latest Run</div><div class="stat-hint">Time since most recent experiment</div></div>
        <div class="stat"><div class="num">${fmtDur(s.longest_run_s)}</div><div class="label">Longest Run</div><div class="stat-hint">Maximum run duration</div></div>
        <div class="stat"><div class="num">${s.unique_tags}</div><div class="label">Tags</div><div class="stat-hint">Unique tags across all experiments</div></div>
        <div class="stat"><div class="num">${s.total_artifacts}</div><div class="label">Artifacts</div><div class="stat-hint">Total artifacts saved</div></div>
        <div class="stat"><div class="num">${s.unique_branches}</div><div class="label">Branches</div><div class="stat-hint">Unique git branches used</div></div>
      </div>
    `;
  }
  renderStatusChips();
}

async function loadExperiments() {
  const url = currentFilter ? '/api/experiments?status=' + currentFilter : '/api/experiments';
  allExperiments = await api(url);
  renderExperiments();
  renderExpList();
}

function onRowClick(id) {
  if (clickTimer) clearTimeout(clickTimer);
  clickTimer = setTimeout(() => { clickTimer = null; showDetail(id); }, 250);
}

function cancelRowClick() {
  if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
}

function renderExpRow(e) {
  const metricsHtml = Object.entries(e.metrics || {}).slice(0, 3)
    .map(([k,v]) => '<span style="color:var(--blue)">' + esc(k.split('/').pop()) + '</span>=' + (typeof v === 'number' ? v.toFixed(3) : esc(String(v))))
    .join(', ');
  const isSelected = selectedIds.has(e.id);
  const isPinned = pinnedIds.has(e.id);
  const rowCls = (isSelected ? 'selected-row' : '') + (isPinned ? ' pinned-row' : '');
  const tagsHtml = (e.tags||[]).map(t=>'<span class="tag">#'+esc(t)+'</span>').join('');
  const notesPreview = e.notes ? esc(e.notes.split('\n')[0].slice(0,60)) : '<span style="color:var(--muted)">--</span>';
  const codeParams = Object.keys(e.params || {}).filter(k => k.startsWith('_code_change/') || k === '_code_changes');
  let codeStatHtml = '--';
  if (codeParams.length) {
    let added = 0, removed = 0;
    for (const k of codeParams) {
      const v = String(e.params[k] || '');
      const parts = v.split('; ');
      for (const p of parts) {
        if (p.trim().startsWith('+')) added++;
        else if (p.trim().startsWith('-')) removed++;
      }
    }
    codeStatHtml = '<span class="code-stat">' + codeParams.length + ' file' + (codeParams.length>1?'s':'');
    if (added || removed) codeStatHtml += ' <span class="lines-added">+' + added + '</span> <span class="lines-removed">-' + removed + '</span>';
    codeStatHtml += '</span>';
  }
  return `<tr class="${rowCls}" onclick="onRowClick('${e.id}')">
    <td onclick="event.stopPropagation()"><button class="pin-btn${isPinned?' pinned':''}" onclick="togglePin('${e.id}')" title="${isPinned?'Unpin':'Pin'}">${isPinned?'\u2605':'\u2606'}</button></td>
    <td onclick="event.stopPropagation()">
      <input type="checkbox" ${isSelected?'checked':''} onclick="toggleSelection('${e.id}')" title="Select" style="cursor:pointer">
    </td>
    <td>${e.id.slice(0,6)}</td>
    <td>
      <span class="editable-name" ondblclick="event.stopPropagation();cancelRowClick();startInlineRename('${e.id}',this)">${esc(e.name.slice(0,45))}</span>
    </td>
    <td class="status-${e.status}">${e.status}</td>
    <td class="tags-cell" ondblclick="event.stopPropagation();cancelRowClick();startInlineTag('${e.id}',this)">${tagsHtml || '<span style="color:var(--muted)">--</span>'}</td>
    <td class="notes-cell-expanded" title="${esc(e.notes||'')}" ondblclick="event.stopPropagation();cancelRowClick();startInlineNote('${e.id}',this)">${notesPreview}</td>
    <td style="font-size:12px">${metricsHtml || '<span style="color:var(--muted)">--</span>'}</td>
    <td>${codeStatHtml}</td>
    <td>${fmtDt(e.created_at)}</td>
  </tr>`;
}

function renderExperiments() {
  const exps = getFilteredExperiments();
  const tbody = document.getElementById('exp-body');
  if (!tbody) return;
  renderTagFilterBar();
  updateSortHeaders();
  renderTableActionsBar();

  if (!groupBy) {
    tbody.innerHTML = exps.map(renderExpRow).join('');
    return;
  }

  // Group experiments
  const groups = new Map();
  for (const e of exps) {
    let key = '';
    if (groupBy === 'git_commit') key = e.git_commit ? e.git_commit.slice(0, 7) : 'no commit';
    else if (groupBy === 'git_branch') key = e.git_branch || 'no branch';
    else if (groupBy === 'status') key = e.status || 'unknown';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(e);
  }

  let html = '';
  for (const [key, items] of groups) {
    const isCollapsed = collapsedGroups.has(key);
    let groupLabel = key;
    if (groupBy === 'git_commit' && items[0].git_branch) {
      groupLabel = key + ' <span class="group-meta">' + esc(items[0].git_branch) + '</span>';
    }
    html += '<tr class="group-header" onclick="toggleGroup(\'' + esc(key).replace(/'/g, "\\'") + '\')"><td colspan="10">';
    html += '<span class="group-toggle">' + (isCollapsed ? '\u25B6' : '\u25BC') + '</span> ';
    html += '<span class="group-label">' + groupLabel + '</span>';
    html += '<span class="group-meta"> \u2014 ' + items.length + ' run' + (items.length > 1 ? 's' : '') + '</span>';
    html += '</td></tr>';
    if (!isCollapsed) {
      html += items.map(renderExpRow).join('');
    }
  }
  tbody.innerHTML = html;
}

// ── Inline rename on double-click ────────────────────────────────────────────
function startInlineRename(id, el) {
  const currentName = el.textContent.trim();
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'name-edit-input';
  input.value = currentName;
  el.replaceWith(input);
  input.focus();
  input.select();

  let saved = false;
  async function doRename() {
    if (saved) return;
    saved = true;
    const newName = input.value.trim();
    if (newName && newName !== currentName) {
      const r = await fetch('/api/experiment/' + id + '/rename', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: newName})
      });
      const d = await r.json();
      if (d.ok) {
        const exp = allExperiments.find(e => e.id === id);
        if (exp) exp.name = newName;
        renderExperiments();
        renderExpList();
        if (currentDetailId === id) {
          const nameEl = document.getElementById('detail-name');
          if (nameEl) nameEl.textContent = newName;
        }
        return;
      }
    }
    renderExperiments();
    renderExpList();
  }

  input.addEventListener('blur', doRename);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.value = currentName; input.blur(); }
  });
}

// ── Tag autocomplete helper ──────────────────────────────────────────────────
function createTagInput(id, tags, exp, onUpdate, opts = {}) {
  const wrapper = document.createElement('div');
  wrapper.className = 'tag-autocomplete';
  wrapper.style.cssText = 'display:inline-block;position:relative';
  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = opts.placeholder || '+ tag';
  input.className = 'name-edit-input';
  input.style.cssText = opts.style || 'width:90px;font-size:12px;padding:2px 4px';
  const dropdown = document.createElement('div');
  dropdown.className = 'tag-autocomplete-list';
  dropdown.style.display = 'none';
  wrapper.appendChild(input);
  wrapper.appendChild(dropdown);
  let activeIdx = -1;

  function showSuggestions() {
    const val = input.value.trim().toLowerCase();
    const existing = new Set(tags.map(t => t.toLowerCase()));
    let suggestions = allKnownTags.filter(t => !existing.has(t.name.toLowerCase()));
    if (val) suggestions = suggestions.filter(t => t.name.toLowerCase().includes(val));
    suggestions = suggestions.slice(0, 8);
    if (val && !suggestions.some(t => t.name.toLowerCase() === val) && !existing.has(val)) {
      suggestions.unshift({name: val, count: 0, isNew: true});
    }
    if (!suggestions.length) { dropdown.style.display = 'none'; return; }
    dropdown.innerHTML = suggestions.map((t, i) =>
      '<div class="tag-autocomplete-item' + (i === activeIdx ? ' active' : '') + '" data-tag="' + esc(t.name) + '">' +
      (t.isNew ? '<span class="tag-autocomplete-new">create "' + esc(t.name) + '"</span>' : '<span>#' + esc(t.name) + '</span>') +
      '<span class="tag-count">' + (t.count || '') + '</span></div>'
    ).join('');
    dropdown.style.display = 'block';
    dropdown.querySelectorAll('.tag-autocomplete-item').forEach(item => {
      item.onmousedown = (ev) => { ev.preventDefault(); selectTag(item.dataset.tag); };
    });
  }

  async function selectTag(val) {
    if (!val) return;
    await fetch('/api/experiment/' + id + '/tag', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({tag: val})
    });
    if (!tags.includes(val)) tags.push(val);
    if (exp) exp.tags = [...tags];
    input.value = '';
    dropdown.style.display = 'none';
    activeIdx = -1;
    loadAllTags();
    if (onUpdate) onUpdate();
  }

  input.addEventListener('input', () => { activeIdx = -1; showSuggestions(); });
  input.addEventListener('focus', showSuggestions);
  input.addEventListener('blur', () => { setTimeout(() => dropdown.style.display = 'none', 150); });
  input.addEventListener('keydown', (ev) => {
    const items = dropdown.querySelectorAll('.tag-autocomplete-item');
    if (ev.key === 'ArrowDown') { ev.preventDefault(); activeIdx = Math.min(activeIdx + 1, items.length - 1); showSuggestions(); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); activeIdx = Math.max(activeIdx - 1, -1); showSuggestions(); }
    else if (ev.key === 'Enter') {
      ev.preventDefault();
      if (activeIdx >= 0 && items[activeIdx]) selectTag(items[activeIdx].dataset.tag);
      else if (input.value.trim()) selectTag(input.value.trim());
    }
    else if (ev.key === 'Escape') { dropdown.style.display = 'none'; if (opts.onEscape) opts.onEscape(); }
  });
  return { wrapper, input };
}

// ── Inline tag editing on double-click ──────────────────────────────────────
function startInlineTag(id, el) {
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  const tags = [...(exp.tags || [])];
  const container = document.createElement('div');
  container.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;align-items:center;min-width:120px';
  container.onclick = (ev) => ev.stopPropagation();

  function render() {
    container.innerHTML = '';
    tags.forEach((t, i) => {
      const chip = document.createElement('span');
      chip.className = 'tag';
      chip.style.cssText = 'display:inline-flex;align-items:center;gap:2px';
      chip.textContent = '#' + t;
      const x = document.createElement('span');
      x.textContent = '\u00d7';
      x.style.cssText = 'cursor:pointer;margin-left:2px;color:var(--red);font-weight:bold';
      x.onclick = async (ev) => {
        ev.stopPropagation();
        await fetch('/api/experiment/' + id + '/delete-tag', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({tag: t})
        });
        tags.splice(i, 1);
        if (exp) exp.tags = [...tags];
        render();
        renderExpList();
        loadAllTags();
      };
      chip.appendChild(x);
      container.appendChild(chip);
    });
    const { wrapper, input } = createTagInput(id, tags, exp, () => { render(); renderExpList(); }, {
      onEscape: () => { renderExperiments(); renderExpList(); }
    });
    container.appendChild(wrapper);
    setTimeout(() => input.focus(), 0);
  }
  el.innerHTML = '';
  el.appendChild(container);
  render();
}

// ── Inline note editing on double-click ─────────────────────────────────────
function startInlineNote(id, el) {
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  const textarea = document.createElement('textarea');
  textarea.value = exp.notes || '';
  textarea.className = 'name-edit-input';
  textarea.style.cssText = 'width:100%;min-height:50px;font-size:12px;font-family:inherit;resize:vertical;padding:4px 6px';
  textarea.onclick = (ev) => ev.stopPropagation();
  el.innerHTML = '';
  el.appendChild(textarea);
  textarea.focus();

  let saved = false;
  async function doSave() {
    if (saved) return;
    saved = true;
    const newNotes = textarea.value.trim();
    await fetch('/api/experiment/' + id + '/edit-notes', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({notes: newNotes})
    });
    if (exp) exp.notes = newNotes;
    renderExperiments();
    renderExpList();
    if (currentDetailId === id) {
      const notesEl = document.getElementById('detail-notes');
      if (notesEl) notesEl.innerHTML = newNotes ? '<div class="notes-display">'+esc(newNotes)+'<button class="notes-edit-btn" onclick="editNotes(\''+id+'\')">edit</button></div>' : '<span style="color:var(--muted)">none</span>';
    }
  }
  textarea.addEventListener('blur', doSave);
  textarea.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && ev.ctrlKey) { ev.preventDefault(); textarea.blur(); }
    if (ev.key === 'Escape') { saved = true; renderExperiments(); renderExpList(); }
  });
}

async function compareSelected() {
  if (selectedIds.size !== 2) return;
  owlSpeak('compare');
  showCompareView();
  await populateCompareDropdowns();
  const ids = [...selectedIds];
  document.getElementById('cmp-id1').value = ids[0];
  document.getElementById('cmp-id2').value = ids[1];
  doCompare();
}

function filterExps(status) {
  currentFilter = status;
  renderStatusChips();
  loadExperiments();
}

async function populateCompareDropdowns() {
  const exps = await api('/api/experiments?limit=100');
  const sel1 = document.getElementById('cmp-id1');
  const sel2 = document.getElementById('cmp-id2');
  const prev1 = sel1.value, prev2 = sel2.value;
  const makeOpts = (exps) => '<option value="">-- Select experiment --</option>' +
    exps.map(e => `<option value="${e.id}">${e.id.slice(0,6)} | ${esc(e.name.slice(0,35))} | ${e.status} | ${fmtDt(e.created_at)}</option>`).join('');
  sel1.innerHTML = makeOpts(exps);
  sel2.innerHTML = makeOpts(exps);
  if (prev1) sel1.value = prev1;
  if (prev2) sel2.value = prev2;
  if (!prev1 && !prev2 && selectedIds.size === 2) {
    const ids = [...selectedIds];
    sel1.value = ids[0];
    sel2.value = ids[1];
  }
}

function artifactTypeBadge(path) {
  const ext = (path || '').split('.').pop().toLowerCase();
  if (['png','jpg','jpeg','svg','gif','bmp','tiff'].includes(ext)) return '<span class="artifact-type-badge img">image</span>';
  if (['pt','pth','h5','hdf5','onnx','pkl','joblib','safetensors'].includes(ext)) return '<span class="artifact-type-badge model">model</span>';
  if (['csv','json','jsonl','parquet','tsv','npy','npz'].includes(ext)) return '<span class="artifact-type-badge data">data</span>';
  return '<span class="artifact-type-badge">file</span>';
}

async function showDetail(id) {
  // Toggle: clicking same experiment deselects
  if (currentDetailId === id) {
    showWelcome();
    return;
  }
  currentDetailId = id;
  showDetailView();
  document.getElementById('exp-sidebar').classList.remove('collapsed');
  renderExpList();

  const [exp, metricsData, diffData] = await Promise.all([
    api('/api/experiment/' + id),
    api('/api/metrics/' + id),
    api('/api/diff/' + id),
  ]);
  if (exp.error) return;

  const regularParams = {};
  const codeChanges = {};
  const varChanges = {};
  let cellsRan = null;
  for (const [k, v] of Object.entries(exp.params)) {
    if (k === '_code_changes' || k.startsWith('_code_change/')) {
      codeChanges[k] = v;
    } else if (k.startsWith('_var/')) {
      varChanges[k.slice(5)] = v;
    } else if (k === '_script_hash' || k === '_cells_ran') {
      if (k === '_cells_ran') cellsRan = v;
    } else if (k === '_tags') {
      // skip, shown elsewhere
    } else {
      regularParams[k] = v;
    }
  }

  const paramRows = Object.entries(regularParams).map(([k,v]) =>
    `<tr><td style="color:var(--blue)">${esc(k)}</td><td>${esc(JSON.stringify(v))}</td></tr>`
  ).join('');

  const metricRows = exp.metrics.map(m =>
    `<tr><td style="color:var(--green)">${esc(m.key)}</td><td>${m.last?.toFixed(4) ?? '--'}</td><td>${m.min?.toFixed(4) ?? '--'}</td><td>${m.max?.toFixed(4) ?? '--'}</td><td>${m.n}</td></tr>`
  ).join('');

  const artRows = exp.artifacts.map(a =>
    `<tr><td><div class="artifact-row">${artifactTypeBadge(a.path)} ${esc(a.label)}</div></td><td style="font-size:12px;color:var(--muted)">${esc(a.path)}</td><td><div class="artifact-actions"><button onclick="editArtifact('${exp.id}','${esc(a.label).replace(/'/g,"\\'")}','${esc(a.path).replace(/'/g,"\\'")}')">edit</button><button class="art-del" onclick="deleteArtifact('${exp.id}','${esc(a.label).replace(/'/g,"\\'")}','${esc(a.path).replace(/'/g,"\\'")}')">del</button></div></td></tr>`
  ).join('');

  const addArtifactForm = `<div class="artifact-add-form" id="add-artifact-form-${exp.id}">
    <input type="text" id="art-label-${exp.id}" placeholder="Label (e.g. model_v2)" style="width:150px">
    <input type="text" id="art-path-${exp.id}" placeholder="Path (e.g. outputs/model.pt)" style="width:250px">
    <button onclick="addArtifact('${exp.id}')">+ Add Artifact</button>
  </div>`;

  // Code changes
  let codeHtml = '';
  if (Object.keys(codeChanges).length) {
    codeHtml = '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Code Changes</h2><div class="section-body"><div class="code-changes">';
    for (const [k, v] of Object.entries(codeChanges)) {
      const label = k === '_code_changes' ? 'Script diff vs. last commit' : k.replace('_code_change/','Cell ');
      const parts = String(v).split('; ').map(part => {
        const trimmed = part.trim();
        if (trimmed.startsWith('+')) return '<span class="diff-add">' + esc(trimmed) + '</span>';
        if (trimmed.startsWith('-')) return '<span class="diff-del">' + esc(trimmed) + '</span>';
        return esc(trimmed);
      }).join('\n');
      codeHtml += '<div class="change-item"><div class="change-label">' + esc(label) + '</div><div class="change-diff">' + parts + '</div></div>';
    }
    codeHtml += '</div></div>';
  }

  // Variable changes
  let varHtml = '';
  if (Object.keys(varChanges).length) {
    const scalars = {}, arrays = {}, other = {};
    for (const [k, v] of Object.entries(varChanges)) {
      const sv = String(v);
      if (sv.startsWith('ndarray(') || sv.startsWith('Tensor(') || sv.startsWith('DataFrame(') || sv.startsWith('Series(')) {
        arrays[k] = v;
      } else if (sv.startsWith("'") || sv.startsWith('"') || !isNaN(Number(sv)) || sv === 'True' || sv === 'False') {
        scalars[k] = v;
      } else {
        other[k] = v;
      }
    }
    varHtml = '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Variables (' + Object.keys(varChanges).length + ')</h2><div class="section-body"><div class="var-changes">';
    const renderGroup = (title, vars) => {
      if (!Object.keys(vars).length) return '';
      let h = '<div class="var-section-title">' + title + ' (' + Object.keys(vars).length + ')</div><table>';
      for (const [k, v] of Object.entries(vars)) {
        let displayVal = String(v);
        // Strip "varname = " prefix if present (capture stores "x = expr  # type")
        if (displayVal.startsWith(k + ' = ')) {
          displayVal = displayVal.slice(k.length + 3);
        }
        h += '<tr><td class="var-name">' + esc(k) + '</td><td>= ' + esc(displayVal) + '</td></tr>';
      }
      return h + '</table>';
    };
    varHtml += renderGroup('Scalars', scalars);
    varHtml += renderGroup('Arrays & Tensors', arrays);
    varHtml += renderGroup('Other', other);
    varHtml += '</div></div>';
  }

  // Summary card
  const totalMetricSteps = exp.metrics.reduce((s,m) => s + m.n, 0);
  const numVars = Object.keys(varChanges).length;
  const numArt = exp.artifacts.length;
  const numCodeChanges = Object.keys(codeChanges).length;
  let summaryHtml = '<div class="summary-card"><div class="summary-grid">';
  summaryHtml += '<div class="summary-item"><div class="val">' + Object.keys(regularParams).length + '</div><div class="lbl">Params</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + exp.metrics.length + '</div><div class="lbl">Metric Keys</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + totalMetricSteps + '</div><div class="lbl">Metric Points</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + numVars + '</div><div class="lbl">Variables</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + numArt + '</div><div class="lbl">Artifacts</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + numCodeChanges + '</div><div class="lbl">Code Changes</div></div>';
  summaryHtml += '</div></div>';

  // Diff
  let diffHtml = '';
  if (diffData.diff) {
    diffHtml = diffData.diff.split('\n').map(line => {
      if (line.startsWith('+') && !line.startsWith('+++')) return '<span class="diff-add">' + esc(line) + '</span>';
      if (line.startsWith('-') && !line.startsWith('---')) return '<span class="diff-del">' + esc(line) + '</span>';
      if (line.startsWith('@@')) return '<span class="diff-hunk">' + esc(line) + '</span>';
      return esc(line);
    }).join('\n');
  }

  const tagsHtml = '<span class="detail-tags-inline" id="detail-tags-area">' +
    (exp.tags.length
      ? exp.tags.map(t => '<span class="tag-removable">#' + esc(t) +
        ' <span class="tag-delete" onclick="event.stopPropagation();deleteTagInline(\'' + exp.id + '\',\'' + esc(t).replace(/'/g,"\\'") + '\')" title="Remove">&times;</span>' +
        '</span>').join('')
      : '') +
    '<span class="tag-input-area" id="detail-tag-input-area"></span>' +
    '</span>';

  document.getElementById('detail-panel').innerHTML = `
    <div class="detail" style="border:none;padding:4px 16px;margin:0">
      <!-- Summary bar -->
      <div class="detail-summary">
        <span class="sum-item"><strong class="status-${exp.status}">${exp.status}</strong></span>
        <span class="sum-sep">|</span>
        <span class="sum-item">Branch: <strong>${esc(exp.git_branch||'--')}</strong></span>
        <span class="sum-item">Commit: <strong>${esc((exp.git_commit||'--').slice(0,7))}</strong></span>
        <span class="sum-sep">|</span>
        <span class="sum-item">Started: <strong>${fmtDt(exp.created_at)}</strong></span>
        <span class="sum-item">Duration: <strong>${fmtDur(exp.duration_s)}</strong></span>
        <span class="sum-sep">|</span>
        <span class="sum-item">${Object.keys(regularParams).length} params</span>
        <span class="sum-item">${exp.metrics.length} metrics</span>
        <span class="sum-item">${exp.artifacts.length} artifacts</span>
      </div>

      <!-- Header with name + actions -->
      <div class="detail-header">
        <h2 id="detail-name" class="editable-hint" ondblclick="startInlineRename('${exp.id}',this)" title="Double-click to rename">${esc(exp.name)}</h2>
        <div class="detail-actions">
          <button class="action-btn danger" onclick="deleteExp('${exp.id}','${esc(exp.name).replace(/'/g,"\\'")}')">Delete</button>
          <button class="close-btn" onclick="showWelcome()" title="Back to list">&times;</button>
        </div>
      </div>

      <div class="detail-export-bar">
        <button class="action-btn primary" onclick="exportExp('${exp.id}')">Export</button>
        <div id="export-container"></div>
      </div>

      <div class="tabs" id="detail-tabs">
        <button class="tab active" onclick="switchDetailTab('overview','${exp.id}')">Overview</button>
        <button class="tab" onclick="switchDetailTab('timeline','${exp.id}')">Timeline</button>
        <button class="tab" onclick="switchDetailTab('compare-within','${exp.id}')">Compare Within</button>
      </div>

      <div id="detail-tab-overview">
        <!-- Two-column grid -->
        <div class="detail-grid">
          <!-- Left column: info + params -->
          <div>
            <div class="info-grid">
              <span class="label">ID</span><span>${exp.id}</span>
              <span class="label">Script</span><span style="font-size:12px">${esc(exp.script||'--')}</span>
              <span class="label">Host</span><span>${exp.hostname||'--'}</span>
              <span class="label">Python</span><span>${exp.python_ver||'--'}</span>
              <span class="label">Tags</span><span class="tag-list" id="detail-tags">${tagsHtml}</span>
              <span class="label">Notes</span><span id="detail-notes" class="detail-notes-inline editable-hint" ondblclick="startDetailNoteEdit('${exp.id}',this)" title="Double-click to edit">${exp.notes ? esc(exp.notes) : '<span style="color:var(--muted)">double-click to add notes</span>'}</span>
            </div>
            ${paramRows ? '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Params (' + Object.keys(regularParams).length + ')</h2><div class="section-body"><table class="params-table"><tr><th>Key</th><th>Value</th></tr>'+paramRows+'</table></div>' : ''}
            ${varHtml}
          </div>
          <!-- Right column: metrics + charts + artifacts -->
          <div>
            ${metricRows ? '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Metrics (' + exp.metrics.length + ')</h2><div class="section-body"><table class="metrics-table"><tr><th>Key</th><th>Last</th><th>Min</th><th>Max</th><th>Steps</th></tr>'+metricRows+'</table><div id="charts-container"></div></div>' : '<div id="charts-container"></div>'}
            <h2 class="section-toggle" onclick="this.classList.toggle('collapsed')">Artifacts (${exp.artifacts.length})</h2>
            <div class="section-body">
            ${artRows ? '<table class="params-table"><tr><th>File</th><th>Path</th><th style="width:80px"></th></tr>'+artRows+'</table>' : '<p style="color:var(--muted);font-size:13px">No artifacts yet.</p>'}
            ${addArtifactForm}
            </div>
          </div>
        </div>
        <!-- Full-width sections below the grid -->
        <div style="margin-top:20px">
          ${codeHtml}
          ${diffHtml ? '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Git Diff ('+exp.diff_lines+' lines)</h2><div class="section-body"><div class="diff-view">'+diffHtml+'</div></div>' : ''}
        </div>
      </div>

      <div id="detail-tab-timeline" style="display:none"></div>
      <div id="detail-tab-compare-within" style="display:none"></div>
    </div>
  `;

  // Wire up inline tag input in detail view
  const tagInputArea = document.getElementById('detail-tag-input-area');
  if (tagInputArea) {
    const detailTags = [...(exp.tags || [])];
    const { wrapper, input } = createTagInput(exp.id, detailTags, null, () => {
      loadExperiments().then(() => showDetail(exp.id));
    }, { placeholder: '+ add tag', style: 'width:100px;font-size:12px;padding:2px 6px' });
    tagInputArea.appendChild(wrapper);
  }

  // Render metric charts
  Object.values(charts).forEach(c => c.destroy());
  charts = {};
  const container = document.getElementById('charts-container');
  for (const [key, points] of Object.entries(metricsData)) {
    if (points.length < 2) continue;
    const div = document.createElement('div');
    div.className = 'chart-container';
    const canvas = document.createElement('canvas');
    div.appendChild(canvas);
    container.appendChild(div);
    charts[key] = new Chart(canvas, {
      type: 'line',
      data: {
        labels: points.map((p,i) => p.step !== null ? p.step : i),
        datasets: [{
          label: key,
          data: points.map(p => p.value),
          borderColor: '#2c5aa0',
          backgroundColor: 'rgba(44,90,160,0.1)',
          fill: true, tension: 0.3, pointRadius: 2,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: true, labels: { font: { family: "'IBM Plex Mono'" } } } },
        scales: {
          x: { title: { display: true, text: 'Step', font: { family: "'IBM Plex Mono'" } } },
          y: { title: { display: true, text: key, font: { family: "'IBM Plex Mono'" } } }
        }
      }
    });
  }
}

// ── Export ──────────────────────────────────────────────────────────────────────

async function exportExp(id) {
  owlSpeak('export');
  const container = document.getElementById('export-container');
  container.innerHTML = '<div class="export-panel"><div class="export-actions">' +
    '<button class="action-btn" onclick="doExport(\'' + id + '\',\'json\')">JSON</button>' +
    '<button class="action-btn" onclick="doExport(\'' + id + '\',\'markdown\')">Markdown</button>' +
    '<button class="action-btn" onclick="doExport(\'' + id + '\',\'plain\')">Plain Text</button>' +
    '<button class="action-btn" onclick="copyExport()">Copy to Clipboard</button>' +
    '<button class="action-btn" onclick="this.closest(\'.export-panel\').remove()">Close</button>' +
    '</div><pre id="export-content">Select a format above...</pre></div>';
}

async function doExport(id, fmt) {
  const data = await api('/api/export/' + id + '?format=' + (fmt === 'plain' ? 'json' : fmt));
  const pre = document.getElementById('export-content');
  if (fmt === 'markdown') {
    pre.textContent = data.markdown || JSON.stringify(data, null, 2);
  } else if (fmt === 'plain') {
    // Plain text format for easy copying
    let lines = [];
    const d = data.data || data;
    lines.push('Experiment: ' + (d.name || ''));
    lines.push('ID: ' + (d.id || ''));
    lines.push('Status: ' + (d.status || ''));
    if (d.created_at) lines.push('Created: ' + d.created_at);
    if (d.duration_s) lines.push('Duration: ' + fmtDur(d.duration_s));
    if (d.script) lines.push('Script: ' + d.script);
    if (d.command) lines.push('Command: ' + d.command);
    if (d.python_ver) lines.push('Python: ' + d.python_ver);
    if (d.git_branch) lines.push('Branch: ' + d.git_branch);
    if (d.git_commit) lines.push('Commit: ' + d.git_commit);
    if (d.hostname) lines.push('Hostname: ' + d.hostname);
    if (d.tags && d.tags.length) lines.push('Tags: ' + d.tags.join(', '));
    if (d.notes) lines.push('Notes: ' + d.notes);
    lines.push('');
    const params = d.params || {};
    if (Object.keys(params).length) {
      lines.push('Parameters:');
      Object.entries(params).forEach(([k,v]) => lines.push('  ' + k + ' = ' + JSON.stringify(v)));
      lines.push('');
    }
    const vars = d.variables || {};
    if (Object.keys(vars).length) {
      lines.push('Variables:');
      Object.entries(vars).forEach(([k,v]) => lines.push('  ' + k + ' = ' + JSON.stringify(v)));
      lines.push('');
    }
    const ms = d.metrics_series || {};
    if (Object.keys(ms).length) {
      lines.push('Metrics:');
      Object.entries(ms).forEach(([k,pts]) => {
        const last = pts.length ? pts[pts.length-1].value : '--';
        lines.push('  ' + k + ' = ' + last + ' (' + pts.length + ' steps)');
      });
      lines.push('');
    }
    if (d.artifacts && d.artifacts.length) {
      lines.push('Artifacts:');
      d.artifacts.forEach(a => lines.push('  ' + a.label + ': ' + a.path));
      lines.push('');
    }
    const changes = d.code_changes || {};
    if (Object.keys(changes).length) {
      lines.push('Code Changes:');
      Object.entries(changes).forEach(([k,v]) => lines.push('  ' + k + ': ' + JSON.stringify(v)));
      lines.push('');
    }
    const ts = d.timeline_summary || {};
    if (ts.total_events) {
      lines.push('Timeline: ' + ts.total_events + ' events (' +
        (ts.cell_executions || 0) + ' cells, ' +
        (ts.variable_sets || 0) + ' vars, ' +
        (ts.artifact_events || 0) + ' artifacts)');
    }
    pre.textContent = lines.join('\n');
  } else {
    pre.textContent = JSON.stringify(data, null, 2);
  }
}

function copyExport() {
  const pre = document.getElementById('export-content');
  if (pre) {
    navigator.clipboard.writeText(pre.textContent).then(() => {
      const btn = event.target;
      btn.textContent = 'Copied!';
      setTimeout(() => btn.textContent = 'Copy to Clipboard', 1500);
    });
  }
}

// ── Compare ────────────────────────────────────────────────────────────────────

let onlyDiffers = false;

async function doCompare() {
  const id1 = document.getElementById('cmp-id1').value.trim();
  const id2 = document.getElementById('cmp-id2').value.trim();
  if (!id1 || !id2) return;
  const data = await api('/api/compare?id1=' + id1 + '&id2=' + id2);
  if (data.error || data.exp1?.error || data.exp2?.error) {
    document.getElementById('compare-result').innerHTML = '<p>One or both experiments not found.</p>';
    return;
  }
  const e1 = data.exp1, e2 = data.exp2;
  const isUserParam = k => !k.startsWith('_code_change') && k !== '_code_changes' && !k.startsWith('_var/') && k !== '_script_hash' && k !== '_cells_ran' && k !== '_tags';
  const allPKeys = [...new Set([...Object.keys(e1.params), ...Object.keys(e2.params)])].filter(isUserParam).sort();
  const [tlVars1, tlVars2] = await Promise.all([
    api('/api/vars-at/' + id1 + '?seq=999999'),
    api('/api/vars-at/' + id2 + '?seq=999999'),
  ]);
  const allVarKeysFromTimeline = [...new Set([...Object.keys(tlVars1), ...Object.keys(tlVars2)])].sort();
  const allMKeys = [...new Set([...e1.metrics.map(m=>m.key), ...e2.metrics.map(m=>m.key)])].sort();
  const m1 = Object.fromEntries(e1.metrics.map(m => [m.key, m.last]));
  const m2 = Object.fromEntries(e2.metrics.map(m => [m.key, m.last]));

  const n1 = e1.name.length > 25 ? e1.name.slice(0,22) + '...' : e1.name;
  const n2 = e2.name.length > 25 ? e2.name.slice(0,22) + '...' : e2.name;

  let html = '<div class="compare-grid">';
  html += '<div><h2>' + esc(n1) + '</h2><p class="status-' + e1.status + '">' + e1.status + ' - ' + fmtDur(e1.duration_s) + '</p></div>';
  html += '<div><h2>' + esc(n2) + '</h2><p class="status-' + e2.status + '">' + e2.status + ' - ' + fmtDur(e2.duration_s) + '</p></div>';
  html += '</div>';
  html += '<label class="only-differs-toggle"><input type="checkbox" ' + (onlyDiffers ? 'checked' : '') + ' onchange="onlyDiffers=this.checked;doCompare()"> Show only differences</label>';

  if (allPKeys.length) {
    html += '<h2>Params</h2><table class="params-table"><tr><th>Key</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th></tr>';
    for (const k of allPKeys) {
      const v1 = JSON.stringify(e1.params[k] ?? '--');
      const v2 = JSON.stringify(e2.params[k] ?? '--');
      const differs = v1 !== v2;
      if (onlyDiffers && !differs) continue;
      const cls = differs ? ' class="differs"' : '';
      html += '<tr><td>' + esc(k) + '</td><td' + cls + '>' + esc(v1) + '</td><td' + cls + '>' + esc(v2) + '</td></tr>';
    }
    html += '</table>';
  }

  if (allVarKeysFromTimeline.length) {
    html += '<h2>Variables <span class="help-icon" title="Final variable state from the execution timeline of each experiment.">?</span></h2><table class="params-table"><tr><th>Variable</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th></tr>';
    for (const k of allVarKeysFromTimeline) {
      const v1 = String(tlVars1[k] ?? '--').slice(0, 60);
      const v2 = String(tlVars2[k] ?? '--').slice(0, 60);
      const differs = v1 !== v2;
      if (onlyDiffers && !differs) continue;
      const cls = differs ? ' class="differs"' : '';
      html += '<tr><td class="var-name">' + esc(k) + '</td><td' + cls + '>' + esc(v1) + '</td><td' + cls + '>' + esc(v2) + '</td></tr>';
    }
    html += '</table>';
  }

  if (allMKeys.length) {
    html += '<h2>Metrics (last)</h2><table class="metrics-table"><tr><th>Key</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th><th>Delta</th></tr>';
    for (const k of allMKeys) {
      const v1 = m1[k], v2 = m2[k];
      const sv1 = v1 !== undefined ? v1.toFixed(4) : '--';
      const sv2 = v2 !== undefined ? v2.toFixed(4) : '--';
      let delta = '';
      if (v1 !== undefined && v2 !== undefined) {
        const d = v1 - v2;
        if (onlyDiffers && Math.abs(d) < 0.0001) continue;
        delta = '<span style="color:' + (d>0?'var(--red)':'var(--green)') + '">' + (d>0?'+':'') + d.toFixed(4) + '</span>';
      }
      html += '<tr><td>' + esc(k) + '</td><td>' + sv1 + '</td><td>' + sv2 + '</td><td>' + delta + '</td></tr>';
    }
    html += '</table>';
  }
  document.getElementById('compare-result').innerHTML = html;
}

function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function renameExp(id) {
  const name = prompt('New name:');
  if (!name) return;
  const r = await fetch('/api/experiment/' + id + '/rename', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name})
  });
  const d = await r.json();
  if (d.ok) { loadExperiments(); showDetail(id); }
  else alert(d.error || 'Failed');
}

async function addTagUI(id) {
  const tag = prompt('Tag name (e.g. baseline, best, ablation):');
  if (!tag) return;
  const r = await fetch('/api/experiment/' + id + '/tag', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({tag: tag.trim()})
  });
  const d = await r.json();
  if (d.ok) { loadExperiments(); showDetail(id); }
  else alert(d.error || 'Failed');
}

async function addNoteUI(id) {
  const note = prompt('Add note:');
  if (!note) return;
  const r = await fetch('/api/experiment/' + id + '/note', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({note})
  });
  const d = await r.json();
  if (d.ok) { showDetail(id); }
  else alert(d.error || 'Failed');
}

async function deleteExp(id, name) {
  owlSpeak('delete');
  if (!confirm('Delete experiment "' + name + '"? This cannot be undone.')) return;
  const r = await fetch('/api/experiment/' + id + '/delete', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({})
  });
  const d = await r.json();
  if (d.ok) {
    showWelcome();
    loadStats();
    loadExperiments();
  } else alert(d.error || 'Failed');
}

// ── Add artifact ─────────────────────────────────────────────────────────────

async function addArtifact(id) {
  const label = document.getElementById('art-label-' + id).value.trim();
  const path = document.getElementById('art-path-' + id).value.trim();
  if (!label && !path) { alert('Provide a label or path'); return; }
  const r = await fetch('/api/experiment/' + id + '/artifact', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({label, path})
  });
  const d = await r.json();
  if (d.ok) { showDetail(id); }
  else alert(d.error || 'Failed');
}

// ── Edit/delete tags, notes, artifacts ────────────────────────────────────────

async function deleteTag(id, tag) {
  if (!confirm('Remove tag "' + tag + '"?')) return;
  const r = await fetch('/api/experiment/' + id + '/delete-tag', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({tag})
  });
  const d = await r.json();
  if (d.ok) { loadExperiments(); showDetail(id); }
  else alert(d.error || 'Failed');
}

async function editTag(id, oldTag) {
  const newTag = prompt('Edit tag:', oldTag);
  if (!newTag || newTag === oldTag) return;
  const r = await fetch('/api/experiment/' + id + '/edit-tag', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({old_tag: oldTag, new_tag: newTag.trim()})
  });
  const d = await r.json();
  if (d.ok) { loadExperiments(); showDetail(id); }
  else alert(d.error || 'Failed');
}

async function deleteTagInline(id, tag) {
  const r = await fetch('/api/experiment/' + id + '/delete-tag', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({tag})
  });
  const d = await r.json();
  if (d.ok) { loadAllTags(); loadExperiments().then(() => showDetail(id)); }
}

function startDetailNoteEdit(id, el) {
  const currentText = el.textContent.trim();
  const isPlaceholder = el.querySelector('span[style]') !== null;
  const textarea = document.createElement('textarea');
  textarea.className = 'notes-edit-area';
  textarea.value = isPlaceholder ? '' : currentText;
  textarea.style.cssText = 'width:100%;min-height:60px;font-size:13px;font-family:inherit';
  el.innerHTML = '';
  el.appendChild(textarea);
  textarea.focus();

  let saved = false;
  async function doSave() {
    if (saved) return;
    saved = true;
    const notes = textarea.value;
    await fetch('/api/experiment/' + id + '/edit-notes', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({notes})
    });
    const exp = allExperiments.find(e => e.id === id);
    if (exp) exp.notes = notes;
    showDetail(id);
  }
  textarea.addEventListener('blur', doSave);
  textarea.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && ev.ctrlKey) { ev.preventDefault(); textarea.blur(); }
    if (ev.key === 'Escape') { saved = true; showDetail(id); }
  });
}

async function editNotes(id) {
  const notesEl = document.getElementById('detail-notes');
  if (!notesEl) return;
  const current = notesEl.querySelector('.notes-display');
  const currentText = current ? current.textContent.replace(/edit$/, '').trim() : '';
  notesEl.innerHTML = '<div><textarea class="notes-edit-area" id="notes-edit-area">' + esc(currentText) + '</textarea>' +
    '<div style="margin-top:4px;display:flex;gap:6px">' +
    '<button class="action-btn" onclick="saveNotes(\'' + id + '\')">Save</button>' +
    '<button class="action-btn" onclick="showDetail(\'' + id + '\')">Cancel</button>' +
    '</div></div>';
  document.getElementById('notes-edit-area').focus();
}

async function saveNotes(id) {
  const area = document.getElementById('notes-edit-area');
  if (!area) return;
  const notes = area.value;
  const r = await fetch('/api/experiment/' + id + '/edit-notes', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({notes})
  });
  const d = await r.json();
  if (d.ok) { showDetail(id); }
  else alert(d.error || 'Failed');
}

async function deleteArtifact(id, label, path) {
  if (!confirm('Delete artifact "' + label + '"?')) return;
  const r = await fetch('/api/experiment/' + id + '/delete-artifact', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({label, path})
  });
  const d = await r.json();
  if (d.ok) { showDetail(id); }
  else alert(d.error || 'Failed');
}

async function editArtifact(id, oldLabel, oldPath) {
  const newLabel = prompt('Edit label:', oldLabel);
  if (newLabel === null) return;
  const newPath = prompt('Edit path:', oldPath);
  if (newPath === null) return;
  const r = await fetch('/api/experiment/' + id + '/edit-artifact', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({old_label: oldLabel, old_path: oldPath, new_label: newLabel.trim(), new_path: newPath.trim()})
  });
  const d = await r.json();
  if (d.ok) { showDetail(id); }
  else alert(d.error || 'Failed');
}

// ── Detail sub-tabs ──────────────────────────────────────────────────────────

let currentDetailTab = 'overview';
let currentDetailExpId = '';

function switchDetailTab(tab, expId) {
  currentDetailTab = tab;
  currentDetailExpId = expId;
  document.querySelectorAll('#detail-tabs .tab').forEach((t,i) => {
    const tabs = ['overview','timeline','compare-within'];
    t.classList.toggle('active', tabs[i] === tab);
  });
  ['overview','timeline','compare-within'].forEach(t => {
    const el = document.getElementById('detail-tab-'+t);
    if (el) el.style.display = t === tab ? '' : 'none';
  });
  if (tab === 'timeline') loadTimeline(expId);
  if (tab === 'compare-within') loadCompareWithin(expId);
}

// ── Timeline visualization ───────────────────────────────────────────────────

let timelineFilter = '';

async function loadTimeline(expId, filter) {
  if (filter !== undefined) timelineFilter = filter;
  const url = timelineFilter
    ? '/api/timeline/' + expId + '?type=' + timelineFilter
    : '/api/timeline/' + expId;
  const events = await api(url);
  const container = document.getElementById('detail-tab-timeline');

  let html = '<div class="tl-filters">';
  const types = ['', 'cell_exec', 'var_set', 'artifact', 'observational'];
  const labels = ['All', 'Code', 'Variables', 'Artifacts', 'Observational'];
  types.forEach((t, i) => {
    html += '<button class="' + (timelineFilter===t?'active':'') + '" onclick="loadTimeline(\'' + expId + '\',\'' + t + '\')">' + labels[i] + '</button>';
  });
  html += '</div>';

  if (!events.length) {
    html += '<p style="color:var(--muted)">No timeline events recorded.</p>';
    container.innerHTML = html;
    return;
  }

  html += '<p style="color:var(--muted);font-size:12px;margin-bottom:8px">' + events.length + ' events. Click "view source" on cells to see full code.</p>';

  const varState = {};

  html += '<div class="timeline">';
  for (const ev of events) {
    const cls = 'tl-event tl-' + ev.event_type;
    const ts = fmtDt(ev.ts);
    const icons = {cell_exec:'&gt;&gt;', var_set:'=', artifact:'&#9633;', metric:'#', observational:'..'};
    const colors = {cell_exec:'var(--tl-cell)', var_set:'var(--tl-var)', artifact:'var(--tl-artifact)', metric:'var(--tl-metric)', observational:'var(--tl-obs)'};
    const typeLabels = {cell_exec:'code', var_set:'var', artifact:'artifact', metric:'metric', observational:'observe'};
    const icon = icons[ev.event_type] || '?';
    const iconColor = colors[ev.event_type] || 'var(--fg)';
    const typeLabel = '<span class="tl-type-label tl-type-' + ev.event_type + '">' + (typeLabels[ev.event_type]||ev.event_type) + '</span>';

    if (ev.event_type === 'cell_exec' || ev.event_type === 'observational') {
      const info = ev.value || {};
      const preview = (info.source_preview || '').split('\n')[0].slice(0, 80);
      let badges = '';
      if (info.code_is_new) badges += '<span class="tl-badge tl-badge-new">new</span>';
      if (info.code_changed) badges += '<span class="tl-badge tl-badge-edited">edited</span>';
      if (info.is_rerun) badges += '<span class="tl-badge tl-badge-rerun">rerun</span>';
      if (info.has_output) badges += '<span class="tl-badge tl-badge-output">output</span>';

      // View source button - uses cell_hash to fetch from lineage
      const viewSrcBtn = ev.cell_hash ? ' <button class="view-source-btn" onclick="event.stopPropagation();viewCellSource(\'' + ev.cell_hash + '\',this)">view source</button>' : '';

      html += '<div class="' + cls + '">';
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong>' + esc(ev.key||'') + '</strong>' + badges + viewSrcBtn;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      if (preview) html += '<div class="tl-code-preview">' + esc(preview) + '</div>';
      if (info.output_preview) {
        html += '<div style="margin-top:3px;font-size:11px;color:var(--green)">output: ' + esc(String(info.output_preview).slice(0,80)) + '</div>';
      }

      if (ev.source_diff && ev.source_diff.length) {
        html += '<div class="tl-diff">';
        for (const d of ev.source_diff.slice(0, 8)) {
          if (d.op === '+') html += '<div class="diff-add">+ ' + esc(d.line.slice(0,80)) + '</div>';
          else if (d.op === '-') html += '<div class="diff-del">- ' + esc(d.line.slice(0,80)) + '</div>';
        }
        if (ev.source_diff.length > 8) html += '<div style="color:var(--muted)">... ' + (ev.source_diff.length - 8) + ' more lines</div>';
        html += '</div>';
      }
      html += '</div></div>';

    } else if (ev.event_type === 'var_set') {
      varState[ev.key] = ev.value;
      let cleanVal = String(ev.value);
      if (cleanVal.startsWith(ev.key + ' = ')) {
        cleanVal = cleanVal.slice(ev.key.length + 3);
      }
      const valStr = cleanVal.slice(0, 60);
      let prevHtml = '';
      if (ev.prev_value !== null && ev.prev_value !== undefined) {
        let cleanPrev = String(ev.prev_value);
        if (cleanPrev.startsWith(ev.key + ' = ')) {
          cleanPrev = cleanPrev.slice(ev.key.length + 3);
        }
        prevHtml = ' <span class="tl-var-arrow">&larr;</span> <span style="color:var(--muted);text-decoration:line-through">' + esc(cleanPrev.slice(0,40)) + '</span>';
      }
      html += '<div class="' + cls + '">';
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong style="color:var(--tl-var)">' + esc(ev.key) + '</strong> = ' + esc(valStr) + prevHtml;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      html += '</div></div>';

    } else if (ev.event_type === 'artifact') {
      html += '<div class="' + cls + '">';
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + artifactTypeBadge(String(ev.value||'')) + ' <strong>' + esc(ev.key||'') + '</strong> &rarr; ' + esc(String(ev.value||'').slice(0,60));
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      const ctxKeys = Object.keys(varState).filter(k => !k.startsWith('_'));
      if (ctxKeys.length) {
        const ctx = ctxKeys.slice(0, 6).map(k => k + '=' + String(varState[k]).slice(0,15)).join(', ');
        html += '<div class="tl-context">context: ' + esc(ctx) + '</div>';
      }
      html += '</div></div>';

    } else if (ev.event_type === 'metric') {
      html += '<div class="' + cls + '">';
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong style="color:var(--tl-metric)">' + esc(ev.key) + '</strong> = ' + ev.value;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      html += '</div></div>';
    }
  }
  html += '</div>';
  container.innerHTML = html;
}

async function viewCellSource(cellHash, btnEl) {
  // Toggle: if source is already showing, hide it
  const existing = btnEl.parentElement.querySelector('.source-view');
  if (existing) {
    existing.remove();
    btnEl.textContent = 'view source';
    return;
  }
  btnEl.textContent = 'loading...';
  const data = await api('/api/cell-source/' + cellHash);
  btnEl.textContent = 'hide source';
  if (data.error) {
    const div = document.createElement('div');
    div.className = 'source-view';
    div.textContent = 'Source not available (cell hash: ' + cellHash + ')';
    btnEl.parentElement.appendChild(div);
    return;
  }
  let html = '<div class="source-view">';
  // Show current source with line numbers
  html += '<div style="margin-bottom:8px;color:var(--blue);font-size:11px;text-transform:uppercase">Current cell source (hash: ' + cellHash + ')</div>';
  const lines = data.source.split('\n');
  for (let i = 0; i < lines.length; i++) {
    html += '<span class="line-num">' + (i+1) + '</span>' + esc(lines[i]) + '\n';
  }
  // If there's a parent, show it too
  if (data.parent_source) {
    html += '<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:8px;color:var(--muted);font-size:11px;text-transform:uppercase">Previous version (hash: ' + data.parent_hash + ')</div>';
    const plines = data.parent_source.split('\n');
    for (let i = 0; i < plines.length; i++) {
      html += '<span class="line-num">' + (i+1) + '</span><span style="color:var(--muted)">' + esc(plines[i]) + '</span>\n';
    }
  }
  html += '</div>';
  btnEl.parentElement.insertAdjacentHTML('beforeend', html);
}

// ── Within-experiment comparison ─────────────────────────────────────────────

let withinSeq1 = null, withinSeq2 = null;

async function loadCompareWithin(expId) {
  const events = await api('/api/timeline/' + expId);
  const container = document.getElementById('detail-tab-compare-within');

  const cellEvents = events.filter(e => e.event_type === 'cell_exec' || e.event_type === 'artifact');

  let html = '<p style="margin-bottom:12px">Select two timeline points to compare variable state. <span class="help-icon" title="Click two events to see how variables changed between them. Useful for tracking how a variable (e.g. learning rate, model weights) evolved during the experiment.">?</span></p>';
  html += '<div class="tl-compare-bar">';
  html += '<span>Point A: <strong id="cw-seq1">' + (withinSeq1 !== null ? 'seq='+withinSeq1 : 'click to select') + '</strong></span>';
  html += '<span>Point B: <strong id="cw-seq2">' + (withinSeq2 !== null ? 'seq='+withinSeq2 : 'click to select') + '</strong></span>';
  html += '<button onclick="doWithinCompare(\'' + expId + '\')">Compare</button>';
  html += '<button onclick="withinSeq1=null;withinSeq2=null;loadCompareWithin(\'' + expId + '\')" style="background:var(--muted)">Clear</button>';
  html += '</div>';

  html += '<div class="timeline" style="max-height:400px;overflow-y:auto">';
  for (const ev of cellEvents) {
    const info = ev.value || {};
    const preview = (info.source_preview || ev.key || '').split('\n')[0].slice(0, 60);
    const selCls = (withinSeq1 === ev.seq || withinSeq2 === ev.seq) ? ' tl-seq-select selected' : ' tl-seq-select';
    html += '<div class="tl-event tl-' + ev.event_type + selCls + '" onclick="selectWithinSeq(' + ev.seq + ',\'' + expId + '\')" style="cursor:pointer">';
    html += '<div class="tl-seq">' + ev.seq + '</div>';
    html += '<div class="tl-body">';
    html += '<strong>' + esc(ev.key||'') + '</strong>';
    html += ' <span style="color:var(--muted);margin-left:8px">' + fmtDt(ev.ts) + '</span>';
    if (preview) html += '<div class="tl-code-preview">' + esc(preview) + '</div>';
    html += '</div></div>';
  }
  html += '</div>';
  html += '<div id="within-compare-result"></div>';
  container.innerHTML = html;
}

function selectWithinSeq(seq, expId) {
  if (withinSeq1 === null || (withinSeq1 !== null && withinSeq2 !== null)) {
    withinSeq1 = seq;
    withinSeq2 = null;
  } else {
    withinSeq2 = seq;
  }
  loadCompareWithin(expId);
}

async function doWithinCompare(expId) {
  if (withinSeq1 === null || withinSeq2 === null) return;
  const [vars1, vars2] = await Promise.all([
    api('/api/vars-at/' + expId + '?seq=' + withinSeq1),
    api('/api/vars-at/' + expId + '?seq=' + withinSeq2),
  ]);

  const allKeys = [...new Set([...Object.keys(vars1), ...Object.keys(vars2)])].sort();
  let html = '<div class="within-compare">';
  html += '<h3>Variable state: seq=' + withinSeq1 + ' vs seq=' + withinSeq2 + '</h3>';
  html += '<table class="params-table">';
  html += '<tr><th>Variable</th><th>@seq=' + withinSeq1 + '</th><th>@seq=' + withinSeq2 + '</th></tr>';

  for (const k of allKeys) {
    const v1 = vars1[k] !== undefined ? String(vars1[k]).slice(0, 50) : '--';
    const v2 = vars2[k] !== undefined ? String(vars2[k]).slice(0, 50) : '--';
    const differs = String(vars1[k]) !== String(vars2[k]);
    const cls = differs ? ' class="differs"' : '';
    html += '<tr><td class="var-name">' + esc(k) + '</td><td' + cls + '>' + esc(v1) + '</td><td' + cls + '>' + esc(v2) + '</td></tr>';
  }
  html += '</table></div>';

  document.getElementById('within-compare-result').innerHTML = html;
}

// Init — sidebar starts collapsed (opens when entering detail view)
document.getElementById('exp-sidebar').classList.add('collapsed');
loadTimezoneConfig();
loadAllTags();
loadStats();
loadExperiments().then(() => {
  if (allExperiments.length === 0) owlSpeak('empty');
  else owlSpeak('welcome');
});
</script>
</body>
</html>
"""

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7331
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"[exptrack] Dashboard running at http://localhost:{port}")
    print(f"[exptrack] Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[exptrack] Dashboard stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
