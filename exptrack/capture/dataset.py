"""
exptrack/capture/dataset.py — Dataset / input versioning

A run isn't reproducible if you don't know *what data* trained it. This module
scans an experiment's captured params for values that point at datasets (data
files or directories) and records a lightweight manifest — path + size + a
content/structure fingerprint — as the `_dataset_manifest` param, so a later
run against changed data is visibly different.

Zero-friction and best-effort: detection piggybacks on params already captured
by the argparse/argv patches, and every step is wrapped so a failure here can
never crash the user's run. Fingerprints are cheap: large files are partial-
hashed and directories are fingerprinted by their (relpath, size) listing
rather than by reading every byte, so pointing at a multi-GB dataset stays fast.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.hashing import file_hash
from ..core.utils import safe_call

if TYPE_CHECKING:
    from ..core import Experiment

# File extensions that, on their own, mark a param value as a dataset.
_DATA_EXTS = {
    ".csv", ".tsv", ".parquet", ".json", ".jsonl", ".ndjson",
    ".npy", ".npz", ".h5", ".hdf5", ".arrow", ".feather",
    ".txt", ".pkl", ".zip", ".tar", ".gz",
}
# Param-key shapes that mark an existing path as a dataset even without a
# data extension (e.g. --data_dir results/imgs, --train_set foo).
_DATA_KEY_RE = re.compile(
    r"(^|[_-])(data|dataset|datadir|datapath|train|val|valid|test|corpus|inputs?)([_-]|$)",
    re.I,
)

_DIR_FILE_CAP = 5000                  # stop listing a data dir past this many files
_FILE_HASH_CAP = 100 * 1024 * 1024    # partial-hash files larger than 100 MB
_MANIFEST_PARAM = "_dataset_manifest"


def _looks_like_dataset(key: str, value) -> bool:
    """True when *value* is an existing path that reads as training data."""
    if not isinstance(value, str) or not value:
        return False
    p = Path(value)
    if not safe_call(p.exists, default=False, context="dataset: exists check"):
        return False
    if p.is_file() and p.suffix.lower() in _DATA_EXTS:
        return True
    # A dataset-shaped key pointing at any existing file/dir counts too.
    return bool(_DATA_KEY_RE.search(key))


def _file_manifest(p: Path) -> dict:
    digest, size = file_hash(p, max_bytes=_FILE_HASH_CAP)
    return {
        "kind": "file",
        "path": str(p),
        "size": size,
        "mtime": round(p.stat().st_mtime, 3),
        "hash": digest,
    }


def _dir_manifest(p: Path) -> dict:
    """Fingerprint a directory by its sorted (relpath, size) listing.

    No file contents are read — this stays fast on huge datasets while still
    detecting added/removed/resized files. Caps at `_DIR_FILE_CAP` entries.
    """
    entries: list[tuple[str, int]] = []
    total = 0
    truncated = False
    for root, dirs, files in os.walk(p):
        dirs.sort()
        for f in sorted(files):
            fp = Path(root) / f
            try:
                st = fp.stat()
            except OSError:
                continue
            entries.append((os.path.relpath(fp, p), st.st_size))
            total += st.st_size
            if len(entries) >= _DIR_FILE_CAP:
                truncated = True
                break
        if truncated:
            break
    h = hashlib.sha256()
    for rel, sz in entries:
        h.update(f"{rel}\0{sz}\0".encode("utf-8", "replace"))
    return {
        "kind": "dir",
        "path": str(p),
        "n_files": len(entries),
        "size": total,
        "hash": h.hexdigest(),
        "truncated": truncated,
    }


def build_manifest(params: dict) -> dict:
    """Return ``{param_key: manifest}`` for every dataset-like value in *params*."""
    manifest: dict[str, dict] = {}
    for k, v in params.items():
        if k.startswith("_") or not _looks_like_dataset(k, v):
            continue
        p = Path(v)
        entry = safe_call(
            lambda pp=p: _dir_manifest(pp) if pp.is_dir() else _file_manifest(pp),
            default=None, context=f"dataset: manifest for {k}",
        )
        if entry:
            manifest[k] = entry
    return manifest


def capture_dataset_manifest(exp: Experiment) -> dict:
    """Fingerprint dataset-like params on *exp* and log `_dataset_manifest`.

    Returns the manifest dict (empty when nothing dataset-shaped was found).
    Best-effort: never raises.
    """
    try:
        params = dict(getattr(exp, "_params", {}) or {})
    except Exception:
        return {}
    manifest = build_manifest(params)
    if manifest:
        safe_call(lambda: exp.log_params({_MANIFEST_PARAM: manifest}),
                  context="dataset: log manifest")
    return manifest
