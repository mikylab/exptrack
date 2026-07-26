"""Tests for exptrack/core/queries.py — shared query functions."""


def test_find_experiment_by_prefix(tmp_project, sample_experiment):
    """find_experiment returns experiment by prefix match."""
    from exptrack.core import get_db
    from exptrack.core.queries import find_experiment

    conn = get_db()
    result = find_experiment(conn, sample_experiment.id[:6])
    assert result is not None
    assert result["id"] == sample_experiment.id


def test_find_experiment_not_found(tmp_project):
    """find_experiment returns None for non-existent ID."""
    from exptrack.core import get_db
    from exptrack.core.queries import find_experiment

    conn = get_db()
    result = find_experiment(conn, "nonexistent")
    assert result is None


def test_get_experiment_detail(tmp_project, sample_experiment):
    """get_experiment_detail returns full experiment with params and metrics."""
    from exptrack.core import get_db
    from exptrack.core.queries import get_experiment_detail

    conn = get_db()
    detail = get_experiment_detail(conn, sample_experiment.id[:6])

    assert detail is not None
    assert detail["id"] == sample_experiment.id
    assert detail["status"] == "done"
    assert detail["params"]["lr"] == 0.01
    assert detail["params"]["epochs"] == 10
    assert len(detail["metrics"]) == 2  # loss and acc
    assert any(m["key"] == "loss" for m in detail["metrics"])
    assert any(m["key"] == "acc" for m in detail["metrics"])


def test_list_experiments(tmp_project, sample_experiment):
    """list_experiments returns recent experiments with metrics."""
    from exptrack.core import get_db
    from exptrack.core.queries import list_experiments

    conn = get_db()
    results = list_experiments(conn, limit=10)

    assert len(results) >= 1
    assert results[0]["id"] == sample_experiment.id


def test_list_experiments_offset_paginates(tmp_project):
    """limit + offset page through experiments in created_at DESC order."""
    import time

    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import list_experiments

    for i in range(5):
        Experiment(script=f"s{i}.py").finish()
        time.sleep(0.005)  # distinct created_at ordering

    conn = get_db()
    full = list_experiments(conn, limit=10)
    assert len(full) == 5

    page1 = list_experiments(conn, limit=2, offset=0)
    page2 = list_experiments(conn, limit=2, offset=2)
    page3 = list_experiments(conn, limit=2, offset=4)
    assert [e["id"] for e in page1] == [e["id"] for e in full[:2]]
    assert [e["id"] for e in page2] == [e["id"] for e in full[2:4]]
    assert [e["id"] for e in page3] == [e["id"] for e in full[4:]]
    # No overlap across pages.
    ids = [e["id"] for e in page1 + page2 + page3]
    assert len(set(ids)) == 5


def test_api_experiments_offset_param(tmp_project):
    """api_experiments threads the offset query param into list_experiments."""
    import time

    from exptrack.core import Experiment, get_db
    from exptrack.dashboard.routes.read_routes import api_experiments

    for i in range(3):
        Experiment(script=f"r{i}.py").finish()
        time.sleep(0.005)

    conn = get_db()
    first = api_experiments(conn, {"limit": "1", "offset": "0"})
    second = api_experiments(conn, {"limit": "1", "offset": "1"})
    assert len(first) == 1 and len(second) == 1
    assert first[0]["id"] != second[0]["id"]


