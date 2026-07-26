"""
exptrack/capture/cell_lineage.py — Content-addressed cell lineage and diffing
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from difflib import SequenceMatcher

from ..core.utils import debug_log


def cell_hash(source: str) -> str:
    """Content hash for a cell — this IS the cell's identity."""
    return hashlib.md5(source.encode()).hexdigest()[:12]


def is_magic_only(source: str) -> bool:
    """True if source is only IPython magics / shell escapes / comments / blanks.

    Magic-only cells (e.g. ``%exptrack checkpoint "..."`` or ``%load_ext exptrack``)
    are commands, not editable code. They must be kept out of cell lineage so the
    fuzzy SequenceMatcher matcher never (a) assigns one a bogus "parent" it then
    word-diffs against, or (b) offers one as a parent candidate for a real cell —
    two short ``%exptrack`` magics trivially clear the 30% similarity bar.
    """
    has_magic = False
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('%') or stripped.startswith('!'):
            has_magic = True
            continue
        return False
    return has_magic


_SIMILARITY_THRESHOLD = 0.3


def lookup_stored_parent(current_hash: str, notebook: str | None = None) -> tuple[bool, str | None]:
    """Return ``(found, parent_hash)`` for an already-stored cell.

    A cell is content-addressed, so if ``current_hash`` is already in
    ``cell_lineage`` this is an exact re-execution of previously-seen source
    — its parent was resolved once and frozen. Reusing that stored value lets
    ``_process_cell_lineage`` skip the O(N) SequenceMatcher scan on every
    unchanged rerun (a hot path in long notebook sessions). ``found`` is
    False when the hash has never been stored (a genuinely new/edited cell,
    which still needs the fuzzy search).

    ``notebook`` scopes the lookup: identical source in two different notebooks
    hashes to the same ``cell_hash``, so without this filter a cell's parent
    resolved in notebook A would leak into notebook B (its own row is never
    stored — ``store_cell_lineage`` INSERT-OR-IGNOREs on the shared PK). When
    ``notebook`` is given, a hit in a *different* notebook reports ``found=False``
    so the fuzzy search runs against B's own lineage instead.
    """
    try:
        from ..core import get_db
        conn = get_db()
        if notebook is None:
            row = conn.execute(
                "SELECT parent_hash FROM cell_lineage WHERE cell_hash=?",
                (current_hash,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT parent_hash FROM cell_lineage WHERE cell_hash=? AND notebook=?",
                (current_hash, notebook),
            ).fetchone()
    except Exception as e:
        debug_log(f"could not look up stored parent: {e}")
        return False, None
    if row is None:
        return False, None
    return True, row["parent_hash"]


def find_parent_hash(notebook: str, source: str, current_hash: str) -> str | None:
    """
    Find the most similar existing cell in this notebook's lineage.
    Used when a cell is edited: the new hash points back to the old hash.
    Also handles cell splits — if a new cell's source is a subset of an
    existing cell, that existing cell is the parent.

    Magic-only cells are excluded both as the search subject and as candidates.

    Cheap prefilters keep the scan from being O(N·L²) on every call: candidates
    whose length can't possibly clear the similarity bar are skipped before any
    matching, and `SequenceMatcher`'s cheap `real_quick_ratio`/`quick_ratio`
    upper bounds gate the full `.ratio()` — an exact port of what
    `difflib.get_close_matches` does. The subject sequence is set once and
    reused across candidates so its autojunk index isn't rebuilt each time.
    """
    if is_magic_only(source):
        return None
    try:
        from ..core import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT cell_hash, source FROM cell_lineage "
            "WHERE notebook=? AND source IS NOT NULL",
            (notebook,)
        ).fetchall()
    except Exception as e:
        debug_log(f"could not query cell lineage: {e}")
        return None

    if not rows:
        return None

    best_hash = None
    best_ratio = 0.0
    src_len = len(source)

    matcher = SequenceMatcher(None)
    matcher.set_seq2(source)  # subject fixed; only seq1 changes per candidate

    for row in rows:
        if row["cell_hash"] == current_hash:
            continue
        cand = row["source"]
        # The lowest ratio still worth evaluating: strictly beat the running
        # best once we have one, otherwise reach the acceptance threshold.
        gate = best_ratio if best_hash is not None else _SIMILARITY_THRESHOLD
        # Length band: ratio() = 2*M/(la+lb) ≤ 2*min(la,lb)/(la+lb), so a
        # candidate whose length upper-bound is below the gate can never
        # qualify — skip it before the magic-only parse or any matching.
        cand_len = len(cand)
        denom = src_len + cand_len
        if denom == 0 or (2.0 * min(src_len, cand_len)) < gate * denom:
            continue
        if is_magic_only(cand):
            continue
        matcher.set_seq1(cand)
        # Cheap upper bounds first; only compute the real ratio if it can reach
        # the gate (an exact port of difflib.get_close_matches's fast path).
        if (matcher.real_quick_ratio() < gate
                or matcher.quick_ratio() < gate):
            continue
        ratio = matcher.ratio()
        if ratio >= _SIMILARITY_THRESHOLD and ratio > best_ratio:
            best_ratio = ratio
            best_hash = row["cell_hash"]

    return best_hash


