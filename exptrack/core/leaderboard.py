"""
exptrack/core/leaderboard.py — which runs won, and whether the search is still
finding anything.

Two questions the parameter matrix can't answer by being scrolled. The matrix
shows every run and marks the best one; that is the right shape for reading a
sweep row by row, and the wrong shape for "what are my top five configurations"
(you have to sort and count) and for "am I still making progress" (nothing in a
table says it at all).

Both views here are **views over** ``param_study.build_matrix``, not parallel
implementations of it. Which runs are eligible, how exclusions are counted,
which metric the set is judged by and how ties break are decisions that must
have exactly one answer across every ranking surface — a "best run" panel that
disagreed with the matrix's own best row, over the same runs, would make both
untrustworthy. The cost is that both load the set's parameters, which is
deliberate: what a top run *is* is its configuration, and the point of the
best-so-far curve is seeing what changed at each improvement.
"""
from __future__ import annotations

from . import primary_metric as pm
from .param_study import build_matrix, params_differ, scored_values


def _matrix(conn, exp_ids, include_running, include_failed, primaries=True):
    # classify=False: the duplicate classification costs a fingerprint per run
    # and no view below reads it. `primaries=False` additionally skips resolving
    # the set's primary metric, for the trade-off view, which names both of its
    # own axes and would otherwise pay a whole windowed pass it discards.
    return build_matrix(conn, exp_ids, include_running=include_running,
                        include_failed=include_failed, classify=False,
                        primaries=primaries)


def _row_out(row: dict, value, metric_key: str = "") -> dict:
    """The shared row shape: enough to identify the run and read its config.

    Deliberately small. ``value`` is already the number for the requested basis
    and the basis is named once on the payload, so carrying ``final``/``best``
    per row would ship the same number twice under three names across up to
    5000 runs — and every unused field reads as a contract to preserve.

    ``off_metric`` separates the two ways a run can have no value here: it
    logged nothing, or it is judged by a *different* metric. Both render as a
    blank, and conflating them would let "this run measures something else"
    read as "this run produced no result".
    """
    primary = row.get("primary") or {}
    return {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "created_at": row["created_at"],
        "params": row.get("params", {}),
        "value": value,
        "off_metric": bool(primary.get("key")) and primary["key"] != metric_key,
    }


def top_runs(conn, exp_ids: list[str], limit: int = 10, rank_by: str = "final",
             include_running: bool = False,
             include_failed: bool = True) -> dict:
    """The best *limit* runs of the set, best first, with their configurations.

    ``rank_by`` picks the number ranked on: ``final`` (the result as the run
    ended) or ``best`` (its best point). The two answer different questions —
    "what would I get if I ran this config" versus "what is this config capable
    of" — and a run that overfits late scores very differently under each, so
    the basis is named on the payload rather than left implicit.

    Runs that produced no value for the set's metric are **not** silently
    dropped to make the list look complete: they are returned separately as
    ``unscored``, because "six of your twenty runs never logged the metric you
    are ranking by" is a fact about the search, not a rendering detail.

    Ties keep the **earlier** run ahead. When two configurations score
    identically the one you already have results for is the more useful answer,
    and an arbitrary tie-break would let the same set reorder between requests.
    """
    matrix = _matrix(conn, exp_ids, include_running, include_failed)
    rows = matrix["rows"]
    # build_matrix already resolved the set's metric by the shared rule; taking
    # its answer rather than recomputing one is what makes "the top run" and
    # "the matrix's best row" the same run by construction, not by coincidence.
    metric_key, goal = matrix["metric"]["key"], matrix["metric"]["goal"]
    scored = scored_values({r["id"]: r["primary"] for r in rows},
                           metric_key, rank_by)

    by_id = {r["id"]: r for r in rows}
    # created_at ascending as the tie-break, so equal scores keep launch order.
    order = sorted(scored, key=lambda e: (by_id[e]["created_at"] or "", e))
    order.sort(key=lambda e: scored[e], reverse=(goal != pm.GOAL_MIN))

    limit = max(1, int(limit or 10))
    best_value = scored[order[0]] if order else None
    ranked = []
    for i, exp_id in enumerate(order[:limit]):
        out = _row_out(by_id[exp_id], scored[exp_id], metric_key)
        out["rank"] = i + 1
        # Distance from the leader, so a top-N list says whether the field is
        # tight or whether one run is far ahead — the thing that decides
        # whether the ranking is worth acting on.
        out["delta_from_best"] = scored[exp_id] - best_value
        ranked.append(out)

    unscored = [_row_out(by_id[e], None, metric_key)
                for e in (r["id"] for r in rows) if e not in scored]

    return {
        "metric": {"key": metric_key, "goal": goal},
        "rank_by": rank_by,
        "limit": limit,
        "n_runs": len(rows),
        "n_scored": len(scored),
        "runs": ranked,
        "unscored": unscored,
        "off_metric_runs": matrix.get("off_metric_runs", 0),
        "excluded": matrix["excluded"],
        "varying": matrix["varying"],
    }


