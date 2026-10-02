"""
exptrack/core/primary_metric.py — which number this run is judged by.

Every surface that ranks, compares or summarizes a run needs one answer to
"what is *the* metric here?", and until now each one improvised: the filmstrip
took the first metric present on any run, the Charts tab rendered every key,
the table offered a sort selector. Three surfaces, three answers, none of them
stated. This module is the single answer.

Resolution order — first configured level wins::

    run override  →  study override  →  project default  →  heuristic

The first three are *configured*: someone said this is the metric. The
heuristic is a guess, and it only runs when nothing at all has been said.
That distinction is the load-bearing part of this module, and it shows up in
two rules that every caller depends on:

**A configured metric is never silently substituted.** If the project says the
metric is ``val_acc`` and a run never logged it, that run's primary metric is
``val_acc`` with no value and ``missing=True`` — not whatever else it happened
to log. Falling back would make a run look comparable when it isn't, and a
table sorted on a column whose rows mean different things per row is worse
than one with gaps in it.

**The answer always says where it came from.** ``source`` is one of
``run`` / ``study`` / ``project`` / ``heuristic`` (or ``None`` when the run
logged no metrics at all), so the UI can show a guessed metric differently
from a declared one and offer to make it explicit.

Storage follows what the codebase already does rather than adding a table:

- the **run** override is the ``_primary_metric`` param, exactly as
  ``_variant_of`` is (see ``queries._explicit_baseline``) — the ``_`` prefix
  already keeps it out of run naming, the params table and the param diff, and
  it needs no migration or ``_SCHEMA_VERSION`` bump;
- the **study** and **project** levels live in ``.exptrack/config.json``,
  because a study is not a row anywhere — it is a name in each run's
  ``experiments.studies`` JSON list, derived at read time by
  ``queries.get_studies``. There is no per-study record to hang this on.

Direction (``goal``) is resolved alongside the key and is explicit whenever the
key was: a configured level may state ``"min"`` or ``"max"``. Only when it
doesn't does the name heuristic below decide, and it mirrors the client-side
``metricGoodDirection`` in ``dashboard/static/js/core.js`` so both ends agree.
Once resolved the goal rides on the payload, so the client reads it rather than
re-deriving it for the primary metric.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from .. import config
from .utils import (
    chunked,
    decode_param_value,
    normalize_metric_key,
    placeholders,
    safe_call,
)

# The run-level override. `_`-prefixed for the same reasons as _variant_of.
PRIMARY_METRIC_KEY = "_primary_metric"

GOAL_MAX = "max"
GOAL_MIN = "min"
_GOALS = (GOAL_MAX, GOAL_MIN)

# Where a resolved metric came from. `resolve_spec` walks these most-specific
# first; `heuristic` is the only one that is a guess.
SOURCE_RUN = "run"
SOURCE_STUDY = "study"
SOURCE_PROJECT = "project"
SOURCE_HEURISTIC = "heuristic"

# Metric names for which *lower* is better. Mirrors LOWER_IS_BETTER_RE in
# dashboard/static/js/core.js — keep the two in sync; tests/test_primary_metric.py
# asserts the two lists match so a one-sided edit fails rather than silently
# colouring a regression green on one end and red on the other.
_LOWER_IS_BETTER = re.compile(
    r"^(loss|losses|err|error|errors|err_rate|error_rate|mse|rmse|mae|mape|"
    r"smape|nll|kl|kld|perplexity|ppl|wer|cer|fpr|fnr|eer|regret|cost|"
    r"latency|runtime|overfit|val_loss|train_loss)$"
)


def goal_for_key(key: str) -> str:
    """``"min"`` when lower is better for *key*, else ``"max"``.

    Matched on the base name (after the last ``/``) so ``train/loss`` resolves
    like bare ``loss``, then on each ``_``-separated part so ``smooth_loss``,
    ``val_rmse`` and ``grad_err`` are caught too.
    """
    base = normalize_metric_key(key)
    if _LOWER_IS_BETTER.match(base):
        return GOAL_MIN
    for part in base.split("_"):
        if _LOWER_IS_BETTER.match(part):
            return GOAL_MIN
    return GOAL_MAX


def _clean_goal(goal: Any) -> str:
    """A stated goal, or ``""`` when unusable — never a raised error.

    A hand-edited config or a stray param value must not be the reason a run
    has no primary metric at all; an unusable goal degrades to the heuristic.
    """
    g = str(goal or "").strip().lower()
    if g in ("maximize", "maximise", "higher", "up"):
        g = GOAL_MAX
    elif g in ("minimize", "minimise", "lower", "down"):
        g = GOAL_MIN
    return g if g in _GOALS else ""


def _spec(key: Any, goal: Any = "") -> dict | None:
    """Normalize one configured level into ``{key, goal}``, or None if unset."""
    k = str(key or "").strip()
    if not k:
        return None
    return {"key": k, "goal": _clean_goal(goal)}


def _parse_level(value: Any) -> dict | None:
    """Read one configured level, which may be a bare key or a ``{key, goal}``.

    Accepting the bare string keeps ``"primary_metric": "val_acc"`` working as
    the obvious thing to hand-write in config.json.
    """
    if isinstance(value, str):
        return _spec(value)
    if isinstance(value, dict):
        return _spec(value.get("key"), value.get("goal"))
    return None


# ── The three configured levels ───────────────────────────────────────────────


def project_primary_metric(conf: dict | None = None) -> dict | None:
    """The project-wide default from ``.exptrack/config.json``, if set."""
    conf = config.load() if conf is None else conf
    return _parse_level(conf.get("primary_metric"))


def study_primary_metric(study: str, conf: dict | None = None) -> dict | None:
    """The override for one study name, if set.

    Study overrides live in config rather than on a row because a study is not
    a row: it is a name inside each run's ``studies`` JSON list.
    """
    if not study:
        return None
    conf = config.load() if conf is None else conf
    by_study = conf.get("primary_metric_by_study")
    if not isinstance(by_study, dict):
        return None
    return _parse_level(by_study.get(study))


def run_primary_metric(conn, exp_id: str) -> dict | None:
    """This run's own override, stored as the ``_primary_metric`` param."""
    return run_primary_metrics(conn, [exp_id]).get(exp_id)


