"""
exptrack/core/metric_alias.py — one name for one measurement.

Two models rarely agree on what to call a number. One logs ``val_acc``, the
other ``accuracy``; a TensorBoard writer contributes ``val/acc``. They are the
same measurement, but every surface that matches metrics matches them by
*string*, so the runs shared no metric at all: the compare table showed two
rows of ``--``, the reference strip reported no overlap, and consensus ranking
excluded one model wholesale rather than admitting it couldn't compare them.
That is the single biggest obstacle to comparing different models, and it is
not something the tracker can infer — only the person who named them knows.

So it is configuration. ``.exptrack/config.json``::

    "metric_aliases": {
      "val_acc": ["accuracy", "val/acc", "eval_accuracy"],
      "val_loss": ["loss", "eval_loss"]
    }

The key is the **canonical** name — what every surface will call it — and the
list is the spellings that mean it. Resolution is exact-match only, after the
same normalization ``primary_metric.goal_for_key`` uses (case, separators, and
the path prefix in ``train/loss``), because a fuzzy rule that guessed
``val_acc ≈ val_accuracy`` would eventually merge two metrics that are
genuinely different and silently average them.

Three rules the callers depend on:

**Canonicalization is display-level, never storage.** Rows keep the key the run
logged. A project that later removes an alias gets its original keys back, and
nothing that was recorded is lost or rewritten.

**A canonical name never collides with a real key it doesn't claim.** If a run
genuinely logs ``val_acc`` *and* ``accuracy`` and the config says they're the
same, the merge is the user's stated intent; that is the one case where two
series fold together, and ``merge_metric_map`` keeps the later-ordered value
rather than inventing an average.

**An unusable config degrades to no aliasing at all** — the documented
invariant for every setting. A malformed map must not be the reason a
comparison stops working.
"""
from __future__ import annotations

from .. import config as _config

# The same normalization the polarity heuristic applies, so `Train/Val Acc` and
# `train/val_acc` resolve alike — shared rather than copied, because the two
# drifting apart is silent.
from .utils import normalize_metric_key as _normalize


def alias_map(conf: dict | None = None) -> dict[str, str]:
    """``{normalized_alias: canonical_key}`` from config, or ``{}``.

    Built per call from the (cached) config rather than memoized here: the
    dashboard edits config live, and a stale alias table would silently keep
    merging metrics the user has just un-merged.
    """
    conf = _config.load() if conf is None else conf
    raw = conf.get("metric_aliases")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for canonical, aliases in raw.items():
        canon = str(canonical or "").strip()
        if not canon:
            continue
        # The canonical name resolves to itself, so a run that already uses it
        # needs no entry in its own alias list.
        out.setdefault(_normalize(canon), canon)
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, (list, tuple)):
            continue
        for a in aliases:
            norm = _normalize(a)
            if norm:
                out[norm] = canon
    return out


def canonical_key(key: str, amap: dict[str, str] | None = None) -> str:
    """The canonical name for *key*, or *key* itself when nothing claims it."""
    amap = alias_map() if amap is None else amap
    if not amap:
        return key
    return amap.get(_normalize(key), key)


def merge_metric_map(metrics: dict, amap: dict[str, str] | None = None) -> dict:
    """Re-key a ``{metric_key: value}`` map onto canonical names.

    Later keys win on a collision — the map is already in the reader's order
    (step, then ts, then insert order), so "later" means "more recent", the
    same rule ``last_metrics`` applies within a single key.
    """
    amap = alias_map() if amap is None else amap
    if not amap:
        return metrics
    out: dict = {}
    for k, v in metrics.items():
        out[canonical_key(k, amap)] = v
    return out


def alias_spellings(conf: dict | None = None) -> dict[str, list[str]]:
    """``{canonical: [aliases exactly as written in config]}``.

    ``alias_map`` keys on the *normalized* form, which is right for resolving a
    name but wrong for fetching one: the rows are stored under the spelling the
    run logged, and `val/acc` normalizes to `val_acc`, which matches no row.
    """
    conf = _config.load() if conf is None else conf
    raw = conf.get("metric_aliases")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for canonical, aliases in raw.items():
        canon = str(canonical or "").strip()
        if not canon:
            continue
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, (list, tuple)):
            aliases = []
        out[canon] = [str(a) for a in aliases if str(a or "").strip()]
    return out


def spellings_for(key: str, conf: dict | None = None) -> list[str]:
    """Every stored spelling that resolves to *key*, *key* itself first.

    The read side of the alias table. A surface that has canonicalized a name
    still has to *fetch* it, and the rows are stored under whatever the run
    logged — so a query for the canonical name alone finds nothing on exactly
    the runs aliasing exists to include, and the metric reads as *missing* on
    the model the alias was configured to bring in.
    """
    conf = _config.load() if conf is None else conf
    canon = canonical_key(key, alias_map(conf))
    out = [key]
    for a in alias_spellings(conf).get(canon, ()):
        if a not in out:
            out.append(a)
    if canon not in out:
        out.append(canon)
    return out


def canonical_groups(keys, amap: dict[str, str] | None = None) -> dict[str, list[str]]:
    """``{canonical: [original keys that resolve to it]}`` for a set of keys.

    Lets a surface say *which* spellings it merged — a merge the user cannot
    see is indistinguishable from a metric that was silently dropped.
    """
    amap = alias_map() if amap is None else amap
    out: dict[str, list[str]] = {}
    for k in keys:
        out.setdefault(canonical_key(k, amap), []).append(k)
    return out
