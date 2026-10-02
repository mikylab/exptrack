"""
exptrack/core/param_study.py — reading a set of runs as a parameter search.

The experiment list answers "what did I run?". This module answers the
questions that come *after* twenty runs exist: which parameters did I actually
vary, what values did I try, and have I already run this configuration?

Everything here works over an **explicit set of run ids** rather than a study
name. What varies is a property of the set you are looking at, not of any
stored grouping: filter to last week's runs and `lr` may be constant; widen to
the whole project and it varies. Deriving it from a stored study would answer a
different question from the one on screen. The set is posted in by the client,
which already knows its own filters.

Two things are load-bearing throughout:

**A parameter missing from a run is a variation, not a blank.** Run A passing
``--dropout 0.1`` and run B never passing it at all is a real difference in the
configuration tested, and the commonest way a sweep is actually written (add a
flag partway through). It is represented by the ``MISSING`` sentinel rather
than ``None``, because ``None`` is a value a run can genuinely log — collapsing
the two would report "I tried None and 0.1" for a parameter half the runs never
had.

**Values are compared after normalization, displayed as captured.** The same
``lr=0.01`` arrives as a float through argparse capture and as the string
``"0.01"`` through the shell-pipeline CLI. Comparing raw would report two
values for one setting and flag identical configurations as different — which
would make the duplicate detection this module exists to support actively
misleading. ``_norm`` collapses those; ``display`` keeps what was captured.
"""
from __future__ import annotations

import json
import math
import statistics
from collections.abc import Iterable
from typing import Any

from .utils import (
    chunked,
    decode_param_value,
    is_user_param_key,
    placeholders,
    safe_call,
)


class _Missing:
    """Sentinel for "this run never had this parameter".

    A singleton class rather than ``None`` so it can never be confused with a
    logged null, and rather than a magic string so it can never collide with a
    parameter whose value genuinely is ``"<missing>"``.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "MISSING"


MISSING = _Missing()

# A pseudo-key for grouping by model rather than by a parameter. Not a param,
# so it lives outside the param namespace and can never collide with one (no
# captured flag is named with a leading underscore that survives
# is_user_param_key).
SCRIPT_GROUP = "_script"
# Its display names, next to its definition rather than in the client.
SCRIPT_GROUP_LABEL = "script (model)"
SCRIPT_GROUP_LABEL_SHORT = "script"

# The same idea for "give every run its own colour", which is the grouping you
# want when the question is *which run is which* rather than what they have in
# common. A pseudo-key for the same reason: it is not a parameter.
RUN_GROUP = "_run"
RUN_GROUP_LABEL = "run (one colour each)"
RUN_GROUP_LABEL_SHORT = "run"

# One table rather than a chain of `if key == …` in four places.
_PSEUDO_GROUPS = (SCRIPT_GROUP, RUN_GROUP)
_GROUP_LABELS = {SCRIPT_GROUP: SCRIPT_GROUP_LABEL_SHORT,
                 RUN_GROUP: RUN_GROUP_LABEL_SHORT}

# Value kinds, used by the matrix to choose a column renderer and by the
# effect summaries to choose between a scatter and a distribution.
KIND_NUMERIC = "numeric"
KIND_BOOL = "bool"
KIND_CATEGORICAL = "categorical"
KIND_MIXED = "mixed"


def _norm(value: Any):
    """A hashable identity for *value*, for grouping and equality.

    Numbers and their string spellings collapse together (``0.01`` and
    ``"0.01"``), since the same setting reaches the database both ways
    depending on whether it was captured from argparse or handed to the
    pipeline CLI. Booleans stay distinct from the numbers 0 and 1: ``--flag
    True`` and ``--flag 1`` are the same intent, but ``epochs=1`` and
    ``epochs=True`` are not, and only the bool-typed value can tell us which
    case we are in.

    Lists and dicts are normalized recursively into a hashable form, so
    ``[1, 2]`` and ``["1", "2"]`` compare equal too. Order is preserved —
    a list-valued parameter is ordered data, not a set.
    """
    if value is MISSING:
        return MISSING
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            # inf/nan are not comparable in the usual way and never survive a
            # JSON round trip; keep them distinguishable but never equal to a
            # real number.
            return ("str", repr(value))
        return ("num", float(value))
    if isinstance(value, str):
        s = value.strip()
        low = s.lower()
        if low in ("true", "false"):
            return ("bool", low == "true")
        try:
            f = float(s)
        except (TypeError, ValueError):
            return ("str", s)
        return ("num", f) if math.isfinite(f) else ("str", s)
    if isinstance(value, (list, tuple)):
        return ("seq", tuple(_norm(v) for v in value))
    if isinstance(value, dict):
        return ("map", tuple(sorted((str(k), _norm(v)) for k, v in value.items())))
    if value is None:
        return ("null", None)
    return ("str", str(value))


def params_differ(a: Any, b: Any) -> bool:
    """Whether two captured param values are genuinely different settings.

    The public form of ``_norm``'s equality, for the surfaces that report param
    *changes* rather than group by value. They used to compare raw stored
    values, so the same ``lr=0.01`` captured from argparse (float) and from the
    pipeline CLI (string) read as a change — and ``best_so_far`` credited a
    record to a non-edit. One rule, so "what varies" and "what changed" can
    never disagree.
    """
    return _norm(a) != _norm(b)


def _kind(norms: Iterable) -> str:
    """Classify a parameter from the normalized values seen, ignoring MISSING."""
    tags = {n[0] for n in norms if n is not MISSING}
    if not tags:
        return KIND_CATEGORICAL
    if tags == {"num"}:
        return KIND_NUMERIC
    if tags == {"bool"}:
        return KIND_BOOL
    if tags <= {"str", "null", "seq", "map"}:
        return KIND_CATEGORICAL
    return KIND_MIXED


def _numeric_value(norm):
    """The float behind a normalized value, or None if it isn't a number."""
    if norm is not MISSING and norm[0] == "num":
        return norm[1]
    return None


