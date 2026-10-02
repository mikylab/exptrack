"""The readable export forms the CLI and the dashboard share.

`core/export_render.py` is the one renderer for the aligned-text export, the
comparison document and markdown -> HTML. These pin what each produces and
that the CLI and the dashboard routes hand back the same text.
"""
from __future__ import annotations

from types import SimpleNamespace

from test_export_readable import FULL

from exptrack.core.export_render import (
    format_comparison_markdown,
    format_export_text,
    html_document,
    markdown_to_html,
    render_runs,
)

PAIR = [
    {"id": "a1", "name": "runA", "status": "done", "script": "train.py",
     "params": {"lr": 0.1, "layers": 4, "_internal": 1},
     "metrics": {"loss": 0.5, "acc": 0.9}},
    {"id": "b2", "name": "runB", "status": "failed", "script": "train.py",
     "params": {"lr": 0.2, "layers": 4}, "metrics": {"loss": 0.25, "acc": 0.8}},
]


# ── text ────────────────────────────────────────────────────────────────────

def test_text_carries_every_field_and_one_changed_line_per_line():
    text = format_export_text(FULL)
    for needle in ["abc123def456", "3.11.14", "baseline, v2", "2 (tune)",
                   "0.41531109885139955", r"C:\proj\outputs\run\loss.png",
                   "first line", "second line", "Artifacts saved"]:
        assert needle in text, needle
    assert "    + lr = args.lr" in text
    assert "    - lr = 0.01" in text
    assert "\\n" not in text, "code changes must not come out JSON-escaped"


def test_text_columns_line_up():
    lines = format_export_text(FULL).splitlines()
    status = next(ln for ln in lines if ln.strip().startswith("Status"))
    created = next(ln for ln in lines if ln.strip().startswith("Created"))
    assert status.index("done") == created.index("2026")


# ── comparison ──────────────────────────────────────────────────────────────

def test_comparison_names_runs_splits_params_and_bolds_the_best():
    md = format_comparison_markdown(PAIR, ["lr"])
    assert "| 1 | runA | `a1` | done | `train.py` |" in md
    assert "| lr | 0.1 | 0.2 |" in md
    assert "## Parameters held constant" in md and "| layers | 4 |" in md
    assert "_internal" not in md
    # Polarity-aware: the lower loss and the higher accuracy are the best.
    assert "| loss | lower is better | 0.5 | **0.25** | -0.25 (-50.0%) |" in md
    assert "| acc | higher is better | **0.9** | 0.8 |" in md


def test_a_readers_polarity_override_decides_the_best():
    md = format_comparison_markdown(PAIR, ["lr"], goals={"acc": "min"})
    assert "| acc | lower is better | 0.9 | **0.8** |" in md


def test_a_comparison_of_three_has_no_pairwise_change_column():
    three = [*PAIR, dict(PAIR[0], id="c3", name="runC")]
    assert "Change (2 vs 1)" not in format_comparison_markdown(three, ["lr"])


def test_missing_picks_are_stated():
    md = format_comparison_markdown(PAIR, ["lr"], unknown=["zzz"])
    assert "Comparing 2 of 3 chosen runs; not found: `zzz`" in md


# ── HTML ────────────────────────────────────────────────────────────────────

def test_html_renders_tables_with_inline_styles_and_right_alignment():
    h = markdown_to_html("| Metric | Last |\n| --- | ---: |\n| loss | 0.5 |")
    assert h.startswith("<table ") and "border:1px solid" in h
    assert "text-align:right\">0.5</td>" in h


def test_html_unescapes_pipes_and_renders_code_bold_headings():
    h = markdown_to_html("# T\n\n| a | b |\n| --- | --- |\n| `x \\| y` | **z** |")
    assert "<h1>T</h1>" in h
    assert ">x | y</code>" in h
    assert "<b>z</b>" in h


def test_html_escapes_everything_it_was_given():
    h = markdown_to_html("<script>alert(1)</script>\n\n| a |\n| --- |\n| <img src=x> |")
    assert "<script>" not in h and "<img" not in h
    assert "&lt;script&gt;" in h


def test_html_tints_diff_lines():
    h = markdown_to_html("```diff\n+new\n-old\n context\n```")
    assert "#e6ffec" in h and "#ffebe9" in h and "+new" in h and "-old" in h


def test_every_markdown_value_reaches_the_html():
    from exptrack.core.queries import format_export_markdown
    h = markdown_to_html(format_export_markdown(FULL))
    for needle in ["abc123def456", "0.41531109885139955", r"C:\proj\outputs\run\loss.png",
                   "lr = args.lr"]:
        assert needle in h, needle


def test_an_html_page_is_ascii_so_a_redirect_cannot_mangle_it():
    page = html_document("run — x", "<p>Δ …</p>")
    page.encode("ascii")
    assert "&#916;" in page


def test_render_runs_joins_a_batch_per_format():
    two = [FULL, dict(FULL, id="zzz999", name="other")]
    assert "\n\n---\n\n" in render_runs(two, "markdown")
    assert "=" * 60 in render_runs(two, "text")
    page = render_runs(two, "html")
    # A run-break rule: a rule on screen, a page break when printed.
    assert page.startswith("<!doctype html>") and '<hr class="run-break">' in page


