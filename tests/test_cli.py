"""Tests for exptrack/cli — calling CLI command functions directly."""
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


def _reset_config():
    """Reset cached config so each test starts fresh."""
    from exptrack import config as cfg
    cfg._root_cache = None
    cfg._cache = None


def _capture_stdout(func, *args):
    """Capture stdout from a function call, return the output string."""
    old = sys.stdout
    sys.stdout = buf = io.StringIO()
    try:
        func(*args)
    finally:
        sys.stdout = old
    return buf.getvalue()


def _make_experiment(script="train.py", params=None, tags=None, notes=""):
    """Helper: create and finish an experiment, return it."""
    from exptrack.core import Experiment
    exp = Experiment(script=script, params=params, tags=tags, notes=notes)
    return exp


def test_cmd_ls_runs():
    """cmd_ls runs without error and produces output."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.cli.inspect_cmds import cmd_ls

        # With no experiments
        args = SimpleNamespace(n=20)
        output = _capture_stdout(cmd_ls, args)
        assert "No experiments" in output or output.strip() == "", \
            "Expected empty list message"

        # With an experiment
        exp = _make_experiment()
        exp.finish()
        output = _capture_stdout(cmd_ls, args)
        assert exp.id[:6] in output, f"Expected ID prefix in output, got: {output[:200]}"

        print("  [PASS] test_cmd_ls_runs")


def test_cmd_show_displays():
    """cmd_show displays experiment details."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.cli.inspect_cmds import cmd_show

        exp = _make_experiment(params={"lr": 0.01})
        exp.log_metric("loss", 0.5, step=1)
        exp.finish()

        args = SimpleNamespace(id=exp.id[:6], timeline=False)
        output = _capture_stdout(cmd_show, args)
        assert exp.name in output, "Experiment name should appear in show output"

        print("  [PASS] test_cmd_show_displays")


def test_cmd_tag_adds():
    """cmd_tag adds a tag to an experiment."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.cli.mutate_cmds import cmd_tag
        from exptrack.core import get_db

        exp = _make_experiment()
        exp.finish()

        args = SimpleNamespace(id=exp.id[:6], tag="best")
        _capture_stdout(cmd_tag, args)

        with get_db() as conn:
            row = conn.execute("SELECT tags FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        tags = json.loads(row["tags"])
        assert "best" in tags, f"Expected 'best' in tags, got {tags}"

        print("  [PASS] test_cmd_tag_adds")


def test_cmd_untag_removes():
    """cmd_untag removes a tag from an experiment."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.cli.mutate_cmds import cmd_untag
        from exptrack.core import get_db

        exp = _make_experiment(tags=["keep", "remove"])
        exp.finish()

        args = SimpleNamespace(id=exp.id[:6], tag="remove")
        _capture_stdout(cmd_untag, args)

        with get_db() as conn:
            row = conn.execute("SELECT tags FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        tags = json.loads(row["tags"])
        assert "remove" not in tags, f"Tag 'remove' should be gone, got {tags}"
        assert "keep" in tags, f"Tag 'keep' should remain, got {tags}"

        print("  [PASS] test_cmd_untag_removes")


def test_cmd_note_adds():
    """cmd_note appends a note to an experiment."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.cli.mutate_cmds import cmd_note
        from exptrack.core import get_db

        exp = _make_experiment()
        exp.finish()

        args = SimpleNamespace(id=exp.id[:6], text="this is a note")
        _capture_stdout(cmd_note, args)

        with get_db() as conn:
            row = conn.execute("SELECT notes FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        assert "this is a note" in (row["notes"] or ""), \
            f"Note not found in DB, got: {row['notes']}"

        print("  [PASS] test_cmd_note_adds")


def test_cmd_export_json():
    """cmd_export produces valid JSON output."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.cli.inspect_cmds import cmd_export

        exp = _make_experiment(params={"lr": 0.01})
        exp.log_metric("loss", 0.5, step=1)
        exp.finish()

        args = SimpleNamespace(id=exp.id[:6], format="json")
        output = _capture_stdout(cmd_export, args)

        data = json.loads(output)
        assert data["id"] == exp.id, "Export ID mismatch"
        assert data["name"] == exp.name, "Export name mismatch"
        assert data["status"] == "done", "Export status should be done"
        assert "lr" in data["params"], "Params should contain lr"
        assert len(data["metrics"]) > 0, "Metrics should not be empty"

        print("  [PASS] test_cmd_export_json")


def test_cmd_finish_marks_done():
    """cmd_finish marks a running experiment as done."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.cli.mutate_cmds import cmd_finish
        from exptrack.core import Experiment, get_db

        # Create but don't finish
        exp = Experiment(script="train.py")

        args = SimpleNamespace(id=exp.id[:6])
        _capture_stdout(cmd_finish, args)

        with get_db() as conn:
            row = conn.execute("SELECT status, duration_s FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        assert row["status"] == "done", f"Expected 'done', got {row['status']}"
        assert row["duration_s"] is not None, "duration_s should be set"

        print("  [PASS] test_cmd_finish_marks_done")


def test_cmd_show_not_found():
    """cmd_show handles nonexistent ID gracefully."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.cli.inspect_cmds import cmd_show
        # Need at least one DB access to create schema
        from exptrack.core import get_db
        get_db()

        args = SimpleNamespace(id="nonexistent", timeline=False)
        output = _capture_stdout(cmd_show, args)
        assert "Not found" in output, "Should report not found"

        print("  [PASS] test_cmd_show_not_found")


def test_cmd_export_markdown():
    """cmd_export --format markdown produces markdown output."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.cli.inspect_cmds import cmd_export

        exp = _make_experiment(params={"lr": 0.01}, tags=["v1"])
        exp.log_metric("acc", 0.95, step=1)
        exp.finish()

        args = SimpleNamespace(id=exp.id[:6], format="markdown")
        output = _capture_stdout(cmd_export, args)

        assert output.startswith("#"), "Markdown should start with heading"
        assert "lr" in output, "Markdown should contain param name"
        assert exp.id in output, "Markdown should contain experiment ID"

        print("  [PASS] test_cmd_export_markdown")


def test_cmd_edit_note():
    """cmd_edit_note replaces the experiment notes."""
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        _reset_config()
        from exptrack import config as cfg
        cfg.init("test")
        from exptrack.cli.mutate_cmds import cmd_edit_note
        from exptrack.core import get_db

        exp = _make_experiment(notes="old note")
        exp.finish()

        args = SimpleNamespace(id=exp.id[:6], text="replaced note")
        _capture_stdout(cmd_edit_note, args)

        with get_db() as conn:
            row = conn.execute("SELECT notes FROM experiments WHERE id=?",
                               (exp.id,)).fetchone()
        assert row["notes"] == "replaced note", \
            f"Expected 'replaced note', got '{row['notes']}'"

        print("  [PASS] test_cmd_edit_note")


if __name__ == "__main__":
    saved_cwd = os.getcwd()
    tests = [
        test_cmd_ls_runs,
        test_cmd_show_displays,
        test_cmd_tag_adds,
        test_cmd_untag_removes,
        test_cmd_note_adds,
        test_cmd_export_json,
        test_cmd_finish_marks_done,
        test_cmd_show_not_found,
        test_cmd_export_markdown,
        test_cmd_edit_note,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            os.chdir(saved_cwd)
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            failed += 1

    os.chdir(saved_cwd)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