def load_params(conn, exp_ids: list[str],
                include_internal: bool = False) -> dict[str, dict]:
    """``{exp_id: {key: decoded_value}}`` for the given runs, in one pass.

    Chunked rather than one query per run: this backs the parameter matrix,
    which is asked about the whole filtered set at once.
    """
    out: dict[str, dict] = {e: {} for e in exp_ids}
    for chunk in chunked(exp_ids):
        rows = conn.execute(
            f"SELECT exp_id, key, value FROM params "
            f"WHERE exp_id IN ({placeholders(chunk)})",
            chunk,
        ).fetchall()
        for r in rows:
            if not include_internal and not is_user_param_key(r["key"]):
                continue
            if r["exp_id"] in out:
                out[r["exp_id"]][r["key"]] = decode_param_value(r["value"])
    return out


def analyze_params(conn, exp_ids: list[str],
                   params_by_exp: dict[str, dict] | None = None) -> dict:
    """Describe how each parameter behaves across *exp_ids*.

    Returns::

        {
          "n_runs": int,
          "varying": [param, ...],    # varies across the set, most-varied first
          "constant": [param, ...],   # same on every run (context, not noise)
        }

    where each *param* is::

        {
          "key": str,
          "kind": "numeric" | "bool" | "categorical" | "mixed",
          "varies": bool,
          "n_values": int,            # distinct values, MISSING counted as one
          "n_missing": int,           # runs that never had this parameter
          "values": [
            {"value": <display>, "count": int, "missing": bool}, ...
          ],
        }

    ``values`` is ordered by count descending then by display text, so the
    listing is stable between requests rather than depending on row order.

    A parameter absent from some runs **varies** if the runs that do have it
    disagree, *or* if it is present on some and absent on others — adding a
    flag partway through a sweep is a real change to what was tested, and the
    matrix has to show it as one.
    """
    exp_ids = list(exp_ids)
    if params_by_exp is None:
        params_by_exp = load_params(conn, exp_ids)

    all_keys: set[str] = set()
    for p in params_by_exp.values():
        all_keys.update(p.keys())

    varying: list[dict] = []
    constant: list[dict] = []
    for key in sorted(all_keys):
        # Every run contributes exactly one entry — MISSING when it lacks the
        # key — so the counts below always sum to len(exp_ids) and a value's
        # share of the set is readable directly off `count`.
        raw_values = [params_by_exp.get(e, {}).get(key, MISSING) for e in exp_ids]
        norms = [_norm(v) for v in raw_values]

        buckets: dict[Any, dict] = {}
        for norm, raw in zip(norms, raw_values):
            b = buckets.get(norm)
            if b is None:
                buckets[norm] = {
                    "value": None if raw is MISSING else raw,
                    "count": 1,
                    "missing": raw is MISSING,
                    "_norm": norm,
                }
            else:
                b["count"] += 1

        values = sorted(
            buckets.values(),
            key=lambda b: (-b["count"], str(b["value"])),
        )
        n_missing = sum(b["count"] for b in values if b["missing"])
        entry = {
            "key": key,
            "kind": _kind(norms),
            "varies": len(buckets) > 1,
            "n_values": len(buckets),
            "n_missing": n_missing,
            "values": [{k: v for k, v in b.items() if k != "_norm"}
                       for b in values],
        }
        (varying if entry["varies"] else constant).append(entry)

    # Most-varied first: the parameter with the most distinct values is the one
    # the sweep was actually over, and belongs in the leftmost column.
    varying.sort(key=lambda p: (-p["n_values"], p["key"]))
    return {"n_runs": len(exp_ids), "varying": varying, "constant": constant}


