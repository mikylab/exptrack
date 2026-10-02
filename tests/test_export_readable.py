"""The markdown export is laid out as tables, and still carries everything.

It was one bold-label line per field, raw floats, a bare bullet per artifact
and — the worst of it — a run's changed lines as a single ``+ a; - b; + c``
string inside a diff fence, so every changed line of the script read as one
paragraph. The dashboard's Copy now puts an HTML rendering of this beside it on
the clipboard, so OneNote/Word receive real tables; these tests pin the text
both are built from.

The constraint that shaped it: nothing the old layout exported may be lost.
"""
from __future__ import annotations

from exptrack.core.queries import (
    format_diff_markdown,
    format_export_markdown,
)
from exptrack.core.utils import split_changed_lines, summarize_changed_lines

FULL = {
    "id": "abc123def456", "name": "Sep24_train__lr0.02", "status": "done",
    "created_at": "2026-09-24T15:20:03+00:00", "duration_s": 1.0812897682189941,
    "script": r"C:\proj\train.py", "command": r"python C:\proj\train.py --lr 0.02",
    "python_ver": "3.11.14", "git_branch": "main", "git_commit": "1a2b3c4",
    "hostname": "box", "tags": ["baseline", "v2"], "studies": ["sweep"],
    "stage": 2, "stage_name": "tune", "output_dir": r"C:\proj\outputs\run",
    "project": "proj", "notes": "first line\nsecond line",
    "params": {"lr": 0.02, "optimizer": "adam", "layers": "4"},
    "variables": {"batch": 32},
    "metrics": {"loss": {"last": 0.41531109885139955, "min": 0.4153, "max": 1.04,
                         "count": 50}},
    "artifacts": [{"label": "loss.png", "path": r"C:\proj\outputs\run\loss.png"}],
    "artifacts_summary": {"total": 1, "listed": 1, "omitted": 0,
                          "by_type": [], "by_dir": []},
    "code_changes": {"script": "+ lr = args.lr; - lr = 0.01"},
    "timeline_summary": {"total_events": 7, "cell_executions": 1,
                         "variable_sets": 0, "artifact_events": 6},
}


def test_every_field_the_old_layout_exported_is_still_there():
    md = format_export_markdown(FULL)
    for needle in ["abc123def456", "done", "2026-09-24T15:20:03+00:00",
                   r"C:\proj\train.py", "--lr 0.02", "3.11.14", "main", "1a2b3c4",
                   "box", "baseline, v2", "sweep", "2 (tune)", r"C:\proj\outputs\run",
                   "proj", "first line", "second line", "adam", "32",
                   "0.41531109885139955", "1.04", "50", "loss.png",
                   r"C:\proj\outputs\run\loss.png", "lr = args.lr", "lr = 0.01",
                   "Total events | 7", "Artifacts saved | 6"]:
        assert needle in md, needle


def test_metric_values_keep_full_precision():
    """Rounding would lose data the export used to carry."""
    assert "| loss | 0.41531109885139955 | 0.4153 | 1.04 | 50 |" in format_export_markdown(FULL)


def test_a_windows_path_is_not_doubled():
    """Backslash escapes do not apply inside a code span."""
    md = format_export_markdown(FULL)
    assert r"`C:\proj\train.py`" in md
    assert "\\\\" not in md


def test_changed_lines_are_one_row_each():
    md = format_export_markdown(FULL)
    assert "| + | `lr = args.lr` |" in md
    assert "| - | `lr = 0.01` |" in md
    assert "1 added, 1 removed" in md
    assert "```diff" not in md


def test_a_pipe_in_a_value_does_not_shear_the_table():
    data = dict(FULL, params={"expr": "a|b"},
                code_changes={"script": "+ x = a | b"})
    md = format_export_markdown(data)
    assert "| expr | a\\|b |" in md
    assert "`x = a \\| b`" in md


def test_a_string_that_reads_as_another_type_keeps_its_quotes():
    md = format_export_markdown(FULL)
    assert "| optimizer | adam |" in md, "a plain string prints bare"
    assert '| layers | "4" |' in md, "the string '4' must not read as the number 4"


def test_the_duration_is_rounded_only_to_the_millisecond():
    assert "| Duration | 1.081 s |" in format_export_markdown(FULL)
    long = format_export_markdown(dict(FULL, duration_s=3725.4))
    assert "3725.400 s (1 h 2 m 5 s)" in long


def test_split_changed_lines_round_trips_the_summary():
    frags = ["+ a = 1; b = 2", "- c", "+ ", "+ d"]
    lines, note = split_changed_lines(summarize_changed_lines(frags))
    assert lines == [("+", "a = 1; b = 2"), ("-", "c"), ("+", ""), ("+", "d")]
    assert note == ""


def test_split_changed_lines_keeps_the_truncation_marker():
    s = summarize_changed_lines(["+ " + "x" * 30] * 10, max_chars=70)
    lines, note = split_changed_lines(s)
    assert note.startswith("… [truncated") and "of 10 changed lines" in note
    assert len(lines) == 2
    assert "truncated" in format_export_markdown(dict(FULL, code_changes={"script": s}))


def test_a_non_fragment_code_change_is_kept_verbatim():
    md = format_export_markdown(dict(FULL, code_changes={"cell_3": "free text"}))
    assert "free text" in md


def test_the_diff_document_leads_with_a_per_file_table_and_keeps_the_diff():
    diff = ("diff --git a/model.py b/model.py\n--- a/model.py\n+++ b/model.py\n"
            "+new\n+new2\n-old\n"
            "diff --git a/data.py b/data.py\n+x\n")
    md = format_diff_markdown("run", "abc", "main", "123", diff)
    assert "# Diff: run" in md
    assert "| `model.py` | 2 | 1 |" in md
    assert "| `data.py` | 1 | 0 |" in md
    # One patch block per file, together the whole diff, nothing rewritten.
    blocks = [b.split("\n```")[0] for b in md.split("```diff\n")[1:]]
    assert "\n".join(blocks) == diff.rstrip("\n")


def test_a_diff_sentinel_is_stated_not_fenced():
    from exptrack.core.db import COMPACT_PREFIX
    md = format_diff_markdown("run", "abc", "", "", COMPACT_PREFIX + "x")
    assert "No diff body is available" in md
    assert "```diff" not in md
