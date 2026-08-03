"""
exptrack/dashboard/routes/read_routes.py — Read-only API endpoints

GET endpoints for stats, experiments, metrics, diffs, timelines, exports.
"""
from __future__ import annotations

import threading
import time

from ...core.queries import (
    find_previous_by_script,
    get_all_tags,
    get_cell_source,
    get_experiment_detail,
    get_experiment_diff,
    get_export_data,
    get_metrics_series,
    get_stats,
    get_studies,
    get_timeline_events,
    get_vars_at_seq,
    list_experiments,
)

# SQLite binds Python ints as 64-bit; anything beyond raises OverflowError at
# execute time, so every query-param int is clamped into range here.
_SQLITE_INT_MAX = 2**63 - 1


def _qint(qs: dict, key: str, default: int) -> int:
    """Parse an int query param, falling back to default on junk input.

    Keeps malformed query strings (?limit=abc) a 200-with-default instead of a
    500 traceback, and clamps to SQLite's integer range so a huge ?offset=
    can't overflow the parameter binding into a 500 either.
    """
    try:
        val = int(qs.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(-_SQLITE_INT_MAX, min(val, _SQLITE_INT_MAX))


def api_stats(conn) -> dict:
    return get_stats(conn)


# Ceiling on rows one /api/experiments request may return. The client pages in
# EXP_PAGE_SIZE (1000) chunks and its "load all" path walks offsets, so nothing
# in the dashboard asks for more — but `limit` is client-supplied and was
# unbounded, so a single request could ask the server to build the whole
# project's list in memory and serialize it.
_MAX_LIST_LIMIT = 5000


def api_experiments(conn, qs: dict) -> list:
    limit = max(0, min(_qint(qs, "limit", 50), _MAX_LIST_LIMIT))
    offset = max(0, _qint(qs, "offset", 0))
    status = qs.get("status", "")
    return list_experiments(conn, limit=limit, status=status, offset=offset)


def api_experiment(conn, exp_id: str) -> dict:
    result = get_experiment_detail(conn, exp_id)
    return result if result else {"error": "not found"}


def api_prev_by_script(conn, exp_id: str) -> dict:
    """Previous experiment with the same script + its params, for the Overview
    "What changed" card. `{}` when there's no earlier same-script run."""
    return find_previous_by_script(conn, exp_id) or {}


def api_trash(conn) -> dict:
    """Return the unified trash: trashed experiments AND trashed session nodes
    (grouped by session). Shape: {experiments: [...], sessions: [...], counts}.

    Carries a ``storage`` block so the view can state what the Trash costs —
    the whole point of soft delete is that nothing is reclaimed until you say
    so, which means the bill has to be visible somewhere. It rides on this
    route, not on the polled badge count, because measuring it walks the
    database's pages and the trashed runs' output directories.
    """
    from ...core.storage import trash_storage
    from ...core.trash import list_unified_trash
    from ...core.utils import safe_call
    payload = list_unified_trash(conn)
    payload["storage"] = safe_call(trash_storage, conn, default=None,
                                   context="api_trash storage")
    return payload


def api_delete_preview(conn, exp_id: str) -> dict:
    """Summary of what permanent deletion of this experiment would remove."""
    from ...core.db import get_delete_preview
    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    return get_delete_preview(conn, exp["id"])


def api_list_confusion(conn, exp_id: str) -> dict:
    """Return the list of saved confusion matrices for this experiment."""
    import json as _json

    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    row = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key=?",
        (exp["id"], "_confusion_matrices"),
    ).fetchone()
    if not row:
        return {"matrices": []}
    try:
        data = _json.loads(row["value"]) if row["value"] else {}
    except (ValueError, TypeError):
        data = {}
    matrices = data.get("matrices", []) if isinstance(data, dict) else []
    return {"matrices": matrices}


def api_metrics(conn, exp_id: str, qs: dict | None = None) -> dict:
    from ...config import load
    from ...core.queries import find_experiment
    exp = find_experiment(conn, exp_id)
    if not exp:
        return {"error": "not found"}
    conf = load()
    max_points = conf.get("metric_max_points", 500)
    if qs and "max_points" in qs:
        try:
            max_points = max(10, min(50000, int(qs["max_points"])))
        except (ValueError, TypeError):
            pass
    return get_metrics_series(conn, exp["id"], max_points=max_points)


def api_diff(conn, exp_id: str) -> dict:
    result = get_experiment_diff(conn, exp_id)
    return result if result else {"error": "not found"}


