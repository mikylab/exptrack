"""
exptrack/dashboard/routes/write_routes/param_study.py

Reading a set of runs as a parameter search. These are reads, but they take a
**posted set of run ids**, so they live with the POST routes: what varies is a
property of the set on screen, not of any stored grouping, and the client is
the only thing that knows its own filters. Putting the ids in a query string
would cap the set at whatever the URL length allows — the experiment list pages
at 1000.
"""
from __future__ import annotations

from pathlib import Path

from exptrack.core import leaderboard, param_study
from exptrack.core.queries import AmbiguousPrefixError, find_experiment
from exptrack.core.utils import chunked, placeholders

from ._shared import body_str

# A posted id list is client-supplied and otherwise unbounded; the experiment
# list pages at 1000, so nothing legitimate exceeds this.
_MAX_IDS = 5000


def _wanted_ids(body: dict) -> list[str]:
    """The posted ``ids`` list, cleaned and capped. ``[]`` for a malformed body.

    Split out from `_resolve_ids` because multi-compare needs the raw posted
    strings *before* resolution: they may be qualified with a project, and a
    foreign project's ids cannot be resolved against this request's database.
    """
    raw = body.get("ids") or []
    if not isinstance(raw, list):
        return []
    return [s for s in (str(i).strip() for i in raw[:_MAX_IDS]) if s]


def _resolve_ids(conn, body: dict) -> tuple[list[str], list[str]]:
    """Resolve the body's posted ids (which may be prefixes) to full ids."""
    return _resolve_id_list(conn, _wanted_ids(body))


def _resolve_id_list(conn, wanted: list[str]) -> tuple[list[str], list[str]]:
    """Resolve *wanted* (which may be prefixes) to full ids, against *conn*.

    Returns ``(resolved, unknown)``. Unknown ids are reported rather than
    dropped: an analysis silently computed over fewer runs than the user
    selected would misreport what varies, which is the one thing these views
    exist to answer.

    Exact ids are matched in bulk first. The dashboard posts whole ids for its
    entire filtered list, so resolving them one at a time was a query per run
    (a thousand `id LIKE 'prefix%'` scans per request, on three endpoints);
    the batch pass answers those in one query per chunk, and only leftovers —
    genuine prefixes, from CLI-shaped input — fall back to the per-item lookup.

    *conn* decides which project the ids are resolved in; the caller is
    responsible for having activated the right one.
    """
    exact: set[str] = set()
    for chunk in chunked(wanted):
        rows = conn.execute(
            f"SELECT id FROM experiments WHERE id IN ({placeholders(chunk)})",
            chunk,
        ).fetchall()
        exact.update(r["id"] for r in rows)

    resolved: list[str] = []
    unknown: list[str] = []
    ambiguous: list[str] = []
    seen: set[str] = set()
    for exp_id in wanted:
        full = exp_id if exp_id in exact else None
        if full is None:
            try:
                exp = find_experiment(conn, exp_id, "id")
            except AmbiguousPrefixError:
                # A prefix matching several runs is a *reportable* input, not a
                # 500: these endpoints promise to name the ids they could not
                # use, and letting it escape broke all six of them.
                ambiguous.append(exp_id)
                continue
            full = exp["id"] if exp else None
        if full is None:
            unknown.append(exp_id)
        elif full not in seen:
            seen.add(full)
            resolved.append(full)
    return resolved, unknown + ambiguous


def _resolved_or_error(conn, body: dict):
    """``(ids, unknown, None)`` or ``(None, None, error_payload)``.

    The resolve-then-short-circuit-then-stamp sequence is identical on all
    three endpoints; spelling the error string three times is how it drifts.
    """
    ids, unknown = _resolve_ids(conn, body)
    if not ids:
        return None, None, {"error": "no known runs in the posted set",
                            "unknown_ids": unknown}
    return ids, unknown, None


def _selection(body: dict) -> dict:
    """The three selection knobs every ranking route shares.

    One definition, applied at every site: the `include_failed=True is not
    False` default is not obvious, and the matrix and the sections rendered
    *underneath* the matrix must never disagree about which runs are in the set.
    """
    # `basis` is the name api_pareto documents for the same knob; accept both so
    # a curl user posting the documented field doesn't silently get the default.
    rank_by = body.get("rank_by", body.get("basis"))
    return {
        "rank_by": "best" if rank_by == "best" else "final",
        "include_running": bool(body.get("include_running")),
        "include_failed": body.get("include_failed", True) is not False,
    }


