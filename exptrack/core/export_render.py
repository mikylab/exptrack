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
        lines += [*_section("Notes"), *("  " + n for n in str(data["notes"]).splitlines()), ""]
    for title, key in (("Parameters", "params"), ("Variables", "variables")):
        if data.get(key):
            lines += _section(title)
            lines += _text_fields([(str(k), _md_value(v)) for k, v in data[key].items()])
            lines.append("")
    summaries = export_metric_summaries(data)
    if summaries:
        lines += _section("Metrics")
        lines += _text_table(["Metric", "Last", "Min", "Max", "Points"],
                             [[k, _plain(s["last"]), _plain(s["min"]),
                               _plain(s["max"]), s["count"]] for k, s in summaries.items()],
                             align="lrrrr")
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
# Exactly the subset the renderers above and in queries.py produce: headings,
# pipe tables with alignment, fenced code (diff lines tinted), bullets,
# paragraphs, **bold**, _italic_ and `code`. Styles are inline because that is
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
_BULLET = re.compile(r"^\s*[-*] ")


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
    out = [f"<table {_TABLE}><tr>"]
    out += [f"<th {_TH.format(a=aligns[i] if i < len(aligns) else 'left')}>{_inline(c)}</th>"
            for i, c in enumerate(head)]
    out.append("</tr>")
    for r in rows[2:]:
        cells = _cells(r)
        out.append("<tr>" + "".join(
            f"<td {_TD.format(a=aligns[i] if i < len(aligns) else 'left')}>{_inline(c)}</td>"
            for i, c in enumerate(cells)) + "</tr>")
    out.append("</table>")
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
        fence = re.match(r"^(`{3,})(\w*)\s*$", ln)
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
        if re.match(r"^\s*[-*] ", ln):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\s*[-*] ", lines[i]):
                item = _inline(_BULLET.sub("", lines[i]))
                items.append(f"<li>{item}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        if not ln.strip():
            flush()
        else:
            para.append(ln.rstrip())
        i += 1
    flush()
    return "\n".join(out)


def html_document(title: str, body: str) -> str:
    """*body* as a standalone page — what `--format html` writes to a file."""
    page = ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>{_html.escape(title)}</title></head>\n"
            '<body style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:14px">\n'
            f"{body}\n</body></html>\n")
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
                patch: bool = True) -> str:
    """One or more runs' export data in a READABLE_FORMATS format.

    Runs are separated the way each format reads best: a rule in markdown, a
    line of ``=`` in text, an ``<hr>`` in HTML — and HTML is a whole page, so
    the output can be written straight to a file and opened, or imported into
    OneNote. ``patch=False`` leaves each run's patch out (the dashboard's Copy).
    """
    from .queries import ARTIFACT_LIST_LIMIT, format_export_markdown
    limit = ARTIFACT_LIST_LIMIT if artifact_limit is None else artifact_limit
    if fmt == "text":
        return ("\n" + "=" * 60 + "\n\n").join(format_export_text(d, patch) for d in batch)
    mds = [format_export_markdown(d, limit, patch) for d in batch]
    if fmt == "html":
        title = batch[0]["name"] if len(batch) == 1 else f"{len(batch)} experiments"
        return html_document(title, "\n<hr>\n".join(markdown_to_html(m) for m in mds))
    return "\n\n---\n\n".join(mds) + "\n"


__all__ = ["READABLE_FORMATS", "export_bundle", "format_comparison_markdown",
           "format_export_text", "html_document", "markdown_to_html", "render_runs"]
