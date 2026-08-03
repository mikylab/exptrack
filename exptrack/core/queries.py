"""
exptrack/core/queries.py — Shared database query functions

Used by both CLI commands and dashboard API to eliminate SQL duplication.
All functions accept a sqlite3.Connection and return plain dicts/lists.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from .db import diff_sentinel_kind, is_diff_sentinel, resolve_git_diff

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.tiff', '.webp')

# How many artifacts a rendering lists before summarising the rest. A
# checkpoint-per-epoch run produces thousands, and a flat list of them buries
# everything else in the export. This now applies to the JSON export too — it
# carries an `artifacts_summary` describing the shape of what was left out, and
# `full=True` (`exptrack export --full`, `?full=1`) restores the complete list
# for round-tripping.
ARTIFACT_LIST_LIMIT = 25

# How many directories the export's artifact/metric summaries name before
# stopping. Past this the tail is long-tail noise, not shape.
SUMMARY_DIR_LIMIT = 10

_ARTIFACT_KINDS = (
    ("model", ('.pt', '.pth', '.ckpt', '.safetensors', '.h5', '.hdf5', '.onnx',
               '.pkl', '.joblib', '.bin')),
    ("image", IMAGE_EXTS),
    ("data", ('.csv', '.json', '.jsonl', '.parquet', '.tsv', '.npy', '.npz',
              '.arrow', '.feather')),
    ("log", ('.log', '.txt', '.out', '.err')),
)


def artifact_kind(path: str) -> str:
    """Coarse type of an artifact path — the grouping key for summaries."""
    lower = str(path or "").lower()
    dot = lower.rfind(".")
    if dot == -1 or "/" in lower[dot:]:
        return "dir"
    ext = lower[dot:]
    for kind, exts in _ARTIFACT_KINDS:
        if ext in exts:
            return kind
    return "file"


def summarize_artifacts(artifacts: list, limit: int = ARTIFACT_LIST_LIMIT) -> dict:
    """Cap a long artifact list and describe what was left out.

    Returns the items to render plus counts by type and by containing
    directory, so a run with 4000 checkpoints reports its *shape* — "4000
    models under outputs/ckpts" — instead of 4000 indistinguishable lines.
    ``limit=0`` means no cap.
    """
    items = list(artifacts or [])
    by_kind: dict = {}
    by_dir: dict = {}
    for a in items:
        path = a.get("path") if isinstance(a, dict) else a["path"]
        by_kind[artifact_kind(path)] = by_kind.get(artifact_kind(path), 0) + 1
        parent = str(path or "").rsplit("/", 1)[0] if "/" in str(path or "") else "."
        by_dir[parent] = by_dir.get(parent, 0) + 1
    shown = items if not limit else items[:limit]
    return {
        "total": len(items),
        "shown": shown,
        "omitted": len(items) - len(shown),
        "by_type": sorted(by_kind.items(), key=lambda kv: -kv[1]),
        "by_dir": sorted(by_dir.items(), key=lambda kv: -kv[1]),
    }


def _rel_path(path: str) -> str:
    """Convert an absolute artifact path to relative from project root.

    Artifact paths are stored as absolute in the DB (via Path.resolve()),
    but the dashboard /api/file/ endpoint expects relative paths.
    """
    import os

    if not path or not os.path.isabs(path):
        return path
    try:
        from ..config import project_root
        return os.path.relpath(path, str(project_root()))
    except (ValueError, ImportError):
        return path


def _safe_json(s):
    """Parse a JSON string, returning the raw string if parsing fails."""
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return s


def _json_list(s, context: str = "") -> list:
    """Parse a ``tags``/``studies`` column into a list, never raising.

    These columns are JSON arrays, but a hand-edited DB, an older writer, or a
    third-party script can leave a bare string (``baseline`` instead of
    ``["baseline"]``) or outright garbage behind. A raw ``json.loads`` here used
    to propagate out of ``list_experiments`` and kill the *whole* request — one
    bad row blanked the entire dashboard with no error shown. Salvage what we
    can instead: a bare string becomes a one-element list, anything else an
    empty one, with a stderr warning when ``context`` names the caller.
    """
    if not s:
        return []
    try:
        v = json.loads(s)
    except (json.JSONDecodeError, ValueError, TypeError):
        # A bare, unquoted string is the common corruption — keep it as a label.
        text = str(s).strip()
        if context:
            print(f"[exptrack] warning: malformed JSON list in {context}: {s!r}",
                  file=sys.stderr)
        return [text] if text else []
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)]
    if isinstance(v, str):
        return [v] if v else []
    if context:
        print(f"[exptrack] warning: unexpected JSON list type in {context}: {type(v).__name__}",
              file=sys.stderr)
    return []

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
        "SELECT key, value, COALESCE(source, 'auto') as source "
        "FROM params WHERE exp_id=? ORDER BY key",
        (full_id,)
    ).fetchall()
    metrics = conn.execute("""
        SELECT key, COALESCE(source, 'auto') as src,
               MIN(value) as min_v, MAX(value) as max_v, COUNT(*) as n,
               MIN(step) as step_min, MAX(step) as step_max,
               (SELECT value FROM metrics m2 WHERE m2.exp_id=metrics.exp_id
                AND m2.key=metrics.key AND COALESCE(m2.source, 'auto')=COALESCE(metrics.source, 'auto')
                ORDER BY COALESCE(step,0) DESC LIMIT 1) as last_v
        FROM metrics WHERE exp_id=? GROUP BY key, COALESCE(source, 'auto') ORDER BY key, src
    """, (full_id,)).fetchall()
    artifacts = conn.execute(
        "SELECT label, path, created_at, timeline_seq FROM artifacts WHERE exp_id=?",
        (full_id,)
    ).fetchall()

    all_params = {p["key"]: json.loads(p["value"]) for p in params}
    # Surface the dataset manifest as its own key (and keep it out of the params
    # table — it's an internal `_`-prefixed bookkeeping param).
    datasets = all_params.pop("_dataset_manifest", {}) or {}
    # Surface the failure traceback (captured by Experiment.fail) as its own
    # `error` key so a failed run shows file+line, not just the short `error`
    # param. Keep it out of the params table.
    error_traceback = all_params.pop("_error_traceback", "") or ""

    # Did this run capture a script at all? The dashboard's code panel needs the
    # answer to decide whether it may say anything about "this run's script",
    # and it is a server-side fact: `_script_hash` is written by
    # `capture_script_snapshot` and nothing else, while `script` itself cannot
    # answer it (a notebook carries its `.ipynb` there and a pipeline run
    # carries a label). State it rather than leaving the client to infer it from
    # which internal param keys happen to be present.
    has_script_capture = bool(
        all_params.get("_script_hash")
        or all_params.get("_code_changes")
        or all_params.get("_code_status")
    )

    _resolved_diff = resolve_git_diff(conn, exp["git_diff"])

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
        "has_script_capture": has_script_capture,
        "git_branch": exp["git_branch"],
        "git_commit": exp["git_commit"],
        "git_diff": _resolved_diff,
        # A sentinel (capture-failed / unavailable / compacted marker) is a
        # status, not diff content — counting it as "1 line" made the detail
        # header claim the run had one line of uncommitted changes.
        "diff_lines": 0 if is_diff_sentinel(_resolved_diff)
                      else len(_resolved_diff.splitlines()),
        "hostname": exp["hostname"],
        "python_ver": exp["python_ver"],
        "notes": exp["notes"],
        "tags": _json_list(exp["tags"], "experiment_detail.tags"),
        "studies": _json_list(exp["studies"], "experiment_detail.studies"),
        "output_dir": exp["output_dir"] or "",
        "stage": exp["stage"],
        "stage_name": exp["stage_name"],
        "params": all_params,
        "param_sources": {p["key"]: p["source"] for p in params},
        "datasets": datasets,
        "error": error_traceback,
        "metrics": [{
            "key": m["key"], "last": m["last_v"],
            "min": m["min_v"], "max": m["max_v"], "n": m["n"],
            "source": m["src"],
            "step_min": m["step_min"], "step_max": m["step_max"],
        } for m in metrics],
        "artifacts": [{"label": a["label"], "path": _rel_path(a["path"]),
                       "timeline_seq": a["timeline_seq"]} for a in artifacts],
        "compact_status": _get_compact_status(conn, full_id, exp["git_diff"]),
        "session_origin": _session_origin(conn, exp["session_node_id"]),
        # The run this one was declared a variant of, if any — the detail view
        # renders it as the baseline the deltas are computed against.
        "variant_of": get_variant_of(conn, full_id),
    }


def find_latest_by_script(conn, script: str) -> dict | None:
    """The most recent surviving run of *script*, newest first.

    Backs post-hoc logging (``%exp_log`` / ``notebook.log_last``): "I ran the
    notebook, it finished, and now I have the test numbers to attach." Trashed
    runs are excluded for the same reason they can't be a baseline — a run the
    user deleted is gone from every list, so silently appending today's
    accuracy to it would put the number somewhere they cannot see it.

    Ordered by ``(created_at, rowid)`` because two runs launched inside the
    same clock tick tie on the timestamp; ``rowid`` is insertion order, so the
    genuinely-latest run wins rather than whichever SQLite happened to emit.
    """
    if not script:
        return None
    row = conn.execute(
        """
        SELECT id, name, status, created_at
        FROM experiments
        WHERE script = ? AND deleted_at IS NULL
        ORDER BY created_at DESC, rowid DESC LIMIT 1
        """,
        (script,),
    ).fetchone()
    return dict(row) if row else None


def find_previous_by_script(conn, exp_id: str) -> dict | None:
    """Find the chronologically-previous experiment that used the same script.

    Backs the dashboard Overview's "What changed" card — auto-diffing a run
    against the last attempt at the same script means the "changed one line,
    reran" workflow gets a param diff without the user ever renaming a run.
    Returns None if this experiment has no script recorded or no earlier run
    shares it. See ``_BASELINE_WHERE`` for which runs can be a baseline.

    A run that declared a ``_variant_of`` target compares against *that* run
    instead: re-running one notebook with a different model is the case where
    "the previous run of this script" is the wrong baseline.
    """
    explicit = _explicit_baseline(conn, exp_id)
    if explicit:
        return {
            "id": explicit["id"], "name": explicit["name"],
            "created_at": explicit["created_at"], "status": explicit["status"] or "",
            "explicit": True,
            "params": get_params_batch(conn, [explicit["id"]]).get(explicit["id"], {}),
            "metrics": get_latest_metrics(conn, explicit["id"]),
        }
    # (created_at, rowid) rather than created_at alone — see get_previous_run:
    # runs launched in the same clock tick tie, and the tie-break decided whether
    # "previous" pointed backwards or forwards in time.
    prev = conn.execute(
        """
        SELECT prev.id AS id, prev.name AS name, prev.created_at AS created_at,
               prev.status AS status
        FROM experiments cur
        JOIN experiments prev
          ON prev.script = cur.script AND prev.script IS NOT NULL
         AND (prev.created_at, prev.rowid) < (cur.created_at, cur.rowid)
         AND prev.deleted_at IS NULL
         AND prev.status != 'running'
        WHERE cur.id = ?
        ORDER BY prev.created_at DESC, prev.rowid DESC LIMIT 1
        """,
        (exp_id,),
    ).fetchone()
    if not prev:
        return None
    params = get_params_batch(conn, [prev["id"]]).get(prev["id"], {})
    return {
        "id": prev["id"], "name": prev["name"], "created_at": prev["created_at"],
        # Carried so the card can say the baseline crashed — its metrics stop
        # wherever it died, which a bare delta would present as a real result.
        "status": prev["status"] or "",
        "params": params,
        "metrics": get_latest_metrics(conn, prev["id"]),
    }


def _session_origin(conn, session_node_id) -> dict | None:
    """Build the session back-link context for an experiment that came from (or
    is linked to) a Session Trees node, so the detail view can render a
    breadcrumb back to the session/checkpoint/branch. Returns None when the run
    has no session origin (or the node was deleted)."""
    if not session_node_id:
        return None
    node = conn.execute(
        "SELECT n.id, n.label, n.node_type, n.parent_id, n.session_id, "
        "s.name AS sess_name, s.status AS sess_status, "
        "s.deleted_at AS sess_deleted_at "
        "FROM session_nodes n LEFT JOIN sessions s ON s.id = n.session_id "
        "WHERE n.id=? AND n.deleted_at IS NULL",
        (session_node_id,),
    ).fetchone()
    if not node:
        return None
    from ..sessions.manager import _node_lineage_labels
    return {
        "node_id": node["id"],
        "session_id": node["session_id"],
        "session_name": node["sess_name"] or "session",
        "session_status": node["sess_status"],
        # The session may itself be in the Trash while this run and node stay
        # live — the session list hides it, so the banner has to say so instead
        # of offering a link to something the user can't find anywhere else.
        "session_deleted": node["sess_deleted_at"] is not None,
        "node_label": node["label"],
        "node_type": node["node_type"],
        "lineage": _node_lineage_labels(conn, node["id"]),
        "siblings": _sibling_branches(conn, node["parent_id"], node["id"]),
    }


def _last_cell_output(blob) -> str:
    """Last non-empty per-cell output from a node's SEP-joined cell_outputs blob."""
    from ..sessions.manager import SessionManager
    if not blob:
        return ""
    parts = [p.strip() for p in blob.split(SessionManager._CELL_SEPARATOR)]
    parts = [p for p in parts if p]
    return parts[-1] if parts else ""


