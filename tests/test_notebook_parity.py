"""Regression tests for notebook / Session Tree behaviour (1.4 audit).

Two themes: **every magic is idempotent under a Run-All** (the constraint most
Session Tree changes break), and a notebook run is a first-class run — it can
be compared, ranked and graduated like a script run.
"""
from __future__ import annotations

from types import SimpleNamespace

from conftest import capture as _capture


def _session(name="explore", notebook="nb.ipynb"):
    from exptrack.sessions import SessionManager, set_current_session
    sm = SessionManager()
    sm.start(name, notebook)
    set_current_session(sm)
    return sm


# ── Run-All idempotency ──────────────────────────────────────────────────────

def test_a_setup_first_branch_does_not_fork_on_every_run_all(tmp_project):
    """The collision baseline was armed from tracked-cell source only, so a
    branch whose first replayed cell is %%setup never matched and every pass
    created `tryA (2)`, `tryA (3)`… with duplicated cells."""
    from exptrack.core import get_db

    sm = _session()
    sm.checkpoint("base")
    sm.branch("tryA")
    sm.record_setup_cell("df = load()", "")
    sm.record_cell("train(df)", "")

    for _ in range(2):                      # two more Run-All passes
        sm.checkpoint("base")
        sm.branch("tryA")
        sm.record_setup_cell("df = load()", "")
        sm.record_cell("train(df)", "")

    labels = [r["label"] for r in get_db().execute(
        "SELECT label FROM session_nodes WHERE session_id=? AND node_type='branch'",
        (sm.session_id,)).fetchall()]
    assert labels == ["tryA"], labels


def test_promoting_a_branch_does_not_duplicate_it_on_the_next_run_all(tmp_project):
    """The existing-node lookup excluded type 'checkpoint', so after
    promote_to_checkpoint a Run-All created a second node with the same label
    beside the promoted one."""
    from exptrack.core import get_db

    sm = _session()
    sm.checkpoint("base")
    nid = sm.branch("tryA")
    sm.record_cell("train()", "")
    from exptrack.sessions.manager import promote_to_checkpoint
    promote_to_checkpoint(nid)

    sm.checkpoint("base")
    sm.branch("tryA")
    sm.record_cell("train()", "")

    rows = get_db().execute(
        "SELECT label FROM session_nodes WHERE session_id=? AND label='tryA'",
        (sm.session_id,)).fetchall()
    assert len(rows) == 1


def test_a_notebook_that_ends_its_session_does_not_duplicate_the_tree(tmp_project):
    """`session end` at the bottom of a notebook is the commonest shape there
    is; re-adopting only `active` sessions meant each Run-All built a whole new
    tree."""
    from exptrack.core import get_db
    from exptrack.sessions import SessionManager, set_current_session

    for _ in range(3):
        sm = SessionManager()
        sm.start("explore", "nb.ipynb")
        set_current_session(sm)
        sm.checkpoint("base")
        sm.end()

    n = get_db().execute(
        "SELECT COUNT(*) FROM sessions WHERE name='explore'").fetchone()[0]
    assert n == 1


def test_an_ended_session_in_another_notebook_is_not_reopened(tmp_project):
    """Re-adoption of an *ended* session requires a definite notebook match —
    otherwise an unrelated notebook could reopen a session someone closed."""
    from exptrack.core import get_db
    from exptrack.sessions import SessionManager, set_current_session

    a = SessionManager(); a.start("explore", "one.ipynb"); a.end()
    b = SessionManager(); b.start("explore", "two.ipynb")
    set_current_session(b)

    n = get_db().execute(
        "SELECT COUNT(*) FROM sessions WHERE name='explore'").fetchone()[0]
    assert n == 2


def test_exp_note_is_idempotent_under_a_run_all(tmp_project):
    """%exp_tag and promote both dedup; %exp_note doubled its lines per pass."""
    from exptrack.core import Experiment

    exp = Experiment(script="nb.ipynb")
    for _ in range(3):
        exp.add_note("tried higher dropout", dedupe=True)
    assert exp.notes.splitlines().count("tried higher dropout") == 1

    # The plain append-only form is untouched (%%pin needs it).
    exp.add_note("tried higher dropout")
    assert exp.notes.splitlines().count("tried higher dropout") == 2
    exp.finish()


# ── Attribution and naming ───────────────────────────────────────────────────

def test_auto_hp_capture_does_not_rename_a_run_the_user_named(tmp_project):
    """The rename was unconditional, so `%exp_start my-named-baseline` plus a
    cell assigning `lr = 0.01` replaced the name the user had just chosen."""
    from exptrack.capture.notebook_hooks import _log_hp_params
    from exptrack.core import Experiment

    exp = Experiment(name="my-named-baseline", script="nb.ipynb")
    _log_hp_params(exp, {"lr": 0.01}, {"lr": {"param": 0.01}}, {}, "",
                   False, False, False, 1)
    assert exp.name == "my-named-baseline"
    assert exp._params.get("lr") == 0.01      # still captured
    exp.finish()


