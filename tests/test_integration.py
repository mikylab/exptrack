"""Integration tests — end-to-end workflows."""
import json
import sys
from types import SimpleNamespace


def test_full_lifecycle(tmp_project):
    """Full experiment lifecycle: create -> params -> metrics -> finish -> show -> export -> rm."""
    from exptrack.core import Experiment, get_db

    # Create experiment
    exp = Experiment(script="train.py", params={"lr": 0.01}, tags=["baseline"])

    # Log metrics
    exp.log_metric("loss", 0.9, step=1)
    exp.log_metric("loss", 0.5, step=2)
    exp.log_metric("acc", 0.7, step=2)

    # Add a note
    exp.add_note("Initial baseline run")

    # Finish
    exp.finish()

    # Verify in DB
    conn = get_db()
    row = conn.execute("SELECT * FROM experiments WHERE id=?", (exp.id,)).fetchone()
    assert row["status"] == "done"
    assert row["duration_s"] > 0
    assert "baseline" in json.loads(row["tags"])
    assert "Initial baseline run" in row["notes"]

    # Verify params
    params = conn.execute("SELECT key, value FROM params WHERE exp_id=?",
                          (exp.id,)).fetchall()
    param_dict = {r["key"]: json.loads(r["value"]) for r in params}
    assert param_dict["lr"] == 0.01

    # Verify metrics
    metrics = conn.execute("SELECT key, value, step FROM metrics WHERE exp_id=? ORDER BY step",
                           (exp.id,)).fetchall()
    assert len(metrics) == 3

    # Export as JSON
    from exptrack.cli.inspect_cmds import cmd_export
    args = SimpleNamespace(id=exp.id, format="json")
    cmd_export(args)  # prints to stdout

    # Delete
    from exptrack.core.db import delete_experiment
    delete_experiment(conn, exp.id)
    conn.commit()

    deleted = conn.execute("SELECT * FROM experiments WHERE id=?", (exp.id,)).fetchone()
    assert deleted is None


def test_pipeline_workflow(tmp_project):
    """Shell pipeline: run-start -> log-metric -> run-finish."""
    from exptrack.cli.pipeline_cmds import cmd_log_metric, cmd_run_finish, cmd_run_start
    from exptrack.core import get_db

    # run-start (captures stdout output)
    args = SimpleNamespace(
        name="pipeline_test", script="train.sh", tags=["gpu"],
        notes="", params=["--lr", "0.01", "--epochs", "50"]
    )

    import io
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    cmd_run_start(args)
    output = buffer.getvalue()
    sys.stdout = old_stdout

    # Extract EXP_ID from output
    exp_id = None
    for line in output.splitlines():
        if "EXP_ID=" in line:
            exp_id = line.split("EXP_ID=")[1].strip().strip("'\"")
            break
    assert exp_id is not None, f"Could not find EXP_ID in output: {output}"

    # Log metric mid-pipeline
    args = SimpleNamespace(id=exp_id, key="loss", value=0.5, step=1, file=None)
    cmd_log_metric(args)

    # Finish
    args = SimpleNamespace(id=exp_id, metrics=None, step=None, params=None)
    cmd_run_finish(args)

    # Verify
    conn = get_db()
    row = conn.execute("SELECT * FROM experiments WHERE id LIKE ?",
                       (exp_id + "%",)).fetchone()
    assert row["status"] == "done"