def store_cell_lineage(notebook: str, source: str, parent_hash: str | None = None):
    """Store a cell's source in the content-addressed lineage table.

    Applies max_cell_source_kb truncation to the stored copy.
    The cell_hash is always computed from the original source.
    """
    try:
        from .. import config as cfg
        from ..core import get_db
        ch = cell_hash(source)
        # Truncate stored source if it exceeds the configured limit
        stored_source = source
        max_kb = cfg.load().get("max_cell_source_kb", 50)
        if max_kb and len(source) > max_kb * 1024:
            stored_source = source[:max_kb * 1024] + (
                f"\n# [truncated at {max_kb} KB by exptrack]"
            )
        with get_db() as conn:
            # cell_hash is the PK; OR IGNORE no-ops on an existing row (drops the
            # separate pre-SELECT).
            conn.execute(
                """INSERT OR IGNORE INTO cell_lineage
                   (cell_hash, notebook, source, parent_hash, created_at)
                   VALUES (?,?,?,?,?)""",
                (ch, notebook, stored_source, parent_hash,
                 datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
    except Exception as e:
        debug_log(f"could not store cell lineage: {e}")


def get_cell_source(cell_hash_val: str) -> str | None:
    """Retrieve source from the lineage table by hash.

    Returns None if the cell was not found or source was compacted (NULL).
    """
    try:
        from ..core import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT source FROM cell_lineage WHERE cell_hash=?", (cell_hash_val,)
        ).fetchone()
        if row and row["source"] is not None:
            return row["source"]
        return None
    except Exception as e:
        debug_log(f"could not get cell source: {e}")
        return None


# ── Legacy code baseline helpers (kept for backward compat) ──────────────────

def get_cell_baseline(notebook: str, cell_seq: int) -> str | None:
    """Get the baseline source for a cell position from the DB."""
    try:
        from ..core import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT source FROM code_baselines WHERE notebook=? AND cell_seq=?",
            (notebook, cell_seq),
        ).fetchone()
        return row["source"] if row else None
    except Exception as e:
        debug_log(f"could not get cell baseline: {e}")
        return None


def update_cell_baseline(notebook: str, cell_seq: int, source: str):
    """Store or update the baseline source for a cell position."""
    try:
        from ..core import get_db
        source_hash = hashlib.md5(source.encode()).hexdigest()[:12]
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO code_baselines
                   (notebook, cell_seq, source, source_hash, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (notebook, cell_seq, source, source_hash,
                 datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
    except Exception as e:
        debug_log(f"could not update cell baseline: {e}")


def simple_diff(old: str, new: str) -> list[dict]:
    """Line-level diff: returns list of {op, line} where op is +/-/=."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    result = []
    old_set = set(old_lines)
    new_set = set(new_lines)
    for line in old_lines:
        if line not in new_set:
            result.append({"op": "-", "line": line})
    for line in new_lines:
        if line not in old_set:
            result.append({"op": "+", "line": line})
        else:
            result.append({"op": "=", "line": line})
    return result
