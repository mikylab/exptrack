"""Integration tests for run adoption in `python -m exptrack <script>`.

A script written for plain `python script.py` creates its own `Experiment()`.
Run under `exptrack run`, it used to produce TWO rows for one script: the
wrapper (code snapshot, no metrics) and the script's own run (the metrics) —
the "phantom run" that then floods the vs-previous delta with None→value
changes. The wrapper is now published so a bare `Experiment()` adopts it: one
run, snapshot + metrics together, no phantom.

These run the wrapper in a subprocess (it calls sys.exit).
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_project(root: Path):
    (root / ".exptrack").mkdir()
    (root / ".exptrack" / "config.json").write_text(json.dumps({
        "db": ".exptrack/experiments.db",
        "outputs_dir": "outputs",
    }))


def _run(root: Path, script_name: str):
    env = {**os.environ}
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "exptrack", script_name],
        cwd=str(root), capture_output=True, text=True, env=env,
    )


def _experiments(root: Path):
    conn = sqlite3.connect(str(root / ".exptrack" / "experiments.db"))
    conn.row_factory = sqlite3.Row
    try:
        out = []
        for e in conn.execute(
            "SELECT id, name, status, deleted_at FROM experiments ORDER BY created_at"
        ):
            n = conn.execute(
                "SELECT COUNT(*) n FROM metrics WHERE exp_id=?", (e["id"],)
            ).fetchone()["n"]
            out.append({"id": e["id"], "name": e["name"],
                        "status": e["status"], "metrics": n,
                        "trashed": e["deleted_at"] is not None})
        return out
    finally:
        conn.close()


_SELF_TRACKING = (
    "from exptrack.core import Experiment\n"
    "with Experiment() as exp:\n"
    "    exp.log_param('lr', 0.01)\n"
    "    exp.log_metric('acc', 0.87)\n"
    "    exp.log_metric('loss', 0.13)\n"
)


def test_self_tracking_script_adopts_wrapper(tmp_path):
    _make_project(tmp_path)
    (tmp_path / "mt.py").write_text(_SELF_TRACKING)
    r = _run(tmp_path, "mt.py")
    assert r.returncode == 0
    exps = _experiments(tmp_path)
    # Exactly one run — no metrics-less phantom wrapper.
    assert len(exps) == 1, exps
    assert exps[0]["status"] == "done"
    assert exps[0]["metrics"] == 2  # metrics landed on the adopted run


def test_two_identical_runs_no_none_flood(tmp_path):
    _make_project(tmp_path)
    (tmp_path / "mt.py").write_text(_SELF_TRACKING)
    _run(tmp_path, "mt.py")
    r2 = _run(tmp_path, "mt.py")
    assert r2.returncode == 0
    # Two runs total (one per invocation), each with its metrics.
    exps = _experiments(tmp_path)
    assert len(exps) == 2, exps
    assert all(e["metrics"] == 2 for e in exps)
    # Identical runs → the finish delta reports no bogus None→value metric moves.
    assert "None→" not in r2.stderr
    assert "acc None" not in r2.stderr and "loss None" not in r2.stderr


def test_cooperative_script_still_single_run(tmp_path):
    # A script that uses the injected __exptrack__ global (never constructs its
    # own Experiment) is unchanged: one run, metrics on it.
    _make_project(tmp_path)
    (tmp_path / "coop.py").write_text(
        "exp = globals().get('__exptrack__')\n"
        "exp.log_metric('acc', 0.9)\n"
    )
    r = _run(tmp_path, "coop.py")
    assert r.returncode == 0
    exps = _experiments(tmp_path)
    assert len(exps) == 1 and exps[0]["metrics"] == 1


def test_adopted_run_failure_no_double_finish(tmp_path):
    # A self-tracking script that raises inside its `with` block: the adopted
    # run is marked failed once (the with-block's __exit__), and the wrapper's
    # own except handler must not finish it a second time (which would raise).
    _make_project(tmp_path)
    (tmp_path / "boom.py").write_text(
        "from exptrack.core import Experiment\n"
        "with Experiment() as exp:\n"
        "    exp.log_metric('acc', 0.9)\n"
        "    raise ValueError('kaboom')\n"
    )
    r = _run(tmp_path, "boom.py")
    assert r.returncode == 1
    assert "kaboom" in r.stderr
    # No "Cannot finish twice" RuntimeError leaked from the wrapper.
    assert "already finished" not in r.stderr
    assert "Cannot finish twice" not in r.stderr
    exps = _experiments(tmp_path)
    assert len(exps) == 1 and exps[0]["status"] == "failed"


_SWEEP = (
    "from exptrack.core import Experiment\n"
    "for lr in (0.1, 0.2, 0.3):\n"
    "    with Experiment(name=f'run_lr{lr}', params={'lr': lr}) as e:\n"
    "        e.log_metric('acc', lr * 2)\n"
)


def test_sweep_with_explicit_args_not_merged(tmp_path):
    # A script that constructs Experiments with explicit identity (a sweep) is
    # never silently merged into the wrapper — each gets its own run with its
    # own name/params/metrics intact.
    _make_project(tmp_path)
    (tmp_path / "sweep.py").write_text(_SWEEP)
    r = _run(tmp_path, "sweep.py")
    assert r.returncode == 0
    live = [e for e in _experiments(tmp_path) if not e["trashed"]]
    names = {e["name"] for e in live}
    # The three explicitly-named runs all exist, kept their identity, and are
    # not trashed (only the phantom wrapper is).
    assert {"run_lr0.1", "run_lr0.2", "run_lr0.3"} <= names
    for e in live:
        if e["name"].startswith("run_lr"):
            assert e["metrics"] == 1


def test_sweep_phantom_wrapper_trashed(tmp_path):
    # The metrics-less wrapper left by an explicit-args sweep is a phantom row.
    # It's moved to Trash (soft-deleted) so it doesn't clutter the list or flood
    # comparisons, while the three real sweep runs stay live.
    _make_project(tmp_path)
    (tmp_path / "sweep.py").write_text(_SWEEP)
    r = _run(tmp_path, "sweep.py")
    assert r.returncode == 0
    exps = _experiments(tmp_path)
    trashed = [e for e in exps if e["trashed"]]
    # Exactly one trashed row — the wrapper — and it has no metrics.
    assert len(trashed) == 1, exps
    assert trashed[0]["metrics"] == 0
    assert not trashed[0]["name"].startswith("run_lr")
    # The three sweep runs are all still live.
    live = [e for e in exps if not e["trashed"]]
    assert sum(1 for e in live if e["name"].startswith("run_lr")) == 3