def build_matrix(conn, exp_ids: list[str], include_running: bool = False,
                 include_failed: bool = True, rank_by: str = "final",
                 classify: bool = True, primaries: bool = True) -> dict:
    """One row per run, one column per *varying* parameter, plus the result.

    This is the analysis view: the experiment list is for navigation, and
    showing every parameter there buries the two or three that were actually
    swept. Columns come from ``analyze_params``, so a parameter constant across
    the set contributes no column — it is reported under ``constant`` instead,
    as context for what was held fixed.

    Exclusions are stated, never silent (``excluded`` carries a count per
    reason), because a matrix quietly missing rows misreports the search:

    - ``running`` runs are hidden by default. Their metrics are still moving,
      so a rank against them doesn't reproduce a minute later — the same rule
      ``_BASELINE_WHERE`` applies for exactly the same reason.
    - ``failed`` runs are **shown** by default, marked. A configuration that
      failed is a result of the search: hiding it invites re-running the thing
      that already broke, which is the one outcome this view exists to prevent.
    - a run with **no value** for the primary metric is kept — it is still a
      configuration that was tested — but it can never be the best row.

    ``rank_by`` picks which number ranks the runs: ``final`` (the result as the
    run ended) or ``best`` (its best point). Both are on every row, and
    ``best_row_id_final`` / ``best_row_id_best`` are both returned, so the
    client can switch the ranking basis without another request *and* without
    re-implementing the ranking rule.

    ``classify=False`` skips the duplicate classification. It is the expensive
    half (a fingerprint per run) and `parameter_effects` uses none of it.
    ``primaries=False`` likewise skips *resolving* the set's primary metric —
    a config read and a per-run `resolve_spec`, then a windowed pass over that
    metric's points — for the caller (the trade-off view) that names both of its
    own axes and reads none of it. The cheap DISTINCT scan of which keys each
    run logged still runs, because that caller does need it, and it comes back
    on the payload as ``metric_keys``.
    """
    from . import primary_metric as pm

    exp_ids = list(exp_ids)
    if not exp_ids:
        # The same shape as the populated return, so a caller reading a key can
        # do it unconditionally — an empty selection is not an error, and a
        # short-form early return makes it act like one at the first lookup.
        return {"n_runs": 0, "n_selected": 0, "varying": [], "constant": [],
                "rows": [], "excluded": {}, "rank_by": rank_by,
                "metric": {"key": "", "goal": pm.GOAL_MAX},
                "off_metric_runs": 0, "metric_keys": {},
                "goal": pm.GOAL_MAX, "best_row_id": None,
                "best_row_id_final": None, "best_row_id_best": None,
                "duplicates": []}

    ph = ",".join("?" * len(exp_ids))
    rows = conn.execute(
        f"""SELECT id, name, status, created_at, duration_s, tags, studies,
                   COALESCE(name_is_auto, 0) AS name_is_auto
            FROM experiments WHERE id IN ({ph}) AND deleted_at IS NULL
            ORDER BY created_at DESC""",
        exp_ids,
    ).fetchall()

    excluded: dict[str, int] = {}
    kept = []
    for r in rows:
        if r["status"] == "running" and not include_running:
            excluded["running"] = excluded.get("running", 0) + 1
            continue
        if r["status"] == "failed" and not include_failed:
            excluded["failed"] = excluded.get("failed", 0) + 1
            continue
        kept.append(r)
    # Trashed runs never reach `kept` (filtered in SQL); count them so the view
    # can say why it is showing fewer runs than were selected.
    missing_rows = len(exp_ids) - len(rows)
    if missing_rows > 0:
        excluded["trashed_or_missing"] = missing_rows

    kept_ids = [r["id"] for r in kept]
    # Loaded once with internals, then narrowed: the matrix columns are user
    # params only, but the duplicate classification needs `_dataset_manifest`.
    all_params = load_params(conn, kept_ids, include_internal=True)
    params_by_exp = {e: {k: v for k, v in p.items() if is_user_param_key(k)}
                     for e, p in all_params.items()}
    analysis = analyze_params(conn, kept_ids, params_by_exp=params_by_exp)

    from .queries import _json_list
    # The heuristic needs each run's own metric keys; without them a run with no
    # configured metric resolves to nothing. Returned on the payload as well,
    # because the caller that wants "which metrics do these runs have" would
    # otherwise re-issue the identical DISTINCT scan a few lines later.
    metric_keys = _metric_keys(conn, kept_ids)
    pm_runs = [{"id": r["id"],
                # _json_list, not a bare decode: a hand-edited `studies` column
                # holding a bare string is salvaged rather than passed through
                # as a str where a list is expected.
                "studies": _json_list(r["studies"], "param_study.studies"),
                "metrics": {k: None for k in metric_keys.get(r["id"], ())}}
               for r in kept]
    primary_by_exp = pm.primary_metric_batch(conn, pm_runs) if primaries else {}

    # Classified rather than merely grouped: "identical rerun", "same params,
    # different code" and "same params and code, different data" lead to
    # different actions, so the row badge names which one it is.
    dup_groups = (classify_duplicates(conn, kept_ids, params_by_exp=all_params)
                  if classify else [])
    # One dict, not two keyed identically: (group index, kind) per run.
    dup_by_exp: dict[str, tuple] = {}
    for i, group in enumerate(dup_groups):
        for exp_id in group["exp_ids"]:
            dup_by_exp[exp_id] = (i, group["kind"])

    varying_keys = [p["key"] for p in analysis["varying"]]
    out_rows = []
    for r in kept:
        params = params_by_exp.get(r["id"], {})
        primary = primary_by_exp.get(r["id"], {})
        out_rows.append({
            "id": r["id"],
            "name": r["name"],
            "status": r["status"],
            "created_at": r["created_at"],
            "duration_s": r["duration_s"],
            "name_is_auto": bool(r["name_is_auto"]),
            # `params` holds only the varying keys — the row is the matrix row,
            # not a full param dump. A key absent here means this run never had
            # it, which `missing` states explicitly rather than leaving the
            # client to infer it from a null (a real logged value).
            "params": {k: params[k] for k in varying_keys if k in params},
            "missing": [k for k in varying_keys if k not in params],
            "primary": primary,
            "dup_group": dup_by_exp.get(r["id"], (None, None))[0],
            "dup_kind": dup_by_exp.get(r["id"], (None, None))[1],
        })

    metric_key, goal = consensus_metric(primary_by_exp)
    created = {r["id"]: (r["created_at"] or "") for r in kept}

    def _best_on(basis):
        scored = scored_values(primary_by_exp, metric_key, basis)
        if not scored:
            return None
        # Identical tie-break to leaderboard.top_runs (created_at asc, then id,
        # then a stable sort by score): on a score tie the *earlier* run wins, so
        # the matrix's best row can never name a different run than the Top-runs
        # / Progress panels over the same set. min/max here returned the *first*
        # of the newest-first dict instead, i.e. the newest run — the opposite.
        order = sorted(scored, key=lambda e: (created[e], e))
        order.sort(key=lambda e: scored[e], reverse=(goal != pm.GOAL_MIN))
        return order[0]

    # Both bases, so switching "rank by" is a re-render rather than a request —
    # and so the ranking rule lives here only, instead of being mirrored in JS
    # where a tie-break could silently disagree about which run is best.
    best_final, best_best = _best_on("final"), _best_on("best")
    best_row_id = best_best if rank_by == "best" else best_final

    return {
        "n_runs": len(out_rows),
        "n_selected": len(exp_ids),
        "varying": analysis["varying"],
        "constant": analysis["constant"],
        "rows": out_rows,
        "excluded": excluded,
        "rank_by": rank_by,
        "metric": {"key": metric_key, "goal": goal},
        "metric_source": consensus_source(primary_by_exp, metric_key),
        "off_metric_runs": off_metric_runs(primary_by_exp, metric_key),
        # Which metric keys each kept run logged. Carried so a caller wanting
        # the set's pickable metrics doesn't repeat the DISTINCT scan above.
        "metric_keys": {e: sorted(ks) for e, ks in metric_keys.items()},
        "goal": goal,
        "best_row_id": best_row_id,
        "best_row_id_final": best_final,
        "best_row_id_best": best_best,
        "duplicates": dup_groups,
    }