def api_run_delta(conn, exp_id: str) -> dict:
    """What changed vs the previous run of the same script (the 'vs previous'
    strip on the detail view). Returns {previous: {...}, ...diff} or
    {previous: None} when this is the first run of its script."""
    from ...core.queries import diff_runs, find_experiment, format_run_delta, get_previous_run
    exp = find_experiment(conn, exp_id, "id, created_at")
    if not exp:
        return {"error": "not found"}
    prev = get_previous_run(conn, exp["id"])
    if not prev:
        return {"previous": None}
    diff = diff_runs(conn, prev["id"], exp["id"])
    diff["previous"] = {
        "id": prev["id"], "name": prev.get("name") or "",
        "created_at": prev.get("created_at") or "",
        # So the strip can mark a crashed baseline — its metrics stop where it
        # died, which an unqualified delta would present as a measured result.
        "status": prev.get("status") or "",
    }
    # So the strip can state how much *earlier* the baseline ran — a timestamp
    # alone doesn't tell the reader which direction the comparison runs.
    diff["current_created_at"] = exp.get("created_at") or ""
    diff["summary"] = format_run_delta(diff, prev)
    return diff


def api_compare(conn, qs: dict) -> dict:
    id1, id2 = qs.get("id1", ""), qs.get("id2", "")
    if not id1 or not id2:
        return {"error": "provide id1 and id2"}
    from ...core.queries import compare_run_code
    # compare_run_code resolves both ids and orders them older → newer itself.
    return {
        "exp1": api_experiment(conn, id1),
        "exp2": api_experiment(conn, id2),
        "code_diff": compare_run_code(conn, id1, id2),
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
    seq = _qint(qs, "seq", 999999)
    return get_vars_at_seq(conn, exp["id"], seq=seq)


def api_cell_source(conn, cell_hash: str) -> dict:
    result = get_cell_source(conn, cell_hash)
    if not result:
        return {"error": "cell not found", "cell_hash": cell_hash}
    return result


def api_run_source(conn, exp_id: str) -> dict:
    """The code a run actually ran — script snapshot or notebook cells.

    Backs the Timeline tab's source fold. Independent of the file on disk, so it
    still answers after the script has been edited or deleted.
    """
    from ...core.queries import get_run_source
    result = get_run_source(conn, exp_id)
    if not result["id"]:
        return {"error": "experiment not found", "id": exp_id}
    return result


def api_export(conn, exp_id: str, qs: dict) -> dict:
    from ...core.queries import PARAMS_EXPORT_FORMATS, format_export_markdown, format_export_params
    full = str(qs.get("full", "")).lower() in ("1", "true", "yes")
    data = get_export_data(conn, exp_id, full=full)
    if not data:
        return {"error": "not found"}
    fmt = qs.get("format", "json")
    if fmt == "markdown":
        md = format_export_markdown(data)
        return {"markdown": md, "data": data}
    if fmt in PARAMS_EXPORT_FORMATS:
        return {"params_text": format_export_params(data, style=PARAMS_EXPORT_FORMATS[fmt]),
                "data": data}
    return data


def api_all_tags(conn) -> dict:
    return {"tags": get_all_tags(conn)}


def api_get_timezone() -> dict:
    from ...config import load
    conf = load()
    return {"timezone": conf.get("timezone", "")}


def api_get_metric_settings() -> dict:
    from ...config import load
    conf = load()
    return {
        "metric_keep_every": conf.get("metric_keep_every", 1),
        "metric_max_points": conf.get("metric_max_points", 500),
    }


def api_get_capture_settings() -> dict:
    from ...config import load
    conf = load()
    auto = conf.get("auto_capture", {}) or {}
    return {
        "notebook_capture": bool(auto.get("notebook", True)),
        "var_fingerprint_max_mb": int(conf.get("var_fingerprint_max_mb", 100)),
    }


def api_result_types() -> dict:
    from ...config import load, save
    conf = load()
    default_types = ["accuracy", "loss", "auroc", "f1", "precision", "recall",
                     "mse", "mae", "r2", "perplexity", "bleu"]
    default_prefixes = ["train", "val", "test"]
    types = conf.get("result_types", default_types)
    prefixes = conf.get("metric_prefixes", default_prefixes)
    # Reverse-migrate abbreviations back to full names
    _full = {"acc": "accuracy", "prec": "precision", "rec": "recall", "ppl": "perplexity"}
    migrated = [_full.get(t, t) for t in types]
    if migrated != types:
        conf["result_types"] = migrated
        save(conf)
        types = migrated
    return {"types": types, "prefixes": prefixes}


def api_studies(conn) -> dict:
    return {"studies": get_studies(conn)}


def api_multi_compare(conn, qs: dict) -> dict:
    """Compare multiple experiments: names, latest metrics, and results."""
    from ...core.queries import get_multi_compare
    ids_str = qs.get("ids", "")
    if not ids_str:
        return {"error": "provide ids parameter (comma-separated)"}
    ids = [i.strip() for i in ids_str.split(",") if i.strip()]
    if len(ids) < 2:
        return {"error": "provide at least 2 experiment ids"}
    return {"experiments": get_multi_compare(conn, ids)}


# Directories a project-wide scan never descends into: version control,
# exptrack's own store, and the usual multi-gigabyte dependency trees. Without
# this the walk below spends its whole budget inside node_modules.
_SCAN_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".exptrack", "node_modules", "__pycache__",
    ".venv", "venv", "env", ".env", ".tox", ".mypy_cache", ".pytest_cache",
    ".ipynb_checkpoints", "site-packages", ".idea", ".vscode", "dist", "build",
}
_SCAN_MAX_DEPTH = 3      # deep enough for data/raw/train, shallow enough to stay fast
_SCAN_MAX_DIRS = 400     # hard ceiling on directories examined
_SCAN_CACHE_TTL = 60.0   # seconds; suggestions are advisory, so staleness is cheap

