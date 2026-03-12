"""
exptrack/core/queries.py — Shared database query functions

Used by both CLI commands and dashboard API to eliminate SQL duplication.
All functions accept a sqlite3.Connection and return plain dicts/lists.
"""
from __future__ import annotations

import json
import sys
from typing import Any


# ── Experiment lookup ─────────────────────────────────────────────────────────

def find_experiment(conn, exp_id_prefix: str, columns: str = "id") -> dict | None:
    """Look up experiment by prefix match. Returns dict or None."""
    row = conn.execute(
        f"SELECT {columns} FROM experiments WHERE id LIKE ?",
        (exp_id_prefix + "%",)
    ).fetchone()
    return dict(row) if row else None


def get_experiment_detail(conn, exp_id: str) -> dict | None:
    """Full experiment detail with params, metrics summary, and artifacts."""
    exp = conn.execute(
        "SELECT * FROM experiments WHERE id LIKE ?",
        (exp_id + "%",)
    ).fetchone()
    if not exp:
        return None

    full_id = exp["id"]
    params = conn.execute(
        "SELECT key, value FROM params WHERE exp_id=? ORDER BY key",
        (full_id,)
    ).fetchall()
    metrics = conn.execute("""
        SELECT key,
               MIN(value) as min_v, MAX(value) as max_v, COUNT(*) as n,
               (SELECT value FROM metrics m2 WHERE m2.exp_id=metrics.exp_id
                AND m2.key=metrics.key ORDER BY COALESCE(step,0) DESC LIMIT 1) as last_v
        FROM metrics WHERE exp_id=? GROUP BY key ORDER BY key
    """, (full_id,)).fetchall()
    artifacts = conn.execute(
        "SELECT label, path, created_at FROM artifacts WHERE exp_id=?",
        (full_id,)
    ).fetchall()

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
        "git_diff": exp.get("git_diff", ""),
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


# ── Experiment listing ────────────────────────────────────────────────────────

def list_experiments(conn, limit: int = 50, status: str = "") -> list[dict]:
    """List experiments with last metrics and params."""
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
        metrics = get_latest_metrics(conn, r["id"])
        ps = conn.execute(
            "SELECT key, value FROM params WHERE exp_id=?",
            (r["id"],)
        ).fetchall()
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
            "metrics": metrics,
            "params": {p["key"]: json.loads(p["value"]) for p in ps},
        })
    return result


# ── Metrics ───────────────────────────────────────────────────────────────────

def get_latest_metrics(conn, exp_id: str) -> dict[str, float]:
    """Get the last value of each metric key for an experiment."""
    rows = conn.execute("""
        SELECT key, value FROM metrics WHERE exp_id=?
        GROUP BY key HAVING MAX(COALESCE(step, 0))
    """, (exp_id,)).fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_metrics_series(conn, exp_id: str) -> dict[str, list[dict]]:
    """Get all metric points grouped by key."""
    rows = conn.execute("""
        SELECT key, value, step, ts FROM metrics
        WHERE exp_id=? ORDER BY key, COALESCE(step, 0)
    """, (exp_id,)).fetchall()
    by_key: dict[str, list] = {}
    for r in rows:
        by_key.setdefault(r["key"], []).append({
            "value": r["value"], "step": r["step"], "ts": r["ts"]
        })
    return by_key


def get_metrics_summary(conn, exp_id: str) -> list[dict]:
    """Get min/max/count/last for each metric key."""
    rows = conn.execute("""
        SELECT key,
               MIN(value) as min_v, MAX(value) as max_v, COUNT(*) as n,
               (SELECT value FROM metrics m2 WHERE m2.exp_id=metrics.exp_id
                AND m2.key=metrics.key ORDER BY COALESCE(step,0) DESC LIMIT 1) as last_v
        FROM metrics WHERE exp_id=? GROUP BY key ORDER BY key
    """, (exp_id,)).fetchall()
    return [{
        "key": m["key"], "last": m["last_v"],
        "min": m["min_v"], "max": m["max_v"], "n": m["n"]
    } for m in rows]


