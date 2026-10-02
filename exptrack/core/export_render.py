"""Readable renderings of an export: aligned text, a comparison, and HTML.

The markdown export (`queries.format_export_markdown`) is the source every
other human-readable form is built from or laid out alongside, and each one
lives here once so the CLI and the dashboard print the same thing:

* ``format_export_text`` — the "Plain text" export, aligned into columns.
  It used to be built in the browser only, so the terminal had no equivalent,
  and its code changes were ``JSON.stringify``'d — one line of ``\\n`` escapes.
* ``format_comparison_markdown`` — a comparison as tables. Compare had a CSV
  export and nothing a person could paste into a notebook.
* ``markdown_to_html`` — the markdown these produce, as HTML. OneNote, Word
  and Outlook do not render markdown; they read the HTML flavour of the
  clipboard. The dashboard's Copy puts this beside the markdown, so a paste
  there lands as real tables while a markdown editor still gets the text.

Nothing is dropped in any of them: every value the markdown carries appears
in the text and in the HTML, at full precision.
"""
from __future__ import annotations

import html as _html
import re

from .primary_metric import goal_for_key
from .queries import (
    _fmt_duration,
    _md_cell,
    _md_code,
    _md_table,
    _md_value,
    export_metric_summaries,
    metric_table,
    single_value_metrics,
)
from .utils import is_user_param_key, split_changed_lines

# ── Aligned plain text ──────────────────────────────────────────────────────


def _text_table(header: list[str], rows: list[list], indent: str = "  ",
                align: str = "") -> list[str]:
    """Rows padded into columns — the plain-text stand-in for a table.

    *align* has one ``l``/``r`` per column; numbers read best right-aligned.
    """
    cells = [[str(c) for c in header]] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]

    def pad(i, c):
        return c.rjust(widths[i]) if align[i:i + 1] == "r" else c.ljust(widths[i])

    def line(r):
        return (indent + "  ".join(pad(i, c) for i, c in enumerate(r))).rstrip()
    return [line(cells[0]), indent + "  ".join("-" * w for w in widths)] + \
        [line(r) for r in cells[1:]]


def _text_fields(pairs: list[tuple[str, str]], indent: str = "  ") -> list[str]:
    width = max((len(k) for k, _ in pairs), default=0)
    return [f"{indent}{k.ljust(width)}  {v}" for k, v in pairs]


def _plain(v) -> str:
    return "--" if v is None else str(v)


def _section(title: str) -> list[str]:
    return [title, "-" * len(title)]


def _text_changed_rows(f: dict) -> list[str]:
    """One file's changed lines as ``was:``/``now:`` pairs, ``^`` under the
    words that changed — readable in any monospace paste, no colour needed."""
    from .diff_view import caret_line, changed_rows, word_segments
    rows = changed_rows(f["patch"])
    if not rows:
        return [f"  {f['path']}: no line changes (mode or rename only)", ""]
    width = max(len(str(r["old_no"] or r["new_no"] or "")) for r in rows)
    pad = " " * (width + 9)
    out = [f"  {f['path']}"]
    for r in rows:
        if r["old"] is not None and r["new"] is not None:
            olds, news = word_segments(r["old"], r["new"])
            out.append(f"  {str(r['old_no']).rjust(width)}  was: {r['old']}")
            if caret_line(olds):
                out.append(pad + caret_line(olds))
            out.append(f"  {str(r['new_no']).rjust(width)}  now: {r['new']}")
            if caret_line(news):
                out.append(pad + caret_line(news))
        elif r["old"] is not None:
            out.append(f"  {str(r['old_no']).rjust(width)}  del: {r['old']}")
        else:
            out.append(f"  {str(r['new_no']).rjust(width)}  add: {r['new']}")
    return [*out, ""]


def _text_code_changes(data: dict, patch: bool = True) -> list[str]:
    """Code changes as a table of where each file changed, then the patch.

    The patch is the run's diff verbatim and unindented, so it can be copied
    out and applied with ``git apply``; the table says which lines of the
    committed file each change replaces, and links there when the repository
    is on a known host. Falls back to the stored changed-line fragments only
    when there is no diff.
    """
    from .git import commit_web_url, file_web_url, parse_diff_files
    from .queries import _diff_where
    links, sha = data.get("git_web"), data.get("git_commit") or ""
    diff = data.get("git_diff") or ""
    changes = dict(data.get("code_changes") or {})
    out: list[str] = []
    if diff.strip():
        changes.pop("script", None)
        parsed = parse_diff_files(diff)
        files = parsed["files"]
        out += _section("Code changes")
        if files:
            added = sum(f["added"] for f in files)
            removed = sum(f["removed"] for f in files)
            against = sha or "the last commit"
            out.append(f"  Uncommitted changes against {against}: {len(files)} "
                       f"file{'s' if len(files) != 1 else ''}, {added} added, "
                       f"{removed} removed.")
            if commit_web_url(links, sha):
                out.append(f"  {commit_web_url(links, sha)}")
            out.append("")
            where = f"Lines at {sha}" if sha else "Lines in the committed file"
            out += _text_table(
                ["File", "Added", "Removed", where],
                [[f["path"] + ("" if f["status"] == "modified" else f" ({f['status']})"),
                  f["added"], f["removed"],
                  ", ".join(_diff_where(f, links, sha, as_md=False)) or "--"]
                 for f in files], align="lrrl")
            urls = []
            for f in files:
                if not f["hunks"] or f["status"] == "added":
                    continue
                h = f["hunks"][0]
                url = file_web_url(links, sha, f["old_path"], h["old_start"],
                                   h["old_start"] + max(h["old_len"], 1) - 1)
                if url:
                    urls.append((f["path"], url))
            if urls:
                out += ["", *_text_fields(urls)]
            out += ["", *_section("What changed")]
            for f in files:
                out += _text_changed_rows(f)
            if not patch:
                from .queries import PATCH_OMITTED_NOTE
                out += ["", "  " + PATCH_OMITTED_NOTE.replace("**", "").replace("`", "'")]
            else:
                out += [*_section("Patch (save as a .patch file and run "
                                  "'git apply <file>' from the repository root)")]
                out += [f["patch"] for f in files]
            if patch and parsed["trailer"]:
                out.append(parsed["trailer"])
        else:
            out.append(diff)
        out.append("")
    elif changes or data.get("git_diff_status"):
        out += _section("Code changes")
        if data.get("git_diff_status"):
            out += [f"  The full diff is not available ({data['git_diff_status']}); "
                    "these are the changed lines recorded for the script, without "
                    "line numbers or indentation.", ""]
    for name_, summary in changes.items():
        changed, note = split_changed_lines(summary)
        added = sum(1 for s_, _ in changed if s_ == "+")
        removed = sum(1 for s_, _ in changed if s_ == "-")
        out.append(f"  {name_}: {added} added, {removed} removed"
                   + (f"; {note}" if note else ""))
        out += [f"    {sign or ' '} {text}" for sign, text in changed]
        out.append("")
    return out


