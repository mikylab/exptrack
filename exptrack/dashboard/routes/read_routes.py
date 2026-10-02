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
    """Project counters, plus which runs are pinned as references.

    The reference ids ride along here rather than on every list row: there are
    at most a handful, the stats call already runs on boot and after every
    mutation, and per-row resolution would mean re-deriving each run's study
    membership for a badge. The client marks a run that *is* a reference; which
    reference applies *to* a given run stays a detail-view question, where the
    strip can state the level it was set at.

    Read from config with **no query** — this is the most-called endpoint in the
    app, and resolving each reference's row here would be one PK select per
    configured level per call for fields (name, status, staleness) that a badge
    throws away. The detail strip resolves properly, where it matters.
    """
    from ...core.reference import configured_ids

    stats = get_stats(conn)
    stats["references"] = configured_ids()
    # Several checkouts and a remote box can each run a different exptrack —
    # the sidebar renders this so "which version is this dashboard" is never
    # a guess. Rides along here since /api/stats already runs on boot and
    # after every mutation, so this costs no extra request.
    from ... import __version__

    stats["version"] = __version__
    return stats


def api_projects(requested: str = "") -> dict:
    """Every project the switcher can offer, and which one is active.

    Takes no connection: the active project's database holds nothing about any
    *other* project, so this answer is built from discovery, which probes each
    candidate read-only (see projects.probe_status — opening a skewed project
    migrates it). The dispatcher still opens the active project's database
    before calling this, as it does for every GET row; the point of the empty
    signature is that no other project is opened, not that none is.

    `path` rides along for display only and is never accepted back as input.
    The client names a project by `id`, and the handler rebuilds the id ->
    path map from discovery on every request, so a path in this payload can
    never become a path the server opens.

    `requested` is the id from the `X-Exptrack-Project` header, passed in
    because this route is exempt from the normal per-request activation (see
    handler.py's `_PROJECT_EXEMPT_PATHS`) — it is the dashboard's recovery
    surface, so it must answer even when the stored id names a project that
    is unknown, stale or schema-skewed, none of which the normal path lets
    through. `current` mirrors what activation *would* have done: the
    requested id when it names a known, healthy entry, and the default
    project's id otherwise — so the switcher still highlights the right
    option on every request, including the ones a stale header can't resolve.
    """
    from ... import config as cfg
    from ... import projects

    root = cfg.project_root()
    entries = projects.discover(current_root=root)
    # Worktrees of one repository are grouped for display only — they stay
    # separate projects with separate databases, and `group` never decides
    # which one a request reads. Annotated here rather than in `discover`
    # because it costs a git subprocess per project, and `discover` also runs
    # on the request path that resolves an id (see projects.discover_cached).
    projects.annotate_worktree_groups(entries)
    current = projects.project_id(root)
    if requested and any(e["id"] == requested and e["status"] == projects.SCHEMA_OK
                          for e in entries):
        current = requested
    return {"projects": entries, "current": current}


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
    if not result:
        return {"error": "not found"}
    # The commit on the hosted repository, so the header's hash is a link.
    # Read from .git/config, never a git spawn: this route is polled.
    from ...core.git import commit_web_url
    from ...core.queries import _export_git_web
    result["git_commit_url"] = commit_web_url(_export_git_web(),
                                              result.get("git_commit") or "")
    return result


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


