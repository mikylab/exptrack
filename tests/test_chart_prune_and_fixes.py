"""2.1.0: prune preview points, short-id "What changed", UTF-8 exports, and the
overwrite warning — each of the bugs a sweep walkthrough found."""
from __future__ import annotations

import json
import subprocess
import sys

from exptrack.core import Experiment
from exptrack.core.db import get_db


def _run(script, params, n=0, key="loss"):
    exp = Experiment(script=script, params=params)
    for i in range(n):
        exp.log_metric(key, 1.0 / (i + 1), step=i)
    exp.finish()
    return exp.id


# ── Prune from the chart ─────────────────────────────────────────────────────

def test_prune_preview_returns_the_points_it_would_remove(tmp_project):
    """The Charts tab draws the kept points as the line and the removed ones as
    dots, so the dry-run must hand back exactly the split it will delete."""
    from exptrack.dashboard.routes.write_routes.admin import api_prune_metrics
    eid = _run("train.py", {"lr": 0.1}, n=200)
    pre = api_prune_metrics(get_db(), {"ids": [eid], "keep_every": 10,
                                       "dry_run": True, "include_points": True})
    s = pre["series"]["loss"]
    assert s["kept_n"] + s["removed_n"] == 200
    assert s["removed_n"] == pre["points"]
    kept_steps = {x for x, _ in s["kept"]}
    assert {0, 199} <= kept_steps  # first and last always survive
    assert not kept_steps & {x for x, _ in s["removed"]}

    res = api_prune_metrics(get_db(), {"ids": [eid], "keep_every": 10,
                                       "preview_token": pre["preview_token"]})
    assert res["deleted"] == pre["points"]
    left = get_db().execute("SELECT COUNT(*) FROM metrics WHERE exp_id=?", (eid,)).fetchone()[0]
    assert left == s["kept_n"]


def test_prune_preview_points_only_for_one_run(tmp_project):
    """A project-wide preview's point set is the whole table — never sent."""
    from exptrack.dashboard.routes.write_routes.admin import api_prune_metrics
    _run("train.py", {"lr": 0.1}, n=50)
    _run("train.py", {"lr": 0.2}, n=50)
    pre = api_prune_metrics(get_db(), {"keep_every": 10, "dry_run": True,
                                       "include_points": True})
    assert "series" not in pre


def test_prune_accepts_a_short_id(tmp_project):
    """A `#run=<prefix>` link reaches the chart with a short id; the selection
    matched ids exactly and reported nothing to prune."""
    from exptrack.dashboard.routes.write_routes.admin import api_prune_metrics
    eid = _run("train.py", {"lr": 0.1}, n=100)
    pre = api_prune_metrics(get_db(), {"ids": [eid[:8]], "keep_every": 10,
                                       "dry_run": True, "include_points": True})
    assert pre["points"] > 0 and "loss" in pre["series"]


# ── "What changed" for a run opened by a short id ────────────────────────────

def test_prev_by_script_resolves_a_prefix(tmp_project):
    from exptrack.dashboard.routes.read_routes import api_prev_by_script
    a = _run("train.py", {"lr": 0.1})
    b = _run("train.py", {"lr": 0.2})
    assert api_prev_by_script(get_db(), b[:8]).get("id") == a
    assert api_prev_by_script(get_db(), b).get("id") == a


# ── Exports written to a file are UTF-8 ──────────────────────────────────────

def _cli(tmp_project, *args):
    """The CLI with the platform's own default for a redirected stdout — on a
    Windows machine that is the ANSI codepage, which is the case being fixed.
    PYTHONIOENCODING is dropped: when set, it is the user's choice and wins."""
    import os
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    return subprocess.run([sys.executable, "-m", "exptrack.cli.main", *args],
                          cwd=str(tmp_project), capture_output=True, env=env)