def run_primary_metrics(conn, exp_ids: list[str]) -> dict[str, dict]:
    """Run-level overrides for many runs, in one query per chunk.

    Batched rather than per-run: `list_experiments` resolves this for a whole
    page (up to 1000 runs) on the dashboard's polled path, so a per-run lookup
    is 1000 queries per request. Callers that already hold the runs' params
    should pass them to `primary_metric_batch` instead and skip this entirely.
    """
    out: dict[str, dict] = {}
    for chunk in chunked(exp_ids):
        rows = conn.execute(
            f"SELECT exp_id, value FROM params "
            f"WHERE key=? AND exp_id IN ({placeholders(chunk)})",
            (PRIMARY_METRIC_KEY, *chunk),
        ).fetchall()
        for r in rows:
            spec = _parse_level(decode_param_value(r["value"]))
            if spec:
                out[r["exp_id"]] = spec
    return out


# ── Resolution ────────────────────────────────────────────────────────────────


def _heuristic_key(metric_keys: Iterable[str], conf: dict | None = None) -> str:
    """Guess a metric from the ones this run actually logged.

    Prefers a key whose base name is one of the configured ``result_types``
    (accuracy, loss, auroc, f1, …) — that list already exists to name the
    numbers that are *results* rather than diagnostics, which is exactly the
    distinction wanted here. Falls back to the first key in sorted order, so
    the guess is at least stable between requests rather than depending on
    whichever row SQLite emitted first.
    """
    keys = [k for k in metric_keys if k]
    if not keys:
        return ""
    conf = config.load() if conf is None else conf
    result_types = conf.get("result_types")
    if isinstance(result_types, list):
        wanted = {str(t).lower() for t in result_types if t}
        for k in sorted(keys):
            base = k.rsplit("/", 1)[-1].lower()
            if base in wanted:
                return k
            if any(part in wanted for part in re.split(r"[\s\-_]+", base)):
                return k
    return sorted(keys)[0]