# ── One metric per set ────────────────────────────────────────────────────────
#
# Every view that ranks a *set* of runs needs one answer to "which metric is
# this set judged by?", and each one used to work it out for itself: the matrix
# took the goal of whichever run happened to sort first and then ranked across
# every run regardless of key, while the effects view took the first key it saw
# and excluded the rest. So the two could rank by different metrics over the
# same runs, and the matrix could crown a "best" run measured in a different
# unit from every other row.


def consensus_metric(primaries: dict) -> tuple[str, str]:
    """``(key, goal)`` — the metric a set of runs is judged by.

    The **most common** key wins, not the first one seen. A project that
    switched from ``loss`` to ``val_acc`` still has the old runs in the set, and
    letting one straggler define the axis would exclude every other run from the
    ranking — the more so because rows arrive newest-first, so a single legacy
    run could take the whole view. Ties break toward the key that sorts first,
    so the answer is stable rather than dependent on dict ordering.

    The goal comes from the runs resolving *that* key. They can disagree (one
    declares ``min``, another takes the heuristic); ``min`` wins the tie, since
    ranking a loss as if larger were better is the more damaging way to be
    wrong.
    """
    from . import primary_metric as pm

    counts: dict[str, int] = {}
    goals: dict[str, set] = {}
    for p in primaries.values():
        key = (p or {}).get("key")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
        goals.setdefault(key, set()).add((p or {}).get("goal") or pm.GOAL_MAX)
    if not counts:
        return "", pm.GOAL_MAX
    key = min(counts, key=lambda k: (-counts[k], k))
    goal = pm.GOAL_MIN if pm.GOAL_MIN in goals[key] else pm.GOAL_MAX
    return key, goal


def consensus_source(primaries: dict, key: str) -> dict:
    """Where the set's metric *key* was chosen: ``{"source", "study"}``.

    The broadest configured level among the runs judged by *key* — project,
    then study, then run — else ``heuristic``. Broadest, because that is the
    setting that decided the set: one run's own override does not make the
    whole search "set for this run", and offering to clear it from the Matrix
    would target a run the reader never named. The client used to guess this
    from the first configured row, which named ``run`` for a mixed set and
    then had no run to clear.
    """
    order = ("project", "study", "run")
    found = {}
    for p in primaries.values():
        if (p or {}).get("key") == key and p.get("source") in order:
            found.setdefault(p["source"], p.get("study") or "")
    for level in order:
        if level in found:
            return {"source": level, "study": found[level]}
    return {"source": "heuristic" if key else None, "study": ""}


def scored_values(primaries: dict, metric_key: str, basis: str = "final") -> dict[str, float]:
    """``{exp_id: value}`` for the runs measured by *metric_key*.

    A run whose primary metric resolved to a different key is left out rather
    than mixed in: two numbers measuring different things do not share a
    ranking, an axis or a "best row". A run that resolved the right key but
    never logged a value is left out too — it is still a configuration that was
    tested, which is why it stays in the matrix, but it cannot be ranked.
    """
    out: dict[str, float] = {}
    if not metric_key:
        return out
    for exp_id, p in primaries.items():
        if (p or {}).get("key") != metric_key:
            continue
        v = (p or {}).get(basis)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[exp_id] = float(v)
    return out


def off_metric_runs(primaries: dict, metric_key: str) -> int:
    """How many runs are judged by some *other* metric — stated, never silent."""
    return sum(1 for p in primaries.values()
               if (p or {}).get("key") and (p or {}).get("key") != metric_key)


