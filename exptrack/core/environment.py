"""
exptrack/core/environment.py — which library versions a run actually used.

A run recorded its Python version and nothing else about its environment, so
"which numpy / torch was this?" — the first thing a reviewer asks of a
paper's numbers — had no answer after the fact.

The record is the non-stdlib packages the run *imported* (a venv's
site-packages, a conda env, an editable `pip install -e`), read from each
top-level module's ``__version__`` at finish: the libraries that could have
affected its numbers, not everything the environment happens to hold. A full
``importlib.metadata.distributions()`` scan was measured at ~2.3 s cold on
Windows for 135 packages — a cost every run would pay for data it mostly does
not need — while this reads attributes already in memory.

Stored content-addressed in ``code_snapshots`` (``kind='environment'``) and
referenced from the ``_environment`` param, so one environment is stored once
however many runs share it, and the blob is reclaimed with the last run that
references it (see ``db._referenced_snapshot_hashes``).
"""
from __future__ import annotations

import json
import platform
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .experiment import Experiment

ENV_PARAM = "_environment"
_MAX_PACKAGES = 200


def _stdlib_dirs() -> tuple:
    import os
    import sysconfig
    paths = sysconfig.get_paths()
    return tuple(os.path.normcase(os.path.realpath(paths[k]))
                 for k in ("stdlib", "platstdlib") if paths.get(k))


def _is_third_party(module, stdlib_dirs: tuple) -> bool:
    """Not the standard library — wherever it lives.

    Excluding the stdlib, rather than requiring a `site-packages` path, is
    what keeps `pip install -e mylib` in the record: an editable install's
    `__file__` is its source checkout, which the path test skipped, and the
    user's own library is exactly the version a paper most needs pinned.
    """
    import os
    f = getattr(module, "__file__", None)
    if not f:
        return False            # builtins and namespace packages
    f = os.path.normcase(os.path.realpath(f))
    if "site-packages" in f or "dist-packages" in f:
        return True
    return not any(f.startswith(d + os.sep) for d in stdlib_dirs)


def imported_packages(modules: dict | None = None) -> dict[str, str]:
    """``{top-level module: version}`` for the third-party packages imported.

    Only modules that state a ``__version__`` (a string or something that
    renders as one); a package that does not is left out rather than guessed.
    The tracker's own package is never listed — it is not an input.
    """
    mods = sys.modules if modules is None else modules
    stdlib = _stdlib_dirs()
    out: dict[str, str] = {}
    for name, mod in list(mods.items()):
        if "." in name or name.startswith("_") or name == "exptrack" or mod is None:
            continue
        if not _is_third_party(mod, stdlib):
            continue
        ver = getattr(mod, "__version__", None)
        if ver is None or callable(ver):
            continue
        ver = str(ver)
        if ver and len(ver) < 64:
            out[name] = ver
        if len(out) >= _MAX_PACKAGES:
            break
    return dict(sorted(out.items()))


def environment_record(modules: dict | None = None) -> dict:
    return {"python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(terse=True),
            "packages": imported_packages(modules)}


def capture_environment(exp: Experiment, modules: dict | None = None) -> str:
    """Store this run's environment and point ``_environment`` at it.

    Returns the snapshot hash, or "" when nothing was stored. Idempotent: a
    second call for the same environment rewrites the same hash.
    """
    from .db import get_db, store_code_snapshot
    content = json.dumps(environment_record(modules), sort_keys=True, indent=1)
    h = store_code_snapshot(get_db(), content, kind="environment")
    if h:
        exp.log_param(ENV_PARAM, h)
    return h


def load_environment(conn, snapshot_hash: str) -> dict | None:
    """The stored environment record for *snapshot_hash*, or None."""
    from .db import get_code_snapshot
    if not snapshot_hash:
        return None
    row = get_code_snapshot(conn, str(snapshot_hash).strip('"'))
    if not row or row.get("kind") != "environment":
        return None
    try:
        return json.loads(row["content"])
    except ValueError:
        return None
