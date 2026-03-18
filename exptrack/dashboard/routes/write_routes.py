"""
exptrack/dashboard/routes/write_routes.py — Mutation API endpoints

POST endpoints for notes, tags, rename, delete, finish, artifacts, groups.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ...core.queries import find_experiment, remove_tag_global, update_experiment_tags


def api_add_note(conn, exp_id: str, body: dict) -> dict:
    from ...core.queries import append_note
    text = body.get("note", "").strip()
    if not text:
        return {"error": "empty note"}
    result = append_note(conn, exp_id, text)
    if result.get("error"):
        return result
    conn.commit()
    return result


def api_add_tag(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id, "id, tags")
    if not exp:
        return {"error": "not found"}
    tag = body.get("tag", "").strip()
    if not tag:
        return {"error": "empty tag"}
    tags = json.loads(exp["tags"] or "[]")
    if tag not in tags:
        tags.append(tag)
    update_experiment_tags(conn, exp["id"], tags)
    conn.commit()
    return {"ok": True, "tags": tags}


def api_rename(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id, "id, name")
    if not exp:
        return {"error": "not found"}
    new_name = body.get("name", "").strip()
    if not new_name:
        return {"error": "empty name"}
    old_name = exp["name"]
    conn.execute(
        "UPDATE experiments SET name=?, updated_at=? WHERE id=?",
        (new_name, datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    from ...core.db import rename_output_folder
    rename_output_folder(conn, exp["id"], old_name, new_name)
    conn.commit()
    return {"ok": True, "name": new_name}


def api_delete(conn, exp_id: str) -> dict:
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    from ...core.db import delete_experiment
    delete_experiment(conn, exp["id"])
    conn.commit()
    return {"ok": True}


def api_finish(conn, exp_id: str) -> dict:
    from ...core.queries import finish_experiment
    result = finish_experiment(conn, exp_id)
    if result.get("error"):
        return result
    conn.commit()
    return result


def api_add_artifact(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id)
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


def api_delete_tag(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id, "id, tags")
    if not exp:
        return {"error": "not found"}
    tag = body.get("tag", "").strip()
    if not tag:
        return {"error": "empty tag"}
    tags = json.loads(exp["tags"] or "[]")
    tags = [t for t in tags if t != tag]
    update_experiment_tags(conn, exp["id"], tags)
    conn.commit()
    return {"ok": True, "tags": tags}


def api_edit_tag(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id, "id, tags")
    if not exp:
        return {"error": "not found"}
    old_tag = body.get("old_tag", "").strip()
    new_tag = body.get("new_tag", "").strip()
    if not old_tag or not new_tag:
        return {"error": "provide old_tag and new_tag"}
    tags = json.loads(exp["tags"] or "[]")
    tags = [new_tag if t == old_tag else t for t in tags]
    update_experiment_tags(conn, exp["id"], tags)
    conn.commit()
    return {"ok": True, "tags": tags}


def api_edit_notes(conn, exp_id: str, body: dict) -> dict:
    from ...core.queries import replace_notes
    notes = body.get("notes", "")
    result = replace_notes(conn, exp_id, notes)
    if result.get("error"):
        return result
    conn.commit()
    return result


def api_delete_artifact(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    label = body.get("label", "")
    path = body.get("path", "")
    if not label and not path:
        return {"error": "provide label or path"}
    if label and path:
        conn.execute(
            "DELETE FROM artifacts WHERE exp_id=? AND label=? AND path=?",
            (exp["id"], label, path)
        )
    elif label:
        conn.execute(
            "DELETE FROM artifacts WHERE exp_id=? AND label=?",
            (exp["id"], label)
        )
    else:
        conn.execute(
            "DELETE FROM artifacts WHERE exp_id=? AND path=?",
            (exp["id"], path)
        )
    conn.commit()
    return {"ok": True}


def api_edit_artifact(conn, exp_id: str, body: dict) -> dict:
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    old_label = body.get("old_label", "")
    old_path = body.get("old_path", "")
    new_label = body.get("new_label", "")
    new_path = body.get("new_path", "")
    if not old_label and not old_path:
        return {"error": "provide old_label or old_path"}
    if old_label and old_path:
        conn.execute(
            "UPDATE artifacts SET label=?, path=? WHERE exp_id=? AND label=? AND path=?",
            (new_label or old_label, new_path or old_path, exp["id"], old_label, old_path)
        )
    elif old_label:
        conn.execute(
            "UPDATE artifacts SET label=?, path=? WHERE exp_id=? AND label=?",
            (new_label or old_label, new_path or old_path, exp["id"], old_label)
        )
    else:
        conn.execute(
            "UPDATE artifacts SET label=?, path=? WHERE exp_id=? AND path=?",
            (new_label or old_label, new_path or old_path, exp["id"], old_path)
        )
    conn.commit()
    return {"ok": True}


def api_compact(conn, body: dict) -> dict:
    """Compact experiments — supports git_diff, cells, timeline, deep modes.

    body.ids: list of experiment IDs (prefix match)
    body.mode: "diff" (default), "cells", "timeline", "deep" (all of the above)
    body.dry_run: if true, only preview what would be removed
    """
    ids = body.get("ids", [])
    if not ids:
        return {"error": "no ids provided"}

    mode = body.get("mode", "diff")
    dry_run = body.get("dry_run", False)
    do_deep = mode == "deep"
    do_diff = mode == "diff" or do_deep
    do_cells = mode == "cells" or do_deep
    do_timeline = mode == "timeline" or do_deep

    # Resolve experiment IDs
    resolved_ids = []
    for eid in ids:
        row = conn.execute(
            "SELECT id FROM experiments WHERE id LIKE ?", (eid + "%",)
        ).fetchone()
        if row:
            resolved_ids.append(row["id"])
    if not resolved_ids:
        return {"ok": True, "compacted": 0, "freed": 0, "detail": "No matching experiments",
                "will_remove": []}

    if dry_run:
        return _compact_preview(conn, resolved_ids, do_diff, do_cells, do_timeline)

    freed = 0
    detail_parts = []

    # ── 1. Git diff compaction ────────────────────────────────────────────
    if do_diff:
        diff_freed, diff_count = _compact_git_diffs(conn, resolved_ids)
        freed += diff_freed
        if diff_count:
            detail_parts.append(f"diffs: {diff_count}")

    # ── 2. Cell lineage source compaction ─────────────────────────────────
    if do_cells:
        cell_freed = _compact_cell_sources(conn, resolved_ids)
        freed += cell_freed
        if cell_freed:
            detail_parts.append(f"cells: {_fmt(cell_freed)}")

    # ── 3. Timeline source_diff compaction ────────────────────────────────
    if do_timeline:
        tl_freed = _compact_timeline_sources(conn, resolved_ids)
        freed += tl_freed
        if tl_freed:
            detail_parts.append(f"timeline: {_fmt(tl_freed)}")

    compacted = len(resolved_ids) if freed > 0 else 0
    detail = ", ".join(detail_parts) if detail_parts else "nothing to compact"
    return {"ok": True, "compacted": compacted, "freed": freed, "detail": detail}


def _compact_preview(conn, exp_ids: list, do_diff: bool, do_cells: bool,
                     do_timeline: bool) -> dict:
    """Preview what compact would remove, without modifying anything."""
    from ...core.db import resolve_git_diff
    will_remove = []
    total_bytes = 0

    if do_diff:
        for eid in exp_ids:
            row = conn.execute(
                "SELECT git_diff, git_commit FROM experiments WHERE id=?", (eid,)
            ).fetchone()
            if not row or not row["git_diff"] or row["git_diff"].startswith("[compacted"):
                continue
            full_diff = resolve_git_diff(conn, row["git_diff"])
            diff_len = len(full_diff)
            files = [line.split()[-1].lstrip("b/")
                     for line in full_diff.splitlines()
                     if line.startswith("diff --git ") and len(line.split()) >= 4]
            total_bytes += diff_len
            will_remove.append(f"Git diff ({_fmt(diff_len)}, {len(files)} file(s): {', '.join(files[:3])}"
                               + (f" +{len(files)-3} more" if len(files) > 3 else "") + ")")

    if do_cells:
        placeholders = ",".join("?" * len(exp_ids))
        try:
            row = conn.execute(f"""
                SELECT COALESCE(SUM(LENGTH(cl.source)), 0) as sz,
                       COUNT(*) as cnt
                FROM cell_lineage cl
                WHERE cl.source IS NOT NULL AND LENGTH(cl.source) > 0
                AND cl.cell_hash IN (
                    SELECT DISTINCT cell_hash FROM timeline
                    WHERE exp_id IN ({placeholders}) AND cell_hash IS NOT NULL
                )
                AND cl.cell_hash NOT IN (
                    SELECT DISTINCT t.cell_hash FROM timeline t
                    WHERE t.exp_id NOT IN ({placeholders})
                      AND t.cell_hash IS NOT NULL
                      AND t.source_diff IS NOT NULL
                )
            """, exp_ids + exp_ids).fetchone()
            sz = row["sz"] if row else 0
            cnt = row["cnt"] if row else 0
            if sz:
                total_bytes += sz
                will_remove.append(f"Cell source code ({_fmt(sz)}, {cnt} cell(s))")
        except Exception:
            pass

    if do_timeline:
        placeholders = ",".join("?" * len(exp_ids))
        try:
            row = conn.execute(f"""
                SELECT COALESCE(SUM(LENGTH(source_diff)), 0) as sz,
                       COUNT(*) as cnt
                FROM timeline
                WHERE exp_id IN ({placeholders}) AND source_diff IS NOT NULL
            """, exp_ids).fetchone()
            sz = row["sz"] if row else 0
            cnt = row["cnt"] if row else 0
            if sz:
                total_bytes += sz
                will_remove.append(f"Timeline inline diffs ({_fmt(sz)}, {cnt} event(s))")
        except Exception:
            pass

    return {"ok": True, "dry_run": True, "will_remove": will_remove,
            "total_bytes": total_bytes, "total_fmt": _fmt(total_bytes)}


def _fmt(b):
    if b < 1024: return f"{b} B"
    if b < 1024**2: return f"{b/1024:.1f} KB"
    return f"{b/1024**2:.1f} MB"


def _compact_git_diffs(conn, exp_ids: list) -> tuple:
    """Strip git_diff from experiments, returns (freed_bytes, count)."""
    from ...core.db import resolve_git_diff
    freed = 0
    count = 0
    for eid in exp_ids:
        row = conn.execute(
            "SELECT id, git_diff, git_commit FROM experiments WHERE id=?", (eid,)
        ).fetchone()
        if not row:
            continue
        raw_diff = row["git_diff"]
        if not raw_diff or raw_diff.startswith("[compacted"):
            continue
        full_diff = resolve_git_diff(conn, raw_diff)
        diff_len = len(full_diff)
        commit = row["git_commit"] or "unknown"
        files = [line.split()[-1].lstrip("b/")
                 for line in full_diff.splitlines()
                 if line.startswith("diff --git ") and len(line.split()) >= 4]
        file_info = f"{len(files)} file(s): {', '.join(files[:5])}" if files else "no files"
        if len(files) > 5:
            file_info += f" +{len(files) - 5} more"
        summary = f"[compacted — {_fmt(diff_len)} stripped — {file_info} — see git commit {commit}]"
        conn.execute("UPDATE experiments SET git_diff = ? WHERE id = ?", (summary, row["id"]))
        # Delete the blob from git_diffs if it was a ref and no other experiment uses it
        if raw_diff.startswith("[ref:sha256:"):
            diff_hash = raw_diff[12:-1]
            other = conn.execute(
                "SELECT 1 FROM experiments WHERE git_diff=? AND id!=?", (raw_diff, eid)
            ).fetchone()
            if not other:
                conn.execute("DELETE FROM git_diffs WHERE diff_hash=?", (diff_hash,))
        freed += diff_len
        count += 1
    if count:
        conn.commit()
    return freed, count


def _compact_cell_sources(conn, exp_ids: list) -> int:
    """Strip cell_lineage.source for cells that no longer need source text.

    Sets source to '' (empty string) since the column has NOT NULL constraint.
    A cell is safe to strip when ALL experiments referencing it either:
      - are in the current compact batch, OR
      - have already had their timeline source_diff stripped (compacted)
    """
    if not exp_ids:
        return 0
    placeholders = ",".join("?" * len(exp_ids))
    # Find cells used by target experiments, excluding cells still needed
    # by other non-compacted experiments
    query = f"""
        SELECT COALESCE(SUM(LENGTH(cl.source)), 0) as sz
        FROM cell_lineage cl
        WHERE cl.source IS NOT NULL AND LENGTH(cl.source) > 0
        AND cl.cell_hash IN (
            SELECT DISTINCT cell_hash FROM timeline
            WHERE exp_id IN ({placeholders}) AND cell_hash IS NOT NULL
        )
        AND cl.cell_hash NOT IN (
            SELECT DISTINCT t.cell_hash FROM timeline t
            WHERE t.exp_id NOT IN ({placeholders})
              AND t.cell_hash IS NOT NULL
              AND t.source_diff IS NOT NULL
        )
    """
    update_query = f"""
        UPDATE cell_lineage SET source = ''
        WHERE source IS NOT NULL AND LENGTH(source) > 0
        AND cell_hash IN (
            SELECT DISTINCT cell_hash FROM timeline
            WHERE exp_id IN ({placeholders}) AND cell_hash IS NOT NULL
        )
        AND cell_hash NOT IN (
            SELECT DISTINCT t.cell_hash FROM timeline t
            WHERE t.exp_id NOT IN ({placeholders})
              AND t.cell_hash IS NOT NULL
              AND t.source_diff IS NOT NULL
        )
    """
    try:
        size_row = conn.execute(query, exp_ids + exp_ids).fetchone()
        freed = size_row["sz"] if size_row else 0
        if freed:
            conn.execute(update_query, exp_ids + exp_ids)
            conn.commit()
        return freed
    except Exception:
        return 0


def _compact_timeline_sources(conn, exp_ids: list) -> int:
    """NULL out timeline.source_diff for given experiments."""
    if not exp_ids:
        return 0
    placeholders = ",".join("?" * len(exp_ids))
    try:
        size_row = conn.execute(f"""
            SELECT COALESCE(SUM(LENGTH(source_diff)), 0) as sz
            FROM timeline
            WHERE exp_id IN ({placeholders}) AND source_diff IS NOT NULL
        """, exp_ids).fetchone()
        freed = size_row["sz"] if size_row else 0
        if freed:
            conn.execute(f"""
                UPDATE timeline SET source_diff = NULL
                WHERE exp_id IN ({placeholders}) AND source_diff IS NOT NULL
            """, exp_ids)
            conn.commit()
        return freed
    except Exception:
        return 0


def api_export_diff(conn, exp_id: str) -> dict:
    """Return the git diff for an experiment as downloadable markdown."""
    exp = find_experiment(conn, exp_id, "id, name, git_branch, git_commit, git_diff")
    if not exp:
        return {"error": "not found"}
    from ...core.db import resolve_git_diff
    diff = resolve_git_diff(conn, exp["git_diff"])
    if diff.startswith("[compacted"):
        return {"error": "diff already compacted", "compacted": True}
    name = exp["name"] or exp["id"][:8]
    md = (f"# Diff: {name}\n\n"
          f"- **Experiment ID:** `{exp['id']}`\n"
          f"- **Branch:** `{exp['git_branch'] or ''}`\n"
          f"- **Commit:** `{exp['git_commit'] or ''}`\n\n"
          f"```diff\n{diff}\n```\n")
    return {"ok": True, "markdown": md, "filename": f"{name}__{exp['id'][:8]}.md"}


def api_bulk_delete(conn, body: dict) -> dict:
    ids = body.get("ids", [])
    if not ids:
        return {"error": "no ids provided"}
    from ...core.db import delete_experiment
    deleted = 0
    for eid in ids:
        exp = find_experiment(conn, eid)
        if exp:
            delete_experiment(conn, exp["id"])
            deleted += 1
    conn.commit()
    return {"ok": True, "deleted": deleted}


def api_bulk_export(conn, body: dict) -> dict | list:
    from ...core.queries import format_export_csv, format_export_markdown, get_batch_export_data
    ids = body.get("ids", [])
    fmt = body.get("format", "json")
    if not ids:
        return {"error": "no ids provided"}
    batch = get_batch_export_data(conn, exp_ids=ids)
    if not batch:
        return {"error": "no experiments found"}
    if fmt in ("csv", "tsv"):
        delimiter = "\t" if fmt == "tsv" else ","
        return {"format": fmt, "content": format_export_csv(batch, delimiter=delimiter)}
    elif fmt == "markdown":
        md_parts = [format_export_markdown(d) for d in batch]
        return {"format": "markdown", "content": "\n\n---\n\n".join(md_parts)}
    else:
        return batch


def api_delete_tag_global(conn, body: dict) -> dict:
    tag = body.get("tag", "").strip()
    if not tag:
        return {"error": "empty tag"}
    count = remove_tag_global(conn, tag)
    conn.commit()
    return {"ok": True, "deleted_from": count}


def api_set_timezone(body: dict) -> dict:
    from ...config import load, save
    tz = body.get("timezone", "").strip()
    valid = {
        "", "UTC", "America/New_York", "America/Chicago", "America/Denver",
        "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Europe/Paris",
        "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata", "Australia/Sydney",
    }
    if tz not in valid:
        return {"error": "invalid timezone"}
    conf = load()
    conf["timezone"] = tz
    save(conf)
    return {"ok": True, "timezone": tz}


# ── Study management ─────────────────────────────────────────────────────────

def api_create_study(conn, body: dict) -> dict:
    """Create a new study, optionally adding specified experiments to it."""
    name = body.get("name", "").strip()
    exp_ids = body.get("experiment_ids", [])
    if not name:
        return {"error": "empty study name"}
    from ...core.queries import add_to_study
    added = 0
    for eid in exp_ids:
        studies = add_to_study(conn, eid, name)
        if studies is not None:
            added += 1
    conn.commit()
    return {"ok": True, "name": name, "added": added}


def api_add_to_study(conn, body: dict) -> dict:
    """Add an experiment to a study."""
    name = body.get("study", "").strip()
    exp_id = body.get("experiment_id", "").strip()
    if not name or not exp_id:
        return {"error": "provide study and experiment_id"}
    from ...core.queries import add_to_study
    studies = add_to_study(conn, exp_id, name)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_remove_from_study(conn, body: dict) -> dict:
    """Remove an experiment from a study."""
    name = body.get("study", "").strip()
    exp_id = body.get("experiment_id", "").strip()
    if not name or not exp_id:
        return {"error": "provide study and experiment_id"}
    from ...core.queries import remove_from_study
    studies = remove_from_study(conn, exp_id, name)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_delete_study(conn, body: dict) -> dict:
    """Delete a study from all experiments."""
    name = body.get("name", "").strip()
    if not name:
        return {"error": "empty study name"}
    from ...core.queries import remove_study_global
    count = remove_study_global(conn, name)
    conn.commit()
    return {"ok": True, "deleted_from": count}


def api_add_study(conn, exp_id: str, body: dict) -> dict:
    """Add a single study to an experiment (inline editing)."""
    from ...core.queries import find_experiment, update_experiment_studies
    exp = find_experiment(conn, exp_id, "id, studies")
    if not exp:
        return {"error": "not found"}
    study = body.get("study", "").strip()
    if not study:
        return {"error": "empty study"}
    studies = json.loads(exp["studies"] or "[]")
    if study not in studies:
        studies.append(study)
    update_experiment_studies(conn, exp["id"], studies)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_delete_exp_study(conn, exp_id: str, body: dict) -> dict:
    """Remove a single study from an experiment (inline editing)."""
    from ...core.queries import find_experiment, update_experiment_studies
    exp = find_experiment(conn, exp_id, "id, studies")
    if not exp:
        return {"error": "not found"}
    study = body.get("study", "").strip()
    if not study:
        return {"error": "empty study"}
    studies = json.loads(exp["studies"] or "[]")
    studies = [s for s in studies if s != study]
    update_experiment_studies(conn, exp["id"], studies)
    conn.commit()
    return {"ok": True, "studies": studies}


def api_all_studies(conn) -> dict:
    """Get all studies with usage counts."""
    from ...core.queries import get_all_studies
    return {"studies": get_all_studies(conn)}


def api_bulk_add_to_study(conn, body: dict) -> dict:
    """Add multiple experiments to a study."""
    name = body.get("study", "").strip()
    ids = body.get("ids", [])
    if not name:
        return {"error": "empty study name"}
    if not ids:
        return {"error": "no ids provided"}
    from ...core.queries import add_to_study
    added = 0
    for eid in ids:
        studies = add_to_study(conn, eid, name)
        if studies is not None:
            added += 1
    conn.commit()
    return {"ok": True, "study": name, "added": added}


def api_set_stage(conn, exp_id: str, body: dict) -> dict:
    """Set stage number and optional stage_name for an experiment."""
    from ...core.queries import update_experiment_stage
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    stage = body.get("stage")
    stage_name = body.get("stage_name", "")
    if stage is None and not stage_name:
        return {"error": "provide stage or stage_name"}
    if stage is not None:
        try:
            stage = int(stage)
        except (ValueError, TypeError):
            return {"error": "stage must be an integer"}
    update_experiment_stage(conn, exp["id"], stage, stage_name or None)
    conn.commit()
    return {"ok": True, "stage": stage, "stage_name": stage_name}


def api_manage_result_types(body: dict) -> dict:
    """Add/remove result types or namespace prefixes from project config."""
    from ...config import load, reload, save
    conf = load()
    default_types = ["accuracy", "loss", "auroc", "f1", "precision", "recall",
                     "mse", "mae", "r2", "perplexity", "bleu"]
    default_prefixes = ["train", "val", "test"]
    types = list(conf.get("result_types", default_types))
    prefixes = list(conf.get("metric_prefixes", default_prefixes))

    target = body.get("target", "type")  # "type" or "prefix"
    action = body.get("action", "")

    if target == "prefix":
        if action == "add":
            name = body.get("name", "").strip().lower().rstrip("/")
            if not name:
                return {"error": "empty name"}
            if name not in prefixes:
                prefixes.append(name)
        elif action == "remove":
            index = body.get("index", -1)
            if 0 <= index < len(prefixes):
                prefixes.pop(index)
        else:
            return {"error": "invalid action"}
        conf["metric_prefixes"] = prefixes
    else:
        if action == "add":
            name = body.get("name", "").strip().lower()
            if not name:
                return {"error": "empty name"}
            if name not in types:
                types.append(name)
        elif action == "remove":
            index = body.get("index", -1)
            if 0 <= index < len(types):
                types.pop(index)
        else:
            return {"error": "invalid action"}
        conf["result_types"] = types

    save(conf)
    reload()
    return {"ok": True, "types": types, "prefixes": prefixes}


def api_log_result(conn, exp_id: str, body: dict) -> dict:
    """Log a manual result. Routes to metrics table with source='manual'."""
    body = dict(body)
    body.setdefault("source", "manual")
    return api_log_metric(conn, exp_id, body)


def api_log_metric(conn, exp_id: str, body: dict) -> dict:
    """Log a metric value. All dashboard-logged values go to the metrics table.

    Accepts optional step. If step is omitted or empty, auto-increments from
    the highest existing step for that key.
    """
    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body.get("key", "").strip()
    value = body.get("value", "").strip()
    if not key or not value:
        return {"error": "provide key and value"}
    try:
        num_val = float(value)
    except ValueError:
        return {"error": "value must be a number"}

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()

    # Use explicit step if provided, otherwise auto-increment
    step_raw = body.get("step", "")
    if step_raw is not None and str(step_raw).strip() != "":
        try:
            step = int(step_raw)
        except (ValueError, TypeError):
            return {"error": "step must be an integer"}
    else:
        row = conn.execute(
            "SELECT MAX(COALESCE(step, -1)) as max_step FROM metrics WHERE exp_id=? AND key=?",
            (exp["id"], key)
        ).fetchone()
        step = (row["max_step"] + 1) if row and row["max_step"] is not None else 0

    source = body.get("source", "manual")

    # Never allow a manual metric to overwrite an auto-captured point at the same step
    if source == "manual":
        auto_row = conn.execute(
            "SELECT 1 FROM metrics WHERE exp_id=? AND key=? AND step=? AND (source IS NULL OR source != 'manual') LIMIT 1",
            (exp["id"], key, step)
        ).fetchone()
        if auto_row:
            return {"error": f"metric '{key}' already has an auto-captured value at step {step}"}

    conn.execute(
        "INSERT INTO metrics (exp_id, key, value, step, ts, source) VALUES (?,?,?,?,?,?)",
        (exp["id"], key, num_val, step, ts, source)
    )
    conn.commit()
    return {"ok": True, "key": key, "value": num_val, "step": step}


def api_delete_result(conn, exp_id: str, body: dict) -> dict:
    """Delete a manually logged result."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body.get("key", "").strip()
    if not key:
        return {"error": "provide key"}

    # Delete from metrics table (unified storage)
    conn.execute(
        "DELETE FROM metrics WHERE exp_id=? AND key=? AND source='manual'",
        (exp["id"], key)
    )
    # Also clean up any legacy _result:* param entries
    conn.execute(
        "DELETE FROM params WHERE exp_id=? AND key=?",
        (exp["id"], f"_result:{key}")
    )
    conn.commit()
    return {"ok": True}


