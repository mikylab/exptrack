"""
exptrack/capture/cell_lineage.py — Content-addressed cell lineage and diffing
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher


def cell_hash(source: str) -> str:
    """Content hash for a cell — this IS the cell's identity."""
    return hashlib.md5(source.encode()).hexdigest()[:12]


def find_parent_hash(notebook: str, source: str, current_hash: str) -> str | None:
    """
    Find the most similar existing cell in this notebook's lineage.
    Used when a cell is edited: the new hash points back to the old hash.
    Also handles cell splits — if a new cell's source is a subset of an
    existing cell, that existing cell is the parent.
    """
    try:
        from ..core import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT cell_hash, source FROM cell_lineage "
            "WHERE notebook=? AND source IS NOT NULL",
            (notebook,)
        ).fetchall()
    except Exception as e:
        print(f"[exptrack] warning: could not query cell lineage: {e}", file=sys.stderr)
        return None

    if not rows:
        return None

    best_hash = None
    best_ratio = 0.0

    for row in rows:
        if row["cell_hash"] == current_hash:
            continue
        ratio = SequenceMatcher(None, row["source"], source).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_hash = row["cell_hash"]

    if best_ratio >= 0.3:
        return best_hash
    return None


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
            existing = conn.execute(
                "SELECT cell_hash FROM cell_lineage WHERE cell_hash=?", (ch,)
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO cell_lineage
                       (cell_hash, notebook, source, parent_hash, created_at)
                       VALUES (?,?,?,?,?)""",
                    (ch, notebook, stored_source, parent_hash,
                     datetime.now(timezone.utc).isoformat())
                )
                conn.commit()
    except Exception as e:
        print(f"[exptrack] warning: could not store cell lineage: {e}", file=sys.stderr)


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
        print(f"[exptrack] warning: could not get cell source: {e}", file=sys.stderr)
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
        print(f"[exptrack] warning: could not get cell baseline: {e}", file=sys.stderr)
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
        print(f"[exptrack] warning: could not update cell baseline: {e}", file=sys.stderr)


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
