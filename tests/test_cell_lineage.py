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