def _metric_keys(conn, exp_ids: list[str]) -> dict[str, set]:
    """``{exp_id: {metric keys}}`` — what the heuristic picks from.

    Canonical names. This is what decides each run's primary metric, so raw
    keys meant two models aliased to one measurement still resolved *different*
    primary metrics — and the matrix then printed one model's `accuracy` under
    a column headed `LOSS`, because the column is the set's metric while each
    cell was that run's own.
    """
    from .metric_alias import alias_map, canonical_key
    amap = alias_map()
    out: dict[str, set] = {e: set() for e in exp_ids}
    for chunk in chunked(exp_ids):
        rows = conn.execute(
            f"SELECT DISTINCT exp_id, key FROM metrics "
            f"WHERE exp_id IN ({placeholders(chunk)})",
            chunk,
        ).fetchall()
        for r in rows:
            if r["exp_id"] in out:
                out[r["exp_id"]].add(canonical_key(r["key"], amap))
    return out


def _partition(exp_ids: list[str], params_by_exp: dict[str, dict],
               key: str) -> frozenset:
    """How *key* splits the runs: a set of frozensets of run ids.

    Two parameters that split the runs identically are indistinguishable from
    this data — see ``_aliased_params``.
    """
    buckets: dict[Any, set] = {}
    for e in exp_ids:
        norm = _norm(params_by_exp.get(e, {}).get(key, MISSING))
        buckets.setdefault(repr(norm), set()).add(e)
    return frozenset(frozenset(v) for v in buckets.values())


def _aliased_params(exp_ids: list[str], params_by_exp: dict[str, dict],
                    keys: list[str]) -> dict[str, list[str]]:
    """``{key: [other keys that split the runs identically]}``.

    This is the honesty guard on the whole effect-summary feature. If ``lr``
    and ``warmup`` were changed together on every run, the data cannot say
    which of them moved the metric — the two are perfectly confounded, and a
    chart captioned "lr vs val_acc" would read as an answer when the experiment
    never separated them. The summaries are descriptive, so the right move is
    to name the confound rather than imply an effect.

    Only exact co-variation is reported. Partial correlation is real too, but
    quantifying it starts making causal claims this module deliberately does
    not make.
    """
    parts = {k: _partition(exp_ids, params_by_exp, k) for k in keys}
    out: dict[str, list[str]] = {}
    for k in keys:
        # A single-bucket partition (every run in one group) is trivially equal
        # to every other single-bucket one; those keys don't vary and aren't here.
        same = sorted(o for o in keys if o != k and parts[o] == parts[k])
        if same:
            out[k] = same
    return out




