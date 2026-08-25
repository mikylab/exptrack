"""
exptrack/core/reference.py — the run you are trying to beat.

exptrack already resolves a baseline for every run, chronologically: the
previous run of the same script, overridable per run by ``_variant_of``. That
answers "what did I change since last time", which is a question about
*lineage*. It is the wrong answer to the other question a parameter search
asks constantly — "is this better than the thing I am trying to beat?" — where
the comparison point is one fixed run: the current production model, the
published number, the configuration everything else is a variation on.

Those two are kept deliberately apart.

**``variant_of`` is lineage; the reference is a target.** A run declares what
it descends from; the project declares what it is measured against. Folding
them together would mean setting a reference silently rewrote every run's "what
changed since last time", and clearing it silently rewrote them back.

**There is no implicit chain.** A reference is resolved study-level then
project-level and that is the whole ladder — it never falls through to "the
best run so far" or "the previous run", because a baseline that quietly moves
when the data changes is a baseline you cannot reason about. If no reference is
set, there is no reference, and the UI says so rather than substituting one.

**A stale reference is reported, never silently absent.** If the referenced run
was trashed or deleted, ``resolve`` returns it with ``stale`` naming why. The
chronological baseline can degrade quietly because it degrades to something
that still works; here there is nothing to degrade *to*, so silence would read
as "no reference set" and hide the fact that the comparison the user is reading
has stopped happening.

Storage mirrors ``primary_metric``: the project level and the per-study map
live in ``config.json``, because a study is not a row anywhere — it is a name
inside each run's ``studies`` list, derived at read time, so there is no record
to hang a setting on.
"""
from __future__ import annotations

from .. import config

PROJECT_KEY = "reference_run"
STUDY_KEY = "reference_run_by_study"

SOURCE_STUDY = "study"
SOURCE_PROJECT = "project"

# Why a configured reference can't be used. Both are states the user can fix,
# and each needs different wording, so they are distinguished rather than
# flattened into one "unavailable".
STALE_MISSING = "missing"    # no such run — deleted permanently, or a bad id
STALE_TRASHED = "trashed"    # in the Trash: restorable, so say that


def _study_map(conf: dict) -> dict:
    raw = conf.get(STUDY_KEY)
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def _project_id(conf: dict) -> str:
    raw = conf.get(PROJECT_KEY)
    return raw.strip() if isinstance(raw, str) else ""


def configured(studies=None, conf: dict | None = None) -> tuple[str, str, str]:
    """``(exp_id, source, study)`` — which reference *applies*, before lookup.

    A run in two studies that both name a reference resolves to the first in
    ``sorted()`` order, matching ``primary_metric.resolve_spec``. Both are
    answering the same question — "which of this run's studies names the
    setting?" — on the same screen, and two different answers to it is a bug
    waiting for the first run that belongs to two configured studies.
    """
    conf = config.load() if conf is None else conf
    by_study = _study_map(conf)
    for study in sorted(s for s in (studies or []) if isinstance(s, str)):
        if by_study.get(study):
            return by_study[study], SOURCE_STUDY, study
    project = _project_id(conf)
    if project:
        return project, SOURCE_PROJECT, ""
    return "", "", ""


def _lookup(conn, exp_id: str, source: str, study: str) -> dict:
    """Resolve one *already-chosen* reference id to its row, with staleness.

    Split from ``resolve`` so ``all_configured`` — which knows its level
    already — can call it directly. It used to synthesize fake config dicts to
    force ``resolve`` down a chosen branch, which encoded the precedence rules a
    second time: add a third level and both synthetic dicts keep working while
    quietly meaning something else.
    """
    row = conn.execute(
        "SELECT id, name, status, created_at, deleted_at, script "
        "FROM experiments WHERE id = ?", (exp_id,),
    ).fetchone()
    if not row:
        return {"id": exp_id, "name": "", "status": "", "created_at": "",
                "script": "", "source": source, "study": study,
                "stale": STALE_MISSING}
    return {
        "id": row["id"], "name": row["name"] or "", "status": row["status"] or "",
        "created_at": row["created_at"] or "", "script": row["script"] or "",
        "source": source, "study": study,
        "stale": STALE_TRASHED if row["deleted_at"] else None,
    }


def resolve(conn, studies=None, conf: dict | None = None) -> dict | None:
    """The reference run in force, or ``None`` when none is configured.

    Returns ``{id, name, status, created_at, source, study, stale}``. ``source``
    is always populated — every surface that shows a comparison has to be able
    to say *why* this run is the baseline, which is the whole difference between
    a reference you can trust and a number that appeared from somewhere.

    ``stale`` is ``None`` for a usable reference, else ``STALE_MISSING`` /
    ``STALE_TRASHED``; the id and source still come back so the message can name
    what was configured and where it was set.
    """
    exp_id, source, study = configured(studies, conf)
    return _lookup(conn, exp_id, source, study) if exp_id else None