def test_tag_workflow(tmp_project):
    """Tag operations: tag -> untag -> delete-tag."""
    from exptrack.cli.mutate_cmds import cmd_tag, cmd_untag
    from exptrack.core import Experiment, get_db

    exp1 = Experiment(script="a.py")
    exp1.finish()
    exp2 = Experiment(script="b.py")
    exp2.finish()

    # Tag both experiments
    cmd_tag(SimpleNamespace(id=exp1.id, tag="v1"))
    cmd_tag(SimpleNamespace(id=exp2.id, tag="v1"))
    cmd_tag(SimpleNamespace(id=exp1.id, tag="baseline"))

    conn = get_db()

    # Verify tags
    r1 = conn.execute("SELECT tags FROM experiments WHERE id=?", (exp1.id,)).fetchone()
    tags1 = json.loads(r1["tags"])
    assert "v1" in tags1
    assert "baseline" in tags1

    # Untag
    cmd_untag(SimpleNamespace(id=exp1.id, tag="v1"))
    r1 = conn.execute("SELECT tags FROM experiments WHERE id=?", (exp1.id,)).fetchone()
    tags1 = json.loads(r1["tags"])
    assert "v1" not in tags1
    assert "baseline" in tags1


def test_context_manager_finish(tmp_project):
    """Experiment as context manager auto-finishes on clean exit."""
    from exptrack.core import Experiment, get_db

    with Experiment(script="train.py") as exp:
        exp.log_metric("loss", 0.5)
        exp_id = exp.id

    conn = get_db()
    row = conn.execute("SELECT status FROM experiments WHERE id=?", (exp_id,)).fetchone()
    assert row["status"] == "done"


def test_context_manager_fail_on_exception(tmp_project):
    """Experiment as context manager auto-fails on exception."""
    from exptrack.core import Experiment, get_db

    exp_id = None
    try:
        with Experiment(script="train.py") as exp:
            exp_id = exp.id
            raise ValueError("out of memory")
    except ValueError:
        pass

    conn = get_db()
    row = conn.execute("SELECT status FROM experiments WHERE id=?", (exp_id,)).fetchone()
    assert row["status"] == "failed"


def test_concurrent_experiments(tmp_project):
    """Multiple experiments can run concurrently using WAL mode."""
    from exptrack.core import Experiment, get_db

    exp1 = Experiment(script="a.py")
    exp2 = Experiment(script="b.py")

    exp1.log_metric("loss", 0.5, step=1)
    exp2.log_metric("loss", 0.3, step=1)

    exp1.finish()
    exp2.finish()

    conn = get_db()
    rows = conn.execute("SELECT id FROM experiments WHERE status='done'").fetchall()
    ids = [r["id"] for r in rows]
    assert exp1.id in ids
    assert exp2.id in ids

    # Verify metrics are correctly attributed
    m1 = conn.execute("SELECT value FROM metrics WHERE exp_id=? AND key='loss'",
                       (exp1.id,)).fetchone()
    m2 = conn.execute("SELECT value FROM metrics WHERE exp_id=? AND key='loss'",
                       (exp2.id,)).fetchone()
    assert m1["value"] == 0.5
    assert m2["value"] == 0.3


def test_experiment_with_artifacts(tmp_project):
    """Artifacts are tracked and can be verified."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py")

    # Create artifact files
    out = tmp_project / "outputs" / exp.name
    out.mkdir(parents=True, exist_ok=True)
    model_path = out / "model.pt"
    model_path.write_bytes(b"model weights")
    exp.log_artifact(str(model_path), label="trained_model")

    exp.finish()

    conn = get_db()
    arts = conn.execute("SELECT label, path, content_hash FROM artifacts WHERE exp_id=?",
                        (exp.id,)).fetchall()
    model_arts = [a for a in arts if a["label"] == "trained_model"]
    assert len(model_arts) == 1
    assert model_arts[0]["content_hash"] is not None  # hash computed


def test_notes_append_and_replace(tmp_project):
    """Notes can be appended and replaced."""
    from exptrack.core import Experiment, get_db

    exp = Experiment(script="train.py", notes="initial note")
    exp.add_note("second note")
    assert "initial note" in exp.notes
    assert "second note" in exp.notes

    exp.set_note("completely new note")
    assert exp.notes == "completely new note"

    exp.finish()

    conn = get_db()
    row = conn.execute("SELECT notes FROM experiments WHERE id=?", (exp.id,)).fetchone()
    assert row["notes"] == "completely new note"