# One cached walk per project root: {root: (expires_at, {rel_dir: {ext: count}})}.
# The walk is up to _SCAN_MAX_DIRS directory listings — ~10 ms on local disk but
# seconds on an sshfs/NFS-mounted project — and it would otherwise run on every
# Images and Data Files request, including the ones a live run's 5-second
# refresh re-issues and the two a Compare view opens at once. Caching per root
# rather than per extension set means opening Images and then Data Files shares
# a single walk.
_scan_cache: dict = {}
_scan_cache_lock = threading.Lock()


def _walk_ext_counts(root: str) -> dict:
    """Per-directory extension histograms for the project, cached with a TTL.

    Bounded by depth and by total directories examined rather than being
    allowed to traverse the whole tree, since a project root can be
    arbitrarily large.
    """
    import os
    now = time.monotonic()
    hit = _scan_cache.get(root)
    if hit and hit[0] > now:
        return hit[1]

    found: dict = {}
    for examined, (dirpath, dirnames, filenames) in enumerate(os.walk(root)):
        if examined >= _SCAN_MAX_DIRS:
            break
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        # Prune in place so os.walk never descends into them at all.
        dirnames[:] = [d for d in dirnames
                       if d not in _SCAN_SKIP_DIRS and not d.startswith(".")]
        if depth >= _SCAN_MAX_DEPTH:
            dirnames[:] = []
        hist: dict = {}
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext:
                hist[ext] = hist.get(ext, 0) + 1
        if hist:
            found[rel if rel != "." else "."] = hist

    with _scan_cache_lock:
        _scan_cache[root] = (now + _SCAN_CACHE_TTL, found)
    return found


# Bounds on a *saved* scan path's walk. Unlike the suggestion walk above this
# one is not cached — it has to reflect files the run just wrote — and both tabs
# re-issue it constantly (a live run's 5-second refresh, the two requests a
# Compare view opens at once). A saved path routinely points at a
# checkpoint-per-epoch tree, so without a ceiling one tab open meant thousands
# of stat calls and a JSON body listing every file, on every request.
_SCAN_MAX_WALK_DIRS = 2000
_SCAN_MAX_FILES = 5000


def _collect_scan_files(root: str, paths: list, exts: set) -> tuple[list, bool]:
    """Files matching *exts* under the saved scan paths, newest first.

    Returns ``(files, truncated)``. A saved path may also be a single file.
    Traversal is bounded by ``_SCAN_MAX_WALK_DIRS`` / ``_SCAN_MAX_FILES`` and
    prunes the same version-control and dependency trees the suggestion walk
    does; ``truncated`` is reported so the tab can say what it left out rather
    than presenting a partial list as the whole set.
    """
    import os

    from ...config import readable_project_path
    files: list = []
    walked_dirs = 0
    truncated = False

    def _entry(full: str, base_dir: str):
        try:
            stat = os.stat(full)
        except OSError:
            return None
        ext = os.path.splitext(full)[1].lower()
        return {
            "name": os.path.basename(full),
            "path": os.path.relpath(full, root),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "dir": os.path.relpath(os.path.dirname(full), base_dir) or ".",
            "ext": ext[1:],
        }

    for scan_path in paths:
        contained = readable_project_path(scan_path)
        if contained is None:
            continue  # outside the project, or exptrack's own internals
        abs_dir = str(contained)
        if not os.path.isdir(abs_dir):
            if os.path.isfile(abs_dir) and os.path.splitext(abs_dir)[1].lower() in exts:
                entry = _entry(abs_dir, os.path.dirname(abs_dir))
                if entry:
                    files.append(entry)
            continue
        for dirpath, dirnames, filenames in os.walk(abs_dir):
            walked_dirs += 1
            if walked_dirs > _SCAN_MAX_WALK_DIRS:
                truncated = True
                break
            # Sorted + pruned in place: deterministic order across requests, so
            # a truncated listing is at least a stable one.
            dirnames[:] = sorted(d for d in dirnames if d not in _SCAN_SKIP_DIRS)
            for fn in sorted(filenames):
                if os.path.splitext(fn)[1].lower() not in exts:
                    continue
                if len(files) >= _SCAN_MAX_FILES:
                    truncated = True
                    break
                entry = _entry(os.path.join(dirpath, fn), abs_dir)
                if entry:
                    files.append(entry)
            if truncated:
                break
        if truncated:
            break

    files.sort(key=lambda x: x["modified"], reverse=True)
    return files, truncated