def parameter_effects(conn, exp_ids: list[str], group_by: str = "",
                      include_running: bool = False,
                      include_failed: bool = True) -> dict:
    """Per varying parameter: what was tried, and how the runs scored.

    **These are descriptive relationships, not causal effects, and not feature
    importance.** Every caller must present them that way. The runs were not
    randomized, the parameters were usually not varied independently, and the
    sample per value is typically a handful — so this reports what was observed
    (values tried, runs per value, best and median primary metric) and refuses
    to go further.

    Two guards keep it from reading as more than it is:

    - ``aliased_with`` names parameters that split the runs identically. If
      ``lr`` and ``warmup`` moved together on every run, neither one's chart
      means what it appears to mean, and saying so is the only honest option.
    - ``single_run_per_value`` marks a parameter where every value was tried
      exactly once. "Best" and "median" of one run are that run — presenting
      them as a summary implies a distribution that was never measured.

    *group_by* adds a second parameter's value to each point, for colouring.
    """
    from . import primary_metric as pm

    # classify=False: the duplicate classification costs a fingerprint per run
    # and nothing below reads it.
    matrix = build_matrix(conn, exp_ids, include_running=include_running,
                          include_failed=include_failed, classify=False)
    rows = matrix["rows"]
    varying = matrix["varying"]
    if not rows:
        return {"n_runs": 0, "params": [], "metric": {}, "n_scored": 0}

    kept_ids = [r["id"] for r in rows]
    params_by_exp = {r["id"]: dict(r["params"]) for r in rows}
    keys = [p["key"] for p in varying]
    aliases = _aliased_params(kept_ids, params_by_exp, keys)

    # One metric across the set — resolved by the shared rule, so the axis a
    # chart is drawn against is the same metric the matrix ranked by.
    primaries = {r["id"]: r["primary"] for r in rows}
    metric_key, goal = consensus_metric(primaries)
    scores = scored_values(primaries, metric_key, "final")

    # "script" is groupable even though it is not a parameter, and it is the
    # grouping a cross-model comparison actually wants: a mixed-script set fuses
    # both models' param namespaces, so a shared `lr` column mixes semantically
    # different knobs and each model's exclusive params render as MISSING
    # "variations" on the other's rows. Colouring the points by model is what
    # makes that readable without pretending the two share a search space.
    scripts_by_exp = _scripts_by_exp(conn, kept_ids)
    names_by_exp = {r["id"]: (r["name"] or r["id"][:8]) for r in rows}
    group_by = group_by if (group_by in keys or group_by in _PSEUDO_GROUPS) else ""

    def _group_value_for(exp_id, key):
        if key == SCRIPT_GROUP:
            sc = scripts_by_exp.get(exp_id)
            return sc.rsplit("/", 1)[-1] if sc else "(no script)"
        if key == RUN_GROUP:
            return names_by_exp.get(exp_id, exp_id[:8])
        return _display(params_by_exp.get(exp_id, {}).get(key, MISSING))

    def _group_value(exp_id):
        return _group_value_for(exp_id, group_by)

    # Every grouping's value for every run, once, keyed by run rather than by
    # point. Changing what the points are coloured by used to be a *request* —
    # the same analysis recomputed server-side to relabel a scatter — which
    # blanked the section and re-rendered it, so a display choice read as the
    # page reloading. With this the client regroups from what it already has.
    #
    # Keyed by run and not by point on purpose: a point exists per (run,
    # parameter), so the per-point form is `params` times larger for data that
    # cannot vary within a run.
    run_groups = {
        e: {k: _group_value_for(e, k) for k in list(keys) + list(_PSEUDO_GROUPS)}
        for e in kept_ids
    }

    out_params = []
    for spec in varying:
        key = spec["key"]
        buckets: dict[str, dict] = {}
        points = []
        for e in kept_ids:
            raw = params_by_exp.get(e, {}).get(key, MISSING)
            norm = _norm(raw)
            b = buckets.setdefault(repr(norm), {
                "value": None if raw is MISSING else raw,
                "missing": raw is MISSING,
                "count": 0, "_scores": [],
            })
            b["count"] += 1
            if e in scores:
                b["_scores"].append(scores[e])
                num = _numeric_value(norm)
                points.append({
                    "id": e,
                    "x": num if num is not None else _display(raw),
                    "y": scores[e],
                    "numeric": num is not None,
                    "group": _group_value(e) if group_by else None,
                })

        values = []
        for b in buckets.values():
            s = b.pop("_scores")
            b["n_scored"] = len(s)
            b["best"] = (max(s) if goal != pm.GOAL_MIN else min(s)) if s else None
            b["median"] = (statistics.median(s) if s else None)
            b["min"] = min(s) if s else None
            b["max"] = max(s) if s else None
            values.append(b)
        values.sort(key=lambda b: (b["missing"], _sort_key(b["value"])))

        scored_counts = [b["n_scored"] for b in values if b["n_scored"]]
        out_params.append({
            "key": key,
            "kind": spec["kind"],
            "values": values,
            "points": points,
            "aliased_with": aliases.get(key, []),
            # Every value tried exactly once: these are individual results, and
            # calling them a median would invent a distribution.
            "single_run_per_value": bool(scored_counts)
                                    and max(scored_counts) == 1,
        })

    return {
        "n_runs": len(rows),
        "n_scored": len(scores),
        "metric": {"key": metric_key, "goal": goal},
        "off_metric_runs": off_metric_runs(primaries, metric_key),
        "group_by": group_by,
        # `{key, label}` pairs, not bare keys: `_script` is a pseudo-key, and
        # sending it raw meant its display name was hardcoded in two places in
        # the client instead of living beside its definition.
        #
        # Every key, *including the one currently selected*. This used to omit
        # `group_by` — "you cannot colour by the axis itself", which is a rule
        # about one panel (colouring the `lr` chart by `lr` just repeats its x
        # axis) applied to the whole section's picker. The list is what the
        # picker is built from, so dropping the selected key left the control
        # with no option to mark: choosing "model" coloured the points and then
        # snapped the dropdown back to "—", which reads as the setting not
        # having taken. The per-panel rule belongs in the panel, and lives in
        # the client's chart builder.
        "groupable": ([{"key": k, "label": k} for k in keys]
                      + [{"key": SCRIPT_GROUP, "label": SCRIPT_GROUP_LABEL},
                         {"key": RUN_GROUP, "label": RUN_GROUP_LABEL}]),
        "run_groups": run_groups,
        "group_by_label": _GROUP_LABELS.get(group_by, group_by),
        "params": out_params,
    }


def _display(value):
    """A short, stable string for a parameter value."""
    if value is MISSING:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict, tuple)):
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _sort_key(value):
    """Order values numerically when they are numbers, else as text."""
    norm = _norm(value)
    if norm is not MISSING and norm[0] == "num":
        return (0, norm[1], "")
    return (1, 0.0, _display(value))


def config_fingerprint(params: dict) -> str:
    """A stable identity for one run's configuration.

    Built from the normalized user params only, so two runs that set the same
    values differ in fingerprint only when the *configuration* differs — not
    when one was captured through argparse and the other through the pipeline
    CLI, and not when exptrack's own bookkeeping params differ (they always do:
    ``_code_snapshot`` names a per-file hash).
    """
    items = sorted(
        (k, _norm(v)) for k, v in params.items() if is_user_param_key(k)
    )
    return json.dumps(items, default=str, sort_keys=True)


DATASET_PARAM = "_dataset_manifest"

# What a run's code / dataset comparison can say. "unknown" is a third state,
# not a synonym for "same": a run that captured no source is not a run whose
# source matched, and reporting "identical configuration" on the strength of an
# uncaptured fact is precisely the confident-but-wrong claim this codebase
# keeps having to remove.
SAME = "same"
DIFFERS = "differs"
UNKNOWN = "unknown"
# No member recorded this fact at all — distinct from UNKNOWN, which means
# *some* did and some didn't. The two lead to opposite conclusions for the
# dataset dimension; see `_duplicate_kind`.
ABSENT = "absent"