def best_so_far(conn, exp_ids: list[str], rank_by: str = "final",
                include_running: bool = False,
                include_failed: bool = True) -> dict:
    """The record over launch order: is the search still finding anything?

    Runs in the order they were started, each with its own value and the best
    value seen up to and including it. The shape of that line is the answer to
    a question a table cannot show — a curve that stepped up three times in the
    first ten runs and has been flat for forty says the sweep has stopped
    paying, which is the point at which the useful move is to change what is
    being varied rather than to run more of the same.

    Three things are load-bearing.

    **Order is launch order, not rank.** ``(created_at, id)`` ascending, and it
    must stay ascending regardless of how the client's list happens to be
    sorted — a "best so far" computed over a metric-sorted list is monotonic by
    construction and means nothing.

    **A run that produced no value keeps its place.** It carries the record
    forward unchanged with ``value: None``. Dropping unscored runs would
    compress the x-axis and make a search look like it converged in twelve
    attempts when it took thirty.

    **Every improvement names what changed.** ``changed`` on an improving run
    is the parameter diff against the run that previously held the record — the
    reason to look at this view at all is to see which edits moved the number.
    """
    matrix = _matrix(conn, exp_ids, include_running, include_failed)
    rows = matrix["rows"]
    metric_key, goal = matrix["metric"]["key"], matrix["metric"]["goal"]
    scored = scored_values({r["id"]: r["primary"] for r in rows},
                           metric_key, rank_by)
    lower_better = goal == pm.GOAL_MIN

    ordered = sorted(rows, key=lambda r: (r["created_at"] or "", r["id"]))

    points = []
    improvements = []
    record = None
    record_row = None
    for i, row in enumerate(ordered):
        value = scored.get(row["id"])
        improved = value is not None and (
            record is None
            or (value < record if lower_better else value > record))
        if improved:
            changed = _param_changes(record_row, row) if record_row else {}
            record, record_row = value, row
        point = _row_out(row, value, metric_key)
        point["index"] = i
        point["best_so_far"] = record
        point["improved"] = improved
        if improved:
            point["changed"] = changed
            improvements.append(row["id"])
        points.append(point)

    # Runs since the record last moved — the number that says "stop". Counted
    # over every run that followed, scored or not: forty attempts that logged
    # nothing are still forty attempts that did not beat the record.
    last_improved = max((p["index"] for p in points if p["improved"]),
                        default=None)
    since = (len(points) - 1 - last_improved) if last_improved is not None else None

    return {
        "metric": {"key": metric_key, "goal": goal},
        "rank_by": rank_by,
        "n_runs": len(points),
        "n_scored": len(scored),
        "points": points,
        "improvements": improvements,
        "since_improvement": since,
        "best_value": record,
        "best_run_id": record_row["id"] if record_row else None,
        "off_metric_runs": matrix.get("off_metric_runs", 0),
        "excluded": matrix["excluded"],
    }


def _param_changes(prev_row: dict, row: dict) -> dict:
    """What differs between two matrix rows, per parameter.

    Only the varying parameters are on a matrix row, so this is already scoped
    to what the sweep moved. A parameter absent from one side is reported with
    an explicit ``*_missing`` flag rather than as ``None``: "this run never
    passed ``--dropout``" is a real difference in what was tested, and ``None``
    is a value a run can genuinely log (the ``MISSING`` rule this module's
    whole analysis layer is built on).
    """
    out: dict[str, dict] = {}
    before, after = prev_row.get("params", {}), row.get("params", {})
    for key in sorted(set(before) | set(after)):
        in_a, in_b = key in before, key in after
        if in_a and in_b and not params_differ(before[key], after[key]):
            continue
        out[key] = {
            "before": before.get(key), "after": after.get(key),
            "before_missing": not in_a, "after_missing": not in_b,
        }
    return out


# ── The trade-off frontier ───────────────────────────────────────────────────
# Ranking assumes one number. Real choices routinely have two that pull against
# each other — accuracy against latency, F1 against model size, recall against
# false positives — and no single ranking can express "these are the runs where
# you cannot do better on one without giving up the other".
#
# What this is NOT, and every caller must present it that way: it is a property
# of **the runs you happened to launch**, not of the parameter space. A run sits
# on the frontier when nothing else *in this set* beat it on both axes, which
# includes the case where it is simply the only run tried in that region. It is
# the same discipline as the effect summaries — describe what was observed and
# refuse to imply what was not measured.


def _dominates(ax, ay, bx, by) -> bool:
    """Does (ax, ay) dominate (bx, by)? Both axes already 'higher is better'.

    At least as good on both and strictly better on one. The strictness is what
    keeps two runs that scored *identically* both on the frontier — neither
    beat the other, so calling either one dominated would be a claim the data
    does not make.
    """
    return ax >= bx and ay >= by and (ax > bx or ay > by)