def test_the_html_page_prints_as_a_report():
    """The PDF path is the browser's Save as PDF from this page: header rows
    repeated, no row split across pages, short sections two-up."""
    two = [FULL, dict(FULL, id="zzz999", name="other")]
    page = render_runs(two, "html")
    assert "@media print" in page and "<thead>" in page and "display: table-header-group" in page
    # Short sections sit two-up, and long cell content wraps inside the page.
    assert 'class="run-cols"' in page and "overflow-wrap: anywhere" in page
    assert "window.print()" in page and 'class="no-print"' in page


# ── the CLI and the routes print the same thing ─────────────────────────────

def _run(tmp_project):
    from exptrack.core import Experiment
    exp = Experiment(script="train.py", params={"lr": 0.01})
    exp.log_metric("loss", 0.5, step=0)
    exp.finish()
    return exp


def test_cli_text_and_html_match_the_dashboard_route(tmp_project, capsys):
    from exptrack.cli.inspect_cmds import cmd_export
    from exptrack.core import get_db
    from exptrack.dashboard.routes.read_routes import api_export

    exp = _run(tmp_project)
    for fmt in ("text", "html"):
        cmd_export(SimpleNamespace(id=exp.id, format=fmt, export_all=False,
                                   full=False, max_artifacts=None))
        printed = capsys.readouterr().out
        served = api_export(get_db(), exp.id, {"format": fmt})["content"]
        assert printed == served, fmt


def test_cli_compare_markdown_matches_the_dashboard_document(tmp_project, capsys):
    from exptrack.cli.inspect_cmds import cmd_compare
    from exptrack.core import Experiment, get_db
    from exptrack.dashboard.routes.write_routes import api_multi_compare

    a = _run(tmp_project)
    b = Experiment(script="train.py", params={"lr": 0.02})
    b.log_metric("loss", 0.25, step=0)
    b.finish()
    cmd_compare(SimpleNamespace(id1=a.id, id2=b.id, ids=[], seq1=None, seq2=None,
                                format="markdown", best=False))
    printed = capsys.readouterr().out
    served = api_multi_compare(get_db(), {"ids": [a.id, b.id], "document": True})
    assert printed == served["markdown"]
    assert served["html"].startswith("<h1>")


def test_the_diff_export_route_carries_html():
    from exptrack.core.export_render import markdown_to_html
    from exptrack.core.queries import format_diff_markdown
    md = format_diff_markdown("r", "id", "main", "c", "diff --git a/x b/x\n+y")
    assert "<table" in markdown_to_html(md) and "<pre" in markdown_to_html(md)


# ── a run's notes ───────────────────────────────────────────────────────────
# Notes are markdown a person wrote in the dashboard's editor: Tab-indented
# sub-points, numbered steps and `- [ ]` tasks. Each export must keep that
# structure rather than flatten it or show it as syntax.

NOTES = """# Question
Does label smoothing help at `noise=0.2`?

## Result
- best_val_acc **+0.0065**
  - seed 0 only
- second point
1. rerun with seeds
2. compare
- [ ] try ls=0.4
- [x] baseline
> looks like noise
```
# a comment, not a heading
```"""


def test_html_nests_indented_list_items():
    h = markdown_to_html("- a\n  - b\n    - c\n- d")
    assert h == "<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li><li>d</li></ul>"


def test_html_numbered_list_is_its_own_list_and_keeps_its_start():
    h = markdown_to_html("- a\n3. three\n4. four")
    assert h == '<ul><li>a</li></ul><ol start="3"><li>three</li><li>four</li></ol>'


def test_html_tasks_quotes_and_rules():
    h = markdown_to_html("- [ ] todo\n- [x] done\n\n> said\n\n---")
    assert "<li>☐ todo</li><li>☑ done</li>" in h
    assert "<blockquote" in h and ">said</blockquote>" in h
    assert "<hr>" in h


def test_a_changed_line_outside_a_fence_is_not_a_list():
    assert "<ul>" not in markdown_to_html("+ added line")


def test_notes_headings_nest_under_the_exports_notes_section():
    from exptrack.core.export_render import nest_headings
    out = nest_headings(NOTES, 3)
    assert "### Question" in out and "#### Result" in out
    assert "\n# a comment, not a heading\n" in out, "fenced lines are not headings"
    assert nest_headings("### deep\ntext", 3) == "### deep\ntext"


def test_markdown_export_keeps_notes_below_their_section(tmp_project):
    from exptrack.core.queries import format_export_markdown
    md = format_export_markdown({**FULL, "notes": NOTES})
    notes = md[md.index("## Notes"):]
    assert notes.startswith("## Notes\n\n### Question")
    assert "\n  - seed 0 only\n" in notes, "indentation is structure"


def test_text_export_reads_notes_without_their_syntax():
    text = format_export_text({**FULL, "notes": NOTES})
    body = text[text.index("Notes"):]
    for needle in ["  Question\n  --------", "  Result\n", "    - seed 0 only",
                   "  [ ] try ls=0.4", "  Does label smoothing help at noise=0.2?",
                   "      # a comment, not a heading"]:
        assert needle in body, needle
    assert "## Result" not in body and "**" not in body


def test_the_notes_copy_format_is_the_notes_and_their_html(tmp_project):
    from exptrack.core import get_db
    from exptrack.core.queries import replace_notes
    from exptrack.dashboard.routes.read_routes import api_export

    exp = _run(tmp_project)
    replace_notes(get_db(), exp.id, NOTES)
    got = api_export(get_db(), exp.id, {"format": "notes-md"})
    assert got["notes_text"] == NOTES
    assert got["html"] == markdown_to_html(NOTES)
    assert "<ol>" in got["html"] and "☐ try ls=0.4" in got["html"]