def set_reference(conn, exp_id: str, study: str = "") -> dict:
    """Pin *exp_id* as the reference, at the project or one study's level.

    An empty *exp_id* clears that level. The level is chosen explicitly rather
    than inferred, for the reason ``primary-metric`` chooses one explicitly:
    writing the wrong one leaves a setting that appears to do nothing because a
    more specific level shadows it.

    A run must exist to become a reference — a typo'd id would otherwise be
    stored and only surface later as a stale reference, which is a worse way to
    learn about it.
    """
    from .queries import find_experiment

    conf = config.load()
    study = (study or "").strip()

    if not exp_id:
        if study:
            by_study = _study_map(conf)
            by_study.pop(study, None)
            conf[STUDY_KEY] = by_study
        else:
            conf[PROJECT_KEY] = ""
        config.save(conf)
        config.reload()
        return {"ok": True, "reference": None,
                "level": SOURCE_STUDY if study else SOURCE_PROJECT, "study": study}

    exp = find_experiment(conn, exp_id, "id, name, deleted_at, status")
    if not exp:
        return {"error": f"run '{exp_id}' not found"}
    if exp.get("deleted_at"):
        return {"error": f"'{exp['name']}' is in the Trash — restore it first"}
    # Pinning a run that is still going is allowed — a long training run is a
    # legitimate target — but its numbers are still moving, which is exactly
    # why `_BASELINE_WHERE` excludes `running` from *chronological* baselines.
    # Say so once, here, rather than letting every later comparison quietly
    # measure against a shifting target.
    warning = (f"'{exp['name']}' is still running — its metrics will keep "
               f"changing while it is the reference"
               if exp.get("status") == "running" else "")

    if study:
        by_study = _study_map(conf)
        by_study[study] = exp["id"]
        conf[STUDY_KEY] = by_study
    else:
        conf[PROJECT_KEY] = exp["id"]
    config.save(conf)
    config.reload()
    return {"ok": True, "reference": exp["id"], "name": exp["name"],
            "warning": warning,
            "level": SOURCE_STUDY if study else SOURCE_PROJECT, "study": study}


def configured_ids(conf: dict | None = None) -> dict[str, list[str]]:
    """``{exp_id: [level_label, ...]}`` for every reference set, without a query.

    What a surface that only needs to *mark* the pinned runs wants — the
    dashboard's list badge, which rides on ``/api/stats`` and so runs on boot
    and after every mutation. Resolving each row there would be one PK select
    per configured level, per call, for fields that surface throws away.

    A **list** per run, because one run can legitimately be pinned at more than
    one level (the project reference and a study's). A single-label map made the
    later write win, so a run that was both showed one badge and the other
    setting looked unset — the exact confusion the levelled commands are
    careful to avoid everywhere else.
    """
    conf = config.load() if conf is None else conf
    out: dict[str, list[str]] = {}
    project = _project_id(conf)
    if project:
        out.setdefault(project, []).append(SOURCE_PROJECT)
    for study, exp_id in sorted(_study_map(conf).items()):
        out.setdefault(exp_id, []).append(study)
    return out


def all_configured(conn, conf: dict | None = None) -> dict:
    """Every reference set in this project, resolved — for a settings view.

    ``{"project": {...}|None, "studies": [{study, ...}]}``, each entry carrying
    the same ``stale`` reporting as ``resolve``.
    """
    conf = config.load() if conf is None else conf
    project = _project_id(conf)
    return {
        "project": _lookup(conn, project, SOURCE_PROJECT, "") if project else None,
        "studies": [_lookup(conn, exp_id, SOURCE_STUDY, study)
                    for study, exp_id in sorted(_study_map(conf).items())],
    }


def delta_vs_reference(conn, exp_id: str, studies=None,
                       conf: dict | None = None) -> dict:
    """This run measured against the reference in force for it.

    ``{"reference": {...}|None, ...diff}``. The diff is the same
    ``queries.diff_runs`` the "vs previous" strip uses, so the two comparisons
    are rendered by one set of rules and can only differ in which baseline they
    name — which is exactly the difference the user is meant to see.

    A run that *is* the reference reports ``is_reference`` rather than a diff
    against itself.
    """
    from .queries import diff_runs, find_experiment

    exp = find_experiment(conn, exp_id, "id, created_at, studies")
    if not exp:
        return {"error": "not found"}

    if studies is None:
        from .queries import _json_list
        studies = _json_list(exp.get("studies"), "reference.studies")

    ref = resolve(conn, studies=studies, conf=conf)
    if not ref:
        return {"reference": None}
    if ref.get("stale"):
        return {"reference": ref}
    if ref["id"] == exp["id"]:
        return {"reference": ref, "is_reference": True}

    diff = diff_runs(conn, ref["id"], exp["id"])
    diff["reference"] = ref
    diff["current_created_at"] = exp.get("created_at") or ""
    return diff
