"""Code changes in an export say where they go, and can be applied.

The export showed a run's code change as the `_code_changes` fragments —
``+ line`` / ``- line`` with indentation stripped, no file, no line number,
and only for the entry script (an edit to an imported module was missing
entirely). The run's full ``git diff`` was stored all along. Exports now render
from it: a table of each file's changed lines *in the committed file*, linked
to that file at that commit when the repository is on a known host, then each
file's patch verbatim, which ``git apply`` accepts.
"""
from __future__ import annotations

import subprocess

import pytest

from exptrack.core.export_render import format_export_text, markdown_to_html
from exptrack.core.git import (
    commit_web_url,
    file_web_url,
    parse_diff_files,
    repo_web_links,
    web_base_from_remote,
)
from exptrack.core.queries import format_export_markdown

DIFF = """diff --git a/model.py b/model.py
index 907b515..8d78fcf 100644
--- a/model.py
+++ b/model.py
@@ -1,10 +1,14 @@
 import math


-def build(layers, width=64):
-    return [width] * layers
+def build(layers, width=128):
+    widths = []
+    for i in range(layers):
+        widths.append(width)
+    return widths
@@ -40,3 +44,3 @@ def loss_fn(x):
-    return x
+    return x | 1
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+A = 1
+B = 2"""

LINKS = {"kind": "github", "base": "https://github.com/o/r"}
DATA = {"id": "abc123", "name": "run", "status": "done", "created_at": "t",
        "git_branch": "main", "git_commit": "3a1e635", "git_web": LINKS,
        "git_diff": DIFF, "git_diff_status": "",
        "project_root": "/home/me/proj", "script": "/home/me/proj/train.py",
        "command": "python /home/me/proj/train.py --lr 0.1",
        "output_dir": "/home/me/proj/outputs/run1",
        "code_changes": {"script": "+ widths = []"},
        "artifacts": [{"label": "log", "path": "/home/me/proj/outputs/run1/log.txt"}],
        "artifacts_summary": {"total": 1, "listed": 1, "omitted": 0,
                              "by_type": [], "by_dir": []}}


# ── parsing ─────────────────────────────────────────────────────────────────

def test_the_diff_is_split_per_file_with_hunk_ranges():
    files = parse_diff_files(DIFF)["files"]
    assert [f["path"] for f in files] == ["model.py", "new.py"]
    model, new = files
    assert (model["added"], model["removed"]) == (6, 3)
    assert model["hunks"] == [{"old_start": 1, "old_len": 10, "new_start": 1, "new_len": 14},
                              {"old_start": 40, "old_len": 3, "new_start": 44, "new_len": 3}]
    assert new["status"] == "added"
    assert "\n".join(f["patch"] for f in files) == DIFF, "patches are the diff, verbatim"


def test_a_truncated_capture_keeps_its_marker():
    cut = DIFF + "\n\n[truncated — exceeded max_git_diff_kb limit]"
    assert "truncated" in parse_diff_files(cut)["trailer"]
    assert "truncated" in format_export_markdown(dict(DATA, git_diff=cut))


# ── links ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("git@github.com:o/r.git", ("github", "https://github.com/o/r")),
    ("https://github.com/o/r", ("github", "https://github.com/o/r")),
    ("ssh://git@gitlab.com:2222/g/sub/p.git", ("gitlab", "https://gitlab.com/g/sub/p")),
    ("https://bitbucket.org/t/r.git", ("bitbucket", "https://bitbucket.org/t/r")),
    ("https://example.com/o/r", None),
    ("/srv/git/r.git", None),
    ("", None),
])
def test_remote_urls_become_web_bases(url, expected):
    assert web_base_from_remote(url) == expected


def test_credentials_in_a_remote_never_reach_a_link():
    """An https remote can embed a token; a link built from it would put the
    token into every exported document."""
    base = web_base_from_remote("https://me:ghp_SECRET@github.com/o/r.git")
    assert base == ("github", "https://github.com/o/r")
    assert "SECRET" not in format_export_markdown(
        dict(DATA, git_web={"kind": base[0], "base": base[1]}))