def api_param_study(conn, body: dict) -> dict:
    """Which parameters vary across the posted runs, and what values were tried.

    Body: ``{"ids": [...], "duplicates": bool}``.
    """
    ids, unknown, err = _resolved_or_error(conn, body)
    if err:
        return err

    # Loaded with internals once, then narrowed: analyze_params wants user
    # params only, classify_duplicates needs `_dataset_manifest`.
    all_params = param_study.load_params(conn, ids, include_internal=True)
    params_by_exp = {e: {k: v for k, v in p.items()
                         if param_study.is_user_param_key(k)}
                     for e, p in all_params.items()}
    out = param_study.analyze_params(conn, ids, params_by_exp=params_by_exp)
    out["unknown_ids"] = unknown
    if body.get("duplicates"):
        out["duplicates"] = param_study.classify_duplicates(
            conn, ids, params_by_exp=all_params)
    return out


def api_param_effects(conn, body: dict) -> dict:
    """Per varying parameter: values tried, runs per value, best/median metric.

    Body: ``{"ids": [...], "group_by": str, "include_running": bool,
    "include_failed": bool}``.

    Descriptive only — see ``param_study.parameter_effects``. The payload
    carries ``aliased_with`` and ``single_run_per_value`` precisely so the
    client cannot render a confounded or single-sample parameter as an answer.
    """
    ids, unknown, err = _resolved_or_error(conn, body)
    if err:
        return err

    sel = _selection(body)
    out = param_study.parameter_effects(
        conn, ids,
        group_by=body.get("group_by") or "",
        include_running=sel["include_running"],
        include_failed=sel["include_failed"],
    )
    out["unknown_ids"] = unknown
    return out


