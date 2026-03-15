"""
exptrack/dashboard/routes/read_routes.py — Read-only API endpoints

GET endpoints for stats, experiments, metrics, diffs, timelines, exports.
"""
from __future__ import annotations

from ...core.queries import (
    get_stats, list_experiments, get_experiment_detail, get_metrics_series,
    get_experiment_diff, get_timeline_events, get_vars_at_seq,
    get_cell_source, get_export_data, get_all_tags, get_groups,
)


def api_stats(conn) -> dict:
    return get_stats(conn)


def api_experiments(conn, qs: dict) -> list:
    limit = int(qs.get("limit", 50))
    status = qs.get("status", "")
    return list_experiments(conn, limit=limit, status=status)


def api_experiment(conn, exp_id: str) -> dict:
    result = get_experiment_detail(conn, exp_id)
    return result if result else {"error": "not found"}


def api_metrics(conn, exp_id: str) -> dict:
    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    return get_metrics_series(conn, exp["id"])


def api_diff(conn, exp_id: str) -> dict:
    result = get_experiment_diff(conn, exp_id)
    return result if result else {"error": "not found"}


def api_compare(conn, qs: dict) -> dict:
    id1, id2 = qs.get("id1", ""), qs.get("id2", "")
    if not id1 or not id2:
        return {"error": "provide id1 and id2"}
    return {
        "exp1": api_experiment(conn, id1),
        "exp2": api_experiment(conn, id2),
    }


def api_timeline(conn, exp_id: str, qs: dict) -> list | dict:
    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    event_type = qs.get("type", "")
    return get_timeline_events(conn, exp["id"], event_type=event_type)


def api_vars_at(conn, exp_id: str, qs: dict) -> dict:
    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    seq = int(qs.get("seq", 999999))
    return get_vars_at_seq(conn, exp["id"], seq=seq)


def api_cell_source(conn, cell_hash: str) -> dict:
    result = get_cell_source(conn, cell_hash)
    if not result:
        return {"error": "cell not found", "cell_hash": cell_hash}
    return result


def api_export(conn, exp_id: str, qs: dict) -> dict:
    from ...core.queries import format_export_markdown
    data = get_export_data(conn, exp_id)
    if not data:
        return {"error": "not found"}
    fmt = qs.get("format", "json")
    if fmt == "markdown":
        md = format_export_markdown(data)
        return {"markdown": md, "data": data}
    return data


def api_all_tags(conn) -> dict:
    return {"tags": get_all_tags(conn)}


def api_get_timezone() -> dict:
    from ...config import load
    conf = load()
    return {"timezone": conf.get("timezone", "")}


def api_groups(conn) -> dict:
    return {"groups": get_groups(conn)}


def api_list_images(conn, exp_id: str) -> dict:
    """List images from user-configured paths for this experiment."""
    import json
    import os
    from ...core.queries import find_experiment
    from ...config import project_root

    exp = find_experiment(conn, exp_id, "id, output_dir, image_paths")
    if not exp:
        return {"error": "not found"}

    root = str(project_root())

    # Load saved image paths from dedicated column
    paths = json.loads(exp["image_paths"] or "[]")

    # Build suggested paths from output_dir
    output_dir = exp["output_dir"] or ""
    suggested = []
    if output_dir and os.path.isdir(os.path.join(root, output_dir)):
        suggested.append(output_dir)
        # Also suggest subdirectories of output_dir
        try:
            for entry in os.scandir(os.path.join(root, output_dir)):
                if entry.is_dir():
                    suggested.append(os.path.join(output_dir, entry.name))
        except OSError:
            pass

    # Scan images from saved paths
    image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.tiff', '.webp'}
    images = []
    for scan_path in paths:
        abs_dir = os.path.normpath(os.path.join(root, scan_path))
        if not abs_dir.startswith(os.path.normpath(root)):
            continue  # security: stay within project
        if not os.path.isdir(abs_dir):
            continue
        for dirpath, _, filenames in os.walk(abs_dir):
            for fn in sorted(filenames):
                ext = os.path.splitext(fn)[1].lower()
                if ext in image_exts:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, root)
                    try:
                        stat = os.stat(full)
                    except OSError:
                        continue
                    images.append({
                        "name": fn,
                        "path": rel,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "dir": os.path.relpath(dirpath, abs_dir) or ".",
                    })
    images.sort(key=lambda x: x["modified"], reverse=True)
    return {"images": images, "paths": paths, "suggested_paths": suggested}