def format_export_text(data: dict, patch: bool = True) -> str:
    """One run as aligned plain text: every field the markdown export has.

    Paths are shown relative to the project root, which is stated once: the
    same long absolute prefix on every line was most of what made this hard
    to read.
    """
    from .git import commit_web_url
    from .queries import _rel_command, _rel_path_for
    root = data.get("project_root") or ""
    sha = data.get("git_commit") or ""
    fields = [("ID", data.get("id", "")), ("Status", data.get("status", ""))]
    if data.get("created_at"):
        fields.append(("Created", data["created_at"]))
    if data.get("duration_s"):
        fields.append(("Duration", _fmt_duration(data["duration_s"])))
    if root:
        fields.append(("Project root", root))
    if data.get("script"):
        fields.append(("Script", _rel_path_for(data["script"], root)))
    if data.get("command"):
        fields.append(("Command" + (" (from root)" if root else ""),
                       _rel_command(data["command"], root)))
    if data.get("python_ver"):
        fields.append(("Python", data["python_ver"]))
    if data.get("git_branch"):
        fields.append(("Branch", data["git_branch"]))
    if sha:
        url = commit_web_url(data.get("git_web"), sha)
        fields.append(("Commit", sha + (f"  {url}" if url else "")))
    if data.get("hostname"):
        fields.append(("Hostname", data["hostname"]))
    if data.get("tags"):
        fields.append(("Tags", ", ".join(data["tags"])))
    if data.get("studies"):
        fields.append(("Studies", ", ".join(data["studies"])))
    if data.get("stage") is not None:
        stage = str(data["stage"])
        if data.get("stage_name"):
            stage += f" ({data['stage_name']})"
        fields.append(("Stage", stage))
    if data.get("output_dir"):
        fields.append(("Output dir", _rel_path_for(data["output_dir"], root)))
    if data.get("project"):
        fields.append(("Project", data["project"]))

    name = data.get("name", "")
    lines = [name, "=" * max(len(name), 3), "", *_text_fields(fields), ""]
    if data.get("notes"):
        lines += [*_section("Notes"), *(("  " + n).rstrip() for n in notes_plain(data["notes"])), ""]
    for title, key in (("Parameters", "params"), ("Variables", "variables")):
        if data.get(key):
            lines += _section(title)
            lines += _text_fields([(str(k), _md_value(v)) for k, v in data[key].items()])
            lines.append("")
    summaries = export_metric_summaries(data)
    if summaries:
        lines += _section("Metrics")
        header, rows, align = metric_table(summaries, _plain)
        lines += _text_table(header, rows, align=align)
        lines.append("")
    art = data.get("artifacts_summary")
    shown = data.get("artifacts") or []
    if art or shown:
        total = art["total"] if art else len(shown)
        lines += _section(f"Artifacts ({total})")
        if art and art.get("omitted"):
            lines.append("  " + ", ".join(f"{t['count']} {t['type']}" for t in art["by_type"]))
            for d in art["by_dir"][:5]:
                lines.append(f"  {d['count']:>6} in {_rel_path_for(d['dir'], root)}")
            lines.append("")
        lines += _text_fields([(a["label"], _rel_path_for(a["path"], root)) for a in shown])
        if art and art.get("omitted"):
            lines.append(f"  ... and {art['omitted']} more "
                         "(`exptrack export --full` for the complete list)")
        lines.append("")
    env = data.get("environment") or {}
    if env:
        lines += _section("Environment")
        lines += _text_fields([("Python", f"{env.get('implementation', '')} "
                                          f"{env.get('python', '')}".strip()),
                               ("Platform", env.get("platform") or "--"),
                               *((k, v) for k, v in (env.get("packages") or {}).items())])
        lines.append("")
    ts = data.get("timeline_summary") or {}
    if ts.get("total_events"):
        lines += _section("Timeline")
        lines += _text_fields([("Total events", ts["total_events"]),
                               ("Cell executions", ts.get("cell_executions", 0)),
                               ("Variable changes", ts.get("variable_sets", 0)),
                               ("Artifacts saved", ts.get("artifact_events", 0))])
        lines.append("")
    # Last, so the patch runs to the end of the document and copies in one go.
    lines += _text_code_changes(data, patch)
    return "\n".join(lines).rstrip() + "\n"


# ── A comparison ────────────────────────────────────────────────────────────


def _delta(a, b) -> str:
    """``+0.343 (+474.2%)`` from *a* to *b*, or '' when either is missing."""
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return ""
    d = b - a
    if not d:
        return "="
    pct = f" ({d / abs(a) * 100:+.1f}%)" if a else ""
    return f"{d:+.6g}{pct}"


