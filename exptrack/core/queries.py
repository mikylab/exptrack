"""
exptrack/core/queries.py — Shared database query functions

Used by both CLI commands and dashboard API to eliminate SQL duplication.
All functions accept a sqlite3.Connection and return plain dicts/lists.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from .db import resolve_git_diff

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
                AND m2.key=metrics.key ORDER BY COALESCE(step,0) DESC LIMIT 1) as last_v,
               (SELECT COALESCE(source, 'auto') FROM metrics m3 WHERE m3.exp_id=metrics.exp_id
                AND m3.key=metrics.key ORDER BY COALESCE(step,0) DESC LIMIT 1) as source
        FROM metrics WHERE exp_id=? GROUP BY key ORDER BY key
    """, (full_id,)).fetchall()
    artifacts = conn.execute(
        "SELECT label, path, created_at, timeline_seq FROM artifacts WHERE exp_id=?",
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
        "git_diff": resolve_git_diff(conn, exp["git_diff"]),
        "diff_lines": len(resolve_git_diff(conn, exp["git_diff"]).splitlines()),
        "hostname": exp["hostname"],
        "python_ver": exp["python_ver"],
        "notes": exp["notes"],
        "tags": json.loads(exp["tags"] or "[]"),
        "studies": json.loads(exp["studies"] or "[]"),
        "output_dir": exp["output_dir"] or "",
        "stage": exp["stage"],
        "stage_name": exp["stage_name"],
        "params": {p["key"]: json.loads(p["value"]) for p in params},
        "metrics": [{
            "key": m["key"], "last": m["last_v"],
            "min": m["min_v"], "max": m["max_v"], "n": m["n"],
            "source": m["source"] or "auto",
        } for m in metrics],
        "artifacts": [{"label": a["label"], "path": a["path"],
                       "timeline_seq": a["timeline_seq"]} for a in artifacts],
        "compact_status": _get_compact_status(conn, full_id, exp["git_diff"]),
    }


def _get_compact_status(conn, exp_id: str, raw_git_diff) -> dict:
    """Check what has been compacted for an experiment.

    Returns status per category:
      diff:     'stored' | 'compacted' | 'clean'
      cells:    'stored' | 'compacted' | 'partial' | 'shared' | 'none'
      timeline: 'stored' | 'compacted' | 'none'

    'shared' means cells exist but can't be compacted because other
    experiments reference the same cell hashes.
    """
    diff_compacted = bool(raw_git_diff and raw_git_diff.startswith("[compacted"))
    # Check if cells are compacted (any NULL source for cells used by this experiment)
    try:
        cell_row = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN cl.source IS NULL OR LENGTH(cl.source) = 0 THEN 1 ELSE 0 END) as nulled
            FROM cell_lineage cl
            WHERE cl.cell_hash IN (
                SELECT DISTINCT cell_hash FROM timeline
                WHERE exp_id=? AND cell_hash IS NOT NULL
            )
        """, (exp_id,)).fetchone()
        cells_total = (cell_row["total"] or 0) if cell_row else 0
        cells_compacted = (cell_row["nulled"] or 0) if cell_row else 0
    except Exception:
        cells_total, cells_compacted = 0, 0

    # For non-compacted cells, check if they're shared with experiments
    # that still have non-compacted timeline data
    cells_compactable = 0
    if cells_total > cells_compacted:
        try:
            compactable_row = conn.execute("""
                SELECT COUNT(*) as cnt
                FROM cell_lineage cl
                WHERE cl.source IS NOT NULL AND LENGTH(cl.source) > 0
                AND cl.cell_hash IN (
                    SELECT DISTINCT cell_hash FROM timeline
                    WHERE exp_id=? AND cell_hash IS NOT NULL
                )
                AND cl.cell_hash NOT IN (
                    SELECT DISTINCT t.cell_hash FROM timeline t
                    WHERE t.exp_id!=? AND t.cell_hash IS NOT NULL
                      AND t.source_diff IS NOT NULL
                )
            """, (exp_id, exp_id)).fetchone()
            cells_compactable = (compactable_row["cnt"] or 0) if compactable_row else 0
        except Exception:
            cells_compactable = 0

    # Check if timeline diffs are compacted
    try:
        tl_row = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN source_diff IS NOT NULL THEN 1 ELSE 0 END) as has_diff
            FROM timeline WHERE exp_id=? AND event_type IN ('cell_exec', 'observational')
        """, (exp_id,)).fetchone()
        tl_total = (tl_row["total"] or 0) if tl_row else 0
        tl_has_diff = (tl_row["has_diff"] or 0) if tl_row else 0
    except Exception:
        tl_total, tl_has_diff = 0, 0

    # Determine cell status
    if cells_total == 0:
        cell_status = "none"
    elif cells_compacted == cells_total:
        cell_status = "compacted"
    elif cells_compacted > 0 and cells_compactable == 0:
        cell_status = "shared"  # remaining cells are all shared
    elif cells_compacted > 0:
        cell_status = "partial"
    elif cells_compactable == 0:
        cell_status = "shared"  # all cells shared with other experiments
    else:
        cell_status = "stored"

    return {
        "diff": "compacted" if diff_compacted else ("clean" if not raw_git_diff else "stored"),
        "cells": cell_status,
        "timeline": "compacted" if (tl_total > 0 and tl_has_diff == 0) else ("none" if tl_total == 0 else "stored"),
    }


