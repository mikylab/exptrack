"""Tests for the 1.4 feature theme: different models are first-class.

Running and comparing *different models* — from scripts and from notebooks —
was the journey 1.2 and 1.3 built toward, and the places it broke down were
mostly places where two runs of different code could not be lined up at all:
they named their metrics differently, nothing could filter by model, and the
ranking layer had no terminal surface.
"""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from conftest import capture as _capture


def _write_config(tmp_project, **keys):
    from exptrack import config as cfg
    path = tmp_project / ".exptrack" / "config.json"
    existing = json.loads(path.read_text()) if path.is_file() else {}
    existing.update(keys)
    path.write_text(json.dumps(existing))
    cfg.reload()


# ── Metric-key aliasing ──────────────────────────────────────────────────────

def test_two_models_naming_one_metric_differently_compare_on_one_row(tmp_project):
    """Model A logs `val_acc`, model B logs `accuracy`. Matched by string they
    shared no metric at all: the compare table was two rows of `--` and
    consensus ranking excluded one model wholesale."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import diff_runs, get_latest_metrics

    _write_config(tmp_project, metric_aliases={"val_acc": ["accuracy"]})

    a = Experiment(script="model_a.py"); a.log_metric("val_acc", 0.80); a.finish()
    b = Experiment(script="model_b.py"); b.log_metric("accuracy", 0.86); b.finish()

    conn = get_db()
    assert get_latest_metrics(conn, a.id) == {"val_acc": 0.80}
    assert get_latest_metrics(conn, b.id) == {"val_acc": 0.86}

    moved = diff_runs(conn, a.id, b.id)["metric_changes"]
    assert [c["key"] for c in moved] == ["val_acc"]


def test_aliasing_is_display_level_and_never_rewrites_storage(tmp_project):
    """A project that removes an alias must get its original keys back."""
    from exptrack.core import Experiment, get_db

    _write_config(tmp_project, metric_aliases={"val_acc": ["accuracy"]})
    b = Experiment(script="model_b.py"); b.log_metric("accuracy", 0.86); b.finish()

    row = get_db().execute(
        "SELECT key FROM metrics WHERE exp_id=?", (b.id,)).fetchone()
    assert row["key"] == "accuracy"


def test_an_unusable_alias_map_degrades_to_no_aliasing(tmp_project):
    """A hand-edited config must never be the reason a comparison stops
    working."""
    from exptrack.core.metric_alias import alias_map, canonical_key

    assert alias_map({"metric_aliases": "nonsense"}) == {}
    assert canonical_key("val_acc", {}) == "val_acc"


def test_alias_matching_normalizes_case_separators_and_path_prefix():
    from exptrack.core.metric_alias import alias_map, canonical_key

    amap = alias_map({"metric_aliases": {"val_acc": ["Val Accuracy", "eval/acc"]}})
    assert canonical_key("val accuracy", amap) == "val_acc"
    assert canonical_key("train/acc", amap) == "val_acc"      # base name matches
    assert canonical_key("f1", amap) == "f1"                  # unclaimed, untouched


def test_a_merge_is_reported_not_silent(tmp_project):
    """A merge the user cannot see is indistinguishable from a dropped metric."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import get_multi_compare

    _write_config(tmp_project, metric_aliases={"val_acc": ["accuracy"]})
    a = Experiment(script="a.py")
    a.log_metric("val_acc", 0.8)
    a.log_metric("accuracy", 0.9)
    a.finish()

    row = get_multi_compare(get_db(), [a.id, a.id])[0]
    assert "val_acc" in row["merged_metric_keys"]
    assert set(row["merged_metric_keys"]["val_acc"]) == {"val_acc", "accuracy"}


# ── Script identity as a first-class filter ──────────────────────────────────

def test_ls_can_filter_to_one_model(tmp_project):
    from exptrack.cli.inspect_cmds import cmd_ls
    from exptrack.core import Experiment

    Experiment(script="model_a.py").finish()
    Experiment(script="model_b.py").finish()

    out, _ = _capture(cmd_ls, SimpleNamespace(n=10, tag=None, status=None, study=None,
                                           script="model_a", json_output=False))
    assert "model_a" in out and "model_b" not in out


