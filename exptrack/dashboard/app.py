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
        return {
            "total": total,
            "done": done,
            "failed": failed,
            "running": running,
            "success_rate": round(done / total * 100, 1) if total else 0,
            "avg_duration_s": round(avg_dur or 0, 1),
        }

    def _api_experiments(self, qs):
        conn = get_db()
        limit = int(qs.get("limit", 50))
        status = qs.get("status", "")
        where = "WHERE status=?" if status else ""
        params = (status, limit) if status else (limit,)
        query = f"""
            SELECT id, project, name, status, created_at, duration_s,
                   git_branch, git_commit, tags
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
                     (new_notes, __import__('datetime').datetime.utcnow().isoformat(), exp["id"]))
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
                     (json.dumps(tags), __import__('datetime').datetime.utcnow().isoformat(), exp["id"]))
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
                     (new_name, __import__('datetime').datetime.utcnow().isoformat(), exp["id"]))
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
        conn.execute("DELETE FROM experiments WHERE id=?", (eid,))
        conn.commit()
        return {"ok": True}


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
    --card-bg: #fff; --code-bg: #f5f3f0;
  }
  body {
    font-family: 'IBM Plex Mono', monospace;
    background: var(--bg); color: var(--fg);
    max-width: 1400px; margin: 0 auto; padding: 28px 36px;
    font-size: 15px; line-height: 1.6;
  }
  h1 { font-size: 24px; font-weight: 600; margin-bottom: 24px; letter-spacing: -0.5px; }
  h2 { font-size: 16px; font-weight: 600; margin: 24px 0 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 28px; }
  .stat {
    background: var(--card-bg); border: 1px solid var(--border);
    padding: 20px; text-align: center; border-radius: 4px;
  }
  .stat .num { font-size: 34px; font-weight: 600; }
  .stat .label { color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }
  .filters { margin-bottom: 18px; display: flex; gap: 10px; align-items: center; }
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
  .cb-col { width: 36px; text-align: center; }
  .cb-col input { cursor: pointer; width: 16px; height: 16px; }
  table { width: 100%; border-collapse: collapse; background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px; }
  th { text-align: left; padding: 12px 16px; border-bottom: 2px solid var(--fg); font-size: 13px; text-transform: uppercase; letter-spacing: 1px; }
  td { padding: 10px 16px; border-bottom: 1px solid var(--border); font-size: 14px; }
  tr:hover { background: var(--code-bg); }
  .status-done { color: var(--green); font-weight: 500; }
  .status-failed { color: var(--red); font-weight: 500; }
  .status-running { color: var(--yellow); font-weight: 500; }
  .tag { background: var(--code-bg); padding: 2px 8px; font-size: 12px; margin-left: 6px; border-radius: 3px; }
  .detail { background: var(--card-bg); border: 1px solid var(--border); padding: 28px; margin-top: 20px; border-radius: 4px; }
  .detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; gap: 12px; flex-wrap: wrap; }
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
  .close-btn { cursor: pointer; font-size: 20px; background: none; border: none; font-family: inherit; padding: 4px 8px; }
  .close-btn:hover { background: var(--code-bg); border-radius: 3px; }
  .info-grid { display: grid; grid-template-columns: 150px 1fr; gap: 6px 20px; margin-bottom: 20px; font-size: 14px; }
  .info-grid .label { color: var(--muted); font-weight: 500; }
  .params-table, .metrics-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
  .params-table td, .metrics-table td { padding: 6px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
  .params-table th, .metrics-table th { padding: 8px 12px; font-size: 13px; }
  .diff-view {
    background: var(--code-bg); padding: 16px; font-size: 13px;
    overflow-x: auto; max-height: 500px; overflow-y: auto;
    white-space: pre; border: 1px solid var(--border); border-radius: 4px;
  }
  .diff-add { color: var(--green); }
  .diff-del { color: var(--red); }
  .diff-hunk { color: var(--blue); font-weight: 600; }
  .code-changes { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; margin-bottom: 20px; font-size: 13px; border-radius: 4px; }
  .code-changes .change-item { margin-bottom: 10px; }
  .code-changes .change-label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .code-changes .change-diff { white-space: pre-wrap; }
  .var-changes { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; margin-bottom: 20px; font-size: 13px; border-radius: 4px; }
  .var-changes td { padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .var-changes .var-name { color: var(--blue); font-weight: 500; }
  .var-changes .var-type { color: var(--muted); font-size: 12px; }
  .var-section-title { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin: 10px 0 6px; }
  .chart-container { max-width: 700px; margin: 20px 0; }
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
  /* Inline edit forms */
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
  .tag-removable { background: var(--code-bg); padding: 3px 10px; font-size: 13px; border-radius: 3px; display: inline-flex; align-items: center; gap: 4px; }
</style>
</head>
<body>
<h1>exptrack</h1>

<div class="stats" id="stats"></div>

<div class="tabs">
  <button class="tab active" onclick="switchTab('list')">Experiments</button>
  <button class="tab" onclick="switchTab('compare')">Compare</button>
</div>

<div id="view">
  <div id="list-view">
    <div class="filters" id="filters"></div>
    <table id="exp-table"><thead><tr>
      <th class="cb-col"></th><th>ID</th><th>Name</th><th>Status</th><th>Started</th><th>Duration</th><th>Branch</th>
    </tr></thead><tbody id="exp-body"></tbody></table>
  </div>
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

<div id="detail-panel"></div>

<script>
let currentFilter = '';
let charts = {};
let selectedForCompare = new Set();

async function api(path) {
  const r = await fetch(path);
  return r.json();
}

function fmtDur(s) {
  if (!s) return '--';
  if (s >= 60) return Math.floor(s/60) + 'm' + Math.floor(s%60) + 's';
  return s.toFixed(1) + 's';
}

function fmtDt(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  return (d.getMonth()+1) + '/' + d.getDate() + ' ' +
         String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}

async function loadStats() {
  const s = await api('/api/stats');
  document.getElementById('stats').innerHTML = `
    <div class="stat"><div class="num">${s.total}</div><div class="label">Total Runs</div></div>
    <div class="stat"><div class="num status-done">${s.done}</div><div class="label">Done</div></div>
    <div class="stat"><div class="num status-failed">${s.failed}</div><div class="label">Failed</div></div>
    <div class="stat"><div class="num status-running">${s.running}</div><div class="label">Running</div></div>
    <div class="stat"><div class="num">${s.success_rate}%</div><div class="label">Success Rate</div></div>
    <div class="stat"><div class="num">${fmtDur(s.avg_duration_s)}</div><div class="label">Avg Duration</div></div>
  `;
  // Filters
  document.getElementById('filters').innerHTML = `
    <button class="${!currentFilter?'active':''}" onclick="filterExps('')">All</button>
    <button class="${currentFilter==='done'?'active':''}" onclick="filterExps('done')">Done</button>
    <button class="${currentFilter==='failed'?'active':''}" onclick="filterExps('failed')">Failed</button>
    <button class="${currentFilter==='running'?'active':''}" onclick="filterExps('running')">Running</button>
    <button class="compare-selected ${selectedForCompare.size===2?'visible':''}" onclick="compareSelected()">Compare Selected (${selectedForCompare.size}/2)</button>
  `;
}

async function loadExperiments() {
  const url = currentFilter ? `/api/experiments?status=${currentFilter}` : '/api/experiments';
  const exps = await api(url);
  const tbody = document.getElementById('exp-body');
  tbody.innerHTML = exps.map(e => `
    <tr>
      <td class="cb-col"><input type="checkbox" ${selectedForCompare.has(e.id)?'checked':''} onclick="event.stopPropagation();toggleCompare('${e.id}')" title="Select for compare"></td>
      <td onclick="showDetail('${e.id}')" style="cursor:pointer">${e.id.slice(0,6)}</td>
      <td onclick="showDetail('${e.id}')" style="cursor:pointer">${e.name.slice(0,40)}${e.tags.map(t=>'<span class="tag">#'+t+'</span>').join('')}</td>
      <td onclick="showDetail('${e.id}')" style="cursor:pointer" class="status-${e.status}">${e.status}</td>
      <td onclick="showDetail('${e.id}')" style="cursor:pointer">${fmtDt(e.created_at)}</td>
      <td onclick="showDetail('${e.id}')" style="cursor:pointer">${fmtDur(e.duration_s)}</td>
      <td onclick="showDetail('${e.id}')" style="cursor:pointer">${e.git_branch||'--'}</td>
    </tr>
  `).join('');
}

function toggleCompare(id) {
  if (selectedForCompare.has(id)) {
    selectedForCompare.delete(id);
  } else {
    if (selectedForCompare.size >= 2) {
      // Remove oldest selection
      const first = selectedForCompare.values().next().value;
      selectedForCompare.delete(first);
    }
    selectedForCompare.add(id);
  }
  loadStats();  // refresh compare button visibility
  loadExperiments();  // refresh checkboxes
}

async function compareSelected() {
  if (selectedForCompare.size !== 2) return;
  switchTab('compare');
  await populateCompareDropdowns();
  const ids = [...selectedForCompare];
  document.getElementById('cmp-id1').value = ids[0];
  document.getElementById('cmp-id2').value = ids[1];
  doCompare();
}

function filterExps(status) {
  currentFilter = status;
  loadStats();
  loadExperiments();
}

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', i === (tab==='list'?0:1)));
  document.getElementById('list-view').style.display = tab==='list' ? '' : 'none';
  document.getElementById('compare-view').style.display = tab==='compare' ? '' : 'none';
  document.getElementById('detail-panel').innerHTML = '';
  if (tab === 'compare') populateCompareDropdowns();
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
  // Restore previous selections or pre-fill from checkboxes
  if (prev1) sel1.value = prev1;
  if (prev2) sel2.value = prev2;
  if (!prev1 && !prev2 && selectedForCompare.size === 2) {
    const ids = [...selectedForCompare];
    sel1.value = ids[0];
    sel2.value = ids[1];
  }
}

async function showDetail(id) {
  const [exp, metricsData, diffData] = await Promise.all([
    api('/api/experiment/' + id),
    api('/api/metrics/' + id),
    api('/api/diff/' + id),
  ]);
  if (exp.error) return;

  // Separate params into regular, code changes, and variable tracking
  const regularParams = {};
  const codeChanges = {};
  const varChanges = {};
  for (const [k, v] of Object.entries(exp.params)) {
    if (k === '_code_changes' || k.startsWith('_code_change/')) {
      codeChanges[k] = v;
    } else if (k.startsWith('_var/')) {
      varChanges[k.slice(5)] = v;  // strip _var/ prefix for display
    } else if (k.startsWith('_script_hash')) {
      // skip internal hash, not useful to show
    } else {
      regularParams[k] = v;
    }
  }

  const paramRows = Object.entries(regularParams).map(([k,v]) =>
    `<tr><td style="color:var(--blue)">${esc(k)}</td><td>${esc(JSON.stringify(v))}</td></tr>`
  ).join('');

  const metricRows = exp.metrics.map(m =>
    `<tr><td style="color:var(--green)">${esc(m.key)}</td><td>${m.last?.toFixed(4)}</td><td>${m.min?.toFixed(4)}</td><td>${m.max?.toFixed(4)}</td><td>${m.n}</td></tr>`
  ).join('');

  const artRows = exp.artifacts.map(a =>
    `<tr><td>${esc(a.label)}</td><td>${esc(a.path)}</td></tr>`
  ).join('');

  // Code changes HTML — render diff-style with +/- coloring
  let codeHtml = '';
  if (Object.keys(codeChanges).length) {
    codeHtml = '<h2>Code Changes</h2><div class="code-changes">';
    for (const [k, v] of Object.entries(codeChanges)) {
      const label = k === '_code_changes' ? 'Script diff vs. last commit' : k.replace('_code_change/','Cell ');
      const parts = String(v).split('; ').map(part => {
        const trimmed = part.trim();
        if (trimmed.startsWith('+')) return `<span class="diff-add">${esc(trimmed)}</span>`;
        if (trimmed.startsWith('-')) return `<span class="diff-del">${esc(trimmed)}</span>`;
        return esc(trimmed);
      }).join('\n');
      codeHtml += `<div class="change-item"><div class="change-label">${esc(label)}</div><div class="change-diff">${parts}</div></div>`;
    }
    codeHtml += '</div>';
  }

  // Variable changes HTML — categorize into scalars, arrays/tensors, and other
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
    varHtml = '<h2>Variables</h2><div class="var-changes">';
    const renderGroup = (title, vars) => {
      if (!Object.keys(vars).length) return '';
      let h = `<div class="var-section-title">${title}</div><table>`;
      for (const [k, v] of Object.entries(vars)) {
        h += `<tr><td class="var-name">${esc(k)}</td><td>= ${esc(String(v))}</td></tr>`;
      }
      return h + '</table>';
    };
    varHtml += renderGroup('Scalars', scalars);
    varHtml += renderGroup('Arrays & Tensors', arrays);
    varHtml += renderGroup('Other', other);
    varHtml += '</div>';
  }

  // Diff HTML
  let diffHtml = '';
  if (diffData.diff) {
    diffHtml = diffData.diff.split('\n').map(line => {
      if (line.startsWith('+') && !line.startsWith('+++')) return `<span class="diff-add">${esc(line)}</span>`;
      if (line.startsWith('-') && !line.startsWith('---')) return `<span class="diff-del">${esc(line)}</span>`;
      if (line.startsWith('@@')) return `<span class="diff-hunk">${esc(line)}</span>`;
      return esc(line);
    }).join('\n');
  }

  const tagsHtml = exp.tags.length
    ? exp.tags.map(t => `<span class="tag-removable">#${esc(t)}</span>`).join('')
    : '<span style="color:var(--muted)">none</span>';

  document.getElementById('detail-panel').innerHTML = `
    <div class="detail">
      <div class="detail-header">
        <h2 id="detail-name">${esc(exp.name)}</h2>
        <div class="detail-actions">
          <button class="action-btn" onclick="renameExp('${exp.id}')">Rename</button>
          <button class="action-btn" onclick="addTagUI('${exp.id}')">+ Tag</button>
          <button class="action-btn" onclick="addNoteUI('${exp.id}')">+ Note</button>
          <button class="action-btn danger" onclick="deleteExp('${exp.id}','${esc(exp.name).replace(/'/g,"\\'")}')">Delete</button>
          <button class="close-btn" onclick="document.getElementById('detail-panel').innerHTML=''">&times;</button>
        </div>
      </div>
      <div class="info-grid">
        <span class="label">ID</span><span>${exp.id}</span>
        <span class="label">Status</span><span class="status-${exp.status}">${exp.status}</span>
        <span class="label">Created</span><span>${fmtDt(exp.created_at)}</span>
        <span class="label">Duration</span><span>${fmtDur(exp.duration_s)}</span>
        <span class="label">Script</span><span>${exp.script||'--'}</span>
        <span class="label">Branch</span><span>${exp.git_branch||'--'} @ ${exp.git_commit||'--'}</span>
        <span class="label">Host</span><span>${exp.hostname||'--'}</span>
        <span class="label">Python</span><span>${exp.python_ver||'--'}</span>
        <span class="label">Tags</span><span class="tag-list" id="detail-tags">${tagsHtml}</span>
        <span class="label">Notes</span><span id="detail-notes">${exp.notes ? '<div class="notes-display">'+esc(exp.notes)+'</div>' : '<span style="color:var(--muted)">none</span>'}</span>
      </div>
      ${paramRows ? '<h2>Params</h2><table class="params-table">'+paramRows+'</table>' : ''}
      ${codeHtml}
      ${varHtml}
      ${metricRows ? '<h2>Metrics</h2><table class="metrics-table"><tr><th>Key</th><th>Last</th><th>Min</th><th>Max</th><th>Steps</th></tr>'+metricRows+'</table>' : ''}
      <div id="charts-container"></div>
      ${artRows ? '<h2>Artifacts</h2><table class="params-table">'+artRows+'</table>' : ''}
      ${diffHtml ? '<h2>Git Diff ('+exp.diff_lines+' lines)</h2><div class="diff-view">'+diffHtml+'</div>' : ''}
    </div>
  `;

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
          fill: true,
          tension: 0.3,
          pointRadius: 2,
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

async function doCompare() {
  const id1 = document.getElementById('cmp-id1').value.trim();
  const id2 = document.getElementById('cmp-id2').value.trim();
  if (!id1 || !id2) return;
  const data = await api(`/api/compare?id1=${id1}&id2=${id2}`);
  if (data.error || data.exp1?.error || data.exp2?.error) {
    document.getElementById('compare-result').innerHTML = '<p>One or both experiments not found.</p>';
    return;
  }
  const e1 = data.exp1, e2 = data.exp2;
  // Separate params, vars, and internal keys
  const isUserParam = k => !k.startsWith('_code_change') && k !== '_code_changes' && !k.startsWith('_var/') && k !== '_script_hash';
  const isVar = k => k.startsWith('_var/');
  const allPKeys = [...new Set([...Object.keys(e1.params), ...Object.keys(e2.params)])].filter(isUserParam).sort();
  const allVarKeys = [...new Set([...Object.keys(e1.params), ...Object.keys(e2.params)])].filter(isVar).sort();
  const allMKeys = [...new Set([...e1.metrics.map(m=>m.key), ...e2.metrics.map(m=>m.key)])].sort();
  const m1 = Object.fromEntries(e1.metrics.map(m => [m.key, m.last]));
  const m2 = Object.fromEntries(e2.metrics.map(m => [m.key, m.last]));

  const n1 = e1.name.length > 25 ? e1.name.slice(0,22) + '...' : e1.name;
  const n2 = e2.name.length > 25 ? e2.name.slice(0,22) + '...' : e2.name;

  let html = `<div class="compare-grid">
    <div><h2>${esc(n1)}</h2><p class="status-${e1.status}">${e1.status} - ${fmtDur(e1.duration_s)}</p></div>
    <div><h2>${esc(n2)}</h2><p class="status-${e2.status}">${e2.status} - ${fmtDur(e2.duration_s)}</p></div>
  </div>`;

  if (allPKeys.length) {
    html += '<h2>Params</h2><table class="params-table"><tr><th>Key</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th></tr>';
    for (const k of allPKeys) {
      const v1 = JSON.stringify(e1.params[k] ?? '--');
      const v2 = JSON.stringify(e2.params[k] ?? '--');
      const cls = v1 !== v2 ? ' class="differs"' : '';
      html += `<tr><td>${esc(k)}</td><td${cls}>${esc(v1)}</td><td${cls}>${esc(v2)}</td></tr>`;
    }
    html += '</table>';
  }

  if (allVarKeys.length) {
    html += '<h2>Variables</h2><table class="params-table"><tr><th>Variable</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th></tr>';
    for (const k of allVarKeys) {
      const displayK = k.slice(5); // strip _var/ prefix
      const v1 = String(e1.params[k] ?? '--');
      const v2 = String(e2.params[k] ?? '--');
      const cls = v1 !== v2 ? ' class="differs"' : '';
      html += `<tr><td class="var-name">${esc(displayK)}</td><td${cls}>${esc(v1)}</td><td${cls}>${esc(v2)}</td></tr>`;
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
        delta = `<span style="color:${d>0?'var(--red)':'var(--green)'}">${d>0?'+':''}${d.toFixed(4)}</span>`;
      }
      html += `<tr><td>${esc(k)}</td><td>${sv1}</td><td>${sv2}</td><td>${delta}</td></tr>`;
    }
    html += '</table>';
  }
  document.getElementById('compare-result').innerHTML = html;
}

function esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function renameExp(id) {
  const name = prompt('New name:');
  if (!name) return;
  const r = await fetch(`/api/experiment/${id}/rename`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name})
  });
  const d = await r.json();
  if (d.ok) { loadExperiments(); showDetail(id); }
  else alert(d.error || 'Failed');
}

async function addTagUI(id) {
  const tag = prompt('Tag name:');
  if (!tag) return;
  const r = await fetch(`/api/experiment/${id}/tag`, {
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
  const r = await fetch(`/api/experiment/${id}/note`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({note})
  });
  const d = await r.json();
  if (d.ok) { showDetail(id); }
  else alert(d.error || 'Failed');
}

async function deleteExp(id, name) {
  if (!confirm(`Delete experiment "${name}"? This cannot be undone.`)) return;
  const r = await fetch(`/api/experiment/${id}/delete`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({})
  });
  const d = await r.json();
  if (d.ok) {
    document.getElementById('detail-panel').innerHTML = '';
    loadStats();
    loadExperiments();
  } else alert(d.error || 'Failed');
}

// Init
loadStats();
loadExperiments();
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