def resolve_spec(conn, exp_id: str, studies: Iterable[str] | None = None,
                 metric_keys: Iterable[str] | None = None,
                 conf: dict | None = None,
                 run_override: dict | None = None) -> dict:
    """Resolve which metric judges this run, and how.

    Returns ``{"key", "goal", "source"}``. ``key`` is ``""`` and ``source`` is
    ``None`` only when nothing is configured *and* the run logged no metrics —
    i.e. there is genuinely nothing to name.

    *studies*, *metric_keys* and *run_override* let a batch caller pass what it
    already loaded; all are read-only inputs, and omitting them is not an error
    (studies then contributes no override, and the heuristic has nothing to
    pick from). *run_override* is the resolved `_primary_metric` spec for this
    run — passing it is what keeps the batch path free of a per-run query.
    """
    conf = config.load() if conf is None else conf

    spec = run_override
    source = SOURCE_RUN
    from_study = ""
    if not spec:
        # First study that names a metric wins. Runs belong to few studies and
        # a run in two studies that disagree has no better answer available —
        # sorted() at least makes the pick stable rather than list-order luck.
        for study in sorted(studies or []):
            spec = study_primary_metric(study, conf)
            if spec:
                source, from_study = SOURCE_STUDY, study
                break
    if not spec:
        spec = project_primary_metric(conf)
        source = SOURCE_PROJECT
    if not spec:
        key = _heuristic_key(metric_keys or [], conf)
        if not key:
            return {"key": "", "goal": GOAL_MAX, "source": None}
        spec, source = _spec(key), SOURCE_HEURISTIC

    out = {
        "key": spec["key"],
        "goal": spec["goal"] or goal_for_key(spec["key"]),
        "source": source,
    }
    if from_study:
        # Which study said so — the dashboard's picker clears that level.
        out["study"] = from_study
    return out


# ── Values ────────────────────────────────────────────────────────────────────


def _value_rows(conn, pairs: dict[str, tuple],
                conf: dict | None = None) -> dict[str, dict]:
    """Final and best point per run, for a ``{exp_id: (key, goal)}`` mapping.

    Grouped by ``(key, goal)`` rather than by key alone: two runs can resolve
    the same metric with opposite directions (one declares ``goal: "min"``, the
    other takes the heuristic), and "best" is meaningless for a group that
    doesn't agree on which end is best.

    One query per group per chunk of ids — normally one query total, since a
    project overwhelmingly resolves every run to the same metric. Each
    is a single indexed pass using window functions rather than a correlated
    subquery per run: the same shape, and the same reason, as
    ``queries._latest_metric_rows``. This runs once per experiment-list request
    over every listed run's points, so a per-run subquery would make it
    quadratic in points-per-metric exactly where that has already bitten once.

    "Final" is the genuinely last-logged point. It orders by
    ``COALESCE(step,-1) DESC, ts DESC, rowid DESC``, matching ``last_metrics``:
    a step-less series (every ``step`` NULL — the plain ``log_metric(k, v)``
    case) then resolves by insert order rather than tying and letting SQLite
    pick, and a real step always outranks a step-less point instead of NULL
    sorting as the largest value under a bare ``DESC``.

    "Best" is by *goal*, ties broken toward the **earliest** step: when a run
    hits its best value twice, the first time it got there is the more useful
    of the two.
    """
    from .metric_alias import spellings_for
    by_group: dict[tuple, list[str]] = {}
    for exp_id, (key, goal) in pairs.items():
        if key:
            by_group.setdefault((key, goal), []).append(exp_id)

    out: dict[str, dict] = {}
    for (key, goal), all_ids in by_group.items():
        best_order = "value ASC" if goal == GOAL_MIN else "value DESC"
        # Match every spelling that resolves to this metric, not just the
        # canonical one: the rows carry the name the run logged, so a run whose
        # `accuracy` is aliased to `val_acc` matched nothing here and its
        # primary metric read as missing — on exactly the runs aliasing exists
        # to bring into the comparison.
        names = spellings_for(key, conf)
        for ids in chunked(all_ids):
            ph = placeholders(ids)
            kph = placeholders(names)
            rows = conn.execute(
                f"""
                SELECT exp_id, value, step, rn_last, rn_best FROM (
                    SELECT exp_id, value, step,
                           ROW_NUMBER() OVER (PARTITION BY exp_id
                               ORDER BY COALESCE(step,-1) DESC, ts DESC,
                                        rowid DESC) AS rn_last,
                           ROW_NUMBER() OVER (PARTITION BY exp_id
                               ORDER BY {best_order}, COALESCE(step,-1),
                                        rowid) AS rn_best
                    FROM metrics
                    WHERE key IN ({kph}) AND value IS NOT NULL
                      AND exp_id IN ({ph})
                ) WHERE rn_last=1 OR rn_best=1
                """,
                (*names, *ids),
            ).fetchall()
            for r in rows:
                entry = out.setdefault(r["exp_id"], {})
                if r["rn_best"] == 1:
                    entry["best"] = r["value"]
                    entry["best_step"] = r["step"]
                if r["rn_last"] == 1:
                    entry["final"] = r["value"]
    return out