def runs_code_diff(code: dict) -> str:
    """`compare_run_code`'s file pairs as one git-style unified diff.

    The Compare view renders these pairs as its Code changes panel; the
    comparison document had no code at all. Built with the stdlib's difflib
    under ``diff --git a/<file> b/<file>`` headers so the same per-file
    renderer as a run's own diff applies — and so the result applies with
    ``git apply`` to a checkout holding the older run's code.
    """
    import difflib
    parts = []
    for cell in (code or {}).get("cells") or []:
        label = str(cell.get("label") or f"cell {cell.get('pos')}").replace("\\", "/")
        a = str(cell.get("a") or "").splitlines()
        b = str(cell.get("b") or "").splitlines()
        body = list(difflib.unified_diff(a, b, f"a/{label}", f"b/{label}", lineterm=""))
        if body:
            parts.append("\n".join([f"diff --git a/{label} b/{label}", *body]))
    return "\n".join(parts)


def format_comparison_markdown(exps: list[dict], varying: list[str],
                               basis: str = "final", goals: dict | None = None,
                               unknown: list[str] | None = None,
                               code: dict | None = None, patch: bool = True) -> str:
    """A comparison — the rows `get_multi_compare` returns — as markdown tables.

    What the Compare view shows, in the order it shows it: which runs, the
    parameters that differ (and, separately, the ones held constant), then one
    row per metric with the best run in bold under the metric's own goal and a
    delta column for a pair. The dashboard's Copy/Export and
    `exptrack compare --format markdown` both call this.
    """
    goals = goals or {}
    spans = len({e.get("project_id") or "" for e in exps}) > 1
    n = len(exps)
    basis_label = "best value" if basis == "best" else "final value"
    lines = [f"# Comparison: {n} runs ({basis_label})", ""]
    if unknown:
        lines += [f"Comparing {n} of {n + len(unknown)} chosen runs; not found: "
                  + ", ".join(_md_code(u) for u in unknown), ""]

    head = ["#", "Run", "ID", "Status", "Script"] + (["Project"] if spans else [])
    rows = []
    for i, e in enumerate(exps, 1):
        row = [i, _md_cell(e.get("name") or ""), _md_code(e.get("id", "")),
               e.get("status") or "", _md_cell(_md_code(e.get("script") or ""))]
        if spans:
            row.append(_md_cell(e.get("project_name") or e.get("project_id") or ""))
        rows.append(row)
    lines += ["## Runs", "", *_md_table(head, rows, "r"), ""]

    cols = [f"{i}. {_md_cell(e.get('name') or e.get('id', ''))}" for i, e in enumerate(exps, 1)]
    params = [e.get("params") or {} for e in exps]

    def pv(p, k):
        return _md_cell(_md_value(p[k])) if k in p else "--"

    if varying:
        lines += ["## Parameters that differ", ""]
        lines += _md_table(["Parameter", *cols],
                           [[_md_cell(k), *[pv(p, k) for p in params]] for k in varying])
        lines.append("")
    constant = sorted({k for p in params for k in p
                       if is_user_param_key(k) and k not in varying})
    if constant:
        lines += ["## Parameters held constant", ""]
        lines += _md_table(["Parameter", "Value"],
                           [[_md_cell(k), pv(next(p for p in params if k in p), k)]
                            for k in constant])
        lines.append("")

    metric_keys = sorted({k for e in exps for k in (e.get("metrics") or {})})
    if metric_keys:
        pair = n == 2
        lines += ["## Metrics", ""]
        mrows = []
        for k in metric_keys:
            vals = [(e.get("metrics") or {}).get(k) for e in exps]
            goal = goals.get(k) or goal_for_key(k)
            nums = [v for v in vals if isinstance(v, (int, float))]
            best = (min(nums) if goal == "min" else max(nums)) if len(nums) > 1 else None
            cells = [("--" if v is None else (f"**{v}**" if v == best else str(v)))
                     for v in vals]
            row = [_md_cell(k), "lower is better" if goal == "min" else "higher is better",
                   *cells]
            if pair:
                row.append(_delta(vals[0], vals[1]))
            mrows.append(row)
        head = ["Metric", "Goal", *cols] + (["Change (2 vs 1)"] if pair else [])
        lines += _md_table(head, mrows, "ll" + "r" * (len(head) - 2))
        lines += ["", "Best value per metric in **bold**."]
        merged = {}
        for e in exps:
            for canon, spellings in (e.get("merged_metric_keys") or {}).items():
                merged.setdefault(canon, set()).update(spellings)
        if merged:
            lines += ["", "Merged metric names: " + "; ".join(
                f"{_md_code(c)} from " + ", ".join(_md_code(s) for s in sorted(sp))
                for c, sp in sorted(merged.items()))]
        lines.append("")
    lines += _comparison_code_section(exps, code, patch)
    return "\n".join(lines).rstrip() + "\n"


def _comparison_code_section(exps: list[dict], code: dict | None,
                             patch: bool = True) -> list[str]:
    """The pair's code diff, last so its patches copy in one go.

    Pairwise by nature: over three runs "the diff" has no single base, so the
    section says how to get one rather than inventing it.
    """
    from .queries import _md_diff_section
    if len(exps) != 2:
        return ["## Code changes", "",
                "A code diff is between two runs: compare a pair "
                "(`exptrack compare <a> <b> --format markdown`) to include one.", ""]
    if code is None:
        return []
    diff = runs_code_diff(code)
    if not diff:
        return ["## Code changes", "", "No code change between these runs.", ""]
    names = {e.get("id"): e.get("name") or e.get("id") for e in exps}
    older = names.get(code.get("base_id"), "the older run")
    newer = names.get(code.get("new_id"), "the newer run")
    intro = f"Code changes from {_md_cell(older)} (older) to {_md_cell(newer)} (newer)"
    return ["## Code changes", "",
            *_md_diff_section(diff, None, "", "###", intro=intro,
                              where="Lines in the older run", patch=patch)]