def test_the_script_filter_escapes_wildcards(tmp_project):
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import list_experiments

    Experiment(script="model_a.py").finish()
    assert list_experiments(get_db(), script="%") == []


# ── The CLI ranking surface ──────────────────────────────────────────────────

def test_top_ranks_by_the_primary_metric_and_names_it(tmp_project):
    """The whole ranking layer was dashboard-only, so the SLURM/SSH audience —
    most likely to have a hundred runs and no browser — could not ask which run
    won."""
    from exptrack.cli.inspect_cmds import cmd_top
    from exptrack.core import Experiment

    for script, acc in (("model_a.py", 0.80), ("model_a.py", 0.86), ("model_b.py", 0.91)):
        e = Experiment(script=script)
        e.log_metric("val_acc", acc)
        e.finish()

    out, _ = _capture(cmd_top, SimpleNamespace(limit=10, n=100, script="", study="",
                                            best=False, include_running=False,
                                            exclude_failed=False))
    assert "val_acc" in out                       # the metric is stated
    lines = [ln for ln in out.splitlines() if ln.strip().startswith(("1.", "2.", "3."))]
    assert lines and "0.91" in lines[0]           # best first


def test_top_counts_unscored_runs_separately(tmp_project):
    """"Six of your twenty runs never logged the metric" is a fact about the
    search, not a rendering detail."""
    from exptrack.cli.inspect_cmds import cmd_top
    from exptrack.core import Experiment

    e = Experiment(script="a.py"); e.log_metric("val_acc", 0.5); e.finish()
    Experiment(script="a.py").finish()            # logs nothing

    out, _ = _capture(cmd_top, SimpleNamespace(limit=10, n=100, script="", study="",
                                            best=False, include_running=False,
                                            exclude_failed=False))
    assert "never logged" in out


def test_compare_handles_more_than_two_runs(tmp_project):
    """Three or more runs is the shape a bake-off actually has; the CLI could
    only ever compare a pair."""
    from exptrack.cli.inspect_cmds import cmd_compare
    from exptrack.core import Experiment

    ids = []
    for script, lr in (("model_a.py", 0.1), ("model_a.py", 0.2), ("model_b.py", 0.1)):
        e = Experiment(script=script, params={"lr": lr})
        e.log_metric("val_acc", lr + 0.7)
        e.finish()
        ids.append(e.id)

    out, _ = _capture(cmd_compare, SimpleNamespace(id1=ids[0], id2=ids[1], ids=ids[2:],
                                                seq1=None, seq2=None))
    assert "lr" in out and "val_acc" in out
    # The script is the first thing that differs in a bake-off and is not a
    # param, so it must appear as its own row.
    assert "model_b.py" in out


# ── Bare `python train.py` ───────────────────────────────────────────────────

def test_a_bare_experiment_arms_the_capture_patches(tmp_project, monkeypatch):
    """The patches installed only under `exptrack run` and in notebooks, so a
    plain `python train.py` captured no params at all — and moving a script
    between launchers made every param read as a change."""
    import argparse

    from exptrack.core import Experiment

    script = tmp_project / "train.py"
    script.write_text("x = 1\n")
    monkeypatch.setattr(sys, "argv", [str(script), "--lr", "0.33"])

    exp = Experiment(script=str(script))
    p = argparse.ArgumentParser()
    p.add_argument("--lr", type=float, default=0.01)
    p.parse_args()

    assert exp._params.get("lr") == 0.33
    exp.finish()


def test_argv_capture_ignores_a_host_processes_command_line(tmp_project,
                                                            monkeypatch):
    """sys.argv is process-global: a run created inside a test runner or a REPL
    must not record that host's flags as its hyperparameters."""
    from exptrack.core import Experiment

    monkeypatch.setattr(sys, "argv", ["/usr/bin/pytest", "-x", "--maxfail", "2"])
    exp = Experiment(script="train.py")
    assert "maxfail" not in exp._params
    exp.finish()