def _sibling_branches(conn, parent_id, this_node_id) -> list[dict]:
    """The other branches tried from the same parent checkpoint, with each one's
    captured result + linked experiment, so a promoted run can show the
    exploratory context it came out of (what else was tried, how it compared)."""
    if not parent_id:
        return []
    rows = conn.execute(
        "SELECT n.id, n.label, n.node_type, n.cell_outputs, "
        "e.id AS exp_id "
        "FROM session_nodes n "
        "LEFT JOIN experiments e ON e.session_node_id = n.id AND e.deleted_at IS NULL "
        "WHERE n.parent_id=? AND n.deleted_at IS NULL ORDER BY n.seq",
        (parent_id,),
    ).fetchall()
    out = []
    for r in rows:
        result = _last_cell_output(r["cell_outputs"])
        if len(result) > 120:
            result = result[:119] + "…"
        out.append({
            "node_id": r["id"],
            "label": r["label"],
            "node_type": r["node_type"],
            "exp_id": r["exp_id"],
            "result": result,
            "is_this": r["id"] == this_node_id,
        })
    return out


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
            SELECT SUM(CASE WHEN source_diff IS NOT NULL
                             AND source_diff NOT LIKE '[compacted%'
                            THEN 1 ELSE 0 END) as has_diff,
                   SUM(CASE WHEN source_diff LIKE '[compacted%'
                            THEN 1 ELSE 0 END) as marked
            FROM timeline WHERE exp_id=? AND event_type IN ('cell_exec', 'observational')
        """, (exp_id,)).fetchone()
        tl_has_diff = (tl_row["has_diff"] or 0) if tl_row else 0
        tl_marked = (tl_row["marked"] or 0) if tl_row else 0
    except Exception:
        tl_has_diff, tl_marked = 0, 0

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
        # Only a marker proves a diff was stripped. A NULL source_diff is the
        # normal state for a script run against a clean tree — reading that as
        # "compacted" told users their source had been reclaimed when nothing
        # had touched it. No marker and no diff simply means nothing stored.
        "timeline": ("compacted" if tl_marked
                     else "stored" if tl_has_diff else "none"),
    }


# ── Experiment listing ────────────────────────────────────────────────────────

def list_experiments(conn, limit: int = 50, status: str = "",
                     tag: str = "", study: str = "",
                     include_trashed: bool = False, offset: int = 0) -> list[dict]:
    """List experiments with last metrics and params.

    Trashed experiments (``deleted_at IS NOT NULL``) are excluded unless
    *include_trashed* is True. *offset* pages past the first N rows (used by
    the dashboard's "Load more" — the list is ``ORDER BY created_at DESC``).
    """
    clauses: list[str] = []
    params: list = []
    if not include_trashed:
        clauses.append("deleted_at IS NULL")
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
    params.append(max(0, offset))
    query = f"""
        SELECT id, project, name, status, created_at, duration_s,
               git_branch, git_commit, tags, studies, notes, output_dir,
               stage, stage_name, script, COALESCE(name_is_auto, 0) AS name_is_auto
        FROM experiments {where}
        ORDER BY created_at DESC LIMIT ? OFFSET ?
    """
    rows = conn.execute(query, params).fetchall()
    # Batch-load metrics, sparklines, and params for every listed experiment in
    # three queries total instead of three queries *per* experiment (the old
    # N+1 pattern that made this — the dashboard's hottest path — scale poorly).
    ids = [r["id"] for r in rows]
    metrics_by_exp = get_latest_metrics_with_source_batch(conn, ids)
    sparklines_by_exp = get_metrics_sparkline_batch(conn, ids)
    params_by_exp = get_params_batch(conn, ids)
    result = []
    for r in rows:
        result.append({
            "id": r["id"],
            "name": r["name"],
            "status": r["status"],
            "created_at": r["created_at"],
            "duration_s": r["duration_s"],
            "git_branch": r["git_branch"],
            "git_commit": r["git_commit"],
            "script": r["script"] or "",
            "tags": _json_list(r["tags"], "list_experiments.tags"),
            "studies": _json_list(r["studies"], "list_experiments.studies"),
            "notes": r["notes"] or "",
            "output_dir": r["output_dir"] or "",
            "stage": r["stage"],
            "stage_name": r["stage_name"],
            "name_is_auto": bool(r["name_is_auto"]),
            "metrics": metrics_by_exp.get(r["id"], {}),
            "sparklines": sparklines_by_exp.get(r["id"], {}),
            "params": params_by_exp.get(r["id"], {}),
        })
    return result


# ── Metrics ───────────────────────────────────────────────────────────────────


def last_metrics(conn, exp_id: str) -> dict:
    """Latest value per metric key (by step, then ts, then insert order).

    Ordering ascending and letting later rows overwrite earlier ones means the
    highest-step (then latest-ts, then last-inserted) value wins. Unlike the old
    ``GROUP BY key HAVING MAX(COALESCE(step,0))`` SQL, step-less metrics (the
    common ``log_metric(k, v)`` case, where every step is NULL) are kept rather
    than dropped by the boolean HAVING filter.
    """
    rows = conn.execute(
        "SELECT key, value FROM metrics WHERE exp_id=? "
        "ORDER BY COALESCE(step, -1), ts, rowid", (exp_id,)
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


# Which runs may serve as a "previous run" baseline. Both baseline lookups
# (get_previous_run, find_previous_by_script) apply this, so the strip, the
# "What changed" card and the finish-time summary always agree on the baseline.
#
#   - Trashed runs are excluded. They're gone from every list, so a delta
#     against one shows a baseline the user can't find, open or verify — and
#     deleting the run between two attempts silently changes the numbers with
#     no visible cause. Excluding them means "previous" simply walks back to
#     the next surviving run, which is what the list shows.
#   - `running` runs are excluded. Their metrics are still moving, so a delta
#     against one doesn't reproduce a minute later, and a parallel sweep would
#     otherwise compare each run against a half-finished sibling. (A run left
#     `running` by a killed process is what `exptrack stale` / `finish` are
#     for; until then it isn't a comparable result.)
#   - `failed` runs are KEPT. "it broke, I fixed it, what changed?" is the loop
#     this whole affordance exists for, and skipping past the failure would
#     hide exactly the comparison the user wants. The baseline's status rides
#     along on the payload instead, so the UI can flag that its metrics stop
#     where it crashed.
_BASELINE_WHERE = "deleted_at IS NULL AND status != 'running'"


VARIANT_OF_KEY = "_variant_of"


def get_variant_of(conn, exp_id: str) -> str | None:
    """The run this one was explicitly declared a variant of, if any.

    Stored as the ``_variant_of`` param rather than a column: it is internal
    bookkeeping, so the ``_`` prefix already keeps it out of run naming, the
    params table and the "what changed" diff, and it needs no migration.
    """
    row = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key=?",
        (exp_id, VARIANT_OF_KEY),
    ).fetchone()
    if not row:
        return None
    raw = row["value"]
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        val = raw
    return val if isinstance(val, str) and val else None


def _explicit_baseline(conn, exp_id: str) -> dict | None:
    """Resolve the declared ``_variant_of`` target to a usable baseline row.

    "Same notebook, swapped the model" is the case chronology gets wrong: the
    run you mean to compare against is often not the one that happened to run
    last. When a target is declared it wins over the chronological pick.

    Falls back to chronological (returns None) when the target is missing or
    can't be a baseline (trashed, still running) — a stale link must degrade to
    the old behaviour rather than leaving the run with no comparison at all.
    """
    target = get_variant_of(conn, exp_id)
    if not target or target == exp_id:
        return None
    row = conn.execute(
        "SELECT id, name, script, status, created_at, git_commit, git_diff "
        f"FROM experiments WHERE id=? AND {_BASELINE_WHERE}",
        (target,),
    ).fetchone()
    if not row:
        return None
    out = dict(row)
    out["explicit"] = True
    return out


def set_variant_of(conn, exp_id: str, target_id: str) -> dict:
    """Declare (or clear, with a falsy *target_id*) this run's baseline.

    Returns ``{"ok": True, ...}`` or ``{"error": ...}``. Rejects self-links and
    a target that doesn't exist; a one-step cycle (A→B while B→A) is refused
    too, since neither run would then have a stable baseline.
    """
    this = find_experiment(conn, exp_id, "id")
    if not this:
        return {"error": "not found"}
    exp_id = this["id"]

    if not target_id:
        conn.execute("DELETE FROM params WHERE exp_id=? AND key=?",
                     (exp_id, VARIANT_OF_KEY))
        conn.commit()
        return {"ok": True, "variant_of": None}

    target = find_experiment(conn, target_id, "id, name")
    if not target:
        return {"error": f"run '{target_id}' not found"}
    if target["id"] == exp_id:
        return {"error": "a run cannot be a variant of itself"}
    if get_variant_of(conn, target["id"]) == exp_id:
        return {"error": f"'{target['name']}' is already a variant of this run"}

    conn.execute(
        "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?) "
        "ON CONFLICT(exp_id, key) DO UPDATE SET value=excluded.value",
        (exp_id, VARIANT_OF_KEY, json.dumps(target["id"]), "manual"),
    )
    conn.commit()
    return {"ok": True, "variant_of": target["id"], "name": target["name"]}


def get_previous_run(conn, exp_id: str) -> dict | None:
    """The previous run of the same script (next-older by created_at).

    Backs the "what changed since last time" affordance: the most recent run of
    the same ``script`` created strictly before this one, restricted to runs
    that can be a baseline (see ``_BASELINE_WHERE``) and excluding the run
    itself. Returns a row dict (id, name, status, created_at, ...) or None.

    Ordered by ``(created_at, rowid)``, not ``created_at`` alone: two runs
    launched inside the same clock tick tie on the timestamp, and the tie-break
    was whatever order SQLite happened to return — so "previous" could resolve
    to the run that started *after* this one. ``rowid`` is insertion order, which
    is launch order, so the pair always resolves the same way and always
    backwards in time.
    """
    this = find_experiment(conn, exp_id, "id, script, created_at, rowid AS _rid")
    if not this:
        return None
    # An explicitly declared baseline wins over chronology — see _explicit_baseline.
    explicit = _explicit_baseline(conn, this["id"])
    if explicit:
        return explicit
    row = conn.execute(
        "SELECT id, name, script, status, created_at, git_commit, git_diff "
        "FROM experiments "
        f"WHERE script=? AND {_BASELINE_WHERE} "
        "  AND (created_at, rowid) < (?, ?) "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (this["script"], this["created_at"], this["_rid"]),
    ).fetchone()
    return dict(row) if row else None


def _run_code_signature(conn, exp_id: str) -> tuple:
    """A coarse (commit, diff, script_hash) signature used to tell whether two
    runs' code differs without a full diff. script_hash comes from the
    ``_script_hash`` param captured by ``capture_script_snapshot``.

    This describes the whole **repository state**, not the run's own code — the
    ``git_diff`` is the entire working tree — so use ``_run_source_identity``
    when the question is "did *this run's* code change?".
    """
    row = find_experiment(conn, exp_id, "git_commit, git_diff")
    commit = (row or {}).get("git_commit") or ""
    diff = (row or {}).get("git_diff") or ""
    sh = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key='_script_hash'", (exp_id,)
    ).fetchone()
    return (commit, diff, sh["value"] if sh else "")


def _run_source_identity(conn, exp_id: str) -> tuple | None:
    """Content identity of the code a run actually executed, or None when the
    run captured none.

    The same sources ``compare_run_code`` diffs: a script run's content-addressed
    snapshot hash, or a notebook run's ordered executed-cell hashes. Comparing
    these answers "did this run's code change?" precisely, which the
    repository-wide ``_run_code_signature`` cannot — an edit to any other tracked
    file in the project moves that signature, so a byte-identical rerun was
    reported as "code changed" right next to a Code-changes panel that (reading
    these same snapshots) correctly said nothing had changed.
    """
    row = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key='_code_snapshot'", (exp_id,)
    ).fetchone()
    if row:
        entries = _safe_json(row["value"])
        if isinstance(entries, str):        # legacy double-encoded rows
            entries = _safe_json(entries)
        if isinstance(entries, list):
            hashes = tuple(
                e["hash"] for e in entries
                if isinstance(e, dict) and e.get("hash")
            )
            if hashes:
                return ("snapshot", *hashes)

    cells = conn.execute(
        "SELECT cell_hash FROM timeline WHERE exp_id=? AND event_type='cell_exec' "
        "AND cell_hash IS NOT NULL ORDER BY seq",
        (exp_id,),
    ).fetchall()
    if cells:
        return ("cells", *(r["cell_hash"] for r in cells))
    return None


# Floats that differ only in the last bits are not a change. `0.9 + 0.03` and
# `0.85 + 0.04 * 2` are both "0.93" but differ by 1.1e-16, which surfaced as a
# metric change rendering "▼ -0.0000 (-0.0%)" — a delta that reads as zero on a
# row claiming something moved. Scaled to the magnitudes involved so it stays a
# noise filter and never swallows a real small change.
_METRIC_EPS_REL = 1e-12


def _metric_moved(a, b) -> bool:
    """True when a metric genuinely changed between two runs (not float noise)."""
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a != b
    return abs(fb - fa) > _METRIC_EPS_REL * max(1.0, abs(fa), abs(fb))


def diff_runs(conn, base_id: str, new_id: str) -> dict:
    """Structured delta between two runs (base → new): param changes, metric
    moves, and a coarse code-changed signal. Used by the finish-time summary and
    the dashboard "vs previous" strip. Never raises on missing runs — returns
    empty sections instead.
    """
    def _params(eid):
        return {
            r["key"]: r["value"]
            for r in conn.execute(
                "SELECT key, value FROM params WHERE exp_id=?", (eid,)
            ).fetchall()
            if not r["key"].startswith("_")
        }

    pa, pb = _params(base_id), _params(new_id)
    param_changes = []
    for k in sorted(set(pa) | set(pb)):
        va, vb = pa.get(k), pb.get(k)
        if va != vb:
            param_changes.append({"key": k, "from": va, "to": vb})

    ma, mb = last_metrics(conn, base_id), last_metrics(conn, new_id)
    metric_changes = []
    for k in sorted(set(ma) | set(mb)):
        va, vb = ma.get(k), mb.get(k)
        # A metric present on only one run isn't a value change — it was simply
        # not measured on the other side. Skip it so comparing against a run that
        # logged no (or different) metrics doesn't flood the delta with
        # None→value rows (e.g. a run made before metric logging was added, or an
        # empty phantom run). A genuine value move still has both sides present.
        if va is None or vb is None:
            continue
        if _metric_moved(va, vb):
            delta = None
            try:
                delta = float(vb) - float(va)
            except (TypeError, ValueError):
                delta = None
            metric_changes.append({"key": k, "from": va, "to": vb, "delta": delta})

    sig_a, sig_b = _run_code_signature(conn, base_id), _run_code_signature(conn, new_id)
    # Two separate facts, kept separate: `source_changed` is this run's own code
    # (what the Code-changes panel diffs), `code_changed` is the repository state
    # around it. Collapsing them into one flag made the strip claim "code
    # changed" for an edit to an unrelated file.
    src_a, src_b = _run_source_identity(conn, base_id), _run_source_identity(conn, new_id)
    return {
        "base_id": base_id,
        "new_id": new_id,
        "param_changes": param_changes,
        "metric_changes": metric_changes,
        "code_changed": sig_a != sig_b,
        # None when either run captured no source, so a caller can tell "the
        # source is the same" from "we don't know".
        "source_changed": None if (src_a is None or src_b is None) else src_a != src_b,
    }


def _run_cells(conn, exp_id: str) -> list[dict]:
    """Ordered code cells actually run by an experiment, each with full source.

    Reads the run's ``cell_exec`` timeline events (in execution order) and joins
    each to its content-addressed source in ``cell_lineage``. Used by
    ``compare_run_code`` to pair cells across two runs and surface the edit —
    the notebook analogue of a script's git diff (notebook JSON is excluded from
    git_diff by design, so the cell edit only lives here).
    """
    rows = conn.execute(
        """SELECT t.cell_pos, t.cell_hash, cl.source
           FROM timeline t
           LEFT JOIN cell_lineage cl ON t.cell_hash = cl.cell_hash
           WHERE t.exp_id=? AND t.event_type='cell_exec'
           ORDER BY t.seq""",
        (exp_id,),
    ).fetchall()
    return [{"cell_pos": r["cell_pos"], "cell_hash": r["cell_hash"],
             "source": r["source"]} for r in rows]


def _script_snapshot_source(conn, exp_id: str) -> str | None:
    """Full script source snapshot for a run, via the ``_code_snapshot`` param
    (content-addressed in ``code_snapshots``). None when the run has no snapshot
    (e.g. a notebook run, or a pre-L3 run)."""
    from .db import get_code_snapshot
    row = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key='_code_snapshot'", (exp_id,)
    ).fetchone()
    if not row:
        return None
    entries = _safe_json(row["value"])
    # Legacy rows (before script_tracking stopped pre-encoding the list) stored
    # the value double-JSON-encoded, so one unwrap yields a string — decode again.
    if isinstance(entries, str):
        entries = _safe_json(entries)
    if not isinstance(entries, list):
        return None
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("kind") == "script" and e.get("hash"):
            snap = get_code_snapshot(conn, e["hash"])
            if snap and snap.get("content") is not None:
                return snap["content"]
    return None


def compare_run_code(conn, id_a: str, id_b: str) -> dict:
    """Code diff between two runs, for the Compare view's cell-edit panel —
    "what code changed between these two attempts?".

    The two ids may be passed in any order; the pair is resolved and ordered
    older → newer by ``created_at`` so the diff always reads base (older) → new
    (newer). The chosen ids are returned as ``base_id`` / ``new_id``.

    - Notebook runs: pairs each run's executed cells (by notebook position when
      known, else execution order) and returns the pairs whose source differs,
      as ``{pos, label, a, b}`` for the shared line/word diff renderer.
    - Script runs: returns a single pair from the ``_code_snapshot`` full-source
      snapshots (``label='script'``).

    Never raises — returns ``{mode: 'none', cells: []}`` (with ``base_id`` /
    ``new_id`` None) when a run is missing or there's nothing to diff.
    """
    ra = find_experiment(conn, id_a, "id, created_at")
    rb = find_experiment(conn, id_b, "id, created_at")
    if not ra or not rb:
        return {"mode": "none", "cells": [], "base_id": None, "new_id": None}
    if (rb.get("created_at") or "") < (ra.get("created_at") or ""):
        ra, rb = rb, ra
    base_id, new_id = ra["id"], rb["id"]
    result = _compare_code(conn, base_id, new_id)
    result["base_id"], result["new_id"] = base_id, new_id
    return result


def _compare_code(conn, base_id: str, new_id: str) -> dict:
    """Ordered (base → new) code diff — see ``compare_run_code``."""
    # ── Script snapshot diff (L3 real-command / snapshot capture) ──────────
    sa = _script_snapshot_source(conn, base_id)
    sb = _script_snapshot_source(conn, new_id)
    if sa is not None or sb is not None:
        cells = ([] if (sa or "") == (sb or "")
                 else [{"pos": None, "label": "script", "a": sa or "", "b": sb or ""}])
        return {"mode": "script", "cells": cells}

    # ── Notebook cell diff ─────────────────────────────────────────────────
    cells_a = _run_cells(conn, base_id)
    cells_b = _run_cells(conn, new_id)
    if not cells_a and not cells_b:
        return {"mode": "none", "cells": []}

    def _key(c, idx):
        # Pair by notebook cell position when both sides recorded it; otherwise
        # fall back to execution order so pre-cell_pos runs still line up.
        return c["cell_pos"] if c["cell_pos"] is not None else f"#{idx}"

    map_a = {_key(c, i): c for i, c in enumerate(cells_a)}
    map_b = {_key(c, i): c for i, c in enumerate(cells_b)}
    # Sort ints (real cell positions) ahead of the "#N" execution-order fallback.
    ordered = sorted(set(map_a) | set(map_b),
                     key=lambda k: (0, k) if isinstance(k, int) else (1, k))

    changed = []
    for k in ordered:
        ca, cb = map_a.get(k), map_b.get(k)
        # Content-addressed identity: equal hashes ⇒ identical cell (robust even
        # when the stored source is NULL after compaction), so skip.
        if ca and cb and ca["cell_hash"] == cb["cell_hash"]:
            continue
        a_src = (ca["source"] if ca else "") or ""
        b_src = (cb["source"] if cb else "") or ""
        if a_src == b_src:
            continue
        pos = k if isinstance(k, int) else None
        label = f"cell {pos}" if pos is not None else "cell"
        changed.append({"pos": pos, "label": label, "a": a_src, "b": b_src})

    return {"mode": "cells", "cells": changed}


def _fmt_val(v) -> str:
    """Short display for a param/metric value (trim long floats)."""
    if isinstance(v, float):
        return f"{v:.4g}"
    s = str(v)
    return s if len(s) <= 24 else s[:21] + "…"


def format_run_delta(diff: dict, prev_row: dict | None) -> str:
    """One-line human summary of diff_runs(), or '' if nothing changed.

    e.g. "vs prev (a3f2c1, 12m ago): lr 0.01→0.02 · code changed · acc 0.84→0.87"
    """
    parts = []
    for c in diff.get("param_changes", [])[:4]:
        parts.append(f"{c['key']} {_fmt_val(c['from'])}→{_fmt_val(c['to'])}")
    extra_p = len(diff.get("param_changes", [])) - 4
    if extra_p > 0:
        parts.append(f"+{extra_p} more params")
    # Prefer the precise signal; fall back to the repository one only when the
    # run's own source couldn't be determined, and name it for what it is
    # otherwise (see diff_runs).
    src = diff.get("source_changed")
    if src or (src is None and diff.get("code_changed")):
        parts.append("code changed")
    elif diff.get("code_changed"):
        parts.append("repo changed elsewhere")
    for c in diff.get("metric_changes", [])[:4]:
        parts.append(f"{c['key']} {_fmt_val(c['from'])}→{_fmt_val(c['to'])}")
    if not parts:
        return ""
    label = "prev"
    if prev_row:
        who = prev_row.get("name") or (prev_row.get("id") or "")[:6]
        # Name the baseline's failure: its metrics stop where it crashed, so a
        # bare "acc 0.4→0.87" against it reads as a win that wasn't measured.
        if prev_row.get("status") == "failed":
            who += ", failed"
        label = f"prev ({who})"
    return f"vs {label}: " + " · ".join(parts)


def _latest_metric_rows(conn, exp_ids: list[str]):
    """One row per (exp_id, key): its latest value + source, and how many
    distinct sources that key has (so the caller can mark it "mixed").

    This is the single hot query behind the experiment list, so how it's
    written matters. It used to find the latest point with a *correlated*
    subquery per row --

        WHERE COALESCE(step,0) = (SELECT MAX(COALESCE(step,0)) FROM metrics m2
                                  WHERE m2.exp_id=m.exp_id AND m2.key=m.key)

    -- plus a second correlated subquery for the distinct-source count. Each
    one re-scans the whole (exp_id, key) group *for every row in that group*,
    so the cost is quadratic in points-per-metric: fine on a toy project,
    but a real training run logs thousands of points per key, and ~70 runs x
    5 keys x 2k points (680k rows, an unremarkable size) never finished. The
    dashboard's `/api/experiments` hung forever while `/api/stats` -- which
    doesn't touch metrics -- returned instantly, so the page rendered its
    headline counts above a permanently empty table.

    Two window/aggregate passes over the same indexed row set replace both
    correlated subqueries: linear instead of quadratic.

    Ordering by ``(step, ts, rowid)`` also makes the pick deterministic. The
    old query returned *every* row tied at the max step and let the Python
    dict comprehension keep whichever SQLite happened to emit last; now the
    genuinely last-logged point wins, matching ``last_metrics``.
    """
    ph = ",".join("?" * len(exp_ids))
    return conn.execute(f"""
        WITH scoped AS (
            SELECT exp_id, key, value, COALESCE(source, 'auto') AS source,
                   COALESCE(step, 0) AS step_n, ts, rowid AS rid
            FROM metrics WHERE exp_id IN ({ph})
        ),
        latest AS (
            SELECT exp_id, key, value, source,
                   ROW_NUMBER() OVER (PARTITION BY exp_id, key
                                      ORDER BY step_n DESC, ts DESC, rid DESC) AS rn
            FROM scoped
        ),
        sources AS (
            SELECT exp_id, key, COUNT(DISTINCT source) AS source_count
            FROM scoped GROUP BY exp_id, key
        )
        SELECT l.exp_id, l.key, l.value, l.source, s.source_count
        FROM latest l
        JOIN sources s ON s.exp_id = l.exp_id AND s.key = l.key
        WHERE l.rn = 1
    """, exp_ids).fetchall()


def get_latest_metrics(conn, exp_id: str) -> dict[str, float]:
    """Get the last value of each metric key for an experiment."""
    return {r["key"]: r["value"] for r in _latest_metric_rows(conn, [exp_id])}


def get_latest_metrics_with_source(conn, exp_id: str) -> dict[str, dict]:
    """Get the last value and source of each metric key for an experiment."""
    return {r["key"]: {
        "value": r["value"],
        "source": "mixed" if r["source_count"] > 1 else r["source"],
    } for r in _latest_metric_rows(conn, [exp_id])}


def get_latest_metrics_with_source_batch(conn, exp_ids: list[str]) -> dict[str, dict[str, dict]]:
    """Batched ``get_latest_metrics_with_source`` for many experiments at once."""
    if not exp_ids:
        return {}
    out: dict[str, dict] = {e: {} for e in exp_ids}
    for r in _latest_metric_rows(conn, exp_ids):
        out[r["exp_id"]][r["key"]] = {
            "value": r["value"],
            "source": "mixed" if r["source_count"] > 1 else r["source"],
        }
    return out


def get_metrics_sparkline_batch(conn, exp_ids: list[str],
                                max_points: int = 10) -> dict[str, dict[str, list[float]]]:
    """Batched ``get_metrics_sparkline`` — last N points per (exp, key) in one query."""
    if not exp_ids:
        return {}
    ph = ",".join("?" * len(exp_ids))
    rows = conn.execute(f"""
        SELECT exp_id, key, value FROM (
            SELECT exp_id, key, value, COALESCE(step, 0) AS s,
                   ROW_NUMBER() OVER (PARTITION BY exp_id, key
                                      ORDER BY COALESCE(step, 0) DESC) AS rn
            FROM metrics WHERE exp_id IN ({ph})
        ) WHERE rn <= ? ORDER BY exp_id, key, s
    """, [*exp_ids, max_points]).fetchall()
    out: dict[str, dict] = {e: {} for e in exp_ids}
    for r in rows:
        out[r["exp_id"]].setdefault(r["key"], []).append(r["value"])
    return out


def get_params_batch(conn, exp_ids: list[str]) -> dict[str, dict]:
    """Batch-load all params for many experiments in one query.

    Malformed JSON values degrade to the raw string rather than crashing the
    whole listing.
    """
    if not exp_ids:
        return {}
    ph = ",".join("?" * len(exp_ids))
    rows = conn.execute(
        f"SELECT exp_id, key, value FROM params WHERE exp_id IN ({ph})", exp_ids
    ).fetchall()
    out: dict[str, dict] = {e: {} for e in exp_ids}
    for r in rows:
        try:
            out[r["exp_id"]][r["key"]] = json.loads(r["value"])
        except (ValueError, TypeError):
            out[r["exp_id"]][r["key"]] = r["value"]
    return out


def get_metrics_sparkline(conn, exp_id: str, max_points: int = 10) -> dict[str, list[float]]:
    """Get last N values per metric key for sparkline rendering."""
    # Get distinct keys first, then fetch only the last N points per key
    keys = conn.execute(
        "SELECT DISTINCT key FROM metrics WHERE exp_id=?", (exp_id,)
    ).fetchall()
    by_key: dict[str, list] = {}
    for k_row in keys:
        key = k_row["key"]
        rows = conn.execute("""
            SELECT value FROM metrics WHERE exp_id=? AND key=?
            ORDER BY COALESCE(step, 0) DESC LIMIT ?
        """, (exp_id, key, max_points)).fetchall()
        by_key[key] = [r["value"] for r in reversed(rows)]
    return by_key


def _downsample_points(points: list[dict], max_points: int = 1500) -> list[dict]:
    """Downsample a metric series using min-max bucketing to preserve peaks/valleys.

    Splits points into buckets and keeps the min and max value point from each,
    plus always keeps the first and last points. This preserves the visual shape
    of the data far better than simple every-Nth sampling.
    """
    n = len(points)
    if n <= max_points:
        return points

    # Always keep first and last
    result = [points[0]]
    # Number of buckets (each contributes up to 2 points: min + max)
    num_buckets = (max_points - 2) // 2
    bucket_size = (n - 2) / num_buckets

    for i in range(num_buckets):
        start = int(1 + i * bucket_size)
        end = int(1 + (i + 1) * bucket_size)
        bucket = points[start:end]
        if not bucket:
            continue
        min_pt = min(bucket, key=lambda p: p["value"])
        max_pt = max(bucket, key=lambda p: p["value"])
        # Add in step order so chart stays chronological
        if min_pt is max_pt:
            result.append(min_pt)
        else:
            pair = sorted([min_pt, max_pt],
                          key=lambda p: p["step"] if p["step"] is not None else 0)
            result.extend(pair)

    result.append(points[-1])
    return result


# One metric point as the charts endpoint returns it.
def _point(row) -> dict:
    return {"value": row["value"], "step": row["step"], "ts": row["ts"]}


def _bucketed_points(conn, exp_id: str, key: str, lo: int, hi: int,
                     num_buckets: int) -> list[dict]:
    """Min/max-per-bucket downsample of one metric key, done in SQL.

    Two aggregate passes over the key's rows — one keeping each bucket's
    lowest-valued point, one its highest. Each relies on SQLite's documented
    "bare columns in an aggregate query" rule: with **exactly one** min()/max()
    aggregate, the non-aggregated columns come from the row that produced it,
    so we get that point's ``step``/``ts`` and not just its value. (That rule
    is why this is two queries rather than one with both aggregates — having
    both voids the guarantee and the bare columns become arbitrary.)

    Buckets are cut on ``COALESCE(step, rowid)``: the step for a normal
    training loop, and insert order for the step-less ``log_metric(k, v)``
    case, where every step is NULL and bucketing on it would collapse the
    whole series into one bucket. The first and last points get reserved
    buckets of their own so a chart always spans the true extent of the run
    and the final value read off it is exact.
    """
    span = max(1, hi - lo + 1)
    # -1 and num_buckets are the reserved first/last buckets.
    bucket = ("CASE WHEN o = ? THEN -1 WHEN o = ? THEN ? "
              "ELSE ((o - ?) * ?) / ? END")
    args = (lo, hi, num_buckets, lo, num_buckets, span, exp_id, key)
    seen: dict[tuple, tuple] = {}
    for agg in ("MIN", "MAX"):
        rows = conn.execute(f"""
            SELECT value, step, ts, o, {agg}(value) AS _extreme, {bucket} AS b
            FROM (SELECT value, step, ts, COALESCE(step, rowid) AS o
                  FROM metrics WHERE exp_id=? AND key=?)
            GROUP BY b
        """, args).fetchall()
        for r in rows:
            # A bucket whose min and max are the same row contributes it once.
            seen.setdefault((r["o"], r["value"]), (r["o"], _point(r)))
    # Sort on `o`, the same value the buckets were cut on — NOT on step/ts. For
    # a step-less series every step is NULL and `ts` resolves only to the
    # second, so ordering by those scrambles the series and the "last" point is
    # whichever bucket happened to sort last.
    return [p for _, p in sorted(seen.values(), key=lambda t: t[0])]


def get_metrics_series(conn, exp_id: str, max_points: int = 500) -> dict[str, list[dict]]:
    """Get metric points grouped by key, downsampled if over max_points.

    The downsampling happens in SQL. This used to ``SELECT`` every point for
    the experiment, build a dict per row, and hand the whole list to
    ``_downsample_points`` — which then threw ~99% of it away. One
    100k-iteration run logging 5 metrics is 500k rows, so rendering 2500
    chart points meant materializing 500k dicts: ~6s per call, of which the
    scan itself was under 1.5s. That is the endpoint the detail view **polls
    every 5 seconds** while a run is live, so the poll could not keep up with
    itself — each one occupied a request thread for longer than the interval.

    Now only the points that survive downsampling ever reach Python. A key
    already at or under *max_points* is returned whole and exactly as stored;
    only larger ones are bucketed.
    """
    # Below 4 there are no interior buckets left. The endpoint clamps to 10,
    # but this is called directly too.
    max_points = max(4, max_points)
    num_buckets = max(1, (max_points - 2) // 2)
    # Cheap prep: one grouped pass telling us which keys even need reducing,
    # and the extent to cut each one's buckets over.
    keys = conn.execute(
        "SELECT key, COUNT(*) AS n, MIN(COALESCE(step, rowid)) AS lo, "
        "MAX(COALESCE(step, rowid)) AS hi "
        "FROM metrics WHERE exp_id=? GROUP BY key", (exp_id,)
    ).fetchall()
    out: dict[str, list[dict]] = {}
    for k in keys:
        if k["n"] <= max_points:
            rows = conn.execute(
                "SELECT value, step, ts FROM metrics WHERE exp_id=? AND key=? "
                "ORDER BY COALESCE(step, 0), rowid", (exp_id, k["key"])
            ).fetchall()
            out[k["key"]] = [_point(r) for r in rows]
        else:
            out[k["key"]] = _bucketed_points(
                conn, exp_id, k["key"], k["lo"], k["hi"], num_buckets)
    return out


def get_metrics_summary(conn, exp_id: str) -> list[dict]:
    """Get min/max/count/last for each metric key, split by source."""
    rows = conn.execute("""
        SELECT key, COALESCE(source, 'auto') as src,
               MIN(value) as min_v, MAX(value) as max_v, COUNT(*) as n,
               (SELECT value FROM metrics m2 WHERE m2.exp_id=metrics.exp_id
                AND m2.key=metrics.key AND COALESCE(m2.source, 'auto')=COALESCE(metrics.source, 'auto')
                ORDER BY COALESCE(step,0) DESC LIMIT 1) as last_v
        FROM metrics WHERE exp_id=? GROUP BY key, COALESCE(source, 'auto') ORDER BY key, src
    """, (exp_id,)).fetchall()
    results = []
    for m in rows:
        results.append({
            "key": m["key"], "last": m["last_v"],
            "min": m["min_v"], "max": m["max_v"], "n": m["n"],
            "source": m["src"],
        })
    return results


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
    """Get experiment names, latest metrics, and image artifacts for multiple experiments."""
    results = []
    for eid in exp_ids:
        exp = find_experiment(conn, eid, "id, name, status")
        if not exp:
            continue
        full_id = exp["id"]
        metrics = get_latest_metrics(conn, full_id)
        art_rows = conn.execute(
            "SELECT label, path FROM artifacts WHERE exp_id=?", (full_id,)
        ).fetchall()
        images = [
            {"label": r["label"], "path": _rel_path(r["path"])}
            for r in art_rows
            if r["path"] and any(r["path"].lower().endswith(ext) for ext in IMAGE_EXTS)
        ]
        results.append({
            "id": full_id,
            "name": exp["name"],
            "status": exp["status"],
            "metrics": metrics,
            "images": images,
        })
    return results


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats(conn) -> dict[str, Any]:
    """Aggregate statistics across all experiments (excludes trashed)."""
    total = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE deleted_at IS NULL").fetchone()["n"]
    done = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE deleted_at IS NULL AND status='done'").fetchone()["n"]
    failed = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE deleted_at IS NULL AND status='failed'").fetchone()["n"]
    running = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE deleted_at IS NULL AND status='running'").fetchone()["n"]
    trashed = conn.execute("SELECT COUNT(*) as n FROM experiments WHERE deleted_at IS NOT NULL").fetchone()["n"]
    try:
        trashed_nodes = conn.execute(
            "SELECT COUNT(*) as n FROM session_nodes WHERE deleted_at IS NOT NULL"
        ).fetchone()["n"]
    except Exception:
        trashed_nodes = 0
    avg_dur = conn.execute("SELECT AVG(duration_s) as v FROM experiments WHERE deleted_at IS NULL AND duration_s IS NOT NULL").fetchone()["v"]
    longest = conn.execute("SELECT MAX(duration_s) as v FROM experiments WHERE deleted_at IS NULL AND duration_s IS NOT NULL").fetchone()["v"]
    most_recent = conn.execute("SELECT created_at FROM experiments WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 1").fetchone()

    tag_rows = conn.execute("SELECT tags FROM experiments WHERE deleted_at IS NULL AND tags IS NOT NULL AND tags != '[]'").fetchall()
    all_tags = set()
    for r in tag_rows:
        try:
            for t in json.loads(r["tags"] or "[]"):
                all_tags.add(t)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            print(f"[exptrack] warning: malformed tags row in get_stats: {e}",
                  file=sys.stderr)

    try:
        total_artifacts = conn.execute(
            "SELECT COUNT(*) as n FROM artifacts "
            "WHERE exp_id IN (SELECT id FROM experiments WHERE deleted_at IS NULL)"
        ).fetchone()["n"]
    except Exception as e:
        print(f"[exptrack] warning: could not count artifacts: {e}", file=sys.stderr)
        total_artifacts = 0

    unique_branches = conn.execute(
        "SELECT COUNT(DISTINCT git_branch) as n FROM experiments "
        "WHERE deleted_at IS NULL AND git_branch IS NOT NULL AND git_branch != ''"
    ).fetchone()["n"]

    # Git diff storage stats
    diff_rows = conn.execute(
        "SELECT LENGTH(git_diff) as sz FROM experiments "
        "WHERE deleted_at IS NULL AND git_diff IS NOT NULL AND git_diff != '' "
        "AND git_diff NOT LIKE '[compacted%' AND git_diff NOT LIKE '[ref:%' "
        "AND git_diff NOT LIKE '[capture-failed%'"
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
        "trashed": trashed,
        "trashed_nodes": trashed_nodes,
        "trashed_total": trashed + trashed_nodes,
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
    """Get all tags with usage counts, sorted by frequency. Skips trashed experiments."""
    rows = conn.execute(
        "SELECT tags FROM experiments "
        "WHERE deleted_at IS NULL AND tags IS NOT NULL AND tags != '[]'"
    ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        try:
            for t in json.loads(r["tags"] or "[]"):
                counts[t] = counts.get(t, 0) + 1
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            print(f"[exptrack] warning: malformed tags row in get_all_tags: {e}",
                  file=sys.stderr)
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
        tags = _json_list(r["tags"], "remove_tag_global")
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
    """Get timeline events for an experiment, with cell lineage parent info."""
    where = "WHERE t.exp_id=?"
    params: list = [exp_id]
    if event_type:
        where += " AND t.event_type=?"
        params.append(event_type)
    rows = conn.execute(
        f"""SELECT t.seq, t.event_type, t.cell_hash, t.cell_pos, t.key,
                   t.value, t.prev_value, t.source_diff, t.ts,
                   cl.parent_hash
            FROM timeline t
            LEFT JOIN cell_lineage cl ON t.cell_hash = cl.cell_hash
            {where} ORDER BY t.seq""",
        params
    ).fetchall()
    return [{
        "seq": r["seq"],
        "event_type": r["event_type"],
        "cell_hash": r["cell_hash"],
        "cell_pos": r["cell_pos"],
        "key": r["key"],
        "value": _safe_json(r["value"]),
        "prev_value": _safe_json(r["prev_value"]),
        "source_diff": _safe_json(r["source_diff"]),
        "ts": r["ts"],
        "parent_hash": r["parent_hash"],
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
    diff = resolve_git_diff(conn, exp["git_diff"])
    return {
        "diff": diff,
        # Classified server-side so the client branches on a field instead of
        # re-hardcoding the marker strings (they were already drifting between
        # the two JS renderers).
        "sentinel": diff_sentinel_kind(diff),
        "branch": exp["git_branch"],
        "commit": exp["git_commit"],
    }


# ── Export ─────────────────────────────────────────────────────────────────────

def summarize_metric_series(points: list[dict]) -> dict:
    """Collapse one metric's points into the numbers you'd read off its chart.

    A run logging every iteration stores tens of thousands of points per key,
    and dumping each one as its own JSON object made the export unreadable —
    the params and the final numbers were buried under the series. The summary
    keeps what a reader actually asks of a finished run (where it ended, where
    it started, its extremes and how many points there were); the raw series is
    still available via ``full=True``.
    """
    vals = [p["value"] for p in points if p.get("value") is not None]
    if not vals:
        return {"count": len(points), "first": None, "last": None,
                "min": None, "max": None, "first_step": None, "last_step": None,
                "min_step": None, "max_step": None}
    lo = min(range(len(vals)), key=lambda i: vals[i])
    hi = max(range(len(vals)), key=lambda i: vals[i])
    steps = [p.get("step") for p in points if p.get("value") is not None]
    return {
        "count": len(points),
        "first": vals[0], "first_step": steps[0],
        "last": vals[-1], "last_step": steps[-1],
        "min": vals[lo], "min_step": steps[lo],
        "max": vals[hi], "max_step": steps[hi],
    }


def _artifact_export_summary(artifacts: list, limit: int) -> dict:
    """Shape-of-the-list payload the export ships alongside the capped list."""
    s = summarize_artifacts(artifacts, limit)
    return {
        "total": s["total"],
        "listed": len(s["shown"]),
        "omitted": s["omitted"],
        "by_type": [{"type": k, "count": n} for k, n in s["by_type"]],
        "by_dir": [{"dir": d, "count": n} for d, n in s["by_dir"][:SUMMARY_DIR_LIMIT]],
        "dirs_omitted": max(0, len(s["by_dir"]) - SUMMARY_DIR_LIMIT),
    }


def get_export_data(conn, exp_id: str, full: bool = False,
                    artifact_limit: int = ARTIFACT_LIST_LIMIT) -> dict | None:
    """Get export data for an experiment.

    By default this is a *summary* export: each metric key is one object
    (count/first/last/min/max) rather than one object per logged point, and the
    artifact list is capped at ``artifact_limit`` with an ``artifacts_summary``
    describing the rest by type and containing directory. ``full=True`` adds
    the complete ``metrics_series`` and lists every artifact, for round-tripping.
    ``artifact_limit=0`` also means "list them all".
    """
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
        ORDER BY key, COALESCE(step, 0), id
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
    # Legacy per-cell keys (notebook runs no longer write them — the Timeline
    # carries that edit) plus the script's own diff-vs-commit, which had never
    # been exported at all: it is filtered out of `user_params` by the `_`
    # prefix and matched none of the `_code_change/` keys collected here.
    code_changes = {k[13:]: v for k, v in all_params.items() if k.startswith("_code_change/")}
    if all_params.get("_code_changes"):
        code_changes["script"] = all_params["_code_changes"]
    datasets = all_params.get("_dataset_manifest") or {}

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
        "tags": _json_list(exp["tags"], "export_data.tags"),
        "studies": _json_list(exp["studies"], "export_data.studies"),
        "notes": exp["notes"],
        "output_dir": exp["output_dir"] or "",
        "stage": exp["stage"],
        "stage_name": exp["stage_name"],
        "params": user_params,
        "variables": variables,
        "code_changes": code_changes,
        "datasets": datasets,
        "metrics": {},
        "timeline_summary": {
            "total_events": len(timeline),
            "cell_executions": sum(1 for t in timeline if t["event_type"] == "cell_exec"),
            "variable_sets": sum(1 for t in timeline if t["event_type"] == "var_set"),
            "artifact_events": sum(1 for t in timeline if t["event_type"] == "artifact"),
        },
    }
    series: dict[str, list[dict]] = {}
    for m in metrics:
        series.setdefault(m["key"], []).append({
            "value": m["value"], "step": m["step"]
        })
    data["metrics"] = {k: summarize_metric_series(pts) for k, pts in series.items()}
    if full:
        data["metrics_series"] = series

    art_rows = [{"label": a["label"], "path": a["path"]} for a in artifacts]
    limit = 0 if full else artifact_limit
    data["artifacts"] = art_rows if not limit else art_rows[:limit]
    data["artifacts_summary"] = _artifact_export_summary(art_rows, limit)
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
        except Exception as e:
            # Don't fail the edit if timeline insert fails, but surface the cause.
            print(f"[exptrack] warning: could not record note_edit in timeline "
                  f"for exp {exp['id'][:8]}: {e}", file=sys.stderr)
    conn.execute(
        "UPDATE experiments SET notes=?, updated_at=? WHERE id=?",
        (text, now, exp["id"])
    )
    return {"ok": True, "notes": text}


# ── Export formatting ─────────────────────────────────────────────────────────

def get_batch_export_data(conn, exp_ids: list[str] | None = None,
                          export_all: bool = False, full: bool = False,
                          artifact_limit: int = ARTIFACT_LIST_LIMIT) -> list[dict]:
    """Get export data for multiple experiments (see ``get_export_data``)."""
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
    return [get_export_data(conn, r["id"], full=full, artifact_limit=artifact_limit)
            for r in rows if r]


def export_metric_summaries(data: dict) -> dict:
    """Per-key metric summary from export data, whichever form it carries.

    The one reader of both shapes: the summary export ships ``metrics``, a
    ``full=True`` export additionally ships the raw ``metrics_series``, and
    older callers may hand over only the latter.
    """
    if data.get("metrics"):
        return data["metrics"]
    return {k: summarize_metric_series(pts)
            for k, pts in (data.get("metrics_series") or {}).items()}


def _m(value) -> str:
    """Render a metric value for a table cell ("--" when there isn't one)."""
    return "--" if value is None else str(value)


def format_export_markdown(data: dict, artifact_limit: int = ARTIFACT_LIST_LIMIT) -> str:
    """Generate a markdown summary of an experiment from export data.

    ``artifact_limit=0`` lists every artifact; the default caps the list and
    summarises the remainder by type and directory.
    """
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
    summaries = export_metric_summaries(data)
    if summaries:
        lines += ["## Metrics", "", "| Key | Last | Min | Max | Points |",
                  "| --- | --- | --- | --- | --- |"]
        for k, s in summaries.items():
            lines.append(f"| {k} | {_m(s['last'])} | {_m(s['min'])} | "
                         f"{_m(s['max'])} | {s['count']} |")
        lines.append("")
    art = data.get("artifacts_summary")
    if art or data.get("artifacts"):
        shown = data.get("artifacts") or []
        if art is None:
            # Raw (uncapped) data from an older caller — cap it here as before.
            s = summarize_artifacts(shown, artifact_limit)
            shown, art = s["shown"], _artifact_export_summary(shown, artifact_limit)
        lines += [f"## Artifacts ({art['total']})", ""]
        if art["omitted"]:
            # State the shape of what is not listed, so the summary is useful
            # on its own rather than just an apology for a truncated list.
            types = ", ".join(f"{t['count']} {t['type']}" for t in art["by_type"])
            lines.append(f"{art['total']} files — {types}.")
            top_dirs = ", ".join(f"`{d['dir']}` ({d['count']})" for d in art["by_dir"][:5])
            if top_dirs:
                lines.append("")
                lines.append(f"Directories: {top_dirs}")
            lines.append("")
        for a in shown:
            lines.append(f"- **{a['label']}**: `{a['path']}`")
        if art["omitted"]:
            lines.append(f"- … and {art['omitted']} more "
                         f"(`exptrack export --full` for the complete list)")
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


PARAMS_EXPORT_FORMATS = {
    "params": "equals",
    "params-flags": "flags",
    "params-json": "json",
    "params-md": "md-table",
    "params-tsv": "tsv",
}


def format_export_params(data: dict, style: str = "equals") -> str:
    """Format just the parameters of an experiment as a plain list.

    Styles:
      - "equals":    key=value (JSON-encoded)   — shell/CLI friendly
      - "flags":     --key value                — argparse-style command flags
      - "json":      {"key": value, ...}        — single-line JSON object
      - "md-table":  | Key | Value | markdown   — pastes into lab notebooks
      - "tsv":       key\\tvalue                 — pastes into spreadsheets
    """
    params = data.get("params", {}) or {}
    if style == "json":
        return json.dumps(params, indent=2, default=str)
    if style == "md-table":
        lines = ["| Key | Value |", "| --- | --- |"]
        for k, v in params.items():
            lines.append(f"| {k} | {json.dumps(v)} |")
        return "\n".join(lines)
    if style == "tsv":
        return "\n".join(f"{k}\t{json.dumps(v)}" for k, v in params.items())
    lines = []
    for k, v in params.items():
        if style == "flags":
            if isinstance(v, bool):
                if v:
                    lines.append(f"--{k}")
            else:
                lines.append(f"--{k} {json.dumps(v)}")
        else:
            lines.append(f"{k}={json.dumps(v)}")
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
    metric_summaries = [export_metric_summaries(d) for d in experiments]
    for data, ms in zip(experiments, metric_summaries):
        all_param_keys.update(k for k in data.get("params", {}) if not k.startswith("_"))
        all_metric_keys.update(ms.keys())
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
    for data, summaries in zip(experiments, metric_summaries):
        params = data.get("params", {})
        variables = data.get("variables", {})
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
            s = summaries.get(k)
            row.append("" if not s or s.get("last") is None else str(s["last"]))
        # Artifacts as semicolon-separated label:path pairs. The list is capped
        # upstream, so say how many were left out rather than implying this is
        # everything the run wrote.
        art_str = ";".join(f"{a.get('label','')}:{a.get('path','')}" for a in artifacts)
        omitted = (data.get("artifacts_summary") or {}).get("omitted") or 0
        if omitted:
            art_str += f";… +{omitted} more"
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
    """Get all studies with usage counts (like get_all_tags). Skips trashed."""
    rows = conn.execute(
        "SELECT studies FROM experiments "
        "WHERE deleted_at IS NULL AND studies IS NOT NULL AND studies != '[]'"
    ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        try:
            for s in json.loads(r["studies"] or "[]"):
                counts[s] = counts.get(s, 0) + 1
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            print(f"[exptrack] warning: malformed studies row in get_all_studies: {e}",
                  file=sys.stderr)
    return [{"name": n, "count": c} for n, c in sorted(counts.items())]


def get_studies(conn) -> list[dict]:
    """Get studies with summary stats. Skips trashed experiments."""
    rows = conn.execute(
        "SELECT id, studies, status, created_at FROM experiments "
        "WHERE deleted_at IS NULL AND studies IS NOT NULL AND studies != '[]'"
    ).fetchall()
    study_data: dict[str, list[dict]] = {}
    for r in rows:
        try:
            for s in json.loads(r["studies"] or "[]"):
                study_data.setdefault(s, []).append(dict(r))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            print(f"[exptrack] warning: malformed studies row in get_studies: {e}",
                  file=sys.stderr)

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
    studies = _json_list(exp["studies"], "add_to_study")
    if study_name not in studies:
        studies.append(study_name)
        update_experiment_studies(conn, exp["id"], studies)
    return studies


def remove_from_study(conn, exp_id: str, study_name: str) -> list[str] | None:
    """Remove an experiment from a study. Returns updated studies list."""
    exp = find_experiment(conn, exp_id, "id, studies")
    if not exp:
        return None
    studies = _json_list(exp["studies"], "remove_from_study")
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
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            print(f"[exptrack] warning: malformed studies row in remove_study_global: {e}",
                  file=sys.stderr)
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


def get_run_source(conn, exp_id: str) -> dict:
    """Everything exptrack captured of a run's own code, for review or rescue.

    The source has always been stored — a script's full snapshot in
    ``code_snapshots``, a notebook's cells in ``cell_lineage`` — but nothing
    outside ``compare_run_code`` could reach it, so "show me the code this run
    actually ran" had no answer at the CLI or in an export. That matters most
    exactly when it is hardest to get any other way: the file has since been
    edited, or was never committed.

    Returns ``{kind, id, name, files}`` where ``kind`` is ``'script'``,
    ``'cells'`` or ``None`` and ``files`` is a list of ``{label, content}``.
    """
    row = find_experiment(conn, exp_id, "id, name, script")
    if not row:
        return {"kind": None, "id": None, "name": None, "files": []}
    out = {"kind": None, "id": row["id"], "name": row["name"], "files": []}

    src = _script_snapshot_source(conn, row["id"])
    if src is not None:
        label = (row["script"] or "script").split("/")[-1]
        out["kind"], out["files"] = "script", [{"label": label, "content": src}]
        return out

    cells = _run_cells(conn, row["id"])
    files = [
        {"label": f"cell {c['cell_pos']}" if c["cell_pos"] is not None
                  else f"cell #{i + 1}",
         "content": c["source"] or ""}
        for i, c in enumerate(cells) if c["source"]
    ]
    if files:
        out["kind"], out["files"] = "cells", files
    return out