# ── Markdown → HTML ─────────────────────────────────────────────────────────
# The subset the renderers above and in queries.py produce — headings, pipe
# tables with alignment, fenced code (diff lines tinted), bullets, paragraphs,
# **bold**, _italic_ and `code` — plus what a person writes in a run's notes:
# nested and numbered lists, `- [ ]` tasks, `>` quotes and `---` rules. Styles are inline because that is
# all a paste target keeps — OneNote and Word drop <style> blocks. The colours
# are literal for the same reason: the dashboard's CSS tokens do not exist in
# the document the HTML lands in.

_TABLE = 'style="border-collapse:collapse;margin:4px 0 10px"'
_CELL = "border:1px solid #c8c8c8;padding:3px 8px;vertical-align:top"
_TH = f'style="{_CELL};background:#f0f0f0;text-align:{{a}}"'
_TD = f'style="{_CELL};text-align:{{a}}"'
# pre-wrap: a changed line's indentation is part of what it says.
_CODE = 'style="font-family:Consolas,Menlo,monospace;font-size:92%;white-space:pre-wrap"'
_PRE = ('style="font-family:Consolas,Menlo,monospace;font-size:90%;background:#f6f8fa;'
        'border:1px solid #d0d7de;padding:6px 8px;white-space:pre-wrap;margin:4px 0 10px"')
_DIFF_ADD = 'style="background:#e6ffec;color:#116329"'
_DIFF_DEL = 'style="background:#ffebe9;color:#a40e26"'

_SPLIT_CELLS = re.compile(r"(?<!\\)\|")
# `+` is not a bullet here: a changed line reads `+ added`, and one that
# landed outside a fence must stay a line, not become a list.
_LIST_ITEM = re.compile(r"^(\s*)([-*]|(\d{1,9})[.)])\s+(.*)$")
_TASK = re.compile(r"^\[([ xX])\](?:\s+(.*))?$")
_RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_FENCE_OPEN = re.compile(r"^(`{3,})(\w*)\s*$")
_QUOTE = ('style="border-left:3px solid #d0d7de;margin:4px 0 10px;padding:0 10px;'
          'color:#57606a"')


_LINK = re.compile(r"\[((?:`[^`]*`|[^\]])+)\]\((https?://[^)\s]+)\)")
_A = 'style="color:#0969da"'


def _inline(text: str) -> str:
    """Links, code spans, bold and italic in one line of markdown, escaped.

    Only http(s) link targets are recognised, so nothing an export carries
    can become a ``javascript:`` link in the pasted document.
    """
    out, i = [], 0
    for m in _LINK.finditer(text):
        out.append(_inline_code(text[i:m.start()]))
        href = _html.escape(m.group(2), quote=True)
        out.append(f'<a href="{href}" {_A}>{_inline_code(m.group(1))}</a>')
        i = m.end()
    out.append(_inline_code(text[i:]))
    return "".join(out)


# A code span wrapped in ~~ or ** is a word the "What changed" view marks as
# removed or added; the paste target gets it tinted like the diff lines.
_CODE_SPAN = re.compile(r"(\*\*|~~)?(`+)(.+?)\2(?(1)\1)")
_WORD_DEL = ('style="font-family:Consolas,Menlo,monospace;font-size:92%;'
             'background:#ffc1c0;color:#82071e;text-decoration:line-through;'
             'white-space:pre-wrap"')
_WORD_ADD = ('style="font-family:Consolas,Menlo,monospace;font-size:92%;'
             'background:#abf2bc;color:#044f1e;font-weight:600;white-space:pre-wrap"')


def _inline_code(text: str) -> str:
    out, i = [], 0
    for m in _CODE_SPAN.finditer(text):
        out.append(_emphasis(text[i:m.start()]))
        code = m.group(3)
        if code.startswith(" ") and code.endswith(" ") and code.strip():
            code = code[1:-1]
        style = {"~~": _WORD_DEL, "**": _WORD_ADD}.get(m.group(1) or "", _CODE)
        tag = {"~~": "del", "**": "ins"}.get(m.group(1) or "", "code")
        out.append(f"<{tag} {style}>{_html.escape(code)}</{tag}>")
        i = m.end()
    out.append(_emphasis(text[i:]))
    return "".join(out)


def _emphasis(text: str) -> str:
    s = _html.escape(text)
    s = s.replace("&lt;br&gt;", "<br>")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w])_(\S(?:.*?\S)?)_(?![\w])", r"<i>\1</i>", s)
    return s


def _cells(row: str) -> list[str]:
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip().replace("\\|", "|") for c in _SPLIT_CELLS.split(body)]