def get_all_latest_metrics(conn, limit: int = 50) -> dict[str, dict[str, float]]:
    """Get last metrics for recent experiments (used by ls command)."""
    rows = conn.execute("""
        SELECT exp_id, key, value FROM metrics m
        WHERE step=(SELECT MAX(step) FROM metrics m2
                    WHERE m2.exp_id=m.exp_id AND m2.key=m.key)
        GROUP BY exp_id, key
    """).fetchall()
    by_exp: dict[str, dict] = {}
    for r in rows:
        by_exp.setdefault(r["exp_id"], {})[r["key"]] = r["value"]
    return by_exp


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats(conn) -> dict[str, Any]:
    """Aggregate statistics across all experiments."""
    total = conn.execute("SELECT COUNT(*) as n FROM experiments").fetchone()["n"]
    done = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE status='done'").fetchone()["n"]
    failed = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE status='failed'").fetchone()["n"]
    running = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE status='running'").fetchone()["n"]
    avg_dur = conn.execute("SELECT AVG(duration_s) as v FROM experiments WHERE duration_s IS NOT NULL").fetchone()["v"]
    longest = conn.execute("SELECT MAX(duration_s) as v FROM experiments WHERE duration_s IS NOT NULL").fetchone()["v"]
    most_recent = conn.execute("SELECT created_at FROM experiments ORDER BY created_at DESC LIMIT 1").fetchone()

    tag_rows = conn.execute("SELECT tags FROM experiments WHERE tags IS NOT NULL AND tags != '[]'").fetchall()
    all_tags = set()
    for r in tag_rows:
        try:
            for t in json.loads(r["tags"] or "[]"):
                all_tags.add(t)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    try:
        total_artifacts = conn.execute("SELECT COUNT(*) as n FROM artifacts").fetchone()["n"]
    except Exception as e:
        print(f"[exptrack] warning: could not count artifacts: {e}", file=sys.stderr)
        total_artifacts = 0

    unique_branches = conn.execute(
        "SELECT COUNT(DISTINCT git_branch) as n FROM experiments "
        "WHERE git_branch IS NOT NULL AND git_branch != ''"
    ).fetchone()["n"]

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


# ── Tags ──────────────────────────────────────────────────────────────────────

