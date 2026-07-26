"""Tests for exptrack/capture/cell_lineage.py — content-addressed cell lineage and diffing."""
from __future__ import annotations


def test_cell_hash_deterministic():
    """Same source always produces the same hash."""
    from exptrack.capture.cell_lineage import cell_hash

    source = "x = 1\ny = 2\n"
    assert cell_hash(source) == cell_hash(source)


def test_cell_hash_different():
    """Different sources produce different hashes."""
    from exptrack.capture.cell_lineage import cell_hash

    assert cell_hash("x = 1") != cell_hash("x = 2")


def test_simple_diff_added_lines():
    """New lines that only appear in 'new' show as +."""
    from exptrack.capture.cell_lineage import simple_diff

    result = simple_diff("", "alpha\nbeta")
    ops = [d["op"] for d in result]
    lines = [d["line"] for d in result]
    assert all(op == "+" for op in ops)
    assert "alpha" in lines
    assert "beta" in lines


def test_simple_diff_removed_lines():
    """Lines only in 'old' show as -."""
    from exptrack.capture.cell_lineage import simple_diff

    result = simple_diff("alpha\nbeta", "")
    ops = [d["op"] for d in result]
    lines = [d["line"] for d in result]
    assert all(op == "-" for op in ops)
    assert "alpha" in lines
    assert "beta" in lines


def test_simple_diff_unchanged():
    """Lines present in both old and new show as =."""
    from exptrack.capture.cell_lineage import simple_diff

    result = simple_diff("a\nb", "b\nc")
    result_map = {d["line"]: d["op"] for d in result}
    assert result_map["a"] == "-"
    assert result_map["b"] == "="
    assert result_map["c"] == "+"


def test_simple_diff_empty():
    """Empty inputs produce an empty diff."""
    from exptrack.capture.cell_lineage import simple_diff

    result = simple_diff("", "")
    assert result == []


def test_simple_diff_identical():
    """Identical inputs produce all = ops."""
    from exptrack.capture.cell_lineage import simple_diff

    result = simple_diff("x = 1\ny = 2", "x = 1\ny = 2")
    assert all(d["op"] == "=" for d in result)
    assert len(result) == 2


def test_store_and_get_cell_source(tmp_project):
    """Roundtrip: store a cell then retrieve its source by hash."""
    from exptrack.capture.cell_lineage import cell_hash, get_cell_source, store_cell_lineage

    source = "print('hello world')"
    store_cell_lineage("notebook.ipynb", source)
    retrieved = get_cell_source(cell_hash(source))
    assert retrieved == source


def test_store_idempotent(tmp_project):
    """Storing the same cell twice does not raise an error."""
    from exptrack.capture.cell_lineage import cell_hash, get_cell_source, store_cell_lineage

    source = "x = 42"
    store_cell_lineage("nb.ipynb", source)
    store_cell_lineage("nb.ipynb", source)  # should not error
    assert get_cell_source(cell_hash(source)) == source


def test_get_cell_source_unknown(tmp_project):
    """Querying an unknown hash returns None."""
    from exptrack.capture.cell_lineage import get_cell_source

    assert get_cell_source("000000000000") is None


def test_find_parent_hash_similar(tmp_project):
    """A cell with >30% similarity to a stored cell is found as parent."""
    from exptrack.capture.cell_lineage import cell_hash, find_parent_hash, store_cell_lineage

    original = "x = 1\ny = 2\nz = 3\nw = 4\nv = 5"
    store_cell_lineage("nb.ipynb", original)

    # Modified version — still very similar
    modified = "x = 1\ny = 2\nz = 3\nw = 4\nv = 99"
    modified_hash = cell_hash(modified)

    parent = find_parent_hash("nb.ipynb", modified, modified_hash)
    assert parent == cell_hash(original)


def test_find_parent_hash_dissimilar(tmp_project):
    """A cell with <30% similarity returns None."""
    from exptrack.capture.cell_lineage import cell_hash, find_parent_hash, store_cell_lineage

    original = "import numpy as np"
    store_cell_lineage("nb.ipynb", original)

    totally_different = "class FooBarBazQuuxLongClassName:\n    def method(self):\n        return 999999"
    different_hash = cell_hash(totally_different)

    parent = find_parent_hash("nb.ipynb", totally_different, different_hash)
    assert parent is None


def test_find_parent_hash_excludes_self(tmp_project):
    """find_parent_hash does not match a cell against itself."""
    from exptrack.capture.cell_lineage import cell_hash, find_parent_hash, store_cell_lineage

    source = "x = 1"
    store_cell_lineage("nb.ipynb", source)
    ch = cell_hash(source)

    # The only candidate is itself, so result should be None
    parent = find_parent_hash("nb.ipynb", source, ch)
    assert parent is None


def test_lookup_stored_parent_hit_and_miss(tmp_project):
    """lookup_stored_parent returns the frozen parent for a re-run cell."""
    from exptrack.capture.cell_lineage import (
        cell_hash,
        lookup_stored_parent,
        store_cell_lineage,
    )

    original = "x = 1\ny = 2\nz = 3\nw = 4\nv = 5"
    store_cell_lineage("nb.ipynb", original)
    edited = "x = 1\ny = 2\nz = 3\nw = 4\nv = 99"
    edited_hash = cell_hash(edited)
    store_cell_lineage("nb.ipynb", edited, cell_hash(original))

    # A stored (re-run) cell: found, parent reused verbatim.
    seen, parent = lookup_stored_parent(edited_hash)
    assert seen is True
    assert parent == cell_hash(original)

    # A root cell stored with no parent: found, parent None.
    seen, parent = lookup_stored_parent(cell_hash(original))
    assert seen is True
    assert parent is None

    # An unseen hash: not found (caller must run the fuzzy search).
    seen, parent = lookup_stored_parent("ffffffffffff")
    assert seen is False
    assert parent is None


