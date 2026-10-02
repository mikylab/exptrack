"""The readable "What changed" view of a diff.

A unified diff is for `git apply`, not for reading: an edited line is a `-`
and a `+` some distance apart and the reader has to find the word that
differs. Exports lead with each changed line beside what it replaced and the
changed words marked, and keep the patch, verbatim, after it.
"""
from __future__ import annotations

from exptrack.core.diff_view import caret_line, changed_rows, word_segments
from exptrack.core.export_render import format_export_text, markdown_to_html
from exptrack.core.queries import format_export_markdown

PATCH = """diff --git a/model.py b/model.py
--- a/model.py
+++ b/model.py
@@ -3,6 +3,8 @@
 def build(layers, width=64):
-    \"\"\"Return widths.\"\"\"
-    return [width] * layers
+    \"\"\"Return widths, tapered.\"\"\"
+    widths = []
+    for i in range(layers):
+    return widths
 x = 1
-y = 2
+y = 3"""


def test_each_edited_line_is_paired_with_the_line_it_replaced():
    rows = changed_rows(PATCH)
    pairs = [(r["old"], r["new"]) for r in rows]
    # Positional pairing matched `return [width] * layers` with `widths = []`;
    # the most similar line is `return widths`.
    assert ('    return [width] * layers', '    return widths') in pairs
    assert (None, '    widths = []') in pairs
    assert ('y = 2', 'y = 3') in pairs


def test_rows_carry_both_sides_line_numbers():
    rows = {r["new"]: r for r in changed_rows(PATCH) if r["new"]}
    assert rows['    return widths']["old_no"] == 5
    assert rows['    return widths']["new_no"] == 7
    assert rows['y = 3']["old_no"] == 7 and rows['y = 3']["new_no"] == 9


def test_context_lines_are_not_rows():
    assert all("x = 1" not in (r["old"] or "") + (r["new"] or "")
               for r in changed_rows(PATCH))


def test_unrelated_lines_are_not_paired():
    rows = changed_rows("@@ -1,1 +1,1 @@\n-import os\n+print('hello world')")
    assert [(r["old"], r["new"]) for r in rows] == [("import os", None),
                                                    (None, "print('hello world')")]


def test_word_segments_mark_only_what_changed():
    olds, news = word_segments("width=64, depth=2", "width=128, depth=2")
    assert olds == [("width=", False), ("64", True), (", depth=2", False)]
    assert news == [("width=", False), ("128", True), (", depth=2", False)]
    assert caret_line(news) == "      ^^^"


def test_a_whitespace_only_change_is_not_marked():
    olds, news = word_segments("x  = 1", "x = 1")
    assert not any(changed for _, changed in olds + news)


def _data(patch):
    return {"id": "a", "name": "r", "status": "done", "created_at": "t",
            "git_commit": "abc", "git_branch": "main", "git_diff": patch,
            "git_diff_status": "", "code_changes": {}}


def test_markdown_shows_before_after_and_still_ends_with_the_patch():
    md = format_export_markdown(_data(PATCH))
    assert "| Line | Before | Line | After |" in md
    assert "| 7 | `y = `~~`2`~~ | 9 | `y = `**`3`** |" in md
    assert md.index("| Line | Before |") < md.index("### Patch")
    assert md.rstrip().endswith("```")
    assert "+y = 3" in md.split("### Patch")[1], "the patch itself is untouched"


def test_html_tints_the_changed_words():
    h = markdown_to_html(format_export_markdown(_data(PATCH)))
    assert "<del " in h and ">2</del>" in h
    assert "<ins " in h and ">3</ins>" in h


def test_text_shows_was_now_with_carets_above_the_patch():
    text = format_export_text(_data(PATCH))
    assert "7  was: y = 2" in text and "9  now: y = 3" in text
    assert "add:     widths = []" in text
    assert text.index("What changed") < text.index("Patch (save as")
    lines = text.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.endswith("now: y = 3"))
    assert lines[i + 1].strip() == "^"
    assert lines[i + 1].index("^") == lines[i].index("3"), "caret sits under the change"