def _is_separator(row: str) -> bool:
    """The ``| --- | ---: |`` row that makes the line above it a table header."""
    cells = _cells(row) if row.strip().startswith("|") else []
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def _table_html(rows: list[str]) -> str:
    head, aligns = _cells(rows[0]), []
    for spec in _cells(rows[1]):
        aligns.append("right" if spec.endswith(":") and not spec.startswith(":")
                      else "center" if spec.startswith(":") and spec.endswith(":")
                      else "left")
    # <thead>/<tbody>: a printed table repeats its header row on each page
    # only when that row is a <thead>.
    out = [f"<table {_TABLE}><thead><tr>"]
    out += [f"<th {_TH.format(a=aligns[i] if i < len(aligns) else 'left')}>{_inline(c)}</th>"
            for i, c in enumerate(head)]
    out.append("</tr></thead><tbody>")
    for r in rows[2:]:
        cells = _cells(r)
        out.append("<tr>" + "".join(
            f"<td {_TD.format(a=aligns[i] if i < len(aligns) else 'left')}>{_inline(c)}</td>"
            for i, c in enumerate(cells)) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _pre_html(lang: str, body: list[str]) -> str:
    if lang == "diff":
        rendered = []
        for ln in body:
            esc = _html.escape(ln)
            if ln.startswith("+") and not ln.startswith("+++"):
                rendered.append(f"<span {_DIFF_ADD}>{esc}</span>")
            elif ln.startswith("-") and not ln.startswith("---"):
                rendered.append(f"<span {_DIFF_DEL}>{esc}</span>")
            else:
                rendered.append(esc)
        text = "\n".join(rendered)
    else:
        text = _html.escape("\n".join(body))
    return f"<pre {_PRE}>{text}</pre>"


def markdown_to_html(md: str) -> str:
    """An HTML fragment for *md*, styled inline so a paste keeps its look."""
    lines = str(md).split("\n")
    out: list[str] = []
    para: list[str] = []
    i = 0

    def flush():
        if para:
            out.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
            para.clear()

    while i < len(lines):
        ln = lines[i]
        fence = _FENCE_OPEN.match(ln)
        if fence:
            flush()
            end = fence.group(1)
            body, i = [], i + 1
            while i < len(lines) and lines[i].rstrip() != end:
                body.append(lines[i])
                i += 1
            out.append(_pre_html(fence.group(2), body))
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if ln.lstrip().startswith("|") and i + 1 < len(lines) and _is_separator(lines[i + 1]):
            flush()
            rows = [ln, lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table_html(rows))
            continue
        if _LIST_ITEM.match(ln):
            flush()
            items = []
            while i < len(lines) and _LIST_ITEM.match(lines[i]):
                items.append(_LIST_ITEM.match(lines[i]))
                i += 1
            out.append(_list_html(items))
            continue
        if ln.lstrip().startswith(">"):
            flush()
            quoted = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quoted.append(_inline(re.sub(r"^\s*>\s?", "", lines[i])))
                i += 1
            out.append(f"<blockquote {_QUOTE}>" + "<br>".join(quoted) + "</blockquote>")
            continue
        if _RULE.match(ln):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if not ln.strip():
            flush()
        else:
            para.append(ln.rstrip())
        i += 1
    flush()
    return "\n".join(out)


def _list_item_html(body: str) -> str:
    """One item's text; a `[ ]`/`[x]` task becomes a box a paste can show."""
    task = _TASK.match(body)
    if not task:
        return _inline(body)
    box = "☑" if task.group(1) in "xX" else "☐"
    return f"{box} {_inline(task.group(2) or '')}"


def _list_html(items: list[re.Match]) -> str:
    """Consecutive list lines as nested ``<ul>``/``<ol>``, by indentation.

    The notes editor indents with Tab, so a sub-point is its own list inside
    its parent's item — flattening it lost which point it belonged to.
    """
    out: list[str] = []
    stack: list[tuple[int, str]] = []   # (indent, tag) of each open list
    for m in items:
        indent = len(m.group(1).expandtabs(4))
        ordered = m.group(3) is not None
        tag = "ol" if ordered else "ul"
        while stack and indent < stack[-1][0]:
            out.append(f"</li></{stack.pop()[1]}>")
        if stack and indent == stack[-1][0] and stack[-1][1] != tag:
            out.append(f"</li></{stack.pop()[1]}>")   # `1.` after `-`: a new list
        if not stack or indent > stack[-1][0]:
            start = int(m.group(3)) if ordered else 1
            out.append(f'<{tag} start="{start}">' if start != 1 else f"<{tag}>")
            stack.append((indent, tag))
        else:
            out.append("</li>")
        out.append("<li>" + _list_item_html(m.group(4)))
    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return "".join(out)


def _fence_kinds(lines: list[str]) -> list[str]:
    """Per line: ``"fence"`` (an opening/closing marker), ``"code"`` or ``"text"``.

    The same rule `markdown_to_html` applies — a fence opens at column 0 and
    closes on an identical line — so the heading shift and the plain-text
    export can never read a line as code that the HTML export reads as text.
    """
    kinds, close = [], None
    for ln in lines:
        if close is None and (m := _FENCE_OPEN.match(ln)):
            close = m.group(1)
            kinds.append("fence")
        elif close is not None and ln.rstrip() == close:
            close = None
            kinds.append("fence")
        else:
            kinds.append("text" if close is None else "code")
    return kinds


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def nest_headings(md: str, top: int) -> str:
    """*md* with its headings shifted so the shallowest is level *top*.

    A run's notes sit under the export's own ``## Notes``; a ``# Result`` the
    user wrote there would otherwise outrank the section holding it, and a
    reader of the document takes the notes' headings for the run's sections.
    Lines inside a fenced block are not headings and are left alone.
    """
    lines = str(md).split("\n")
    heads = {i: h for i, (ln, kind) in enumerate(zip(lines, _fence_kinds(lines)))
             if kind == "text" and (h := _HEADING.match(ln))}
    shallowest = min((len(h.group(1)) for h in heads.values()), default=top)
    if shallowest >= top:
        return str(md)
    for i, h in heads.items():
        lines[i] = "#" * min(len(h.group(1)) + top - shallowest, 6) + " " + h.group(2)
    return "\n".join(lines)


def notes_plain(md: str) -> list[str]:
    """A run's notes as plain-text lines: the structure stays, the syntax goes.

    A heading is its text underlined (as `_section` underlines the export's
    own), bold and code markers drop, and a list keeps its indentation — a task
    reads `[ ] rerun`, not `- [ ] rerun`.
    """
    lines = str(md).splitlines()
    out = []
    for ln, kind in zip(lines, _fence_kinds(lines)):
        if kind != "text":
            if kind == "code":
                out.append("    " + ln)
            continue
        h = _HEADING.match(ln)
        text = re.sub(r"\*\*(.+?)\*\*|`([^`]+)`",
                      lambda m: m.group(1) or m.group(2), h.group(2) if h else ln)
        out += _section(text) if h else [re.sub(r"^(\s*)[-*]\s+(\[[ xX]\])", r"\1\2", text)]
    return out


# The page's own stylesheet: how the export reads in a browser and how it
# prints. A `<style>` block, not inline styles, because only a file opened in a
# browser uses it — a paste into OneNote or Word takes markdown_to_html's
# inline styles and drops this. Printing is the PDF path: exptrack writes no
# PDF itself (the package is stdlib-only), and a browser's Save as PDF from
# this page gives a cover summary, one run per page, header rows repeated on
# each page and no row split across two.
_PAGE_CSS = """
@page { size: A4; margin: 10mm 9mm 12mm; }
body { font-family: "Segoe UI", Helvetica, Arial, sans-serif; font-size: 14px;
  color: #1d2330; line-height: 1.45; max-width: 1120px; margin: 24px auto; padding: 0 20px; }
h1 { font-size: 22px; margin: 18px 0 8px; padding-bottom: 4px; border-bottom: 2px solid #2c5aa0;
  overflow-wrap: anywhere; }
h2 { font-size: 16px; margin: 16px 0 6px; color: #2c5aa0; }
h3 { font-size: 14px; margin: 12px 0 4px; }
.report-bar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between;
  font-size: 12px; color: #5f6878; border-bottom: 1px solid #dde1e8; padding-bottom: 8px; }
.report-bar button { font: inherit; font-size: 13px; padding: 5px 14px; cursor: pointer;
  border: 1px solid #2c5aa0; background: #2c5aa0; color: #fff; border-radius: 4px; }
hr.run-break { border: 0; border-top: 1px solid #dde1e8; margin: 28px 0; }
table { font-variant-numeric: tabular-nums; max-width: 100%; }
td, th { overflow-wrap: anywhere; }
.sec { min-width: 0; }
@media (min-width: 900px) {
  .run-cols { columns: 2; column-gap: 28px; }
  .run-cols .sec { break-inside: avoid; }
}
@media print {
  body { font-size: 9pt; line-height: 1.3; max-width: none; margin: 0; padding: 0; }
  .no-print { display: none !important; }
  .report-bar { font-size: 8pt; border-bottom: 1px solid #999; padding-bottom: 4px; }
  h1 { font-size: 12.5pt; margin: 6px 0 4px; padding-bottom: 2px; border-bottom-width: 1.5px; }
  h2 { font-size: 9.5pt; margin: 7px 0 2px; }
  h3 { font-size: 9pt; margin: 6px 0 2px; }
  p, ul, ol { margin: 2px 0 4px; }
  h1, h2, h3 { break-after: avoid; }
  hr.run-break { border: 0; border-top: 1px solid #b5bcc8; margin: 8px 0; }
  hr.summary-break { break-after: page; border: 0; margin: 0; }
  table { font-size: 7.5pt; margin: 2px 0 6px !important; }
  th, td { padding: 1px 4px !important; }
  thead { display: table-header-group; }
  tr, pre, blockquote, img { break-inside: avoid; }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 7pt !important; padding: 4px 6px !important; }
  .run-cols { columns: 2; column-gap: 7mm; }
  .run-cols .sec { break-inside: avoid; }
  a { color: inherit; text-decoration: none; }
}
"""


# Sections short enough to sit two-up. Metrics (full-precision values),
# Artifacts and Code Changes (long paths, wide tables) stay full width.
_NARROW_SECTIONS = ("Notes", "Parameters", "Variables", "Environment", "Timeline Summary",
                    "Datasets", "Studies")


def _run_layout_html(html: str, narrow_metrics: bool = False) -> str:
    """One run's HTML with its short sections grouped into two columns.

    Laid out one under another, a run's Parameters, Environment and Timeline
    tables were each a narrow strip down the left of a full-width page — the
    87-run report printed to 396 pages. Consecutive short sections are
    wrapped in a ``.run-cols`` block (two columns in print and on a wide
    screen); the rest keep the full width. Nothing is dropped or reordered.
    """
    parts = html.split("<h2>")
    out, group = [parts[0]], []

    def flush():
        if group:
            out.append('<div class="run-cols">' + "".join(group) + "</div>")
            group.clear()

    for part in parts[1:]:
        title = part.split("</h2>", 1)[0]
        sec = '<div class="sec"><h2>' + part + "</div>"
        # A Metrics table of single values is two columns wide, so it can sit
        # beside Parameters; the last/min/max form needs the full width.
        if title.startswith(_NARROW_SECTIONS) or (title == "Metrics" and narrow_metrics):
            group.append(sec)
        else:
            flush()
            out.append(sec)
    flush()
    return "".join(out)


def html_document(title: str, body: str, subtitle: str = "") -> str:
    """*body* as a standalone page — what `--format html` writes to a file.

    *subtitle* goes in the bar at the top (project, export date). The bar's
    Save as PDF button opens the browser's print dialog and does not print.
    """
    bar = ('<div class="report-bar"><span>' + _html.escape(subtitle or title) + "</span>"
           '<button class="no-print" onclick="window.print()" '
           'title="Opens the print dialog: choose Save as PDF">Save as PDF</button></div>')
    page = ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{_html.escape(title)}</title><style>{_PAGE_CSS}</style></head>\n"
            f"<body>\n{bar}\n{body}\n</body></html>\n")
    # ASCII with character references, so `> run.html` from a console whose
    # encoding cannot spell an em dash still writes the page it was asked for.
    return page.encode("ascii", "xmlcharrefreplace").decode("ascii")


