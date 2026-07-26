"""F15: not-found / hard-error CLI paths exit non-zero with the message on stderr.

Scripts rely on this (`exptrack show $ID || handle_missing`), so a not-found run
must raise SystemExit(1) and print to stderr, not print to stdout and return 0.
"""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

import pytest


def _run_die(func, args):
    """Call a cmd_* expected to die(); return (stdout, stderr, exit_code)."""
    out, err = io.StringIO(), io.StringIO()
    code = None
    with redirect_stdout(out), redirect_stderr(err):
        try:
            func(args)
        except SystemExit as e:
            code = e.code
    return out.getvalue(), err.getvalue(), code


NF = "nope-no-such-id"


@pytest.mark.parametrize("modname,func,args", [
    ("inspect_cmds", "cmd_show", SimpleNamespace(id=NF, timeline=False, json_output=False)),
    ("inspect_cmds", "cmd_diff", SimpleNamespace(id=NF)),
    ("inspect_cmds", "cmd_timeline", SimpleNamespace(id=NF, compact=False)),
    ("inspect_cmds", "cmd_compare", SimpleNamespace(id1=NF, id2=NF, seq1=None, seq2=None)),
    ("inspect_cmds", "cmd_watch", SimpleNamespace(id=NF, interval=1)),
    ("inspect_cmds", "cmd_export", SimpleNamespace(id=NF, format="json", export_all=False)),
    ("mutate_cmds", "cmd_note", SimpleNamespace(id=NF, text="x")),
    ("mutate_cmds", "cmd_edit_note", SimpleNamespace(id=NF, text="x")),
    ("mutate_cmds", "cmd_finish", SimpleNamespace(id=NF)),
    ("mutate_cmds", "cmd_study", SimpleNamespace(id=NF, study="s")),
    ("mutate_cmds", "cmd_unstudy", SimpleNamespace(id=NF, study="s")),
    ("mutate_cmds", "cmd_stage", SimpleNamespace(id=NF, number=1, name=None)),
])
def test_not_found_exits_1_on_stderr(tmp_project, modname, func, args):
    import importlib
    mod = importlib.import_module(f"exptrack.cli.{modname}")
    from exptrack.core import get_db
    get_db()  # ensure schema

    stdout, stderr, code = _run_die(getattr(mod, func), args)
    assert code == 1, f"{func} should exit 1 on not-found"
    assert "not found" in stderr.lower() or "no " in stderr.lower()
    assert stdout == "", f"{func} must print nothing to stdout on error"


def test_export_requires_id(tmp_project):
    from exptrack.cli.inspect_cmds import cmd_export
    from exptrack.core import get_db
    get_db()
    args = SimpleNamespace(id=None, format="json", export_all=False)
    stdout, stderr, code = _run_die(cmd_export, args)
    assert code == 1
    assert "required" in stderr.lower()
    assert stdout == ""


def test_tag_requires_tag_arg(tmp_project):
    from exptrack.cli.mutate_cmds import cmd_tag
    from exptrack.core import get_db
    get_db()
    # nargs="+" with a single element: no tag name provided.
    args = SimpleNamespace(id=["only-one"])
    stdout, stderr, code = _run_die(cmd_tag, args)
    assert code == 1
    assert "usage" in stderr.lower()
