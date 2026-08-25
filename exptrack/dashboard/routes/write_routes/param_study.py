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

from exptrack.core import leaderboard, param_study
from exptrack.core.queries import AmbiguousPrefixError, find_experiment
from exptrack.core.utils import chunked, placeholders

from ._shared import body_str

# A posted id list is client-supplied and otherwise unbounded; the experiment
# list pages at 1000, so nothing legitimate exceeds this.
_MAX_IDS = 5000


def _resolve_ids(conn, body: dict) -> tuple[list[str], list[str]]:
    """Resolve posted ids (which may be prefixes) to full ids.

    Returns ``(resolved, unknown)``. Unknown ids are reported rather than
    dropped: an analysis silently computed over fewer runs than the user
    selected would misreport what varies, which is the one thing these views
    exist to answer.

    Exact ids are matched in bulk first. The dashboard posts whole ids for its
    entire filtered list, so resolving them one at a time was a query per run
    (a thousand `id LIKE 'prefix%'` scans per request, on three endpoints);
    the batch pass answers those in one query per chunk, and only leftovers —
    genuine prefixes, from CLI-shaped input — fall back to the per-item lookup.
    """
    raw = body.get("ids") or []
    if not isinstance(raw, list):
        return [], []
    wanted = [s for s in (str(i).strip() for i in raw[:_MAX_IDS]) if s]

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


def api_multi_compare(conn, body: dict) -> dict:
    """Names, latest metrics and image artifacts for a posted set of runs.

    POST rather than GET for the reason the ranking routes above document: the
    id set is the request. As a query string, ~5000 selected runs blew past
    http.server's 64 KiB request-line limit and came back as a bare 414 with no
    explanation.

    ``unknown_ids`` is returned rather than silently dropped — picking four
    runs and rendering three, with nothing saying so, is the failure the
    branch-compare and matrix surfaces already refuse to make.
    """
    from exptrack.core.queries import get_multi_compare, varying_param_keys

    ids, unknown = _resolve_ids(conn, body)
    if len(ids) < 2:
        return {"error": "provide at least 2 known experiment ids",
                "unknown_ids": unknown}
    basis = _selection(body)["rank_by"]
    # The reader's per-metric direction overrides, so "best" here means what
    # the table beside it tints as best.
    raw_goals = body.get("metric_goals")
    goals = ({str(k): v for k, v in raw_goals.items() if v in ("min", "max")}
             if isinstance(raw_goals, dict) else {})
    exps = get_multi_compare(conn, ids, rank_by=basis, goals=goals)
    # Which params differ is decided here, by the same rule `param_study` and
    # the CLI use, rather than re-derived in the browser with JSON equality.
    return {"experiments": exps, "varying_params": varying_param_keys(exps),
            "rank_by": basis, "unknown_ids": unknown}