def test_link_shapes_per_host():
    assert commit_web_url(LINKS, "abc") == "https://github.com/o/r/commit/abc"
    assert file_web_url(LINKS, "abc", "a/b.py", 3, 7) == \
        "https://github.com/o/r/blob/abc/a/b.py#L3-L7"
    gl = {"kind": "gitlab", "base": "https://gitlab.com/g/p"}
    assert file_web_url(gl, "abc", "x.py", 3, 7) == "https://gitlab.com/g/p/-/blob/abc/x.py#L3-7"
    assert commit_web_url(None, "abc") == "" and file_web_url(LINKS, "", "x") == ""


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_the_remote_is_read_from_config_even_below_the_repo_root(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "remote", "add", "origin", "git@github.com:o/r.git")
    sub = tmp_path / "project"
    sub.mkdir()
    assert repo_web_links(sub) == LINKS
    assert repo_web_links(tmp_path / "missing") is None or True  # never raises


def test_a_worktree_finds_its_common_config(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
         "--allow-empty", "-m", "i")
    _git(main, "remote", "add", "origin", "https://github.com/o/r.git")
    _git(main, "worktree", "add", "-q", str(tmp_path / "wt"))
    assert repo_web_links(tmp_path / "wt") == LINKS


def test_no_remote_means_no_link_not_an_error(tmp_path):
    _git(tmp_path, "init", "-q")
    assert repo_web_links(tmp_path) is None


# ── rendering ───────────────────────────────────────────────────────────────

def test_markdown_says_where_each_change_goes_and_links_it():
    md = format_export_markdown(DATA)
    assert "[`3a1e635`](https://github.com/o/r/commit/3a1e635)" in md
    assert "[1-10](https://github.com/o/r/blob/3a1e635/model.py#L1-L10)" in md
    assert "[40-42](https://github.com/o/r/blob/3a1e635/model.py#L40-L42)" in md
    assert "`new.py` (added)" in md
    # Each edited line sits beside what it replaced, with both line numbers.
    assert "| 40 | `    return x` | 44 | `    return x`**` | 1`** |" in md.replace("\\|", "|")


def test_the_patch_keeps_indentation_and_every_file():
    md = format_export_markdown(DATA)
    assert "+        widths.append(width)" in md, "indentation must survive"
    assert "diff --git a/new.py b/new.py" in md
    # The lossy script fragments are dropped when the diff covers them.
    assert "| + | `widths = []` |" not in md


def test_the_patches_come_last_so_they_copy_in_one_go():
    md = format_export_markdown(dict(DATA, timeline_summary={
        "total_events": 3, "cell_executions": 1, "variable_sets": 0, "artifact_events": 2}))
    assert md.index("## Timeline Summary") < md.index("## Code Changes")
    text = format_export_text(DATA)
    assert text.rstrip().endswith("+B = 2")