def code_fingerprint(conn, exp_id: str, params: dict | None = None):
    """Identity of the code this run executed, or None when none was captured.

    The run's own content-addressed script snapshot, else its ordered
    executed-cell hashes — never the repository-wide ``_run_code_signature``,
    which moves when *any* tracked file changes and would report "different
    code" for a byte-identical rerun.

    *params* is the run's already-decoded params. When given, a script run is
    answered **entirely from memory**: the snapshot lives in `_code_snapshot`,
    which every caller here has already loaded, and querying for it again was a
    round trip per run (200-400 on a matrix request). Only a run with no
    snapshot — a notebook — falls through to the cell-hash query.
    """
    if params is not None:
        entries = params.get("_code_snapshot")
        if isinstance(entries, str):        # legacy double-encoded rows
            entries = decode_param_value(entries)
        if isinstance(entries, list):
            hashes = tuple(e["hash"] for e in entries
                           if isinstance(e, dict) and e.get("hash"))
            if hashes:
                return ("snapshot", *hashes)
    from .queries import _run_source_identity
    return safe_call(_run_source_identity, conn, exp_id,
                     default=None, context="param_study.code_fingerprint")


def dataset_fingerprint(params: dict):
    """Identity of the inputs this run read, or None when none were captured.

    Built from the ``_dataset_manifest`` param that ``Experiment.finish()``
    already records (per input: path, size and a content or listing hash), so
    "same params, same code, but the data moved underneath" is answerable
    without capturing anything new.
    """
    manifest = params.get(DATASET_PARAM)
    if not isinstance(manifest, dict) or not manifest:
        return None
    out = []
    for key in sorted(manifest):
        entry = manifest[key]
        if isinstance(entry, dict):
            out.append((key, str(entry.get("hash") or ""), entry.get("size")))
        else:
            out.append((key, str(entry), None))
    return tuple(out)


def _agreement(values: list) -> str:
    """SAME / DIFFERS / UNKNOWN / ABSENT across a group's fingerprints.

    UNKNOWN wins over SAME whenever *some* member lacks the fact, because the
    group can then only be shown to agree on what was captured. It does **not**
    win over DIFFERS: two members that demonstrably differ differ, whatever a
    third member failed to record.

    ABSENT is when *no* member recorded it — a different situation from a
    partial record, and one the caller resolves per dimension.
    """
    if all(v is None for v in values):
        return ABSENT
    if any(v is None for v in values):
        known = [v for v in values if v is not None]
        return DIFFERS if len({repr(v) for v in known}) > 1 else UNKNOWN
    return SAME if len({repr(v) for v in values}) == 1 else DIFFERS


def _duplicate_kind(code: str, dataset: str, script: str = ABSENT) -> str:
    """One label for the (script, code, dataset) triple — most specific first.

    Ordering matters: a group whose *script* differs is not a duplicate at all
    in the sense the feature exists to report — it is two different models that
    happen to share a hyperparameter configuration, which is the normal shape
    of a cross-model comparison. Reporting `model_a.py --lr 0.01` and
    `model_b.py --lr 0.01` as "you already ran this" told the user to skip the
    second model. Below that, a group whose code differs is a "same params,
    different code" finding regardless of its data, because that is the
    actionable difference; only when the code is known to match does the
    dataset become the distinguishing fact.
    """
    if script == DIFFERS:
        return "script_differs"
    if code == DIFFERS:
        return "code_differs"
    if code == SAME and dataset == DIFFERS:
        return "dataset_differs"
    if code == SAME and dataset in (SAME, ABSENT):
        # ABSENT counts as "nothing to differ on" for the **dataset** and not
        # for the code, and the asymmetry is deliberate: a run may genuinely
        # read no data files, so "neither recorded a dataset" is a complete
        # answer — but every run executes *some* code, so "neither captured
        # source" is missing evidence, not the absence of a difference.
        # Without this, a project whose scripts take no data path would see
        # every duplicate degrade to `params_only`, and the one verdict the
        # feature exists to deliver — "you have already run exactly this" —
        # would never appear.
        return "identical"
    # Params match, but something wasn't captured on at least one side — say
    # that, rather than implying a match nothing verified.
    return "params_only"


def _scripts_by_exp(conn, exp_ids: list[str]) -> dict[str, str | None]:
    """``{exp_id: script}`` for the set, with an unrecorded script as None.

    None rather than ``""`` so it flows through ``_agreement`` as "not
    captured" — a script-less run is missing evidence about which model ran,
    not evidence that it was the same one.
    """
    out: dict[str, str | None] = {}
    for chunk in chunked(list(exp_ids)):
        rows = conn.execute(
            f"SELECT id, script FROM experiments WHERE id IN ({placeholders(chunk)})",
            chunk,
        ).fetchall()
        for r in rows:
            out[r["id"]] = (r["script"] or "").strip() or None
    return out