def export_bundle(md: str) -> dict:
    """``{"markdown", "html"}`` — what the dashboard's Copy puts on the clipboard."""
    return {"markdown": md, "html": markdown_to_html(md)}


# The human-readable export formats, shared by `exptrack export --format` and
# the dashboard's /api/export and /api/bulk-export.
READABLE_FORMATS = ("markdown", "text", "html")


def render_runs(batch: list[dict], fmt: str, artifact_limit: int | None = None,
                patch: bool = True, summary: dict | None = None,
                summary_only: bool = False) -> str:
    """One or more runs' export data in a READABLE_FORMATS format.

    Runs are separated the way each format reads best: a rule in markdown, a
    line of ``=`` in text, an ``<hr>`` in HTML — and HTML is a whole page, so
    the output can be written straight to a file and opened, or imported into
    OneNote. ``patch=False`` leaves each run's patch out (the dashboard's Copy).
    *summary* (from ``build_runs_summary``) leads the export when given;
    ``summary_only`` leaves the per-run reports out — an 87-run report printed
    to 396 pages, and the first few were the ones read.
    """
    from .queries import ARTIFACT_LIST_LIMIT, format_export_markdown
    limit = ARTIFACT_LIST_LIMIT if artifact_limit is None else artifact_limit
    reports = [] if summary_only and summary else batch
    follow = bool(reports)
    if fmt == "text":
        parts = ([_summary_text(summary)] if summary else []) + \
            [format_export_text(d, patch) for d in reports]
        return ("\n" + "=" * 60 + "\n\n").join(parts)
    mds = ([_summary_markdown(summary, follow)] if summary else []) + \
        [format_export_markdown(d, limit, patch) for d in reports]
    if fmt == "html":
        from datetime import datetime, timezone
        title = batch[0]["name"] if len(batch) == 1 else f"{len(batch)} experiments"
        projects = sorted({d.get("project") for d in batch if d.get("project")})
        subtitle = " · ".join([
            "exptrack report", *projects,
            f"{len(batch)} run{'s' if len(batch) != 1 else ''}",
            "exported " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")])
        # The summary ends its own printed page; runs then follow one another
        # with a rule between them rather than a page each, which spent a
        # whole sheet on a run that filled a third of it.
        pages = [markdown_to_html(m) for m in mds]
        start = 1 if summary else 0
        pages[start:] = [_run_layout_html(h, single_value_metrics(export_metric_summaries(d)))
                         for h, d in zip(pages[start:], reports)]
        body = '\n<hr class="run-break">\n'.join(pages[start:])
        if summary:
            body = pages[0] + ('\n<hr class="summary-break">\n' + body if body else "")
        return html_document(title, body, subtitle)
    return "\n\n---\n\n".join(mds) + "\n"


# ── A summary ahead of a multi-run export ───────────────────────────────────
#
# An export of many runs was every run's full report, one after another: 172
# runs came out as 684 KB of markdown with nothing on the first page saying
# what the set was, what varied, or which run won. The summary answers those
# first, and the per-run reports follow unchanged. Its ranking is
# `leaderboard.top_runs` — a view over `param_study.build_matrix` — so the
# export's "top run" is the Parameter Matrix's best row by construction.

SUMMARY_TOP_N = 10
SUMMARY_MAX_PARAM_COLS = 6


def _short(v) -> str:
    """A number at 4 significant figures, for a summary cell. The per-run
    reports below keep every value at full precision."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return _md_value(v) if v is not None else "--"
    if isinstance(v, int) or float(v).is_integer():
        return f"{int(v):,}" if abs(v) < 1e15 else f"{v:.4g}"
    return f"{v:.4g}"


def _run_label(d: dict, varying: list[str] | None = None) -> str:
    """A run as a summary row names it.

    A name the user chose, with the short id. A generated name repeats the
    settings (`train__lr0.001_batch_si128_…`) that the summary already gives
    their own columns, so it is the short id alone — or, given *varying*, the
    settings that tell the run apart, for a cell with no columns beside it.
    """
    from .naming import looks_auto_named
    rid = str(d.get("id", ""))[:8]
    name = str(d.get("name") or "")
    if name and not looks_auto_named(name):
        return f"{name} ({rid})"
    params = d.get("params") or {}
    bits = [f"{k}={_md_value(params[k])}" for k in (varying or []) if k in params]
    return (" ".join(bits) + f" ({rid})") if bits else rid


def build_runs_summary(conn, batch: list[dict]) -> dict:
    """What a multi-run export leads with, as data — rendered by the formats.

    ``fields`` (label, value) pairs; ``top`` the leaderboard rows with the
    varying params; ``metrics`` one row per metric key across the runs;
    ``notes`` (label, first line) for runs that have notes.
    """
    from collections import Counter
    from statistics import median

    from . import primary_metric as pm
    from .leaderboard import top_runs

    ids = [d["id"] for d in batch]
    by_id = {d["id"]: d for d in batch}
    status = Counter(d.get("status") or "unknown" for d in batch)
    started = sorted(str(d.get("created_at") or "")[:16].replace("T", " ") for d in batch
                     if d.get("created_at"))

    try:
        lb = top_runs(conn, ids, limit=SUMMARY_TOP_N)
    except Exception:  # a summary must never be why an export fails
        lb = {"metric": {}, "runs": [], "varying": [], "n_scored": 0, "unscored": [],
              "excluded": {}}
    metric = lb.get("metric") or {}
    varying = [v["key"] for v in (lb.get("varying") or []) if is_user_param_key(v["key"])]
    constant = {}
    for d in batch:
        for k, v in (d.get("params") or {}).items():
            if is_user_param_key(k) and k not in varying:
                constant.setdefault(k, set()).add(_md_value(v))
    held = [f"{k}={next(iter(vs))}" for k, vs in sorted(constant.items()) if len(vs) == 1]

    fields = [("Runs", f"{len(batch)} (" + ", ".join(f"{n} {s}" for s, n in status.most_common()) + ")")]
    projects = sorted({d.get("project") for d in batch if d.get("project")})
    if projects:
        fields.append(("Project", ", ".join(projects)))
    if started:
        fields.append(("Started", started[0] + " to " + started[-1] + " UTC"))
    if metric.get("key"):
        goal = "lower is better" if metric.get("goal") == pm.GOAL_MIN else "higher is better"
        fields.append(("Judged by", f"{metric['key']}, {goal} (final value)"))
    if varying:
        counts = {v["key"]: v.get("n_values") for v in lb.get("varying") or []}
        fields.append(("Varied", ", ".join(f"{k} ({counts.get(k)} values)" for k in varying)))
    if held:
        fields.append(("Held constant", ", ".join(held)))
    unscored = len(lb.get("unscored") or [])
    if unscored:
        fields.append(("Not ranked", f"{unscored} run(s) did not log {metric.get('key')}"))

    # Columns are the settings that differ *among the top runs*, not the first
    # ones that varied anywhere: seed and asof varied across the set but were
    # identical in all ten top rows, so they filled the table with one value.
    top_rows = lb.get("runs") or []
    cols = [k for k in varying
            if len({_md_value((r.get("params") or {}).get(k)) for r in top_rows}) > 1]
    cols = (cols or varying)[:SUMMARY_MAX_PARAM_COLS]
    top = []
    for r in top_rows:
        p = r.get("params") or {}
        top.append([r["rank"], _run_label(by_id.get(r["id"], r)), r.get("status", "")]
                   + [_md_value(p[k]) if k in p else "--" for k in cols]
                   + [_short(r.get("value")), _short(r.get("delta_from_best"))])

    metrics = []
    keys = sorted({k for d in batch for k in (d.get("metrics") or {})})
    for k in keys:
        vals = [(d["metrics"][k].get("last"), d) for d in batch
                if isinstance((d.get("metrics") or {}).get(k, {}).get("last"), (int, float))]
        if not vals:
            continue
        nums = [v for v, _ in vals]
        lower = goal_for_key(k) == pm.GOAL_MIN
        # Ties go to the earlier run — leaderboard.top_runs' tie-break — so
        # this row's best and the Top table's #1 are the same run.
        best_v, best_d = min(vals, key=lambda t: ((t[0] if lower else -t[0]),
                                                  str(t[1].get("created_at") or ""), t[1]["id"]))
        same = max(nums) == min(nums)
        metrics.append([k, "lower" if lower else "higher", len(nums), _short(min(nums)),
                        _short(median(nums)), _short(max(nums)),
                        "same for every run" if same
                        else f"{_short(best_v)} {_run_label(best_d, varying)}"])

    notes = []
    for d in batch:
        text = str(d.get("notes") or "").strip()
        if text:
            first = next((ln.strip(" #-*") for ln in text.splitlines() if ln.strip(" #-*")), "")
            notes.append((_run_label(d, varying), first[:160]))

    return {"fields": fields, "metric": metric.get("key") or "", "param_cols": cols,
            "top": top, "metrics": metrics, "notes": notes, "n": len(batch)}


def _summary_markdown(s: dict, reports_follow: bool = True) -> str:
    out = [f"# Summary: {s['n']} runs", ""]
    out += _md_table(["", ""], [[f"**{_md_cell(k)}**", _md_cell(v)] for k, v in s["fields"]])
    if s["top"]:
        out += ["", f"## Top {len(s['top'])} by {_md_cell(s['metric'])}", ""]
        out += _md_table(["#", "Run", "Status"] + [_md_cell(c) for c in s["param_cols"]]
                         + [_md_cell(s["metric"]), "vs best"],
                         [[_md_cell(c) for c in r] for r in s["top"]],
                         "rll" + "l" * len(s["param_cols"]) + "rr")
    if s["metrics"]:
        out += ["", "## Metrics across runs", "",
                "Final value of each run. Goal is read from the metric's name.", ""]
        out += _md_table(["Metric", "Better", "Runs", "Min", "Median", "Max", "Best"],
                         [[_md_cell(c) for c in r] for r in s["metrics"]], "llrrrrl")
    if s["notes"]:
        out += ["", "## Runs with notes", ""]
        out += [f"- **{_md_cell(label)}**: {_md_cell(first)}" for label, first in s["notes"]]
    out += ["", "Each run's full report follows; its values are at full precision."
            if reports_follow else
            "Summary only — export without it for each run's full report.", ""]
    return "\n".join(out)


def _summary_text(s: dict) -> str:
    out = [f"Summary: {s['n']} runs", "=" * (len(str(s["n"])) + 15), ""]
    out += _text_fields(s["fields"])
    if s["top"]:
        out += ["", *_section(f"Top {len(s['top'])} by {s['metric']}")]
        out += _text_table(["#", "Run", "Status"] + s["param_cols"] + [s["metric"], "vs best"],
                           s["top"], align="rll" + "l" * len(s["param_cols"]) + "rr")
    if s["metrics"]:
        out += ["", *_section("Metrics across runs (final values)")]
        out += _text_table(["Metric", "Better", "Runs", "Min", "Median", "Max", "Best"],
                           s["metrics"], align="llrrrrl")
    if s["notes"]:
        out += ["", *_section("Runs with notes")]
        out += [f"  {label}: {first}" for label, first in s["notes"]]
    return "\n".join(out) + "\n"


__all__ = ["READABLE_FORMATS", "build_runs_summary", "export_bundle", "format_comparison_markdown",
           "format_export_text", "html_document", "markdown_to_html", "render_runs"]