def _walk_candidate_dirs(root: str, exts: set) -> dict:
    """Project directories containing files with *exts*, mapped to their count."""
    return {rel: n for rel, hist in _walk_ext_counts(root).items()
            if (n := sum(c for ext, c in hist.items() if ext in exts))}


def _suggested_scan_paths(conn, exp, root: str, exts: set, saved: list) -> list:
    """Directories worth scanning for this run, best first.

    Suggestions used to be `output_dir` and its immediate subdirectories only,
    and were hidden as soon as one path had been saved — so the common case
    (data living somewhere else entirely, and needing a *second* path) was left
    to typing a raw relative path by hand. These are drawn from what the run
    actually touched first, then from the project layout.
    """
    import json
    import os

    out: list = []
    seen = {p.strip("/") for p in (saved or [])}

    def rel_inside(path):
        """Project-relative form of *path*, or None if it escapes the root.

        Anything outside the project cannot be served by /api/file/, so it is
        never a useful suggestion.
        """
        p = str(path or "")
        if not p:
            return None
        rel = os.path.relpath(p, root) if os.path.isabs(p) else p
        return None if rel.startswith("..") else rel

    def add(path, why, known_dir=False):
        p = str(path or "").strip("/")
        if not p or p in seen:
            return
        # known_dir: os.walk already proved this is a directory, so skip the
        # stat — on a network filesystem that is hundreds of avoidable calls.
        if not known_dir and not os.path.isdir(os.path.join(root, p)):
            return
        seen.add(p)
        out.append({"path": p, "why": why})

    # 1. The run's own output directory and its immediate children.
    output_dir = exp.get("output_dir") or ""
    if output_dir:
        add(output_dir, "this run's output dir")
        try:
            for entry in sorted(os.scandir(os.path.join(root, output_dir)),
                                key=lambda e: e.name):
                if entry.is_dir():
                    add(os.path.join(output_dir, entry.name), "in the output dir")
        except OSError:
            pass

    # 2. Directories the run's registered artifacts live in — files it really
    #    wrote, which is a stronger signal than anything the layout implies.
    try:
        for r in conn.execute("SELECT DISTINCT path FROM artifacts WHERE exp_id=?",
                              (exp["id"],)).fetchall():
            rel = rel_inside(r["path"])
            if rel:
                add(os.path.dirname(rel), "holds this run's outputs")
    except Exception:
        pass

    # 3. Inputs exptrack fingerprinted for this run (the dataset manifest).
    try:
        row = conn.execute(
            "SELECT value FROM params WHERE exp_id=? AND key='_dataset_manifest'",
            (exp["id"],)).fetchone()
        manifest = json.loads(row["value"]) if row else {}
        if isinstance(manifest, str):
            manifest = json.loads(manifest)
        for entry in (manifest or {}).values() if isinstance(manifest, dict) else []:
            if not isinstance(entry, dict):
                continue
            rel = rel_inside(entry.get("path"))
            if rel:
                add(rel if entry.get("kind") == "dir" else os.path.dirname(rel),
                    "a dataset this run read")
    except Exception:
        pass

    # 4. Anywhere else in the project actually holding matching files.
    try:
        for rel, n in sorted(_walk_candidate_dirs(root, exts).items(),
                             key=lambda kv: -kv[1]):
            add(rel, f"{n} matching file{'s' if n != 1 else ''}", known_dir=True)
    except Exception:
        pass

    return out[:12]