def api_top_runs(conn, body: dict) -> dict:
    """The best N runs of the posted set, with their configurations.

    Body: ``{"ids": [...], "limit": int, "rank_by": "final"|"best",
    "include_running": bool, "include_failed": bool}``.
    """
    ids, unknown, err = _resolved_or_error(conn, body)
    if err:
        return err

    try:
        limit = int(body.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    out = leaderboard.top_runs(conn, ids, limit=min(limit, 100),
                               **_selection(body))
    out["unknown_ids"] = unknown
    return out


def api_best_so_far(conn, body: dict) -> dict:
    """The record over launch order across the posted set.

    Body: ``{"ids": [...], "rank_by": "final"|"best", "include_running": bool,
    "include_failed": bool}``.
    """
    ids, unknown, err = _resolved_or_error(conn, body)
    if err:
        return err

    out = leaderboard.best_so_far(conn, ids, **_selection(body))
    out["unknown_ids"] = unknown
    return out


def api_pareto(conn, body: dict) -> dict:
    """Which runs are not beaten on both of two metrics at once.

    Body: ``{"ids": [...], "x": str, "y": str, "x_goal": str, "y_goal": str,
    "basis": "final"|"best", "include_running": bool, "include_failed": bool}``.

    Both axes are named by the caller — guessing the second objective would be
    inventing the trade-off the user is examining. With neither supplied the
    payload still comes back carrying ``available_metrics``, so the client can
    populate its pickers without a second, differently-shaped request.
    """
    ids, unknown, err = _resolved_or_error(conn, body)
    if err:
        return err

    sel = _selection(body)
    out = leaderboard.pareto_front(
        conn, ids,
        x_key=body_str(body, "x"), y_key=body_str(body, "y"),
        x_goal=body_str(body, "x_goal"), y_goal=body_str(body, "y_goal"),
        # _selection already normalized rank_by to exactly "final" or "best",
        # which is the same vocabulary the basis uses.
        basis=sel["rank_by"],
        include_running=sel["include_running"],
        include_failed=sel["include_failed"],
    )
    out["unknown_ids"] = unknown
    return out


def api_param_matrix(conn, body: dict) -> dict:
    """The parameter matrix: one row per run, one column per varying parameter.

    Body: ``{"ids": [...], "include_running": bool, "include_failed": bool,
    "rank_by": "final"|"best"}``.

    Defaults hide ``running`` (metrics still moving, so a rank against them
    doesn't reproduce) and keep ``failed`` (a config that failed is a result of
    the search). Whatever is hidden is counted back in ``excluded``.
    """
    ids, unknown, err = _resolved_or_error(conn, body)
    if err:
        return err

    out = param_study.build_matrix(conn, ids, **_selection(body))
    out["unknown_ids"] = unknown
    return out


# ── Cross-project compare ───────────────────────────────────────────────────
# Compare is the *only* cross-project surface. Every other view here operates on
# a set whose members must share a parameter space — a matrix, a leaderboard or
# a merged run list across two projects would be comparing columns that mean
# different things. Compare operates on an explicitly chosen handful of runs,
# which is the one case where "these two, from wherever they live" is a question
# the user can actually be asking.


class _ProjectUnavailable(Exception):
    """A posted id names a project the server will not open."""


def _group_by_project(wanted: list[str]) -> tuple[list, dict, list]:
    """``(order, groups, malformed)`` — the posted ids grouped by project.

    ``None`` is the request's own project (a bare id) and is forced first in
    *order*, because it is the only group that can be served with the
    connection this route was handed: the first switch to another project
    closes that handle (`core.db.get_db` closes the previous connection when
    the resolved path changes), and nothing may touch it afterwards.

    Grouping at all — rather than resolving run by run — keeps the number of
    project switches bounded by the number of *projects*, not the number of
    runs. Each switch is a sqlite close plus open.

    *malformed* is every posted id with an empty run half (``"somepid:"``).
    It is **returned rather than skipped** so it lands in ``unknown_ids`` with
    every other id the route could not use: an id quietly dropped on the way
    in is the one failure this endpoint family refuses to make, and "it cannot
    name a run so it cannot matter" is exactly the reasoning that produces a
    comparison rendering three of the four runs the user picked.
    """
    from exptrack.projects import split_qualified_id

    groups: dict = {}
    order: list = []
    malformed: list = []
    for value in wanted:
        project, run_id = split_qualified_id(value)
        if not run_id:
            malformed.append(value)
            continue
        if project not in groups:
            groups[project] = []
            order.append(project)
        groups[project].append(run_id)
    if None in groups:
        order.remove(None)
        order.insert(0, None)
    return order, groups, malformed


def _project_entries(project_ids: list[str]) -> dict:
    """``{project id: discovery entry}`` for every foreign project named.

    Resolved from discovery, **never** from client input: the client names a
    project by an id the server issued, so no request can point this at an
    arbitrary directory. `discover_cached` rather than `discover` because this
    runs on a request path and `discover` costs a git subprocess.

    Raises `_ProjectUnavailable` for an id discovery does not know, or one
    whose database is stale or schema-skewed — the same two refusals the
    ``X-Exptrack-Project`` header gets in `handler._activate_requested_project`,
    and for the same reason: serving the current project's runs instead would
    look like success while quietly answering a different question. Opening a
    schema-skewed database would also migrate and re-stamp it behind the
    owner's back.
    """
    from exptrack import config as cfg
    from exptrack import projects

    if not project_ids:
        return {}
    known = {e["id"]: e
             for e in projects.discover_cached(current_root=cfg.project_root())}
    out = {}
    for pid in project_ids:
        entry = known.get(pid)
        if entry is None:
            raise _ProjectUnavailable(f"Unknown project {pid}")
        if entry["status"] != projects.SCHEMA_OK:
            raise _ProjectUnavailable(
                entry["message"] or f"Project {pid} is unavailable")
        out[pid] = entry
    return out


def _current_project_identity() -> tuple[str, str]:
    """``(id, name)`` for the project this request is already bound to.

    The id is derived from the root the same way the switcher's is, so the
    client can tell the current project's runs from a foreign one's by
    comparing ids alone. The *name* comes from discovery when it knows this
    root — the user named it there — and falls back to the directory name,
    which is what discovery would have shown anyway.
    """
    from exptrack import config as cfg
    from exptrack import projects

    root = cfg.project_root()
    pid = projects.project_id(root)
    for entry in projects.discover_cached(current_root=root):
        if entry["id"] == pid:
            return pid, entry["name"]
    return pid, root.name


def _stamp_project(rows: list[dict], pid: str, name: str) -> None:
    """Say which project each run came from.

    Two projects can hold runs with the same name — and auto-generated names
    are drawn from one shared vocabulary, so this is the common case, not the
    unlucky one. A column labelled only by name would identify nothing.
    ``qualified_id`` is the id the client hands back to ask about this run
    again.
    """
    for row in rows:
        row["project_id"] = pid
        row["project_name"] = name
        row["qualified_id"] = f"{pid}:{row['id']}"


def _ask_positions(wanted: list[str]) -> dict:
    """``{(project, run id): first position}`` over the posted list."""
    from exptrack.projects import split_qualified_id

    pos: dict = {}
    for i, value in enumerate(wanted):
        pos.setdefault(split_qualified_id(value), i)
    return pos


def _ask_index(pos: dict, groups: dict, key, run_id: str, fallback: int) -> int:
    """Where *run_id* sat in the posted list, so the answer keeps its order.

    The exact lookup covers every id the dashboard posts (it posts full ids).
    Only a genuine *prefix* — CLI-shaped input — falls through to the scan,
    and then only over that one project's asked ids, so the quadratic path
    never runs on the request the UI actually makes.
    """
    hit = pos.get((key, run_id))
    if hit is not None:
        return hit
    for asked in groups.get(key, ()):
        if run_id.startswith(asked):
            return pos.get((key, asked), fallback)
    return fallback


def _compare_one(fconn, key, run_ids: list[str], pid: str, name: str,
                 basis: str, goals: dict, stamp: bool) -> tuple[list, list]:
    """One project's share of a comparison: ``(rows, unknown)``.

    *fconn* must already be the connection for the project *key* names, and
    *key* is the project half exactly as posted (``None`` for a bare id) — the
    unknown ids are re-qualified with it, so what comes back to the client is
    the string the client sent rather than a bare id it cannot place.

    Module-level rather than a closure inside the route so the per-project
    fetch can be exercised on its own: the route's own job is parse, group,
    resolve, scope-loop, merge, and each of those is a different kind of
    mistake.
    """
    from exptrack.core.queries import get_multi_compare

    ids, missing = _resolve_id_list(fconn, run_ids)
    rows = (get_multi_compare(fconn, ids, rank_by=basis, goals=goals)
            if ids else [])
    if stamp:
        _stamp_project(rows, pid, name)
    return rows, [f"{key}:{m}" if key else m for m in missing]


def api_multi_compare(conn, body: dict) -> dict:
    """Names, latest metrics and image artifacts for a posted set of runs.

    POST rather than GET for the reason the ranking routes above document: the
    id set is the request. As a query string, ~5000 selected runs blew past
    http.server's 64 KiB request-line limit and came back as a bare 414 with no
    explanation.

    ``unknown_ids`` is returned rather than silently dropped — picking four
    runs and rendering three, with nothing saying so, is the failure the
    branch-compare and matrix surfaces already refuse to make.

    An id may be qualified as ``<project-id>:<run-id>``, which is what makes
    this the one cross-project surface. A **bare** id still means the request's
    own project, so every existing caller, bookmark and saved URL is unchanged
    — and a request that qualifies nothing runs exactly the code it used to,
    against exactly the connection it was handed.
    """
    from exptrack import config as cfg
    from exptrack.core.db import get_db
    from exptrack.core.queries import varying_param_keys

    wanted = _wanted_ids(body)
    order, groups, malformed = _group_by_project(wanted)
    basis = _selection(body)["rank_by"]
    # The reader's per-metric direction overrides, so "best" here means what
    # the table beside it tints as best.
    raw_goals = body.get("metric_goals")
    goals = ({str(k): v for k, v in raw_goals.items() if v in ("min", "max")}
             if isinstance(raw_goals, dict) else {})

    foreign = [k for k in order if k is not None]
    try:
        # Resolved up front, before a single query runs: a refusal must be a
        # refusal, not a comparison silently narrowed to the projects that
        # happened to work.
        entries = _project_entries(foreign)
    except _ProjectUnavailable as e:
        return {"error": str(e), "experiments": [], "unknown_ids": malformed}

    collected: list = []          # (group key, run row), group key as posted
    # Malformed ids are unusable, not invisible — they are reported alongside
    # every other id that named no run.
    unknown: list[str] = list(malformed)
    # The project stamp goes on only when the request actually used the
    # qualified grammar: a plain single-project compare then answers
    # byte-for-byte what it always did.
    stamp = bool(foreign)
    try:
        for key in order:
            if key is None:
                # The current project FIRST, on the connection handed in —
                # after any switch that handle is closed.
                pid, name = _current_project_identity() if stamp else ("", "")
                rows, missing = _compare_one(conn, key, groups[key], pid, name,
                                             basis, goals, stamp)
            else:
                entry = entries[key]
                with cfg.project_scope(Path(entry["path"])):
                    # get_db() re-resolves the root per call and rebinds the
                    # thread's connection; `conn` is dead from here on.
                    rows, missing = _compare_one(
                        get_db(), key, groups[key], key, entry["name"],
                        basis, goals, stamp)
            collected.extend((key, r) for r in rows)
            unknown.extend(missing)
    finally:
        if foreign:
            # Leave the thread holding the *request's* project, connection
            # included. `project_scope` restored the thread's project id, but
            # the thread's cached connection is still the last foreign one —
            # so this reopens the request project's database and, by doing so,
            # closes the foreign handle (`get_db` closes the previous
            # connection when the resolved path changes).
            #
            # Two things this does NOT do, so nobody credits it with them
            # later. It does not revive the `conn` object this route was
            # handed: that handle was closed by the first switch and stays
            # closed, so `_run_post`'s `_wal_checkpoint(conn)` after this
            # route is a no-op whichever way this goes (it swallows the
            # error, and multi-compare is a read with nothing to checkpoint).
            # And it does not matter to *this* request's answer, which is
            # already assembled. The guarantee is entirely about what the
            # thread is left holding: the next request served by this pooled
            # thread resolves against the right database, and no foreign
            # project's connection stays open behind it.
            get_db()

    if len(collected) < 2:
        found = len(collected)
        return {"error": (f"only {found} of the chosen runs "
                          f"{'was' if found == 1 else 'were'} found; "
                          "a comparison needs at least 2"),
                "experiments": [], "unknown_ids": unknown}

    # Merged in the order the ids were asked for: the client laid the columns
    # out in the order the user picked them, and a reordered answer silently
    # relabels every column.
    pos = _ask_positions(wanted)
    fallback = len(wanted)
    exps = [r for _, r in sorted(
        collected,
        key=lambda pair: _ask_index(pos, groups, pair[0], pair[1]["id"],
                                    fallback))]
    # Which params differ is decided here, by the same rule `param_study` and
    # the CLI use, rather than re-derived in the browser with JSON equality.
    varying = varying_param_keys(exps)
    answer = {"experiments": exps, "varying_params": varying,
              "rank_by": basis, "unknown_ids": unknown}
    if body.get("document"):
        # Compare's Copy/Export: the tables `exptrack compare --format
        # markdown` prints, plus the HTML a paste into OneNote/Word needs.
        from exptrack.core.export_render import export_bundle, format_comparison_markdown
        from exptrack.core.queries import compare_run_code
        # The pair's code diff, as the Compare view's Code changes panel
        # shows it. Not across projects: the two runs' sources live in two
        # databases, and `conn` belongs to this request's project only.
        code = (compare_run_code(get_db(), exps[0]["id"], exps[1]["id"])
                if len(exps) == 2 and not stamp else None)
        # `patch: false` is Copy, which leaves the patch to Export .patch;
        # `patch` in the answer is that download — the pair's diff, applicable
        # with `git apply` to the older run's code.
        from exptrack.core.export_render import runs_code_diff
        answer.update(export_bundle(format_comparison_markdown(
            exps, varying, basis, goals, unknown, code=code,
            patch=body.get("patch", True) is not False)))
        diff = runs_code_diff(code) if code else ""
        answer["patch"] = diff + "\n" if diff else ""
    return answer