# ── Session branches carry their numbers ─────────────────────────────────────

def test_the_session_tree_reports_metrics_per_branch(tmp_project):
    """The numbers were tagged with session_node_id at write time but nothing
    read them back, so comparing val_acc across branches meant materializing
    both branches first."""
    from exptrack.core import Experiment
    from exptrack.sessions import SessionManager, set_current_session
    from exptrack.sessions.manager import build_tree

    sm = SessionManager()
    sm.start("explore", "nb.ipynb")
    set_current_session(sm)
    sm.checkpoint("base")

    run = Experiment(script="nb.ipynb")
    node = sm.branch("A")
    sm.autolink_run(run.id)
    run.log_metric("val_acc", 0.77)
    run.finish()

    tree = build_tree(sm.session_id)

    def _find(n):
        if n["id"] == node:
            return n
        for c in n["children"]:
            got = _find(c)
            if got:
                return got
        return None

    found = _find(tree["root"])
    assert found and found["metrics"].get("val_acc") == 0.77


# ── The rest of the set-description vocabulary ───────────────────────────────

def test_ls_filters_by_param_using_normalized_equality(tmp_project):
    """`--param lr=0.01` must find a run whose value was captured as a float —
    the same equality "what varies" and duplicate detection use, not a third
    one that disagrees with both."""
    from exptrack.cli.inspect_cmds import _parse_param_filters
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import list_experiments

    a = Experiment(script="a.py", params={"lr": 0.01}); a.finish()
    b = Experiment(script="b.py", params={"lr": 0.5}); b.finish()

    got = list_experiments(get_db(), limit=10,
                           param_filters=_parse_param_filters(["lr=0.01"]))
    assert [r["id"] for r in got] == [a.id]


def test_ls_since_accepts_relative_and_absolute_forms(tmp_project):
    from exptrack.cli.inspect_cmds import _since_iso

    assert _since_iso("") == ""
    assert _since_iso("7d")            # a timestamp, not an error
    assert _since_iso("24h")
    assert _since_iso("2026-08-01").startswith("2026-08-01")


def test_vs_reference_measures_every_run_against_the_pinned_one(tmp_project):
    """`reference` pins the run everything is measured against, but the only way
    to read that comparison was one run at a time on the dashboard."""
    from exptrack.cli.inspect_cmds import cmd_vs_reference
    from exptrack.core import Experiment, get_db
    from exptrack.core.reference import set_reference

    base = Experiment(script="model_a.py"); base.log_metric("val_acc", 0.80); base.finish()
    other = Experiment(script="model_b.py"); other.log_metric("val_acc", 0.91); other.finish()
    set_reference(get_db(), base.id)

    out, _ = _capture(cmd_vs_reference, SimpleNamespace(n=50, script="", study=""))
    assert base.name in out                    # the reference is named
    assert "+0.11" in out                      # and the delta is the movement
    assert other.name[:32] in out


def test_vs_reference_refuses_rather_than_inventing_a_baseline(tmp_project):
    """A baseline that appears from somewhere is the failure the whole feature
    exists to avoid, so with nothing pinned this must not fall back."""
    import pytest

    from exptrack.cli.inspect_cmds import cmd_vs_reference
    from exptrack.core import Experiment

    Experiment(script="a.py").finish()
    with pytest.raises(SystemExit) as e:
        _capture(cmd_vs_reference, SimpleNamespace(n=50, script="", study=""))
    assert e.value.code != 0