def primary_metric_batch(conn, runs: Iterable[dict], conf: dict | None = None,
                         params_by_exp: dict[str, dict] | None = None) -> dict[str, dict]:
    """Primary-metric payload for many runs at once.

    *runs* are dicts carrying at least ``id``, and optionally ``studies`` and
    ``metrics`` (the latter only to give the heuristic something to pick from) —
    i.e. exactly what ``queries.list_experiments`` has already loaded, so this
    adds no per-run query.

    *params_by_exp* is an already-loaded ``{exp_id: {key: value}}``; when given,
    the run-level override is read from it and this costs **no** query beyond
    the metric-value lookup. `list_experiments` has those params loaded already
    (`get_params_batch`), so passing them makes the whole page free.

    Returns ``{exp_id: payload}`` where payload is::

        {key, goal, source, final, best, best_step, missing}

    ``missing`` is True when the metric was *configured* but this run never
    logged it. A heuristic key can never be missing (it was chosen from the
    run's own keys), and a run with no metric at all has ``key=""`` and
    ``source=None`` instead.
    """
    conf = config.load() if conf is None else conf
    runs = list(runs)
    ids = [r.get("id") for r in runs if r.get("id")]

    # One query for every run's override — or none at all when the caller
    # already holds the params. Resolving this per run inside the loop was a
    # query per listed run on the dashboard's polled path.
    if params_by_exp is not None:
        overrides = {}
        for exp_id in ids:
            spec = _parse_level((params_by_exp.get(exp_id) or {}).get(PRIMARY_METRIC_KEY))
            if spec:
                overrides[exp_id] = spec
    else:
        overrides = safe_call(run_primary_metrics, conn, ids,
                              default={}, context="primary_metric.overrides") or {}

    specs: dict[str, dict] = {}
    for r in runs:
        exp_id = r.get("id")
        if not exp_id:
            continue
        specs[exp_id] = resolve_spec(
            conn, exp_id,
            studies=r.get("studies") or [],
            metric_keys=(r.get("metrics") or {}).keys(),
            conf=conf,
            run_override=overrides.get(exp_id),
        )

    pairs = {e: (s["key"], s["goal"]) for e, s in specs.items() if s["key"]}
    values = safe_call(_value_rows, conn, pairs, conf,
                       default={}, context="primary_metric.values") or {}

    out: dict[str, dict] = {}
    for exp_id, spec in specs.items():
        vals = values.get(exp_id) or {}
        has_value = "final" in vals
        out[exp_id] = {
            "key": spec["key"],
            "goal": spec["goal"],
            "source": spec["source"],
            "final": vals.get("final"),
            "best": vals.get("best"),
            "best_step": vals.get("best_step"),
            "missing": bool(spec["key"]) and not has_value,
        }
        if spec.get("study"):
            out[exp_id]["study"] = spec["study"]
    return out


def resolve_goal(key: str, goal: str = "") -> str:
    """The direction for *key*: an explicit *goal* if usable, else inferred.

    One line, but it is the line every caller that names its own metric needs —
    and a caller that spells it itself ends up disagreeing with the value lookup
    it then calls (the trade-off view resolved the goal for its payload while
    ``metric_values`` resolved it again for the query).
    """
    return _clean_goal(goal) or goal_for_key(key)


