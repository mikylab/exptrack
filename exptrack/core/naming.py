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

    base  = Path(script).stem if script else "exp"
    parts = []
    if params:
        for k, v in list(params.items())[:max_keys]:
            short_k = k.split(".")[-1][:key_len]
            if isinstance(v, float):
                parts.append(f"{short_k}{v:.3g}")
            elif isinstance(v, bool):
                parts.append(f"{short_k}{int(v)}")
            else:
                parts.append(f"{short_k}{str(v)[:12]}")

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