def pareto_front(conn, exp_ids: list[str], x_key: str, y_key: str,
                 x_goal: str = "", y_goal: str = "", basis: str = "final",
                 include_running: bool = False,
                 include_failed: bool = True) -> dict:
    """Which runs are not beaten on both of two metrics at once.

    Both metrics are named by the caller — the second objective cannot be
    guessed, and picking one would be inventing the trade-off the user is
    trying to examine. Each goal defaults to the shared name heuristic
    (``goal_for_key``), so ``latency`` is minimized without being told, and both
    are stated on the payload so a wrong inference is visible and correctable
    rather than silently inverting the frontier.

    A run missing **either** metric cannot be placed on a two-axis plot at all.
    Those come back as ``unplaced`` with the keys they lack, never dropped: on a
    chart, an absent point and a point that was never measured look identical,
    and the second is the one that changes what you do next.
    """
    # primaries=False: both axes are named by the caller, so the set's primary
    # metric — a DISTINCT scan plus a windowed pass over its points — would be
    # resolved here and read by nothing.
    matrix = _matrix(conn, exp_ids, include_running, include_failed,
                     primaries=False)
    rows = matrix["rows"]
    by_id = {r["id"]: r for r in rows}
    ids = list(by_id)

    x_goal = pm.resolve_goal(x_key, x_goal)
    y_goal = pm.resolve_goal(y_key, y_goal)
    xs = pm.metric_values(conn, ids, x_key, x_goal, basis) if x_key else {}
    ys = pm.metric_values(conn, ids, y_key, y_goal, basis) if y_key else {}

    # Normalize both axes to "higher is better" for the sweep, and report the
    # values as recorded. Flipping the *displayed* number to make an algorithm
    # simpler would put a negated loss on screen.
    xsign = -1.0 if x_goal == pm.GOAL_MIN else 1.0
    ysign = -1.0 if y_goal == pm.GOAL_MIN else 1.0

    placed, unplaced = [], []
    for exp_id in ids:
        missing = [k for k, vals in ((x_key, xs), (y_key, ys)) if exp_id not in vals]
        if missing:
            entry = _row_out(by_id[exp_id], None)
            entry["missing_metrics"] = missing
            unplaced.append(entry)
            continue
        placed.append((exp_id, xs[exp_id] * xsign, ys[exp_id] * ysign))

    # Best-x first (ties: best-y first), then one sweep keeping the best point
    # seen. A point that fails to beat it is dominated by whichever run set it,
    # which necessarily has x at least as good — so the sweep also names *a*
    # dominating run, which is more useful than a bare "dominated" flag.
    #
    # `frontier` is built in this order, which *is* draw order, so the payload
    # ships it as-is rather than re-deriving it from `placed` — two orderings a
    # reader would have to prove agree, and which the drawn line and the listed
    # frontier would silently disagree on if they ever didn't.
    placed.sort(key=lambda t: (-t[1], -t[2], t[0]))
    frontier: list[str] = []
    dominated_by: dict[str, str] = {}
    holder = None
    for exp_id, nx, ny in placed:
        # Equal on both axes as the current holder: nothing beat it, so it is on
        # the frontier too. Only a strict win on one axis is domination.
        if holder is not None and _dominates(holder[1], holder[2], nx, ny):
            dominated_by[exp_id] = holder[0]
            continue
        frontier.append(exp_id)
        if holder is None or ny > holder[2]:
            holder = (exp_id, nx, ny)

    front_set = set(frontier)
    points = [dict(_row_out(by_id[e], None),
                   x=xs[e], y=ys[e],
                   frontier=e in front_set,
                   dominated_by=dominated_by.get(e))
              for e, _nx, _ny in placed]

    return {
        "x": {"key": x_key, "goal": x_goal},
        "y": {"key": y_key, "goal": y_goal},
        "basis": basis,
        "n_runs": len(rows),
        "n_placed": len(placed),
        "points": points,
        # Already best-x first — the order the frontier line is drawn in.
        "frontier": frontier,
        "unplaced": unplaced,
        "available_metrics": available_metrics(matrix["metric_keys"]),
        "excluded": matrix["excluded"],
        "varying": matrix["varying"],
    }


def available_metrics(metric_keys: dict) -> list[dict]:
    """``[{key, n_runs}]`` across the set, most-logged first.

    What the axis pickers offer. Takes the ``{exp_id: [keys]}`` map
    ``build_matrix`` already returns rather than re-issuing its DISTINCT scan
    over the same ids — and reading the *same* map is also what keeps the picker
    offering keys over exactly the run set the frontier was computed on. Sorted
    by how many runs recorded each key so the metrics describing the whole set
    come before one run's stray key, with the name as a stable tie-break.
    """
    counts: dict[str, int] = {}
    for keys in metric_keys.values():
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    return [{"key": k, "n_runs": counts[k]}
            for k in sorted(counts, key=lambda k: (-counts[k], k))]