def test_text_patch_applies_with_git_apply(tmp_path):
    """The whole point of the Patch section: copy it out, `git apply` it."""
    import textwrap
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "m.py").write_text(textwrap.dedent("""\
        def f(x):
            return x
        """), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
    (repo / "m.py").write_text(textwrap.dedent("""\
        def f(x):
            y = x * 2
            return y
        """), encoding="utf-8")
    diff = subprocess.run(["git", "diff"], cwd=repo, capture_output=True,
                          text=True, check=True).stdout
    _git(repo, "checkout", "--", ".")
    text = format_export_text(dict(DATA, git_diff=diff))
    patch = text.split("from the repository root)\n", 1)[1].split("\n", 1)[1]
    (tmp_path / "p.patch").write_bytes(patch.encode("utf-8"))
    subprocess.run(["git", "apply", str(tmp_path / "p.patch")], cwd=repo, check=True)
    assert "y = x * 2" in (repo / "m.py").read_text(encoding="utf-8")


def test_paths_are_relative_to_a_stated_root():
    md = format_export_markdown(DATA)
    assert "| Project root | `/home/me/proj` |" in md
    assert "| Script | `train.py` |" in md
    assert "`python train.py --lr 0.1`" in md
    assert "`outputs/run1/log.txt`" in md
    text = format_export_text(DATA)
    assert "outputs/run1/log.txt" in text and "/home/me/proj/outputs" not in text


def test_a_path_outside_the_root_stays_absolute():
    md = format_export_markdown(dict(DATA, output_dir="/scratch/elsewhere"))
    assert "`/scratch/elsewhere`" in md


def test_without_a_diff_the_fragments_are_kept_and_the_reason_is_said():
    md = format_export_markdown(dict(DATA, git_diff="", git_diff_status="[compacted]"))
    assert "not available (`[compacted]`)" in md
    assert "| + | `widths = []` |" in md


def test_no_links_when_the_host_is_unknown():
    md = format_export_markdown(dict(DATA, git_web=None))
    assert "https://" not in md
    assert "| `model.py` | 6 | 3 | 1-10, 40-42 |" in md


def test_html_links_are_real_anchors_and_only_http():
    h = markdown_to_html(format_export_markdown(DATA))
    assert '<a href="https://github.com/o/r/commit/3a1e635"' in h
    assert "<a href" not in markdown_to_html("[x](javascript:alert(1))")


def test_the_export_data_carries_the_diff_root_and_links(tmp_project):
    from exptrack.core import Experiment, get_db
    from exptrack.core.queries import get_export_data
    exp = Experiment(script="train.py", params={"lr": 0.01})
    exp.finish()
    data = get_export_data(get_db(), exp.id)
    assert {"git_diff", "git_diff_status", "project_root", "git_web"} <= set(data)
    assert data["project_root"]


# ── every other surface carries the code change too ────────────────────────

def test_csv_code_cell_is_the_per_file_summary():
    import csv
    import io

    from exptrack.core.queries import format_export_csv
    rows = list(csv.reader(io.StringIO(format_export_csv([DATA]))))
    cell = rows[1][rows[0].index("code_changes")]
    assert cell == "model.py +6/-3 @1-10,40-42; new.py (added) +2/-0 @new file"


def test_csv_has_no_blank_rows():
    from exptrack.core.queries import format_export_csv
    assert "\r" not in format_export_csv([DATA, DATA])


def test_csv_without_a_diff_keeps_the_change_names():
    from exptrack.core.queries import format_export_csv
    out = format_export_csv([dict(DATA, git_diff="")])
    assert "script" in out


def test_a_pair_comparison_carries_the_code_diff_between_the_runs():
    from exptrack.core.export_render import format_comparison_markdown, runs_code_diff
    exps = [{"id": "a", "name": "old", "params": {}, "metrics": {}},
            {"id": "b", "name": "new", "params": {}, "metrics": {}}]
    code = {"mode": "script", "base_id": "a", "new_id": "b", "cells": [
        {"label": "train.py", "a": "x = 1\ny = 2\n", "b": "x = 1\ny = 3\n"}]}
    md = format_comparison_markdown(exps, [], code=code)
    assert "Code changes from old (older) to new (newer): 1 file, 1 added, 1 removed" in md
    assert "-y = 2\n+y = 3" in md
    assert md.rstrip().endswith("```"), "the patch comes last"
    assert runs_code_diff(code).startswith("diff --git a/train.py b/train.py")


def test_a_pair_with_no_code_change_says_so():
    from exptrack.core.export_render import format_comparison_markdown
    exps = [{"id": "a", "name": "x"}, {"id": "b", "name": "y"}]
    md = format_comparison_markdown(exps, [], code={"cells": []})
    assert "No code change between these runs." in md


def test_three_runs_say_the_code_diff_is_pairwise():
    from exptrack.core.export_render import format_comparison_markdown
    exps = [{"id": c, "name": c} for c in "abc"]
    assert "compare a pair" in format_comparison_markdown(exps, [])


def test_the_runs_code_diff_applies_to_the_older_runs_code(tmp_path):
    from exptrack.core.export_render import runs_code_diff
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    # write_bytes, not write_text(newline=): that keyword is Python 3.10+.
    (repo / "train.py").write_bytes(b"x = 1\ny = 2\n")
    patch = runs_code_diff({"cells": [{"label": "train.py", "a": "x = 1\ny = 2\n",
                                       "b": "x = 1\ny = 3\n"}]}) + "\n"
    (tmp_path / "p.patch").write_bytes(patch.encode("utf-8"))
    subprocess.run(["git", "apply", str(tmp_path / "p.patch")], cwd=repo, check=True)
    assert (repo / "train.py").read_text(encoding="utf-8") == "x = 1\ny = 3\n"