def test_effects_can_group_by_script(tmp_project):
    """A mixed-script set fuses both models' param namespaces; colouring the
    points by model is what makes that readable."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.param_study import SCRIPT_GROUP, parameter_effects

    ids = []
    for script, lr in (("model_a.py", 0.1), ("model_b.py", 0.2)):
        e = Experiment(script=script, params={"lr": lr})
        e.log_metric("val_acc", lr + 0.7)
        e.finish()
        ids.append(e.id)

    out = parameter_effects(get_db(), ids, group_by=SCRIPT_GROUP)
    assert out["group_by"] == SCRIPT_GROUP
    groups = {pt["group"] for p in out["params"] for pt in p["points"]}
    assert groups == {"model_a.py", "model_b.py"}


def test_a_run_pinned_at_two_levels_shows_both(tmp_project):
    """A single-label map made the later write win, so one setting looked
    unset."""
    from exptrack.core import Experiment, get_db
    from exptrack.core.reference import configured_ids, set_reference

    exp = Experiment(script="a.py"); exp.finish()
    conn = get_db()
    set_reference(conn, exp.id)
    set_reference(conn, exp.id, study="sweep-a")

    levels = configured_ids()[exp.id]
    assert set(levels) == {"project", "sweep-a"}


def test_a_resumed_run_accumulates_its_wall_time(tmp_project):
    """duration_s means "time this run was actually running, summed across
    resumes" — not elapsed-since-creation, which counts the night between two
    sessions as compute time."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")
    exp.finish()
    conn = get_db()
    conn.execute("UPDATE experiments SET duration_s=100.0 WHERE id=?", (exp.id,))
    conn.commit()

    again = Experiment.resume(exp.id)
    again.finish()

    row = get_db().execute("SELECT duration_s FROM experiments WHERE id=?",
                           (exp.id,)).fetchone()
    assert row["duration_s"] >= 100.0


def test_tensorboard_scalars_logged_before_the_run_are_not_dropped(tmp_project):
    """The savefig patch buffers pre-experiment figures and flushes them; the
    TensorBoard patch just dropped them, so the same "log first, start tracking
    a moment later" shape lost metrics but kept plots."""
    from exptrack.capture import tensorboard_patch as tb
    from exptrack.capture.notebook_hooks import _nb_state
    from exptrack.core import Experiment, get_db
    tb._pending_metrics.clear()
    tb._active_exp = None
    _nb_state["exp"] = None          # no notebook run to fall back onto either
    tb._mirror_scalar("loss", 0.5, 1)
    assert tb._pending_metrics                    # buffered, not dropped

    exp = Experiment(script="train.py")
    tb.patch_tensorboard(exp)                     # retarget flushes
    exp.finish()

    row = get_db().execute(
        "SELECT value FROM metrics WHERE exp_id=? AND key='loss'",
        (exp.id,)).fetchone()
    assert row and row["value"] == 0.5
    tb._active_exp = None


def test_session_studies_are_keyed_by_notebook_too(tmp_project):
    """Two notebooks each running a session called "explore" — the obvious name,
    and the one the docs use — merged their runs into one study."""
    from exptrack.core import get_db
    from exptrack.sessions import SessionManager
    from exptrack.sessions._shared import _session_study_name

    a = SessionManager(); a.start("explore", "one.ipynb")
    b = SessionManager(); b.start("explore", "two.ipynb")

    conn = get_db()
    assert _session_study_name(conn, a.session_id) != _session_study_name(conn, b.session_id)


def test_metric_series_are_aliased_like_every_other_metric_read(tmp_project):
    """The Compare table merged `accuracy` into `val_acc` while the training-curve
    overlay directly beneath it charted the raw key, so the aliased model's curve
    was silently missing from the one chart built to compare models."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_metrics_series

    _write_config(tmp_project, metric_aliases={"val_acc": ["accuracy"]})
    b = Experiment(script="model_b.py")
    for s in range(4):
        b.log_metric("accuracy", 0.8 + s / 100, step=s)
    b.finish()

    series = get_metrics_series(get_db(), b.id)
    assert "val_acc" in series, "the aliased spelling never reached the chart"
    assert "accuracy" not in series
    assert len(series["val_acc"]) == 4


def test_a_run_logging_both_spellings_keeps_both_series(tmp_project):
    """Two spellings on the *same* run are two real series. Folding them would
    lose points or interleave two curves into a zigzag, so the rename is skipped
    and the run keeps its original keys."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.queries import get_metrics_series

    _write_config(tmp_project, metric_aliases={"val_acc": ["accuracy"]})
    e = Experiment(script="both.py")
    for s in range(3):
        e.log_metric("val_acc", 0.9, step=s)
        e.log_metric("accuracy", 0.5, step=s)
    e.finish()

    series = get_metrics_series(get_db(), e.id)
    assert set(series) == {"val_acc", "accuracy"}
    assert len(series["val_acc"]) == 3 and len(series["accuracy"]) == 3