def test_redirected_export_is_utf8_whatever_the_console(tmp_project):
    """`exptrack export --format csv > runs.csv` on a cp1252 console wrote 0x97
    for an em dash, and pandas.read_csv refused the file."""
    eid = _run("train.py", {"lr": 0.1})
    conn = get_db()
    conn.execute("UPDATE experiments SET notes=? WHERE id=?", ("plateaus — try cosine", eid))
    conn.commit()
    r = _cli(tmp_project, "export", "--all", "--format", "csv")
    assert r.returncode == 0, r.stderr
    assert "plateaus — try cosine" in r.stdout.decode("utf-8")


def test_export_output_flag_writes_utf8(tmp_project):
    eid = _run("train.py", {"lr": 0.1})
    conn = get_db()
    conn.execute("UPDATE experiments SET notes=? WHERE id=?", ("café — ok", eid))
    conn.commit()
    out = tmp_project / "runs.md"
    r = _cli(tmp_project, "export", "--all", "--format", "markdown", "-o", str(out))
    assert r.returncode == 0, r.stderr
    assert "café — ok" in out.read_text(encoding="utf-8")


# ── A run that overwrites another run's output says so ───────────────────────

def test_overwriting_another_runs_artifact_warns(tmp_project, capsys):
    """A fixed `drift.png` path made every run in a sweep point at the last
    run's plot, found only when Compare showed 39 copies of one image."""
    f = tmp_project / "drift.png"
    a = Experiment(script="train.py", params={"seed": 1})
    f.write_bytes(b"first")
    a.log_artifact(f)
    a.finish()
    capsys.readouterr()
    b = Experiment(script="train.py", params={"seed": 2})
    f.write_bytes(b"second")
    b.log_artifact(f)
    b.finish()
    err = capsys.readouterr().err
    assert "drift.png overwrote the copy run " + a.id[:8] in err


def test_same_bytes_at_a_shared_path_is_not_an_overwrite(tmp_project, capsys):
    """A shared input (a dataset, a cache) logged by several runs is fine."""
    f = tmp_project / "vocab.json"
    f.write_text(json.dumps({"a": 1}))
    for seed in (1, 2):
        e = Experiment(script="train.py", params={"seed": seed})
        e.log_artifact(f)
        e.finish()
    assert "overwrote" not in capsys.readouterr().err


def test_prune_can_cover_one_metric(tmp_project):
    """Prune applies to the chart chosen, not every series of the run."""
    from exptrack.dashboard.routes.write_routes.admin import api_prune_metrics
    exp = Experiment(script="train.py", params={"lr": 0.1})
    for i in range(100):
        exp.log_metrics({"train/loss": 1.0 / (i + 1), "val/loss": 2.0 / (i + 1)}, step=i)
    exp.finish()
    pre = api_prune_metrics(get_db(), {"ids": [exp.id], "keys": ["val/loss"], "keep_every": 25,
                                       "dry_run": True, "include_points": True})
    assert set(pre["series"]) == {"val/loss"}
    api_prune_metrics(get_db(), {"ids": [exp.id], "keys": ["val/loss"], "keep_every": 25,
                                 "preview_token": pre["preview_token"]})
    counts = dict(get_db().execute(
        "SELECT key, COUNT(*) FROM metrics WHERE exp_id=? GROUP BY key", (exp.id,)).fetchall())
    assert counts["train/loss"] == 100
    assert counts["val/loss"] < 100


def test_scoped_preview_counts_its_own_points(tmp_project):
    """The list's Prune states "remove X of Y" for the selected runs, not the
    whole table's point count."""
    from exptrack.dashboard.routes.write_routes.admin import api_prune_metrics
    a = _run("train.py", {"lr": 0.1}, n=100)
    _run("train.py", {"lr": 0.2}, n=300)
    pre = api_prune_metrics(get_db(), {"ids": [a], "keep_every": 10, "dry_run": True})
    assert pre["scope_points"] == 100
    assert pre["total_points"] == 400
