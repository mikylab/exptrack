"""
exptrack/core/naming.py — Run naming and output path helpers
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from .. import config as cfg

# Trailing fingerprint of an auto-generated name: a `__<8 hex>` suffix, optionally
# preceded by the legacy `_MMDD` numeric date. Used to tell whether a run still
# carries its generated name (vs. one the user deliberately renamed).
_AUTO_NAME_RE = re.compile(r"__(?:\d{4}_)?[0-9a-f]{8}$")

# Characters that must never reach a run name: the name doubles as an on-disk
# output-folder component, so a slash (or whitespace, or other path-hostile
# char) would split it into nested dirs and break the rename. Collapse runs of
# them away rather than substituting, to keep names compact.
_PATH_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._+=-]+")


def _path_safe(s: str) -> str:
    """Strip characters that aren't safe in a single filesystem path component."""
    return _PATH_UNSAFE_RE.sub("", s)


# Substituting rather than stripping (so distinct names stay distinct) and
# length-capped, for values that become a *filename* on export rather than a
# run name. `_path_safe`'s strip-and-keep-compact rule is right for names;
# this one is right for paths built from user-controlled text.
_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(s: str, max_len: int = 80, default: str = "unnamed") -> str:
    """Reduce a user-controlled string to one safe filename component.

    The single rule for export paths — `exptrack source --out` builds both a
    directory and a filename from stored, user-controlled text (a run name, a
    recorded script path), and three inline copies of the character class is
    three places to miss when it changes. An empty result falls back to
    `default` rather than producing a path component of `""`.
    """
    return _FILENAME_UNSAFE_RE.sub("_", str(s or ""))[:max_len] or default


def make_run_name(script: str = "", params: dict | None = None) -> str:
    """
    Produces (readable, default):   May22_train__lr0.01_bs32__a3f25b1c
    Or (date_style="numeric"):      train__lr0.01_bs32__0312_a3f25b1c

    Readable date + script stem + top N params + short uid.
    Always unique, always tells you what it was and *when* you ran it.

    The ``naming.date_style`` config key controls the date: ``"readable"``
    (default, e.g. ``May22``) front-loads a friendly month/day so un-renamed
    runs read chronologically; ``"numeric"`` keeps the terse legacy ``MMDD``
    in the middle.
    """
    ncfg       = cfg.load().get("naming", {})
    max_keys   = ncfg.get("max_param_keys", 4)
    key_len    = ncfg.get("key_max_len", 8)
    date_style = ncfg.get("date_style", "readable")

    base  = _path_safe(Path(script).stem) if script else "exp"
    parts = []
    if params:
        # Skip exptrack-internal bookkeeping params (prefixed with "_": _var/…,
        # _code_change/…, _cells_ran, _confusion_matrices). They aren't
        # hyperparameters — their values are assignment exprs / diff fragments /
        # JSON whose slashes and spaces would otherwise pollute the name and
        # break the on-disk output-dir rename. Filter *before* taking the top N.
        real = [(k, v) for k, v in params.items() if not k.startswith("_")]
        for k, v in real[:max_keys]:
            short_k = k.split(".")[-1][:key_len]
            if isinstance(v, bool):
                val = str(int(v))
            elif isinstance(v, float):
                val = f"{v:.3g}"
            else:
                val = str(v)[:12]
            parts.append(_path_safe(f"{short_k}{val}"))

    uid = uuid.uuid4().hex[:8]
    now = datetime.now()

    if date_style == "numeric":
        # Legacy layout: base__params__MMDD_uid
        name = base
        if parts:
            name += "__" + "_".join(parts)
        name += f"__{now.strftime('%m%d')}_{uid}"
        return name

    # Readable layout: MonDD_base__params__uid  (e.g. May22_train__lr0.01__a3f2…)
    name = f"{now.strftime('%b%d')}_{base}"
    if parts:
        name += "__" + "_".join(parts)
    name += f"__{uid}"
    return name


def looks_auto_named(name: str) -> bool:
    """True if *name* matches the generated-name fingerprint (a `__<8 hex>`
    suffix). Used to flag runs the user never renamed."""
    return bool(name) and _AUTO_NAME_RE.search(name) is not None


def output_path(filename: str, exp_name: str = "") -> Path:
    """Return outputs/<exp_name>/<filename>, creating dirs as needed."""
    conf = cfg.load()
    base = cfg.project_root() / conf.get("outputs_dir", "outputs")
    if exp_name:
        base = base / exp_name
    base.mkdir(parents=True, exist_ok=True)
    return base / filename
