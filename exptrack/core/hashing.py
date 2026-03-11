"""
exptrack/core/hashing.py — Content hashing for artifact integrity

Stdlib-only (hashlib). Supports partial hashing for very large files
(e.g. multi-GB model checkpoints) to keep logging fast.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 65536  # 64 KB


def file_hash(path: str | Path, max_bytes: int = 0) -> tuple[str, int]:
    """Return (hex_digest, size_bytes) for the file at *path*.

    If *max_bytes* > 0, only the first *max_bytes* are hashed and the
    digest is prefixed with ``partial:`` to distinguish it from a
    full-file hash.  This keeps hashing fast for multi-GB checkpoints
    while still detecting most overwrites.
    """
    p = Path(path)
    size = p.stat().st_size
    partial = max_bytes > 0 and size > max_bytes

    h = hashlib.sha256()
    bytes_read = 0
    limit = max_bytes if partial else size

    with open(p, "rb") as f:
        while bytes_read < limit:
            chunk = f.read(min(_CHUNK_SIZE, limit - bytes_read))
            if not chunk:
                break
            h.update(chunk)
            bytes_read += len(chunk)

    digest = h.hexdigest()
    if partial:
        digest = f"partial:{digest}"

    return digest, size