# ── Experiment listing ────────────────────────────────────────────────────────

def list_experiments(conn, limit: int = 50, status: str = "",
                     tag: str = "", study: str = "") -> list[dict]:
    """List experiments with last metrics and params."""
    clauses: list[str] = []
    params: list = []
    if status:
        clauses.append("status=?")
        params.append(status)
    if tag:
        clauses.append('tags LIKE ?')
        params.append(f'%"{tag}"%')
    if study:
        clauses.append('studies LIKE ?')
        params.append(f'%"{study}"%')
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    query = f"""
        SELECT id, project, name, status, created_at, duration_s,
               git_branch, git_commit, tags, studies, notes, output_dir,
               stage, stage_name
        FROM experiments {where}
        ORDER BY created_at DESC LIMIT ?
    """
    rows = conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        metrics = get_latest_metrics_with_source(conn, r["id"])
        sparklines = get_metrics_sparkline(conn, r["id"])
        ps = conn.execute(
            "SELECT key, value FROM params WHERE exp_id=?",
            (r["id"],)
        ).fetchall()
        all_params = {p["key"]: json.loads(p["value"]) for p in ps}
        result.append({
            "id": r["id"],
            "name": r["name"],
            "status": r["status"],
            "created_at": r["created_at"],
            "duration_s": r["duration_s"],
            "git_branch": r["git_branch"],
            "git_commit": r["git_commit"],
            "tags": json.loads(r["tags"] or "[]"),
            "studies": json.loads(r["studies"] or "[]"),
            "notes": r["notes"] or "",
            "output_dir": r["output_dir"] or "",
            "stage": r["stage"],
            "stage_name": r["stage_name"],
            "metrics": metrics,
            "sparklines": sparklines,
            "params": all_params,
        })
    return result


# ── Metrics ───────────────────────────────────────────────────────────────────



def get_latest_metrics(conn, exp_id: str) -> dict[str, float]:
    """Get the last value of each metric key for an experiment."""
    rows = conn.execute("""
        SELECT key, value FROM metrics m WHERE exp_id=?
        AND COALESCE(step, 0) = (
            SELECT MAX(COALESCE(step, 0)) FROM metrics m2
            WHERE m2.exp_id=m.exp_id AND m2.key=m.key
        )
    """, (exp_id,)).fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_latest_metrics_with_source(conn, exp_id: str) -> dict[str, dict]:
    """Get the last value and source of each metric key for an experiment."""
    rows = conn.execute("""
        SELECT key, value, COALESCE(source, 'auto') as source FROM metrics m WHERE exp_id=?
        AND COALESCE(step, 0) = (
            SELECT MAX(COALESCE(step, 0)) FROM metrics m2
            WHERE m2.exp_id=m.exp_id AND m2.key=m.key
        )
    """, (exp_id,)).fetchall()
    return {r["key"]: {"value": r["value"], "source": r["source"]} for r in rows}