def test_lookup_stored_parent_is_notebook_scoped(tmp_project):
    """An identical cell in two notebooks must not share a lineage parent.

    Cells are content-addressed, so the same source hashes to the same
    ``cell_hash`` in every notebook and ``store_cell_lineage`` INSERT-OR-IGNOREs
    on that shared PK — B's own row is never written. Without the notebook
    filter, ``lookup_stored_parent`` would hand notebook B the parent that was
    resolved in notebook A (a phantom "edited from" link). Regression test for
    the cross-notebook lineage bleed fix (AUDIT_DIFF_REVERT 5.3 / L6).
    """
    from exptrack.capture.cell_lineage import (
        cell_hash,
        lookup_stored_parent,
        store_cell_lineage,
    )

    # Notebook A: a root cell, then an edited cell whose parent is the root.
    root = "x = 1\ny = 2\nz = 3\nw = 4\nv = 5"
    edited = "x = 1\ny = 2\nz = 3\nw = 4\nv = 99"
    root_hash = cell_hash(root)
    edited_hash = cell_hash(edited)
    store_cell_lineage("nb_a.ipynb", root)
    store_cell_lineage("nb_a.ipynb", edited, root_hash)

    # Notebook B runs the *identical* edited source. Its hash collides with A's
    # row, but scoped to nb_b it has no lineage yet, so the lookup must miss and
    # defer to the fuzzy search (found=False) rather than leak A's parent.
    seen, parent = lookup_stored_parent(edited_hash, notebook="nb_b.ipynb")
    assert seen is False
    assert parent is None

    # Scoped to its own notebook, the same hash still resolves A's parent.
    seen, parent = lookup_stored_parent(edited_hash, notebook="nb_a.ipynb")
    assert seen is True
    assert parent == root_hash

    # Unscoped (notebook=None) is the legacy behavior that would bleed across
    # notebooks — it finds the row regardless of notebook.
    seen, parent = lookup_stored_parent(edited_hash)
    assert seen is True
    assert parent == root_hash


def test_find_parent_hash_boundary_similarity(tmp_project):
    """The optimized matcher keeps the exact >= 0.3 acceptance boundary."""
    from exptrack.capture.cell_lineage import (
        cell_hash,
        find_parent_hash,
        store_cell_lineage,
    )
    # Two candidates, one clearly similar; the optimized gates must still
    # pick the best real match, not prune it.
    store_cell_lineage("nb.ipynb", "a = 1\nb = 2\nc = 3\nd = 4")
    store_cell_lineage("nb.ipynb", "completely unrelated text here xyz")
    edited = "a = 1\nb = 2\nc = 3\nd = 5"
    parent = find_parent_hash("nb.ipynb", edited, cell_hash(edited))
    assert parent == cell_hash("a = 1\nb = 2\nc = 3\nd = 4")


def test_is_magic_only():
    """Magic-only cells are detected; mixed/code/comment-only cells are not."""
    from exptrack.capture.cell_lineage import is_magic_only

    assert is_magic_only('%exptrack checkpoint "after preprocessing clean"') is True
    assert is_magic_only('%exptrack checkpoint "x"\n# (snapshots the diff)') is True
    assert is_magic_only('%load_ext exptrack\n%exptrack session start "s"') is True
    assert is_magic_only('!ls -la') is True
    # Real code, with or without a leading magic line, is NOT magic-only
    assert is_magic_only("results = run_pipeline(data)") is False
    assert is_magic_only('%exptrack branch "b"\nresults = run_pipeline(data)') is False
    # No actual magic line → not magic-only (don't suppress real comment edits)
    assert is_magic_only("# just a comment") is False
    assert is_magic_only("") is False


def test_find_parent_hash_skips_magic_subject(tmp_project):
    """A magic-only cell never gets a fuzzy-matched parent (root cause fix)."""
    from exptrack.capture.cell_lineage import cell_hash, find_parent_hash, store_cell_lineage

    # An earlier session-start magic is stored in lineage...
    store_cell_lineage("nb.ipynb", '%load_ext exptrack\n%exptrack session start "threshold sensitivity"')

    # ...a later checkpoint magic shares enough text to clear the 30% bar,
    # but must NOT be diffed against it.
    checkpoint = '%exptrack checkpoint "after preprocessing clean"'
    assert find_parent_hash("nb.ipynb", checkpoint, cell_hash(checkpoint)) is None


def test_find_parent_hash_excludes_magic_candidates(tmp_project):
    """Magic-only cells are never offered as a parent for a real code cell."""
    from exptrack.capture.cell_lineage import cell_hash, find_parent_hash, store_cell_lineage

    store_cell_lineage("nb.ipynb", '%exptrack checkpoint "x"')
    code = "model = train(data)"
    # Only candidate is a magic cell → no parent
    assert find_parent_hash("nb.ipynb", code, cell_hash(code)) is None


def test_store_truncates_large_source(tmp_project, monkeypatch):
    """Source exceeding max_cell_source_kb is truncated on storage."""
    from exptrack import config as cfg
    from exptrack.capture.cell_lineage import cell_hash, get_cell_source, store_cell_lineage

    # Set a tiny limit: 1 KB
    conf = cfg.load()
    conf["max_cell_source_kb"] = 1
    monkeypatch.setattr(cfg, "_cache", conf)

    source = "a" * 2048  # 2 KB of content, exceeds 1 KB limit
    store_cell_lineage("nb.ipynb", source)
    retrieved = get_cell_source(cell_hash(source))

    assert retrieved is not None
    assert len(retrieved) < len(source)
    assert "[truncated at 1 KB by exptrack]" in retrieved