def api_list_logs(conn, exp_id: str) -> dict:
    """List log/text/data files from user-configured paths for this experiment."""
    import json

    from ...config import project_root
    from ...core.queries import find_experiment

    exp = find_experiment(conn, exp_id, "id, output_dir, log_paths")
    if not exp:
        return {"error": "not found"}

    root = str(project_root())

    # Load saved log paths from dedicated column
    paths = json.loads(exp["log_paths"] or "[]")

    log_exts = {'.log', '.txt', '.out', '.err', '.csv', '.json', '.jsonl', '.tsv'}
    suggested = _suggested_scan_paths(conn, exp, root, log_exts, paths)

    # Scan log/text/data files from saved paths (bounded — see _collect_scan_files)
    files, truncated = _collect_scan_files(root, paths, log_exts)
    return {"files": files, "paths": paths, "suggested_paths": suggested,
            "truncated": truncated, "max_files": _SCAN_MAX_FILES}


def api_get_todos() -> dict:
    """Return the todo list from project config."""
    from ...config import load
    conf = load()
    return {"todos": conf.get("todos", [])}


def api_get_commands() -> dict:
    """Return saved commands from project config."""
    from ...config import load
    conf = load()
    return {"commands": conf.get("commands", [])}


def api_list_images(conn, exp_id: str) -> dict:
    """List images from user-configured paths for this experiment."""
    import json
    import os

    from ...config import project_root
    from ...core.queries import IMAGE_EXTS, _rel_path, find_experiment

    exp = find_experiment(conn, exp_id, "id, output_dir, image_paths")
    if not exp:
        return {"error": "not found"}

    root = str(project_root())

    # Load saved image paths from dedicated column
    paths = json.loads(exp["image_paths"] or "[]")

    image_exts_set = set(IMAGE_EXTS)
    suggested = _suggested_scan_paths(conn, exp, root, image_exts_set, paths)

    # Scan images from saved paths (bounded — see _collect_scan_files)
    images, truncated = _collect_scan_files(root, paths, image_exts_set)

    # Also include image artifacts from the artifacts table
    artifact_images = []
    art_rows = conn.execute(
        "SELECT label, path, created_at FROM artifacts WHERE exp_id=?",
        (exp["id"],)
    ).fetchall()
    for r in art_rows:
        if not r["path"] or not any(r["path"].lower().endswith(ext) for ext in IMAGE_EXTS):
            continue
        art_path = _rel_path(r["path"])
        abs_path = os.path.normpath(os.path.join(root, art_path))
        try:
            stat = os.stat(abs_path)
            size, modified = stat.st_size, stat.st_mtime
        except OSError:
            size, modified = 0, 0
        artifact_images.append({
            "name": os.path.basename(art_path),
            "path": art_path,
            "size": size,
            "modified": modified,
            "dir": "artifacts",
            "label": r["label"],
        })

    return {
        "images": images, "paths": paths,
        "suggested_paths": suggested, "artifact_images": artifact_images,
        "truncated": truncated, "max_files": _SCAN_MAX_FILES,
    }




# ── Session Trees ────────────────────────────────────────────────────────────

def api_sessions(conn) -> dict:
    """List all sessions with summary counts."""
    from ...sessions.tree import list_sessions
    return {"sessions": list_sessions()}


def api_session_tree(conn, session_id: str) -> dict:
    """Return a session's full tree."""
    from ...sessions.manager import build_tree
    tree = build_tree(session_id)
    if not tree:
        return {"error": "not found"}
    return tree


def api_session_nodes(conn, session_id: str) -> dict:
    """Return the flat node list for a session (live nodes only)."""
    rows = conn.execute(
        "SELECT id, parent_id, node_type, label, note, seq, created_at "
        "FROM session_nodes WHERE session_id=? AND deleted_at IS NULL "
        "ORDER BY seq",
        (session_id,),
    ).fetchall()
    return {"nodes": [dict(r) for r in rows]}


def api_session_trash(conn, session_id: str) -> dict:
    """Return the session's trashed nodes (for the Trash panel)."""
    from ...sessions.manager import list_trashed_nodes
    sess = conn.execute(
        "SELECT id FROM sessions WHERE id=?", (session_id,),
    ).fetchone()
    if not sess:
        return {"error": "not found"}
    return {"nodes": list_trashed_nodes(session_id)}


def api_session_finalize_preview(conn, session_id: str) -> dict:
    """Preview what `finalize` would graduate: the session's nodes annotated
    with promoted/un-promoted status for the Finalize checklist UI."""
    from ...sessions.manager import finalize_session_preview
    res = finalize_session_preview(session_id)
    if not res.get("ok"):
        return {"error": res.get("error", "not found")}
    return res
