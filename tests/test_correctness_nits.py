"""Regression tests for the Phase-3 correctness nits (F17).

Covers:
  - param `source` is preserved when a manual param is re-logged (no OR REPLACE reset)
  - `diff_b_path` strips a leading `b/` prefix, not a char-set
  - batch params export honours `--format params*` instead of silently emitting JSON
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from types import SimpleNamespace

# ── F17.3: param source preservation on re-log ───────────────────────────────

def test_manual_param_source_preserved_on_relog(sample_experiment, db_conn):
    exp = sample_experiment
    # Insert a manual param directly (mirrors the dashboard add-param path).
    db_conn.execute(
        "INSERT INTO params (exp_id, key, value, source) VALUES (?,?,?,?)",
        (exp.id, "manual_key", json.dumps("v1"), "manual"),
    )
    db_conn.commit()

    # Re-logging the same key via the normal path must NOT reset source to 'auto'.
    exp._finished = False  # allow log_params on a finished exp for the test
    exp.log_params({"manual_key": "v2"})

    row = db_conn.execute(
        "SELECT value, source FROM params WHERE exp_id=? AND key=?",
        (exp.id, "manual_key"),
    ).fetchone()
    assert json.loads(row["value"]) == "v2"   # value updated
    assert row["source"] == "manual"          # source preserved


# ── F17.1: diff_b_path prefix strip ──────────────────────────────────────────

def test_diff_b_path_strips_prefix_not_charset():
    from exptrack.core.db import diff_b_path
    assert diff_b_path("b/backbone.py") == "backbone.py"   # not "ackbone.py"
    assert diff_b_path("b/src/b_utils.py") == "src/b_utils.py"
    assert diff_b_path("a/foo.py") == "a/foo.py"           # only b/ is stripped
    assert diff_b_path("nob.py") == "nob.py"


# ── F17.5: batch params export ───────────────────────────────────────────────

def _make_two_experiments():
    from exptrack.core import Experiment
    e1 = Experiment(script="train.py", params={"lr": 0.01, "epochs": 5})
    e1.finish()
    e2 = Experiment(script="train.py", params={"lr": 0.02, "epochs": 9})
    e2.finish()
    return e1, e2


def test_batch_params_export_equals(tmp_project):
    from exptrack.cli.inspect_cmds import cmd_export
    _make_two_experiments()
    args = SimpleNamespace(format="params", export_all=True, id=None)
    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_export(args)
    out = buf.getvalue()
    # params style, not JSON dump of the whole batch payload.
    assert "lr=0.01" in out
    assert "lr=0.02" in out
    assert "epochs=5" in out
    assert '"created_at"' not in out   # would appear in the fallback JSON dump


def test_batch_params_export_json_is_valid_array(tmp_project):
    from exptrack.cli.inspect_cmds import cmd_export
    _make_two_experiments()
    args = SimpleNamespace(format="params-json", export_all=True, id=None)
    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_export(args)
    parsed = json.loads(buf.getvalue())
    assert isinstance(parsed, list) and len(parsed) == 2
    assert all("params" in entry and "id" in entry for entry in parsed)
    lrs = {entry["params"]["lr"] for entry in parsed}
    assert lrs == {0.01, 0.02}