def test_a_second_run_in_one_kernel_starts_its_setup_numbering_at_one(tmp_project):
    """`setup_count` never reset between runs, so the second run's setup cells
    were labelled setup_3, setup_4…"""
    from exptrack.capture.notebook_hooks import _nb_state, attach_notebook
    from exptrack.core import Experiment

    _nb_state["setup_count"] = 7
    exp = Experiment(script="nb.ipynb")
    attach_notebook(exp, "nb.ipynb", ip=None)
    assert _nb_state["setup_count"] == 0
    exp.finish()


def test_session_metric_tagging_skips_another_sessions_run(tmp_project):
    """The tag went on any metric logged while a session was live, whoever
    owned the run — and materialize then copied foreign numbers onto the
    graduated branch run."""
    from exptrack.core import Experiment, get_db

    sm = _session()
    sm.checkpoint("base")
    sm.branch("A")

    mine = Experiment(script="nb.ipynb")
    sm.autolink_run(mine.id)
    mine.log_metric("acc", 0.9)

    stranger = Experiment(script="other_train.py")
    stranger.log_metric("acc", 0.1)

    conn = get_db()
    tagged = conn.execute(
        "SELECT session_node_id FROM metrics WHERE exp_id=?", (mine.id,)).fetchone()
    untagged = conn.execute(
        "SELECT session_node_id FROM metrics WHERE exp_id=?", (stranger.id,)).fetchone()
    assert tagged["session_node_id"]
    assert untagged["session_node_id"] is None


def test_exp_log_finds_the_run_when_detection_returns_a_relative_path(tmp_project):
    """log_last searched for the raw detected name while runs store the
    resolved absolute path, so in every JupyterLab deployment reporting a
    relative name the post-hoc logging feature silently found nothing."""
    from exptrack.core import Experiment, get_db
    from exptrack.notebook import log_last

    nb = tmp_project / "analysis.ipynb"
    nb.write_text("{}")
    exp = Experiment(script=str(nb))
    exp.finish()

    got = log_last(_nb_file="analysis.ipynb", test_acc=0.93)
    assert got is not None and got.id == exp.id

    row = get_db().execute(
        "SELECT value FROM metrics WHERE exp_id=? AND key='test_acc'",
        (exp.id,)).fetchone()
    assert row["value"] == 0.93


# ── Materialized runs are first-class ────────────────────────────────────────

def test_a_materialized_branch_carries_a_script_and_its_hyperparameters(tmp_project):
    """Graduated branch runs had no script and no params, so they joined no
    baseline chain and a param study over a finalized session showed nothing
    varying — even though the branches differed by exactly the knob the user
    was exploring."""
    from exptrack.core import get_db
    from exptrack.core.param_study import analyze_params
    from exptrack.sessions.materialize import materialize_experiment

    sm = _session(notebook="nb.ipynb")
    sm.checkpoint("base")

    ids = []
    for lr in (0.1, 0.2):
        node = sm.branch(f"lr{lr}")
        sm.record_cell(f"lr = {lr}\ntrain(lr)", "")
        res = materialize_experiment(node)
        assert res.get("ok"), res
        ids.append(res["id"])

    conn = get_db()
    for eid in ids:
        row = conn.execute("SELECT script FROM experiments WHERE id=?",
                           (eid,)).fetchone()
        assert row["script"], "a materialized run must have a script identity"

    varying = {p["key"] for p in analyze_params(conn, ids)["varying"]}
    assert "lr" in varying


def test_materialize_only_promotes_scalar_hyperparameter_assignments(tmp_project):
    """`df = load()` is not a hyperparameter, and `lr = base * 0.1` is not a
    value this layer can know."""
    from exptrack.core import get_db
    from exptrack.sessions.materialize import materialize_experiment

    sm = _session(name="scoped", notebook="nb.ipynb")
    sm.checkpoint("base")
    node = sm.branch("try")
    sm.record_cell("df = load_data()\nlr = base_lr * 0.1\nepochs = 30", "")
    res = materialize_experiment(node)
    assert res.get("ok"), res

    keys = {r["key"] for r in get_db().execute(
        "SELECT key FROM params WHERE exp_id=?", (res["id"],)).fetchall()}
    assert "epochs" in keys
    assert "df" not in keys and "lr" not in keys


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_session_nodes_marks_a_trashed_node(tmp_project):
    """A trashed thing that is still reachable must say it is trashed."""
    from exptrack.cli.session_cmds import cmd_session_nodes
    from exptrack.core import get_db

    sm = _session("marked")
    nid = sm.checkpoint("base")
    conn = get_db()
    conn.execute("UPDATE session_nodes SET deleted_at='2026-01-01' WHERE id=?", (nid,))
    conn.commit()

    out, _ = _capture(cmd_session_nodes, SimpleNamespace(id_or_name="marked"))
    assert "[trashed]" in out