def get_all_tags(conn) -> list[dict]:
    """Get all tags with usage counts, sorted by frequency."""
    rows = conn.execute(
        "SELECT tags FROM experiments WHERE tags IS NOT NULL AND tags != '[]'"
    ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        try:
            for t in json.loads(r["tags"] or "[]"):
                counts[t] = counts.get(t, 0) + 1
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return [{"name": t, "count": c} for t, c in sorted(counts.items(), key=lambda x: -x[1])]


def update_experiment_tags(conn, exp_id: str, tags: list[str]):
    """Update tags for an experiment."""
    from datetime import datetime, timezone
    conn.execute(
        "UPDATE experiments SET tags=?, updated_at=? WHERE id=?",
        (json.dumps(tags), datetime.now(timezone.utc).isoformat(), exp_id)
    )


def remove_tag_global(conn, tag: str) -> int:
    """Remove a tag from all experiments. Returns count of affected experiments."""
    rows = conn.execute(
        "SELECT id, tags FROM experiments WHERE tags LIKE ?",
        (f'%"{tag}"%',)
    ).fetchall()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for r in rows:
        tags = json.loads(r["tags"] or "[]")
        if tag in tags:
            tags = [t for t in tags if t != tag]
            conn.execute(
                "UPDATE experiments SET tags=?, updated_at=? WHERE id=?",
                (json.dumps(tags), now, r["id"])
            )
            count += 1
    return count


# ── Timeline ──────────────────────────────────────────────────────────────────

def get_timeline_events(conn, exp_id: str, event_type: str = "") -> list[dict]:
    """Get timeline events for an experiment."""
    where = "WHERE exp_id=?"
    params: list = [exp_id]
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


def get_vars_at_seq(conn, exp_id: str, seq: int = 999999) -> dict:
    """Get variable state at a specific timeline sequence point."""
    rows = conn.execute("""
        SELECT key, value FROM timeline
        WHERE exp_id=? AND event_type='var_set' AND seq <= ?
        ORDER BY seq DESC
    """, (exp_id, seq)).fetchall()
    ctx: dict = {}
    for r in rows:
        if r["key"] not in ctx:
            try:
                ctx[r["key"]] = json.loads(r["value"]) if r["value"] else None
            except (json.JSONDecodeError, ValueError):
                ctx[r["key"]] = r["value"]
    return ctx


# ── Cell lineage ──────────────────────────────────────────────────────────────

def get_cell_source(conn, cell_hash: str) -> dict | None:
    """Return full source code for a cell by its content hash."""
    row = conn.execute(
        "SELECT source, parent_hash, notebook, created_at FROM cell_lineage WHERE cell_hash=?",
        (cell_hash,)
    ).fetchone()
    if not row:
        return None
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


# ── Diff ──────────────────────────────────────────────────────────────────────

def get_experiment_diff(conn, exp_id: str) -> dict | None:
    """Get git diff for an experiment."""
    exp = conn.execute(
        "SELECT git_diff, git_branch, git_commit FROM experiments WHERE id LIKE ?",
        (exp_id + "%",)
    ).fetchone()
    if not exp:
        return None
    return {
        "diff": exp["git_diff"] or "",
        "branch": exp["git_branch"],
        "commit": exp["git_commit"],
    }


# ── Export ─────────────────────────────────────────────────────────────────────

def get_export_data(conn, exp_id: str) -> dict | None:
    """Get full export data for an experiment."""
    exp = conn.execute(
        "SELECT * FROM experiments WHERE id LIKE ?",
        (exp_id + "%",)
    ).fetchone()
    if not exp:
        return None
    full_id = exp["id"]

    params = conn.execute(
        "SELECT key, value FROM params WHERE exp_id=? ORDER BY key",
        (full_id,)
    ).fetchall()
    metrics = conn.execute("""
        SELECT key, value, step, ts FROM metrics WHERE exp_id=?
        ORDER BY key, COALESCE(step, 0)
    """, (full_id,)).fetchall()
    artifacts = conn.execute(
        "SELECT label, path, created_at FROM artifacts WHERE exp_id=?",
        (full_id,)
    ).fetchall()
    timeline = conn.execute("""
        SELECT seq, event_type, key, value, ts FROM timeline WHERE exp_id=?
        ORDER BY seq
    """, (full_id,)).fetchall()

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
    return data


# ── Groups ────────────────────────────────────────────────────────────────────

def get_groups(conn) -> list[dict]:
    """Get experiment groups (tag-based grouping with metadata)."""
    # Groups are experiments that share the same tag prefix "group/"
    tag_rows = conn.execute(
        "SELECT id, tags FROM experiments WHERE tags IS NOT NULL AND tags != '[]'"
    ).fetchall()
    groups: dict[str, list[str]] = {}
    for r in tag_rows:
        try:
            tags = json.loads(r["tags"] or "[]")
            for t in tags:
                if t.startswith("group/"):
                    group_name = t[6:]
                    groups.setdefault(group_name, []).append(r["id"])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    result = []
    for name, exp_ids in sorted(groups.items()):
        exp_count = len(exp_ids)
        # Get summary stats for the group
        placeholders = ",".join("?" * len(exp_ids))
        done = conn.execute(
            f"SELECT COUNT(*) as n FROM experiments WHERE id IN ({placeholders}) AND status='done'",
            exp_ids
        ).fetchone()["n"]
        failed = conn.execute(
            f"SELECT COUNT(*) as n FROM experiments WHERE id IN ({placeholders}) AND status='failed'",
            exp_ids
        ).fetchone()["n"]
        latest = conn.execute(
            f"SELECT created_at FROM experiments WHERE id IN ({placeholders}) ORDER BY created_at DESC LIMIT 1",
            exp_ids
        ).fetchone()

        result.append({
            "name": name,
            "experiment_ids": exp_ids,
            "count": exp_count,
            "done": done,
            "failed": failed,
            "running": exp_count - done - failed,
            "latest": latest["created_at"] if latest else None,
        })
    return result


def add_to_group(conn, exp_id: str, group_name: str) -> list[str]:
    """Add an experiment to a group (via tag)."""
    tag = f"group/{group_name}"
    exp = find_experiment(conn, exp_id, "id, tags")
    if not exp:
        return []
    tags = json.loads(exp["tags"] or "[]")
    if tag not in tags:
        tags.append(tag)
        update_experiment_tags(conn, exp["id"], tags)
    return tags


def remove_from_group(conn, exp_id: str, group_name: str) -> list[str]:
    """Remove an experiment from a group."""
    tag = f"group/{group_name}"
    exp = find_experiment(conn, exp_id, "id, tags")
    if not exp:
        return []
    tags = json.loads(exp["tags"] or "[]")
    tags = [t for t in tags if t != tag]
    update_experiment_tags(conn, exp["id"], tags)
    return tags