def test_list_experiments_status_filter(tmp_project):
    """list_experiments filters by status."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import list_experiments

    # Create one done and one failed
    e1 = Experiment(script="a.py")
    e1.finish()
    e2 = Experiment(script="b.py")
    e2.fail("crash")

    conn = get_db()
    done = list_experiments(conn, status="done")
    failed = list_experiments(conn, status="failed")

    assert all(e["status"] == "done" for e in done)
    assert all(e["status"] == "failed" for e in failed)


def test_get_latest_metrics(tmp_project, sample_experiment):
    """get_latest_metrics returns the last value for each metric key."""
    from exptrack.core import get_db
    from exptrack.core.queries import get_latest_metrics

    conn = get_db()
    metrics = get_latest_metrics(conn, sample_experiment.id)

    assert "loss" in metrics
    assert metrics["loss"] == 0.3  # step 2 value
    assert "acc" in metrics
    assert metrics["acc"] == 0.85


def test_format_export_params_equals(tmp_project, sample_experiment):
    """format_export_params(style='equals') emits key=JSONvalue lines."""
    from exptrack.core import get_db
    from exptrack.core.queries import format_export_params, get_export_data

    conn = get_db()
    data = get_export_data(conn, sample_experiment.id)
    text = format_export_params(data, style="equals")
    lines = text.splitlines()
    assert "lr=0.01" in lines
    assert "epochs=10" in lines
    # Private keys should not appear
    assert not any(line.startswith("_") for line in lines)


def test_format_export_params_flags(tmp_project, sample_experiment):
    """format_export_params(style='flags') emits --key value pairs."""
    from exptrack.core import get_db
    from exptrack.core.queries import format_export_params, get_export_data

    conn = get_db()
    data = get_export_data(conn, sample_experiment.id)
    text = format_export_params(data, style="flags")
    lines = text.splitlines()
    assert "--lr 0.01" in lines
    assert "--epochs 10" in lines


def test_format_export_params_json(tmp_project, sample_experiment):
    """format_export_params(style='json') emits a JSON object."""
    import json as _json

    from exptrack.core import get_db
    from exptrack.core.queries import format_export_params, get_export_data

    conn = get_db()
    data = get_export_data(conn, sample_experiment.id)
    text = format_export_params(data, style="json")
    parsed = _json.loads(text)
    assert parsed["lr"] == 0.01
    assert parsed["epochs"] == 10


def test_format_export_params_md_table(tmp_project, sample_experiment):
    """format_export_params(style='md-table') emits a Keep-a-Changelog-style markdown table."""
    from exptrack.core import get_db
    from exptrack.core.queries import format_export_params, get_export_data

    conn = get_db()
    data = get_export_data(conn, sample_experiment.id)
    text = format_export_params(data, style="md-table")
    lines = text.splitlines()
    assert lines[0] == "| Key | Value |"
    assert lines[1] == "| --- | --- |"
    assert "| lr | 0.01 |" in lines
    assert "| epochs | 10 |" in lines


def test_format_export_params_tsv(tmp_project, sample_experiment):
    """format_export_params(style='tsv') emits key<TAB>value for spreadsheet paste."""
    from exptrack.core import get_db
    from exptrack.core.queries import format_export_params, get_export_data

    conn = get_db()
    data = get_export_data(conn, sample_experiment.id)
    text = format_export_params(data, style="tsv")
    lines = text.splitlines()
    assert "lr\t0.01" in lines
    assert "epochs\t10" in lines


def test_format_export_params_bool_flag(tmp_project):
    """Boolean True renders as a bare --flag; False is omitted in flags style."""
    from exptrack.core.queries import format_export_params

    data = {"params": {"train": True, "debug": False, "lr": 0.1}}
    text = format_export_params(data, style="flags")
    lines = text.splitlines()
    assert "--train" in lines
    assert "--debug" not in " ".join(lines)
    assert "--lr 0.1" in lines


def test_list_experiments_batches_metrics_and_params(tmp_project):
    """list_experiments returns per-exp metrics/sparklines/params (batched path)."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import list_experiments

    for i in range(3):
        e = Experiment(script="train.py", params={"lr": 0.01 * (i + 1), "run": i})
        e.log_metric("loss", 0.5 - i * 0.1, step=1)
        e.log_metric("loss", 0.3 - i * 0.1, step=2)
        e.finish()

    conn = get_db()
    rows = list_experiments(conn, limit=50)
    assert len(rows) == 3
    for r in rows:
        assert "loss" in r["metrics"]
        assert r["metrics"]["loss"]["value"] is not None
        assert r["sparklines"]["loss"] == sorted(r["sparklines"]["loss"], reverse=True) or \
            len(r["sparklines"]["loss"]) >= 1
        assert "lr" in r["params"] and "run" in r["params"]


