"""Tests for the notebook explicit API (tag/note).

`notebook.tag()` used to only mutate an in-memory list + write a `_tags` param,
never touching the experiments.tags column, so interactive tags were invisible
to the dashboard/CLI. `notebook.note()` reimplemented note-writing with raw SQL.
Both now route through the real Experiment mutators.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def active_exp(tmp_project):
    from exptrack import notebook
    from exptrack.core import Experiment

    exp = Experiment(script="notebook")
    notebook._active = exp
    yield exp
    notebook._active = None


def _tags_in_db(exp_id):
    from exptrack.core.db import get_db
    row = get_db().execute(
        "SELECT tags FROM experiments WHERE id=?", (exp_id,)).fetchone()
    return json.loads(row["tags"] or "[]")


def test_tag_persists_to_tags_column(active_exp):
    from exptrack import notebook

    notebook.tag("baseline", "resnet")
    assert _tags_in_db(active_exp.id) == ["baseline", "resnet"]


def test_tag_dedupes(active_exp):
    from exptrack import notebook

    notebook.tag("baseline")
    notebook.tag("baseline")   # duplicate — no-op
    assert _tags_in_db(active_exp.id) == ["baseline"]


def test_tag_no_longer_writes_tags_param(active_exp):
    from exptrack import notebook
    from exptrack.core.db import get_db

    notebook.tag("a")
    row = get_db().execute(
        "SELECT COUNT(*) FROM params WHERE exp_id=? AND key='_tags'",
        (active_exp.id,)).fetchone()
    assert row[0] == 0


def test_note_appends_to_notes_column(active_exp):
    from exptrack import notebook
    from exptrack.core.db import get_db

    notebook.note("first")
    notebook.note("second")
    row = get_db().execute(
        "SELECT notes FROM experiments WHERE id=?", (active_exp.id,)).fetchone()
    assert row["notes"] == "first\nsecond"
