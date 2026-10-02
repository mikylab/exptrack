"""A diff read as "before / after", with the words that changed marked.

A unified diff is the right thing to hand ``git apply`` and a hard thing to
read: a changed line is a ``-`` line and a ``+`` line some distance apart, and
finding the one word that differs between them is left to the reader's eye.
Exports therefore show a readable view first — each changed line paired with
what it replaced, the changed words marked — and keep the patch, verbatim,
after it for applying.

Stdlib only (``difflib``), and nothing here ever rewrites the patch.
"""
from __future__ import annotations

import difflib
import re

_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_TOKEN = re.compile(r"\w+|\s+|[^\w\s]")

# Below this similarity a removed and an added line are two changes, not one
# line edited — pairing them would mark every word of both as "changed".
_PAIR_MIN_RATIO = 0.5


def changed_rows(patch: str) -> list[dict]:
    """The changed lines of one file's patch, paired before/after.

    ``[{"old_no", "old", "new_no", "new"}]`` in file order — ``old``/``new``
    None on the side a line does not exist (a pure addition or removal).
    Context lines are left out: they are what did *not* change.
    """
    rows: list[dict] = []
    old_no = new_no = 0
    removed: list[tuple[int, str]] = []
    added: list[tuple[int, str]] = []

    def flush():
        rows.extend(_pair(removed, added))
        removed.clear()
        added.clear()

    for line in str(patch or "").split("\n"):
        m = _HUNK.match(line)
        if m:
            flush()
            old_no, new_no = int(m.group(1)), int(m.group(2))
            continue
        if not old_no and not new_no and not line.startswith("@@"):
            continue                       # file headers before the first hunk
        if line.startswith("\\"):          # "\ No newline at end of file"
            continue
        if line.startswith("-") and not line.startswith("---"):
            removed.append((old_no, line[1:]))
            old_no += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added.append((new_no, line[1:]))
            new_no += 1
        else:
            flush()
            old_no += 1
            new_no += 1
    flush()
    return rows


def _row(o, n) -> dict:
    return {"old_no": o[0] if o else None, "old": o[1] if o else None,
            "new_no": n[0] if n else None, "new": n[1] if n else None}


def _pair(removed, added) -> list[dict]:
    """One change block (removed lines, then the lines added in their place)
    as rows, each removed line paired with the added line most like it.

    Pairing by position paired the wrong lines as soon as a block grew or
    shrank — ``return [width] * layers`` against ``widths = []`` instead of
    ``return widths`` — and then marked every word of both as changed. The
    most similar pair is taken first and the two sides either side of it are
    aligned the same way, which keeps the rows in file order (the approach
    ``difflib.Differ`` uses for the same problem).
    """
    out: list[dict] = []
    _align(removed, added, out)
    return out


def _align(olds, news, out) -> None:
    if not olds or not news or len(olds) * len(news) > 40000:
        out.extend(_row(o, None) for o in olds)
        out.extend(_row(None, n) for n in news)
        return
    best, bi, bj = _PAIR_MIN_RATIO, -1, -1
    sm = difflib.SequenceMatcher(autojunk=False)
    for j, (_, nt) in enumerate(news):
        sm.set_seq2(nt)
        for i, (_, ot) in enumerate(olds):
            sm.set_seq1(ot)
            if (sm.real_quick_ratio() > best and sm.quick_ratio() > best
                    and sm.ratio() > best):
                best, bi, bj = sm.ratio(), i, j
    if bi < 0:
        # Nothing alike: a rewrite, shown as what went and what came.
        out.extend(_row(o, None) for o in olds)
        out.extend(_row(None, n) for n in news)
        return
    _align(olds[:bi], news[:bj], out)
    out.append(_row(olds[bi], news[bj]))
    _align(olds[bi + 1:], news[bj + 1:], out)


def word_segments(old: str, new: str) -> tuple[list, list]:
    """``(old_segments, new_segments)``, each ``[(text, changed)]``.

    Split on words, runs of whitespace and single punctuation, so ``64`` ->
    ``128`` marks the number and not the whole ``width=64``. A change that is
    only whitespace is not marked — an indent change would otherwise shade a
    run of blanks nobody can see.
    """
    a, b = _TOKEN.findall(old or ""), _TOKEN.findall(new or "")
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    olds: list[tuple[str, bool]] = []
    news: list[tuple[str, bool]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        _push(olds, "".join(a[i1:i2]), tag != "equal")
        _push(news, "".join(b[j1:j2]), tag != "equal")
    return olds, news


def _push(segs: list, text: str, changed: bool) -> None:
    if not text:
        return
    changed = changed and bool(text.strip())
    if segs and segs[-1][1] == changed:
        segs[-1] = (segs[-1][0] + text, changed)
    else:
        segs.append((text, changed))


def caret_line(segments: list) -> str:
    """``^`` under each changed segment — the plain-text marker for it."""
    return "".join(("^" if changed else " ") * len(text) for text, changed in segments).rstrip()