def test_batch_helpers_match_per_exp_helpers(tmp_project, sample_experiment):
    """The batched query helpers agree with the single-exp versions."""
    from exptrack.core import get_db
    from exptrack.core import queries as q

    conn = get_db()
    eid = sample_experiment.id
    assert q.get_latest_metrics_with_source_batch(conn, [eid])[eid] == \
        q.get_latest_metrics_with_source(conn, eid)
    assert q.get_metrics_sparkline_batch(conn, [eid])[eid] == \
        q.get_metrics_sparkline(conn, eid)
    # empty input is a safe no-op
    assert q.get_params_batch(conn, []) == {}
    assert q.get_metrics_sparkline_batch(conn, []) == {}


def test_get_experiment_detail_exposes_datasets(tmp_project):
    """A logged _dataset_manifest surfaces under the 'datasets' detail key."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import get_experiment_detail

    exp = Experiment(script="train.py", params={"lr": 0.01})
    manifest = {"data_dir": {"kind": "dir", "path": "data", "n_files": 2,
                             "size": 16, "hash": "abc", "truncated": False}}
    exp.log_params({"_dataset_manifest": manifest})
    exp.finish()

    conn = get_db()
    detail = get_experiment_detail(conn, exp.id)
    assert detail["datasets"] == manifest
    # the raw underscore param is not leaked into user params
    assert "_dataset_manifest" not in detail["params"]


# ── Malformed tags/studies resilience ────────────────────────────────────────
# A bare string or garbage in the tags/studies JSON columns used to raise out of
# list_experiments and kill the whole request — the dashboard rendered an empty
# table with no error while the stats cards still reported a run count.


def test_json_list_salvages_bare_string():
    """A bare, unquoted string becomes a one-element list rather than raising."""
    from exptrack.core.queries import _json_list

    assert _json_list('baseline') == ["baseline"]
    assert _json_list('["a", "b"]') == ["a", "b"]
    assert _json_list('"solo"') == ["solo"]


def test_json_list_handles_empty_and_bad_types():
    """Empty/None/garbage and non-list JSON all degrade to a list, never raise."""
    from exptrack.core.queries import _json_list

    assert _json_list(None) == []
    assert _json_list("") == []
    assert _json_list("[]") == []
    assert _json_list("{bad") == ["{bad"]
    assert _json_list("123") == []           # a number is not a label list
    assert _json_list('{"k": 1}') == []      # an object is not a label list
    # Non-string members are dropped rather than leaking into the UI.
    assert _json_list('["ok", 5, null]') == ["ok"]


def test_list_experiments_survives_malformed_tags(tmp_project, sample_experiment):
    """One bad row must not blank the entire experiment list."""
    from exptrack.core import get_db
    from exptrack.core.queries import list_experiments

    conn = get_db()
    conn.execute(
        "UPDATE experiments SET tags='{bad', studies='oops' WHERE id=?",
        (sample_experiment.id,),
    )
    conn.commit()

    rows = list_experiments(conn)
    assert len(rows) >= 1
    row = next(r for r in rows if r["id"] == sample_experiment.id)
    # Salvaged, not crashed — and still a list so the UI can render it.
    assert row["tags"] == ["{bad"]
    assert row["studies"] == ["oops"]


def test_get_experiment_detail_survives_malformed_tags(tmp_project, sample_experiment):
    """The detail view tolerates the same corruption as the list."""
    from exptrack.core import get_db
    from exptrack.core.queries import get_experiment_detail

    conn = get_db()
    conn.execute(
        "UPDATE experiments SET tags='nope', studies='{' WHERE id=?",
        (sample_experiment.id,),
    )
    conn.commit()

    detail = get_experiment_detail(conn, sample_experiment.id)
    assert detail is not None
    assert detail["tags"] == ["nope"]
    assert detail["studies"] == ["{"]
