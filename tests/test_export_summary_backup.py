"""A multi-run export opens with a summary of the set; Settings can export every
run and back up the database."""
from __future__ import annotations

import sqlite3
import urllib.error
import urllib.request

from exptrack.core import Experiment
from exptrack.core.db import get_db


def _run(params, loss, notes=""):
    exp = Experiment(script="train.py", params=params)
    exp.log_metric("val/loss", loss, step=1)
    exp.log_metric("val/acc", 1 - loss, step=1)
    if notes:
        exp.add_note(notes)
    exp.finish()
    return exp.id


def _sweep():
    return [_run({"lr": 0.1, "seed": 0}, 0.5),
            _run({"lr": 0.01, "seed": 0}, 0.2, notes="best so far"),
            _run({"lr": 0.001, "seed": 0}, 0.4)]


def test_multi_run_markdown_export_leads_with_a_summary(tmp_project):
    from exptrack.dashboard.routes.write_routes.bulk import api_bulk_export
    ids = _sweep()
    md = api_bulk_export(get_db(), {"ids": ids, "format": "markdown"})["content"]
    head = md.split("\n---\n")[0]
    assert head.startswith("# Summary: 3 runs")
    assert "lr (3 values)" in head and "seed=0" in head   # varied / held constant
    assert "## Top 3 by" in head
    assert "## Metrics across runs" in head
    assert "best so far" in head                            # the notes are listed
    # Each run's own report still follows.
    assert md.count("## Parameters") == 3


def test_summary_top_run_is_the_matrix_best_row(tmp_project):
    """No ranking surface may disagree with the Parameter Matrix."""
    from exptrack.core.export_render import build_runs_summary
    from exptrack.core.param_study import build_matrix
    from exptrack.core.queries import get_batch_export_data
    ids = _sweep()
    conn = get_db()
    s = build_runs_summary(conn, get_batch_export_data(conn, exp_ids=ids))
    best = build_matrix(conn, ids)["best_row_id"]
    assert best[:8] in s["top"][0][1]
    row = next(m for m in s["metrics"] if m[0] == s["metric"])
    assert best[:8] in row[-1]


def test_one_run_export_has_no_summary(tmp_project):
    from exptrack.dashboard.routes.write_routes.bulk import api_bulk_export
    eid = _run({"lr": 0.1}, 0.5)
    md = api_bulk_export(get_db(), {"ids": [eid], "format": "markdown"})["content"]
    assert "# Summary" not in md


def test_export_all_takes_every_run_server_side(tmp_project):
    """The dashboard's list is paginated, so "all" is chosen by the server."""
    from exptrack.dashboard.routes.write_routes.bulk import api_bulk_export
    _sweep()
    csv = api_bulk_export(get_db(), {"all": True, "format": "csv"})["content"]
    assert len(csv.strip().splitlines()) == 4   # header + 3 runs
    md = api_bulk_export(get_db(), {"all": True, "format": "markdown"})["content"]
    assert md.startswith("# Summary: 3 runs")


def test_backup_db_writes_a_restorable_copy(tmp_project):
    from exptrack.core.db import backups_dir
    from exptrack.dashboard.routes.write_routes.admin import api_backup_db
    ids = _sweep()
    a = api_backup_db(get_db())
    b = api_backup_db(get_db())
    assert a["ok"] and b["ok"] and a["name"] != b["name"]   # same second, no overwrite
    copy = sqlite3.connect(str(backups_dir() / a["name"]))
    n = copy.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    copy.close()
    assert n == len(ids)


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_backup_download_serves_only_backup_files(live_server_with_token):
    from exptrack.dashboard.routes.write_routes.admin import api_backup_db
    base, token = live_server_with_token
    _sweep()
    name = api_backup_db(get_db())["name"]
    status, headers, body = _get(f"{base}/api/backup-file?name={name}", token)
    assert status == 200 and body.startswith(b"SQLite format 3")
    assert "attachment" in headers["Content-Disposition"]
    # Nothing but a backup-shaped name: not the token, not a path.
    for bad in ("dashboard_token", "../dashboard_token", "..%2Fexperiments.db", "x.db"):
        assert _get(f"{base}/api/backup-file?name={bad}", token)[0] == 400, bad


def test_summary_only_leaves_the_run_reports_out(tmp_project):
    """An 87-run report printed to 396 pages; the summary alone is a few."""
    from exptrack.dashboard.routes.write_routes.bulk import api_bulk_export
    ids = _sweep()
    md = api_bulk_export(get_db(), {"ids": ids, "format": "markdown",
                                    "summary_only": True})["content"]
    assert md.startswith("# Summary: 3 runs") and "## Parameters" not in md
    assert "Summary only" in md


def test_csv_has_best_min_max_and_relative_paths(tmp_project):
    import csv
    import io

    from exptrack.dashboard.routes.write_routes.bulk import api_bulk_export
    _sweep()
    rows = list(csv.DictReader(io.StringIO(
        api_bulk_export(get_db(), {"all": True, "format": "csv"})["content"])))
    r = rows[0]
    for col in ("metric:val/loss", "metric:val/loss:best", "metric:val/loss:min",
                "metric:val/loss:max", "project_root"):
        assert col in r, col
    # val/loss is lower-is-better, so its best is its min.
    assert r["metric:val/loss:best"] == r["metric:val/loss:min"]
    assert r["metric:val/acc:best"] == r["metric:val/acc:max"]
    assert r["project_root"] and not r["script"].startswith(r["project_root"])


def test_single_value_metrics_print_one_column(tmp_project):
    """A run whose every metric is one value (an evaluation, a results.json)
    printed it three times as last/min/max; it is one Value column now, and
    the table sits two-up beside Parameters in the printed report."""
    from exptrack.core.export_render import render_runs
    from exptrack.core.queries import get_batch_export_data
    ids = _sweep()
    batch = get_batch_export_data(get_db(), exp_ids=ids)
    md = render_runs(batch[:1], "markdown")
    assert "| Metric | Value |" in md and "| Points |" not in md
    page = render_runs(batch, "html")
    i = page.index("<h2>Metrics</h2>")
    j = page.rfind('<div class="run-cols">', 0, i)
    # Metrics is inside a still-open two-column group.
    assert j >= 0 and page[j:i].count("<div") > page[j:i].count("</div>")