def metric_values(conn, exp_ids: Iterable[str], key: str, goal: str = "",
                  basis: str = "final") -> dict[str, float]:
    """``{exp_id: value}`` for one *named* metric across many runs.

    The public door onto ``_value_rows`` for callers that already know which
    key they want — the trade-off view, which plots two arbitrary metrics and so
    cannot go through the primary-metric resolution at all. It reuses the same
    windowed query rather than a second implementation, because that query's
    shape (and its "final" ordering, and its earliest-step tie-break for "best")
    is the definition of what those two words mean here.
    """
    pairs = {e: (key, resolve_goal(key, goal)) for e in exp_ids}
    rows = safe_call(_value_rows, conn, pairs, default={},
                     context="primary_metric.metric_values") or {}
    return {e: v[basis] for e, v in rows.items()
            if isinstance(v.get(basis), (int, float))}


def primary_metric_for_run(conn, exp_id: str, studies: Iterable[str] | None = None,
                           metric_keys: Iterable[str] | None = None,
                           conf: dict | None = None,
                           params_by_exp: dict[str, dict] | None = None) -> dict:
    """The payload above, for one run. Thin wrapper over the batch form."""
    run = {"id": exp_id, "studies": list(studies or []),
           "metrics": {k: None for k in (metric_keys or [])}}
    return primary_metric_batch(conn, [run], conf=conf,
                                params_by_exp=params_by_exp)[exp_id]


# ── Setters ───────────────────────────────────────────────────────────────────


def set_run_primary_metric(conn, exp_id: str, key: str, goal: str = "") -> dict:
    """Set (or clear, with a falsy *key*) this run's own override."""
    if not key:
        conn.execute("DELETE FROM params WHERE exp_id=? AND key=?",
                     (exp_id, PRIMARY_METRIC_KEY))
        conn.commit()
        return {"ok": True, "primary_metric": None}
    spec = _spec(key, goal)
    conn.execute(
        "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?) "
        "ON CONFLICT(exp_id, key) DO UPDATE SET value=excluded.value",
        (exp_id, PRIMARY_METRIC_KEY, json.dumps(spec), "manual"),
    )
    conn.commit()
    return {"ok": True, "primary_metric": spec}


def set_project_primary_metric(key: str, goal: str = "") -> dict:
    """Set (or clear) the project-wide default in ``.exptrack/config.json``."""
    conf = config.load()
    spec = _spec(key, goal)
    if spec:
        conf["primary_metric"] = spec
    else:
        conf.pop("primary_metric", None)
    config.save(conf)
    config.reload()
    return {"ok": True, "primary_metric": spec}


def set_study_primary_metric(study: str, key: str, goal: str = "") -> dict:
    """Set (or clear) the override for one study name."""
    if not study:
        return {"error": "study name required"}
    conf = config.load()
    # A copy: with nothing set yet, the dict `load()` hands back is the shared
    # default itself, and writing into it changed the default for the rest of
    # the process (every later project then "had" this study's setting).
    by_study = conf.get("primary_metric_by_study")
    by_study = dict(by_study) if isinstance(by_study, dict) else {}
    spec = _spec(key, goal)
    if spec:
        by_study[study] = spec
    else:
        by_study.pop(study, None)
    conf["primary_metric_by_study"] = by_study
    config.save(conf)
    config.reload()
    return {"ok": True, "study": study, "primary_metric": spec}


LEVELS = ("project", "study", "run")


def set_primary_metric(conn, level: str, key: str, goal: str = "",
                       study: str = "", run: str = "") -> dict:
    """Set (or clear, with a falsy *key*) the metric at the *named* level.

    The one dispatch behind `exptrack primary-metric` and the dashboard's
    picker. The level is always named, never inferred: they resolve run →
    study → project, and a write at the wrong one is shadowed by a more
    specific level and appears to do nothing. *run* is an id prefix; an empty
    one is refused rather than handed to a prefix match that fits every run.
    Returns the setter's answer plus ``level`` (and ``name`` for a run).
    """
    from .queries import find_experiment
    if level == "project":
        return {**set_project_primary_metric(key, goal), "level": level}
    if level == "study":
        return {**set_study_primary_metric(study, key, goal), "level": level}
    if level == "run":
        exp = find_experiment(conn, run, "id, name") if run else None
        if not exp:
            return {"error": f"run not found: {run}" if run else "run id required"}
        return {**set_run_primary_metric(conn, exp["id"], key, goal),
                "level": level, "name": exp["name"]}
    return {"error": "level must be one of " + ", ".join(LEVELS)}
