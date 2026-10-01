"""The raw patch leaves the tool byte-for-byte, so `git apply` takes it.

`exptrack diff <id> --patch` (stdout or ``-o FILE``), the dashboard's Patch
download and the save-to-exports-folder route all carry the diff verbatim.
Windows is where this breaks: text-mode writes turn ``\\n`` into ``\\r\\n`` and
PowerShell 5's ``>`` re-encodes to UTF-16, and either corrupts a patch.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

DIFF = "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"


def _run_with_diff(tmp_project, diff=DIFF):
    from exptrack.core import Experiment, get_db
    exp = Experiment(script="train.py", params={})
    exp.finish()
    conn = get_db()
    conn.execute("UPDATE experiments SET git_diff=?, git_commit='abc1234' WHERE id=?",
                 (diff, exp.id))
    conn.commit()
    return exp


def test_patch_to_a_file_is_lf_bytes(tmp_project, tmp_path):
    from exptrack.cli.inspect_cmds import cmd_diff
    exp = _run_with_diff(tmp_project)
    out = tmp_path / "run.patch"
    cmd_diff(SimpleNamespace(id=exp.id, patch=True, output=str(out)))
    assert out.read_bytes() == DIFF.encode()


def test_patch_to_stdout_is_the_diff_only(tmp_project, capfdbinary):
    from exptrack.cli.inspect_cmds import cmd_diff
    exp = _run_with_diff(tmp_project)
    cmd_diff(SimpleNamespace(id=exp.id, patch=True, output=None))
    assert capfdbinary.readouterr().out == DIFF.encode()


def test_no_patch_is_an_error_not_text(tmp_project, capsys):
    from exptrack.cli.inspect_cmds import cmd_diff
    exp = _run_with_diff(tmp_project, diff="")
    with pytest.raises(SystemExit):
        cmd_diff(SimpleNamespace(id=exp.id, patch=True, output=None))


def test_the_dashboard_route_carries_the_raw_patch(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes.write_routes import api_export_diff
    exp = _run_with_diff(tmp_project)
    d = api_export_diff(get_db(), exp.id)
    assert d["patch"] == DIFF and d["patch_filename"].endswith(".patch")


def test_saving_an_export_keeps_its_line_endings(tmp_project):
    from exptrack.dashboard.routes.write_routes import api_save_export
    r = api_save_export({"filename": "run.patch", "content": DIFF})
    assert r["ok"]
    assert (tmp_project / r["path"]).read_bytes() == DIFF.encode()


def test_the_detail_api_links_the_commit(tmp_project, monkeypatch):
    from exptrack.core import get_db, queries
    from exptrack.dashboard.routes.read_routes import api_experiment
    exp = _run_with_diff(tmp_project)
    monkeypatch.setattr(queries, "_export_git_web",
                        lambda: {"kind": "github", "base": "https://github.com/o/r"})
    assert api_experiment(get_db(), exp.id)["git_commit_url"] == \
        "https://github.com/o/r/commit/abc1234"
    monkeypatch.setattr(queries, "_export_git_web", lambda: None)
    assert api_experiment(get_db(), exp.id)["git_commit_url"] == ""


# Copy leaves the patch out. Pasted into a notebook it is a wall of +/- lines
# under the before/after tables that already say the same thing; Export .patch
# is the way to take it, and a download still ends with it.

def test_a_copy_of_the_diff_leaves_the_patch_out(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes.write_routes import api_export_diff
    exp = _run_with_diff(tmp_project)
    full = api_export_diff(get_db(), exp.id)
    copy = api_export_diff(get_db(), exp.id, {"patch": False})
    assert "```diff" in full["markdown"]
    assert "```diff" not in copy["markdown"]
    assert "Export .patch" in copy["markdown"] and "Export .patch" in copy["html"]
    assert "`x = `**`2`**" in copy["markdown"], "the before/after view stays"
    assert copy["patch"] == DIFF, "the patch download is unchanged"


def test_a_copy_of_the_export_leaves_the_patch_out(tmp_project):
    from exptrack.core import get_db
    from exptrack.dashboard.routes.read_routes import api_export
    exp = _run_with_diff(tmp_project)
    md = api_export(get_db(), exp.id, {"format": "markdown", "patch": "0"})["markdown"]
    assert "```diff" not in md and "Export .patch" in md
    assert "```diff" in api_export(get_db(), exp.id, {"format": "markdown"})["markdown"]
    text = api_export(get_db(), exp.id, {"format": "text", "patch": "0"})["content"]
    assert "diff --git" not in text and "Export .patch" in text


def test_a_copy_of_a_comparison_leaves_the_patch_out():
    from exptrack.core.export_render import format_comparison_markdown
    exps = [{"id": "a", "name": "old", "params": {}, "metrics": {}},
            {"id": "b", "name": "new", "params": {}, "metrics": {}}]
    code = {"mode": "script", "base_id": "a", "new_id": "b", "cells": [
        {"label": "train.py", "a": "x = 1\n", "b": "x = 2\n"}]}
    md = format_comparison_markdown(exps, [], code=code, patch=False)
    assert "```diff" not in md and "Export .patch" in md
    assert "```diff" in format_comparison_markdown(exps, [], code=code)