def api_edit_result(conn, exp_id: str, body: dict) -> dict:
    """Edit a manually logged result value."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body.get("key", "").strip()
    value = body.get("value", "").strip()
    if not key or not value:
        return {"error": "provide key and value"}
    try:
        num_val = float(value)
    except ValueError:
        return {"error": "value must be a number"}

    ts = datetime.now(timezone.utc).isoformat()
    # Delete old manual entry and insert new one
    conn.execute(
        "DELETE FROM metrics WHERE exp_id=? AND key=? AND source='manual'",
        (exp["id"], key)
    )
    conn.execute(
        "INSERT INTO metrics (exp_id, key, value, step, ts, source) "
        "VALUES (?,?,?,0,?,?)",
        (exp["id"], key, num_val, ts, "manual")
    )
    # Clean up any legacy _result:* param
    conn.execute(
        "DELETE FROM params WHERE exp_id=? AND key=?",
        (exp["id"], f"_result:{key}")
    )
    conn.commit()
    return {"ok": True, "key": key, "value": num_val}


def api_delete_metric(conn, exp_id: str, body: dict) -> dict:
    """Delete metric data points. Supports deleting last step, a specific step, or all.

    body.mode: "last" (default) | "step" | "all"
    body.key: metric key (required)
    body.step: step number (required when mode="step")
    """
    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    key = body.get("key", "").strip()
    if not key:
        return {"error": "provide key"}

    mode = body.get("mode", "last")

    if mode == "all":
        conn.execute(
            "DELETE FROM metrics WHERE exp_id=? AND key=?",
            (exp["id"], key)
        )
    elif mode == "step":
        step = body.get("step")
        if step is None:
            return {"error": "provide step number"}
        conn.execute(
            "DELETE FROM metrics WHERE exp_id=? AND key=? AND step=?",
            (exp["id"], key, int(step))
        )
    else:
        # Delete just the last (highest step) entry
        conn.execute("""
            DELETE FROM metrics WHERE id = (
                SELECT id FROM metrics WHERE exp_id=? AND key=?
                ORDER BY COALESCE(step, 0) DESC, id DESC LIMIT 1
            )
        """, (exp["id"], key))

    conn.commit()
    remaining = conn.execute(
        "SELECT COUNT(*) as n FROM metrics WHERE exp_id=? AND key=?",
        (exp["id"], key)
    ).fetchone()["n"]
    return {"ok": True, "remaining": remaining}


def api_rename_metric(conn, exp_id: str, body: dict) -> dict:
    """Rename a metric key (e.g. 'loss' -> 'train/loss')."""
    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    old_key = body.get("old_key", "").strip()
    new_key = body.get("new_key", "").strip()
    if not old_key or not new_key:
        return {"error": "provide old_key and new_key"}
    if old_key == new_key:
        return {"ok": True}
    # Check old key exists
    count = conn.execute(
        "SELECT COUNT(*) as n FROM metrics WHERE exp_id=? AND key=?",
        (exp["id"], old_key)
    ).fetchone()["n"]
    if not count:
        return {"error": f"metric '{old_key}' not found"}
    conn.execute(
        "UPDATE metrics SET key=? WHERE exp_id=? AND key=?",
        (new_key, exp["id"], old_key)
    )
    conn.commit()
    return {"ok": True, "old_key": old_key, "new_key": new_key}


def api_edit_script(conn, exp_id: str, body: dict) -> dict:
    """Edit the script/notebook path for an experiment."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    script = body.get("script", "").strip()
    conn.execute(
        "UPDATE experiments SET script=?, updated_at=? WHERE id=?",
        (script or None, datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    conn.commit()
    return {"ok": True, "script": script}


def api_edit_command(conn, exp_id: str, body: dict) -> dict:
    """Edit the reproduce command for an experiment."""
    exp = find_experiment(conn, exp_id, "id")
    if not exp:
        return {"error": "not found"}
    command = body.get("command", "").strip()
    conn.execute(
        "UPDATE experiments SET command=?, updated_at=? WHERE id=?",
        (command or None, datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    conn.commit()
    return {"ok": True, "command": command}


def api_create_experiment(conn, body: dict) -> dict:
    """Create a manual experiment entry."""
    import uuid
    name = body.get("name", "").strip()
    if not name:
        return {"error": "name is required"}

    exp_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    created_at = body.get("created_at", "").strip() or now
    status = body.get("status", "done").strip()
    if status not in ("done", "failed", "running"):
        status = "done"

    script = body.get("script", "").strip() or None
    command = body.get("command", "").strip() or None
    notes = body.get("notes", "").strip() or None
    tags = body.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tags_json = json.dumps(tags) if tags else "[]"

    from ...config import load as load_config
    conf = load_config()
    project = conf.get("project", "")

    conn.execute(
        """INSERT INTO experiments
           (id, project, name, status, created_at, updated_at,
            script, command, hostname, python_ver, notes, tags, studies)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (exp_id, project, name, status, created_at, now,
         script, command, None, None, notes, tags_json, "[]")
    )

    # Insert params
    params = body.get("params", {})
    if isinstance(params, dict):
        for k, v in params.items():
            conn.execute(
                "INSERT INTO params (exp_id, key, value) VALUES (?,?,?)",
                (exp_id, k, json.dumps(v))
            )

    # Insert metrics
    metrics = body.get("metrics", {})
    if isinstance(metrics, dict):
        for k, v in metrics.items():
            try:
                num_val = float(v)
            except (ValueError, TypeError):
                continue
            conn.execute(
                "INSERT INTO metrics (exp_id, key, value, step, ts, source) VALUES (?,?,?,0,?,?)",
                (exp_id, k, num_val, now, "manual")
            )

    conn.commit()
    return {"ok": True, "id": exp_id}


def api_log_path(conn, exp_id: str, body: dict) -> dict:
    """Manage log paths for an experiment (add/edit/delete).

    Stored in experiments.log_paths as a JSON array of strings.
    """
    exp = find_experiment(conn, exp_id, "id, log_paths")
    if not exp:
        return {"error": "not found"}
    action = body.get("action", "")
    paths = json.loads(exp["log_paths"] or "[]")

    if action == "add":
        path = body.get("path", "").strip()
        if not path:
            return {"error": "empty path"}
        if path not in paths:
            paths.append(path)
    elif action == "delete":
        index = body.get("index", -1)
        if 0 <= index < len(paths):
            paths.pop(index)
    elif action == "edit":
        index = body.get("index", -1)
        path = body.get("path", "").strip()
        if 0 <= index < len(paths) and path:
            paths[index] = path
    else:
        return {"error": "invalid action"}

    conn.execute(
        "UPDATE experiments SET log_paths=?, updated_at=? WHERE id=?",
        (json.dumps(paths), datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    conn.commit()
    return {"ok": True, "paths": paths}


def api_image_path(conn, exp_id: str, body: dict) -> dict:
    """Manage image paths for an experiment (add/edit/delete).

    Stored in experiments.image_paths as a JSON array of strings.
    """
    exp = find_experiment(conn, exp_id, "id, image_paths")
    if not exp:
        return {"error": "not found"}
    action = body.get("action", "")
    paths = json.loads(exp["image_paths"] or "[]")

    if action == "add":
        path = body.get("path", "").strip()
        if not path:
            return {"error": "empty path"}
        if path not in paths:
            paths.append(path)
    elif action == "delete":
        index = body.get("index", -1)
        if 0 <= index < len(paths):
            paths.pop(index)
    elif action == "edit":
        index = body.get("index", -1)
        path = body.get("path", "").strip()
        if 0 <= index < len(paths) and path:
            paths[index] = path
    else:
        return {"error": "invalid action"}

    conn.execute(
        "UPDATE experiments SET image_paths=?, updated_at=? WHERE id=?",
        (json.dumps(paths), datetime.now(timezone.utc).isoformat(), exp["id"])
    )
    conn.commit()
    return {"ok": True, "paths": paths}


def api_clean_db(conn) -> dict:
    """Remove orphaned rows from all child tables and orphaned output dirs."""
    import shutil

    from ... import config as cfg
    from ...core.db import sweep_orphans

    counts = sweep_orphans(conn)
    total = sum(counts.values())

    # Clean orphaned output directories
    n_dirs = 0
    try:
        root = cfg.project_root()
        conf = cfg.load()
        outputs_dir = root / conf.get("outputs_dir", "outputs")
        if outputs_dir.is_dir():
            exp_dirs = set()
            for r in conn.execute(
                "SELECT output_dir FROM experiments WHERE output_dir IS NOT NULL"
            ).fetchall():
                exp_dirs.add(str(Path(r["output_dir"]).resolve()))
            exp_names = {r[0] for r in conn.execute("SELECT name FROM experiments").fetchall()}
            for child in outputs_dir.iterdir():
                if not child.is_dir():
                    # Remove orphan files too (e.g. leftover .exptrack_run.env)
                    resolved = str(child.resolve())
                    # Check if any experiment output_dir contains this file
                    if not any(resolved.startswith(d) for d in exp_dirs):
                        child.unlink()
                        n_dirs += 1
                    continue
                resolved = str(child.resolve())
                if resolved not in exp_dirs and child.name not in exp_names:
                    shutil.rmtree(child)
                    n_dirs += 1
    except Exception:
        pass
    if n_dirs:
        counts["output_dirs"] = n_dirs
        total += n_dirs

    return {"ok": True, "removed": total, "details": counts}


def api_vacuum_db(conn) -> dict:
    """Checkpoint WAL and VACUUM the database to reclaim space."""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def api_reset_db(conn) -> dict:
    """Delete ALL experiments and data, then VACUUM."""
    import shutil

    from ... import config as cfg
    from ...core.db import delete_experiment

    rows = conn.execute("SELECT id FROM experiments").fetchall()
    n_exp = len(rows)
    for r in rows:
        delete_experiment(conn, r["id"])
    # Clear remaining tables
    for table in ("params", "metrics", "artifacts", "timeline",
                  "cell_lineage", "code_baselines", "git_diffs"):
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:
            pass
    conn.commit()
    # Clean outputs directory
    try:
        root = cfg.project_root()
        conf = cfg.load()
        outputs_dir = root / conf.get("outputs_dir", "outputs")
        if outputs_dir.is_dir():
            for child in outputs_dir.iterdir():
                try:
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    except Exception:
        pass
    return {"ok": True, "deleted_experiments": n_exp}


def api_storage_info(conn) -> dict:
    """Return database size and WAL size info."""
    from ... import config as cfg
    root = cfg.project_root()
    conf = cfg.load()
    db_path = root / conf.get("db", ".exptrack/experiments.db")
    wal_path = Path(str(db_path) + "-wal")
    db_size = db_path.stat().st_size if db_path.exists() else 0
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    n_exp = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    n_params = conn.execute("SELECT COUNT(*) FROM params").fetchone()[0]
    n_metrics = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    n_artifacts = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    n_timeline = conn.execute("SELECT COUNT(*) FROM timeline").fetchone()[0]
    return {
        "ok": True,
        "db_bytes": db_size,
        "wal_bytes": wal_size,
        "total_bytes": db_size + wal_size,
        "experiments": n_exp,
        "params": n_params,
        "metrics": n_metrics,
        "artifacts": n_artifacts,
        "timeline": n_timeline,
    }
