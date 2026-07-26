"""Tests for exptrack/core/hashing.py — file_hash (full + partial)."""
from __future__ import annotations

import re

_HEX64 = re.compile(r"^[a-f0-9]{64}$")


def test_full_hash_small_file(tmp_path):
    """A full hash returns (64-char hex digest, correct size), no 'partial:' prefix."""
    from exptrack.core.hashing import file_hash

    data = b"hello world\n"
    f = tmp_path / "a.txt"
    f.write_bytes(data)

    digest, size = file_hash(f)
    assert size == len(data)
    assert not digest.startswith("partial:")
    assert _HEX64.match(digest)


def test_empty_file(tmp_path):
    """An empty file hashes cleanly with size 0 and a full digest."""
    from exptrack.core.hashing import file_hash

    f = tmp_path / "empty.bin"
    f.write_bytes(b"")

    digest, size = file_hash(f)
    assert size == 0
    assert not digest.startswith("partial:")
    assert _HEX64.match(digest)


def test_partial_hash_reports_full_size(tmp_path):
    """A file larger than max_bytes returns a 'partial:'-prefixed digest and FULL size."""
    from exptrack.core.hashing import file_hash

    data = b"x" * 1000
    f = tmp_path / "big.bin"
    f.write_bytes(data)

    digest, size = file_hash(f, max_bytes=100)
    assert digest.startswith("partial:")
    # The hex part after the prefix is still a full sha256.
    assert _HEX64.match(digest.split("partial:", 1)[1])
    # Size is the real on-disk size, not the truncated read length.
    assert size == 1000


def test_same_content_same_digest_changed_content_differs(tmp_path):
    """Identical content → identical digest; a change flips the digest."""
    from exptrack.core.hashing import file_hash

    f1 = tmp_path / "f1.txt"
    f2 = tmp_path / "f2.txt"
    f1.write_bytes(b"same content")
    f2.write_bytes(b"same content")

    d1, _ = file_hash(f1)
    d2, _ = file_hash(f2)
    assert d1 == d2

    f2.write_bytes(b"different content")
    d3, _ = file_hash(f2)
    assert d3 != d1


def test_max_bytes_larger_than_file_is_full_hash(tmp_path):
    """When max_bytes exceeds the file size, the hash is full (no 'partial:')."""
    from exptrack.core.hashing import file_hash

    data = b"small"
    f = tmp_path / "s.txt"
    f.write_bytes(data)

    digest, size = file_hash(f, max_bytes=10_000)
    assert not digest.startswith("partial:")
    assert size == len(data)

    # It must equal the plain full hash of the same content.
    full_digest, _ = file_hash(f)
    assert digest == full_digest