def api_reference_delta(conn, exp_id: str) -> dict:
    """This run measured against the reference run in force for it.

    Separate from ``/api/run-delta/`` on purpose: that answers "what changed
    since last time" (lineage), this answers "is it better than the thing I am
    trying to beat" (a fixed target). Both are rendered from the same
    ``diff_runs`` rules, so they differ only in which baseline they name — which
    is exactly the distinction the user is meant to see.
    """
    from ...core.reference import delta_vs_reference
    return delta_vs_reference(conn, exp_id)


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
    # `patch=0` is Copy: the patch goes out through Export .patch instead of
    # riding along in the pasted document.
    patch = str(qs.get("patch", "1")).lower() not in ("0", "false", "no")
    if fmt == "markdown":
        # `html` rides along so Copy can put real tables on the clipboard for
        # OneNote/Word while a markdown editor still receives the text.
        from ...core.export_render import export_bundle
        return {**export_bundle(format_export_markdown(data, patch=patch)), "data": data}
    if fmt in ("text", "html"):
        # Rendered here, not in the browser, so `exptrack export --format
        # text|html` and the dashboard print the same thing.
        from ...core.export_render import render_runs
        return {"content": render_runs([data], fmt, patch=patch), "format": fmt, "data": data}
    if fmt in PARAMS_EXPORT_FORMATS:
        text = format_export_params(data, style=PARAMS_EXPORT_FORMATS[fmt])
        out = {"params_text": text, "data": data}
        if fmt == "params-md":
            from ...core.export_render import markdown_to_html
            out["html"] = markdown_to_html(text)
        return out
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
    seen_paths: set = set()
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
                if entry and entry["path"] not in seen_paths:
                    seen_paths.add(entry["path"])
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
                # Two saved scan paths can nest (``outputs`` and
                # ``outputs/figs``); the same file walked twice listed the
                # image twice.
                if entry and entry["path"] not in seen_paths:
                    seen_paths.add(entry["path"])
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


def _drop_scanned_duplicates(root: str, images: list, artifact_images: list) -> list:
    """Artifact images that are not already in the scanned list, by content.

    A configured scan folder often *is* where the run wrote its figures, so the
    same image arrived twice — once from the walk, once from its artifact row —
    and the gallery showed every plot twice. Path equality does not catch it:
    the artifact row can point at the savefig copy under ``outputs/<run>/``.
    Hashing is gated on an exact size match, so files the scan cannot possibly
    duplicate are never read.
    """
    import os

    from ...core.hashing import file_hash

    by_size: dict = {}
    for img in images:
        by_size.setdefault(img.get("size"), []).append(img)
    if not by_size:
        return artifact_images

    cache: dict = {}

    def _digest(rel: str):
        if rel not in cache:
            try:
                cache[rel] = file_hash(os.path.normpath(os.path.join(root, rel)))[0]
            except OSError:
                cache[rel] = None
        return cache[rel]

    kept = []
    for art in artifact_images:
        peers = by_size.get(art.get("size")) or []
        art_digest = _digest(art["path"]) if peers else None
        if art_digest is not None and any(_digest(p["path"]) == art_digest for p in peers):
            continue
        kept.append(art)
    return kept


def api_list_images(conn, exp_id: str) -> dict:
    """List images from user-configured paths for this experiment."""
    import json
    import os

    from ...config import project_root
    from ...core.queries import (
        IMAGE_EXTS,
        _rel_path,
        drop_protected_copy_duplicates,
        find_experiment,
    )

    exp = find_experiment(conn, exp_id, "id, name, output_dir, image_paths")
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
        "SELECT label, path, created_at, content_hash, size_bytes FROM artifacts "
        "WHERE exp_id=?", (exp["id"],)
    ).fetchall()
    # The savefig patch registers its copy under `outputs/` and the finish-time
    # scan registers the file the script wrote: two rows, one image, and this
    # tab showed every plot twice. See drop_protected_copy_duplicates.
    img_rows = drop_protected_copy_duplicates([
        {"label": r["label"], "path": r["path"], "hash": r["content_hash"],
         "size": r["size_bytes"]}
        for r in art_rows
        if r["path"] and any(r["path"].lower().endswith(ext) for ext in IMAGE_EXTS)
    ], exp["name"] or "")
    for r in img_rows:
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
    artifact_images = _drop_scanned_duplicates(root, images, artifact_images)

    return {
        # The run's name travels with its images: the compare modal labels each
        # side with the run it came from, and the Images tab is the one caller
        # that would otherwise have only an id.
        "name": exp["name"] or "",
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
    from ...sessions.tree import compact_payload
    tree = build_tree(session_id)
    if not tree:
        return {"error": "not found"}
    # Shared diff bodies once, no per-node lineage chain — the client hydrates
    # both back (js/sessions.js `_hydrateTree`). See compact_payload.
    return compact_payload(tree)


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