def test_aliasing_reaches_the_ranking_surfaces_not_just_compare(tmp_project):
    """`list_experiments` feeds the table, the primary-metric heuristic, the
    leaderboard and the effect summaries. While it returned raw keys, two models
    resolved *different* primary metrics — `loss` for one, `accuracy` for the
    other — so the effect summaries reported one model's runs as off-metric and
    scored none of them, on a project that had said the two are the same metric."""
    from exptrack.core import Experiment
    from exptrack.core import primary_metric as pm
    from exptrack.core.db import get_db
    from exptrack.core.queries import list_experiments

    _write_config(tmp_project, metric_aliases={"val_acc": ["accuracy"]})
    a = Experiment(script="model_a.py"); a.log_metric("loss", 0.2); a.log_metric("val_acc", 0.9); a.finish()
    b = Experiment(script="model_b.py"); b.log_metric("loss", 0.3); b.log_metric("accuracy", 0.8); b.finish()

    conn = get_db()
    rows = list_experiments(conn, limit=10)
    for r in rows:
        assert "accuracy" not in (r.get("metrics") or {})
        assert "val_acc" in (r.get("metrics") or {})
    primaries = pm.primary_metric_batch(conn, rows)
    keys = {(primaries.get(r["id"]) or {}).get("key") for r in rows}
    assert len(keys) == 1, f"two models resolved different primary metrics: {keys}"


def test_the_matrix_never_prints_one_metric_under_another_metrics_heading(tmp_project):
    """The matrix heads its score column with the *set's* metric but fills each
    cell from that run's own primary. While the key scan returned raw names, two
    aliased models resolved different primaries, so a model's `accuracy` (0.90)
    was printed under a column headed LOSS beside another model's real loss
    (0.09) — and the ranking mixed two different measurements."""
    from exptrack.core import Experiment
    from exptrack.core.db import get_db
    from exptrack.core.param_study import build_matrix

    _write_config(tmp_project, metric_aliases={"val_acc": ["accuracy"]})
    ids = []
    for script, acc_key in (("model_a.py", "val_acc"), ("model_b.py", "accuracy")):
        e = Experiment(script=script)
        e.log_metric("loss", 0.09 if script == "model_a.py" else 0.11)
        e.log_metric(acc_key, 0.90)
        e.finish()
        ids.append(e.id)

    m = build_matrix(get_db(), ids)
    assert m["metric"]["key"] == "loss"
    for row in m["rows"]:
        assert row["primary"]["key"] == "loss", "a row scored on a different metric"
        assert row["primary"]["final"] < 0.5, "an accuracy value landed in the loss column"


def test_a_configured_metric_is_found_under_the_spelling_the_run_logged(tmp_project):
    """Resolution canonicalizes the name; the rows still carry what was logged.
    Querying the canonical name alone found nothing on exactly the runs the
    alias exists to bring in, so their metric read as missing."""
    from exptrack.core import Experiment
    from exptrack.core import primary_metric as pm
    from exptrack.core.db import get_db

    _write_config(tmp_project, metric_aliases={"val_acc": ["accuracy", "val/acc"]},
                  primary_metric="val_acc")
    e = Experiment(script="model_b.py")
    e.log_metric("accuracy", 0.87)
    e.finish()

    got = pm.primary_metric_for_run(get_db(), e.id)
    assert got["key"] == "val_acc"
    assert got["missing"] is False, "the aliased spelling read as a missing metric"
    assert got["final"] == 0.87
