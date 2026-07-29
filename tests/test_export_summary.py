"""The JSON export is a summary by default, complete only on request.

A run logging every iteration stores tens of thousands of metric points and can
register thousands of checkpoints; dumping one JSON object per point and one per
artifact made the export unreadable — the params and final numbers were buried.
The default export therefore ships one entry per metric key and a capped
artifact list plus an ``artifacts_summary`` describing the rest by type and
containing directory. ``full=True`` restores everything for round-tripping.
"""
from __future__ import annotations

# Values chosen so the summary's first/last/min/max are exact and readable.
LOSS = [1.0, 0.75, 0.25, 0.5, 0.125] * 40          # 200 points
N_CKPTS = 60


def _run_with_data(tmp_project, n_artifacts=N_CKPTS):
    from exptrack.core import Experiment

    exp = Experiment(script="train.py", params={"lr": 0.01})
    for i, v in enumerate(LOSS):
        exp.log_metric("loss", v, step=i)
    ckpt_dir = tmp_project / "outputs" / "ckpts"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n_artifacts):
        p = ckpt_dir / f"epoch{i}.pt"
        p.write_bytes(b"x")
        exp.log_artifact(str(p), label=f"ckpt{i}")
    exp.finish()
    return exp


def test_json_export_summarizes_metrics(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.queries import get_export_data

    exp = _run_with_data(tmp_project)
    data = get_export_data(get_db(), exp.id)

    assert "metrics_series" not in data, "summary export must not carry raw points"
    loss = data["metrics"]["loss"]
    assert loss["count"] == len(LOSS)
    assert loss["first"] == 1.0 and loss["first_step"] == 0
    assert loss["last"] == 0.125 and loss["last_step"] == len(LOSS) - 1
    assert loss["max"] == 1.0 and loss["max_step"] == 0
    assert loss["min"] == 0.125 and loss["min_step"] == 4


def test_json_export_caps_artifacts_and_describes_the_rest(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.queries import ARTIFACT_LIST_LIMIT, get_export_data

    exp = _run_with_data(tmp_project)
    data = get_export_data(get_db(), exp.id)

    assert len(data["artifacts"]) == ARTIFACT_LIST_LIMIT
    s = data["artifacts_summary"]
    assert s["total"] >= N_CKPTS
    assert s["listed"] == ARTIFACT_LIST_LIMIT
    assert s["omitted"] == s["total"] - ARTIFACT_LIST_LIMIT
    # The shape of what was left out: type counts and the containing directory.
    assert {"type": "model", "count": N_CKPTS} in s["by_type"]
    assert s["by_dir"][0]["count"] == N_CKPTS
    assert s["by_dir"][0]["dir"].endswith("outputs/ckpts")


def test_full_export_round_trips_everything(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.queries import get_export_data

    exp = _run_with_data(tmp_project)
    data = get_export_data(get_db(), exp.id, full=True)

    assert len(data["metrics_series"]["loss"]) == len(LOSS)
    assert data["metrics"]["loss"]["count"] == len(LOSS), "summary ships alongside"
    assert len(data["artifacts"]) == data["artifacts_summary"]["total"] >= N_CKPTS
    assert data["artifacts_summary"]["omitted"] == 0


def test_artifact_limit_zero_lists_all(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.queries import get_export_data

    exp = _run_with_data(tmp_project)
    data = get_export_data(get_db(), exp.id, artifact_limit=0)
    assert len(data["artifacts"]) >= N_CKPTS
    assert data["artifacts_summary"]["omitted"] == 0


def test_markdown_export_reads_the_summary(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.queries import format_export_markdown, get_export_data

    exp = _run_with_data(tmp_project)
    md = format_export_markdown(get_export_data(get_db(), exp.id))

    assert "## Metrics" in md
    assert "| loss | 0.125 | 0.125 | 1.0 | 200 |" in md
    assert "## Artifacts (" in md
    assert "60 model" in md
    assert "more" in md


def test_csv_export_uses_the_summary_last_value(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.queries import format_export_csv, get_export_data

    exp = _run_with_data(tmp_project)
    csv_text = format_export_csv([get_export_data(get_db(), exp.id)])
    header, row = csv_text.splitlines()[:2]
    cols = header.split(",")
    assert "metric:loss" in cols
    assert row.split(",")[cols.index("metric:loss")] == "0.125"
    assert "more" in csv_text, "capped artifact cell must say what is missing"


def test_summarize_metric_series_handles_empty_and_null(tmp_project):
    from exptrack.core.queries import summarize_metric_series

    assert summarize_metric_series([])["count"] == 0
    assert summarize_metric_series([])["last"] is None
    s = summarize_metric_series([{"value": None, "step": 1}])
    assert s["count"] == 1 and s["min"] is None