def classify_duplicates(conn, exp_ids: list[str],
                        params_by_exp: dict[str, dict] | None = None) -> list[dict]:
    """Duplicate parameter configurations, split by what else is or isn't equal.

    "I already ran this" has three useful answers and they lead to different
    actions, so collapsing them into one flag would be worse than not having
    it: an **identical** rerun is wasted compute, **same params / different
    code** is the whole point of the change-one-line loop and not a duplicate
    at all in the sense that matters, and **same params and code / different
    dataset** is the one that silently invalidates a comparison.

    Returns one entry per group of two or more runs sharing a parameter
    configuration::

        {"fingerprint", "exp_ids", "n", "code", "dataset", "kind",
         "subgroups": [{"code", "dataset", "exp_ids"}, ...]}

    This is the only duplicate grouper. A plain "these runs share parameters"
    list is this one with the verdict dropped, and a second copy of the
    grouping meant two places to keep in step with the fingerprint rules.

    ``code``/``dataset`` are ``same`` / ``differs`` / ``unknown``; ``kind`` is
    the derived label. ``subgroups`` splits the group by the exact (code,
    dataset) pair, so a three-run group where two share code and one doesn't
    still says which is which.
    """
    exp_ids = list(exp_ids)
    if params_by_exp is None:
        params_by_exp = load_params(conn, exp_ids, include_internal=True)

    groups: dict[str, list[str]] = {}
    for exp_id in exp_ids:
        fp = config_fingerprint(params_by_exp.get(exp_id, {}))
        groups.setdefault(fp, []).append(exp_id)

    scripts = _scripts_by_exp(conn, exp_ids)

    out = []
    for fp, ids in groups.items():
        if len(ids) < 2:
            continue
        codes = {e: code_fingerprint(conn, e, params_by_exp.get(e)) for e in ids}
        datasets = {e: dataset_fingerprint(params_by_exp.get(e, {})) for e in ids}
        code = _agreement([codes[e] for e in ids])
        dataset = _agreement([datasets[e] for e in ids])
        script = _agreement([scripts.get(e) for e in ids])

        sub: dict[tuple, list[str]] = {}
        for e in ids:
            sub.setdefault(
                (repr(scripts.get(e)), repr(codes[e]), repr(datasets[e])), []
            ).append(e)
        subgroups = [{"script": k[0], "code": k[1], "dataset": k[2], "exp_ids": v}
                     for k, v in sub.items()]
        subgroups.sort(key=lambda g: (-len(g["exp_ids"]), g["exp_ids"][0]))

        out.append({
            "fingerprint": fp, "exp_ids": ids, "n": len(ids),
            "code": code, "dataset": dataset, "script": script,
            "kind": _duplicate_kind(code, dataset, script),
            "subgroups": subgroups,
        })
    out.sort(key=lambda g: (-g["n"], g["exp_ids"][0]))
    return out


def find_equivalent_runs(conn, exp_id: str, params: dict,
                         script: str = "", limit: int = 200) -> list[dict]:
    """Earlier runs whose parameter configuration matches *params*.

    Backs the post-capture notice (see ``Experiment._warn_if_duplicate``), so
    it is bounded and cheap on purpose: only the most recent *limit* surviving
    runs of the same script are considered. A sweep that has already run 5000
    times does not need an exhaustive scan to tell the user the config is a
    repeat, and this sits on the run path.

    Each result carries the same ``code``/``dataset``/``kind`` verdict
    ``classify_duplicates`` produces, for this run against that one.
    """
    want = config_fingerprint(params)
    clauses = ["deleted_at IS NULL", "id != ?"]
    args: list = [exp_id]
    # Script equality is required in *both* directions, including the empty
    # case. Dropping the filter when this run has no script made a script-less
    # run a candidate duplicate of every script in the project, so a notebook
    # or a bare pipeline step was told it repeated some unrelated model's
    # configuration.
    clauses.append("COALESCE(script, '') = ?")
    args.append(script or "")
    rows = conn.execute(
        f"""SELECT id, name, created_at FROM experiments
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC LIMIT ?""",
        (*args, limit),
    ).fetchall()
    if not rows:
        return []

    candidates = [r["id"] for r in rows]
    others = load_params(conn, candidates, include_internal=True)
    mine_code = code_fingerprint(conn, exp_id, params)
    mine_data = dataset_fingerprint(params)

    out = []
    for r in rows:
        p = others.get(r["id"], {})
        if config_fingerprint(p) != want:
            continue
        code = _agreement([mine_code, code_fingerprint(conn, r["id"], p)])
        dataset = _agreement([mine_data, dataset_fingerprint(p)])
        out.append({
            "id": r["id"], "name": r["name"], "created_at": r["created_at"],
            "code": code, "dataset": dataset,
            "kind": _duplicate_kind(code, dataset),
        })
    return out


# Message per finding. Which of the three it is matters more than the count:
# "same params, different code" is the change-one-line loop working correctly
# and must not read as waste, while "different data" is the one that quietly
# invalidates a comparison.
_DUPLICATE_LABELS = {
    "script_differs": "same params, but a different script",
    "identical": "same params, code and data",
    "code_differs": "same params, but the code changed",
    "dataset_differs": "same params and code, but the data changed",
    "params_only": "same params (code/data not captured for both)",
}


def duplicate_notice(conn, exp_id: str, params: dict, script: str = "") -> str:
    """The one-line "already run" notice for this run, or ``""``.

    Lives here rather than on ``Experiment`` because it is duplicate-detection
    policy, not run lifecycle: the config gate, the candidate scan and the
    wording all belong beside the classification they describe, and a pure
    function is testable without constructing an Experiment.
    """
    from .. import config
    if not config.load().get("warn_duplicate_runs", True):
        return ""
    matches = find_equivalent_runs(conn, exp_id, params, script=script)
    if not matches:
        return ""
    # Newest first from the query: the most recent repeat is the one most
    # likely to be the accident worth naming.
    top = matches[0]
    label = _DUPLICATE_LABELS.get(top["kind"], "same params")
    extra = f" (+{len(matches) - 1} more)" if len(matches) > 1 else ""
    return f"already run: '{top['name']}' — {label}{extra}"