def get_metrics_sparkline(conn, exp_id: str, max_points: int = 10) -> dict[str, list[float]]:
    """Get last N values per metric key for sparkline rendering."""
    rows = conn.execute("""
        SELECT key, value FROM metrics WHERE exp_id=?
        ORDER BY key, COALESCE(step, 0)
    """, (exp_id,)).fetchall()
    by_key: dict[str, list] = {}
    for r in rows:
        by_key.setdefault(r["key"], []).append(r["value"])
    return {k: v[-max_points:] for k, v in by_key.items()}


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
                AND m2.key=metrics.key ORDER BY COALESCE(step,0) DESC LIMIT 1) as last_v,
               (SELECT COALESCE(source, 'auto') FROM metrics m3 WHERE m3.exp_id=metrics.exp_id
                AND m3.key=metrics.key ORDER BY COALESCE(step,0) DESC LIMIT 1) as source
        FROM metrics WHERE exp_id=? GROUP BY key ORDER BY key
    """, (exp_id,)).fetchall()
    return [{
        "key": m["key"], "last": m["last_v"],
        "min": m["min_v"], "max": m["max_v"], "n": m["n"],
        "source": m["source"] or "auto",
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


def get_multi_compare(conn, exp_ids: list[str]) -> list[dict]:
    """Get experiment names, latest metrics for multiple experiments."""
    results = []
    for eid in exp_ids:
        exp = find_experiment(conn, eid, "id, name, status")
        if not exp:
            continue
        full_id = exp["id"]
        metrics = get_latest_metrics(conn, full_id)
        results.append({
            "id": full_id,
            "name": exp["name"],
            "status": exp["status"],
            "metrics": metrics,
        })
    return results


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

    # Git diff storage stats
    diff_rows = conn.execute(
        "SELECT LENGTH(git_diff) as sz FROM experiments "
        "WHERE git_diff IS NOT NULL AND git_diff != '' "
        "AND git_diff NOT LIKE '[compacted%' AND git_diff NOT LIKE '[ref:%'"
    ).fetchall()
    diff_total_bytes = sum(r["sz"] for r in diff_rows)
    diff_count = len(diff_rows)

    from .. import config as cfg
    conf = cfg.load()
    max_diff_kb = conf.get("max_git_diff_kb", 256)

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
        "diff_total_bytes": diff_total_bytes,
        "diff_count": diff_count,
        "max_diff_kb": max_diff_kb,
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
    """Return full source code for a cell by its content hash.

    Returns source/parent_source as None if compacted.
    """
    row = conn.execute(
        "SELECT source, parent_hash, notebook, created_at FROM cell_lineage WHERE cell_hash=?",
        (cell_hash,)
    ).fetchone()
    if not row:
        return None

    source = row["source"]  # may be None if compacted

    parent_source = None
    if row["parent_hash"]:
        parent = conn.execute(
            "SELECT source FROM cell_lineage WHERE cell_hash=?",
            (row["parent_hash"],)
        ).fetchone()
        if parent and parent["source"] is not None:
            parent_source = parent["source"]
    return {
        "cell_hash": cell_hash,
        "source": source,
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
        "diff": resolve_git_diff(conn, exp["git_diff"]),
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
        "studies": json.loads(exp["studies"] or "[]"),
        "notes": exp["notes"],
        "output_dir": exp["output_dir"] or "",
        "stage": exp["stage"],
        "stage_name": exp["stage_name"],
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


# ── Finish ─────────────────────────────────────────────────────────────────────

def finish_experiment(conn, exp_id_prefix: str) -> dict:
    """Mark a running experiment as done. Returns result dict.

    Used by both CLI cmd_finish and dashboard api_finish.
    """
    from datetime import datetime, timezone
    exp = conn.execute(
        "SELECT id, name, status, created_at FROM experiments WHERE id LIKE ?",
        (exp_id_prefix + "%",)
    ).fetchone()
    if not exp:
        return {"error": "not found"}
    if exp["status"] == "done":
        return {"ok": True, "id": exp["id"], "name": exp["name"],
                "status": "done", "message": "already done", "duration_s": None}
    now = datetime.now(timezone.utc).isoformat()
    duration = (datetime.fromisoformat(now) -
                datetime.fromisoformat(exp["created_at"])).total_seconds()
    prev_status = exp["status"]
    conn.execute("""
        UPDATE experiments SET status='done', updated_at=?, duration_s=? WHERE id=?
    """, (now, duration, exp["id"]))
    return {
        "ok": True, "id": exp["id"], "name": exp["name"],
        "prev_status": prev_status, "status": "done", "duration_s": duration,
    }


# ── Notes ─────────────────────────────────────────────────────────────────────

def append_note(conn, exp_id_prefix: str, text: str) -> dict:
    """Append text to an experiment's notes. Returns result dict."""
    from datetime import datetime, timezone
    exp = find_experiment(conn, exp_id_prefix, "id, notes")
    if not exp:
        return {"error": "not found"}
    existing = exp["notes"] or ""
    new_notes = (existing + "\n" + text).strip() if existing else text.strip()
    conn.execute(
        "UPDATE experiments SET notes=?, updated_at=? WHERE id=?",
        (new_notes, datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    return {"ok": True, "notes": new_notes}


def replace_notes(conn, exp_id_prefix: str, text: str) -> dict:
    """Replace an experiment's notes entirely. Records old notes in timeline."""
    from datetime import datetime, timezone
    exp = find_experiment(conn, exp_id_prefix, "id, notes")
    if not exp:
        return {"error": "not found"}
    old_notes = exp["notes"] or ""
    now = datetime.now(timezone.utc).isoformat()
    # Record note edit in timeline for history
    if old_notes and old_notes != text:
        try:
            max_seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM timeline WHERE exp_id=?",
                (exp["id"],)
            ).fetchone()[0]
            conn.execute("""
                INSERT INTO timeline (exp_id, seq, event_type, key, value, prev_value, ts)
                VALUES (?, ?, 'note_edit', 'notes', ?, ?, ?)
            """, (exp["id"], max_seq + 1, json.dumps(text), json.dumps(old_notes), now))
        except Exception:
            pass  # Don't fail the edit if timeline insert fails
    conn.execute(
        "UPDATE experiments SET notes=?, updated_at=? WHERE id=?",
        (text, now, exp["id"])
    )
    return {"ok": True, "notes": text}


# ── Export formatting ─────────────────────────────────────────────────────────

def get_batch_export_data(conn, exp_ids: list[str] | None = None,
                          export_all: bool = False) -> list[dict]:
    """Get export data for multiple experiments."""
    if export_all:
        rows = conn.execute(
            "SELECT id FROM experiments ORDER BY created_at DESC"
        ).fetchall()
    elif exp_ids:
        rows = []
        for eid in exp_ids:
            r = conn.execute(
                "SELECT id FROM experiments WHERE id LIKE ?",
                (eid + "%",)
            ).fetchone()
            if r:
                rows.append(r)
    else:
        return []
    return [get_export_data(conn, r["id"]) for r in rows if r]


def format_export_markdown(data: dict) -> str:
    """Generate a markdown summary of an experiment from export data."""
    lines = [
        f"# {data['name']}",
        "",
        f"**ID:** {data['id']}  ",
        f"**Status:** {data['status']}  ",
        f"**Created:** {data['created_at']}  ",
    ]
    if data.get('duration_s'):
        lines.append(f"**Duration:** {data['duration_s']}s  ")
    if data.get('script'):
        lines.append(f"**Script:** `{data['script']}`  ")
    if data.get('command'):
        lines.append(f"**Command:** `{data['command']}`  ")
    if data.get('python_ver'):
        lines.append(f"**Python:** {data['python_ver']}  ")
    if data.get('git_branch'):
        lines.append(f"**Git:** {data['git_branch']} @ {data['git_commit']}  ")
    if data.get('hostname'):
        lines.append(f"**Hostname:** {data['hostname']}  ")
    if data.get('tags'):
        lines.append(f"**Tags:** {', '.join(data['tags'])}  ")
    if data.get('studies'):
        lines.append(f"**Studies:** {', '.join(data['studies'])}  ")
    if data.get('stage') is not None:
        stage_str = str(data['stage'])
        if data.get('stage_name'):
            stage_str += f" ({data['stage_name']})"
        lines.append(f"**Stage:** {stage_str}  ")
    if data.get('output_dir'):
        lines.append(f"**Output Dir:** `{data['output_dir']}`  ")
    if data.get('project'):
        lines.append(f"**Project:** {data['project']}  ")
    lines.append("")
    if data.get("notes"):
        lines += ["## Notes", "", data["notes"], ""]
    if data.get("params"):
        lines += ["## Parameters", "", "| Key | Value |", "| --- | --- |"]
        for k, v in data["params"].items():
            lines.append(f"| {k} | {json.dumps(v)} |")
        lines.append("")
    if data.get("variables"):
        lines += ["## Variables", "", "| Name | Value |", "| --- | --- |"]
        for k, v in data["variables"].items():
            lines.append(f"| {k} | {json.dumps(v)} |")
        lines.append("")
    if data.get("metrics_series"):
        lines += ["## Metrics", "", "| Key | Last | Steps |", "| --- | --- | --- |"]
        for k, pts in data["metrics_series"].items():
            last = pts[-1]["value"] if pts else "--"
            lines.append(f"| {k} | {last} | {len(pts)} |")
        lines.append("")
    if data.get("artifacts"):
        lines += ["## Artifacts", ""]
        for a in data["artifacts"]:
            lines.append(f"- **{a['label']}**: `{a['path']}`")
        lines.append("")
    if data.get("code_changes"):
        lines += ["## Code Changes", ""]
        for name, diff in data["code_changes"].items():
            lines.append(f"### {name}")
            lines.append("```diff")
            lines.append(str(diff))
            lines.append("```")
            lines.append("")
    ts = data.get("timeline_summary", {})
    if ts.get("total_events"):
        lines += [
            "## Timeline Summary",
            "",
            f"- Total events: {ts['total_events']}",
            f"- Cell executions: {ts['cell_executions']}",
            f"- Variable changes: {ts['variable_sets']}",
            f"- Artifacts saved: {ts['artifact_events']}",
        ]
    return "\n".join(lines)


def format_export_csv(experiments: list[dict], delimiter: str = ",") -> str:
    """Format batch export data as CSV/TSV string.

    Includes all the same data as JSON export: metadata, params, variables,
    metrics (last value), code_changes, artifacts, and timeline summary.
    """
    import csv as csv_mod
    import io

    if not experiments:
        return ""

    # Collect all dynamic keys across experiments
    all_param_keys: set[str] = set()
    all_metric_keys: set[str] = set()
    all_var_keys: set[str] = set()
    for data in experiments:
        all_param_keys.update(k for k in data.get("params", {}) if not k.startswith("_"))
        all_metric_keys.update(data.get("metrics_series", {}).keys())
        all_var_keys.update(data.get("variables", {}).keys())

    param_keys = sorted(all_param_keys)
    metric_keys = sorted(all_metric_keys)
    var_keys = sorted(all_var_keys)

    output = io.StringIO()
    writer = csv_mod.writer(output, delimiter=delimiter)

    # Header — all fields from get_export_data()
    header = ["id", "name", "project", "status", "created_at", "duration_s",
              "script", "command", "python_ver", "git_branch", "git_commit",
              "hostname", "tags", "studies", "stage", "stage_name", "notes", "output_dir"]
    header += [f"param:{k}" for k in param_keys]
    header += [f"var:{k}" for k in var_keys]
    header += [f"metric:{k}" for k in metric_keys]
    header += ["artifacts", "code_changes",
               "timeline_total", "timeline_cells", "timeline_vars", "timeline_artifacts"]
    writer.writerow(header)

    # Rows
    for data in experiments:
        params = data.get("params", {})
        variables = data.get("variables", {})
        metrics_series = data.get("metrics_series", {})
        artifacts = data.get("artifacts", [])
        code_changes = data.get("code_changes", {})
        ts = data.get("timeline_summary", {})

        row = [
            data.get("id", ""),
            data.get("name", ""),
            data.get("project", ""),
            data.get("status", ""),
            data.get("created_at", ""),
            data.get("duration_s", "") or "",
            data.get("script", "") or "",
            data.get("command", "") or "",
            data.get("python_ver", "") or "",
            data.get("git_branch", "") or "",
            data.get("git_commit", "") or "",
            data.get("hostname", "") or "",
            ";".join(data.get("tags", [])),
            ";".join(data.get("studies", []) if isinstance(data.get("studies"), list) else []),
            data.get("stage", "") if data.get("stage") is not None else "",
            data.get("stage_name", "") or "",
            data.get("notes", "") or "",
            data.get("output_dir", "") or "",
        ]
        row += [str(params.get(k, "")) for k in param_keys]
        row += [str(variables.get(k, "")) for k in var_keys]
        for k in metric_keys:
            pts = metrics_series.get(k, [])
            row.append(str(pts[-1]["value"]) if pts else "")
        # Artifacts as semicolon-separated label:path pairs
        art_str = ";".join(f"{a.get('label','')}:{a.get('path','')}" for a in artifacts)
        # Code changes as semicolon-separated key:value
        cc_str = ";".join(f"{k}" for k in code_changes) if code_changes else ""
        row += [art_str, cc_str,
                ts.get("total_events", ""), ts.get("cell_executions", ""),
                ts.get("variable_sets", ""), ts.get("artifact_events", "")]
        writer.writerow(row)

    return output.getvalue()


# ── Studies ───────────────────────────────────────────────────────────────────

def update_experiment_studies(conn, exp_id: str, studies: list[str]):
    """Set the studies list for an experiment."""
    from datetime import datetime, timezone
    conn.execute(
        "UPDATE experiments SET studies=?, updated_at=? WHERE id=?",
        (json.dumps(studies), datetime.now(timezone.utc).isoformat(), exp_id)
    )


def get_all_studies(conn) -> list[dict]:
    """Get all studies with usage counts (like get_all_tags)."""
    rows = conn.execute(
        "SELECT studies FROM experiments WHERE studies IS NOT NULL AND studies != '[]'"
    ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        try:
            for s in json.loads(r["studies"] or "[]"):
                counts[s] = counts.get(s, 0) + 1
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return [{"name": n, "count": c} for n, c in sorted(counts.items())]


def get_studies(conn) -> list[dict]:
    """Get studies with summary stats."""
    rows = conn.execute(
        "SELECT id, studies, status, created_at FROM experiments "
        "WHERE studies IS NOT NULL AND studies != '[]'"
    ).fetchall()
    study_data: dict[str, list[dict]] = {}
    for r in rows:
        try:
            for s in json.loads(r["studies"] or "[]"):
                study_data.setdefault(s, []).append(dict(r))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    result = []
    for name, exps in sorted(study_data.items()):
        done = sum(1 for e in exps if e["status"] == "done")
        failed = sum(1 for e in exps if e["status"] == "failed")
        latest = max((e["created_at"] for e in exps), default=None)
        result.append({
            "name": name,
            "experiment_ids": [e["id"] for e in exps],
            "count": len(exps),
            "done": done,
            "failed": failed,
            "running": len(exps) - done - failed,
            "latest": latest,
        })
    return result


def add_to_study(conn, exp_id: str, study_name: str) -> list[str] | None:
    """Add an experiment to a study. Returns updated studies list."""
    exp = find_experiment(conn, exp_id, "id, studies")
    if not exp:
        return None
    studies = json.loads(exp["studies"] or "[]")
    if study_name not in studies:
        studies.append(study_name)
        update_experiment_studies(conn, exp["id"], studies)
    return studies


def remove_from_study(conn, exp_id: str, study_name: str) -> list[str] | None:
    """Remove an experiment from a study. Returns updated studies list."""
    exp = find_experiment(conn, exp_id, "id, studies")
    if not exp:
        return None
    studies = json.loads(exp["studies"] or "[]")
    studies = [s for s in studies if s != study_name]
    update_experiment_studies(conn, exp["id"], studies)
    return studies


def remove_study_global(conn, study_name: str) -> int:
    """Remove a study from all experiments. Returns count of affected rows."""
    rows = conn.execute(
        "SELECT id, studies FROM experiments WHERE studies LIKE ?",
        (f'%"{study_name}"%',)
    ).fetchall()
    count = 0
    for r in rows:
        try:
            studies = json.loads(r["studies"] or "[]")
            if study_name in studies:
                studies = [s for s in studies if s != study_name]
                update_experiment_studies(conn, r["id"], studies)
                count += 1
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return count


def update_experiment_stage(conn, exp_id: str, stage: int, stage_name: str | None = None):
    """Set stage number and optional label for a run."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    if stage_name is not None:
        conn.execute(
            "UPDATE experiments SET stage=?, stage_name=?, updated_at=? WHERE id=?",
            (stage, stage_name, now, exp_id)
        )
    else:
        conn.execute(
            "UPDATE experiments SET stage=?, updated_at=? WHERE id=?",
            (stage, now, exp_id)
        )
