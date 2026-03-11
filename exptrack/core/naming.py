"""
exptrack/core/naming.py — Run naming and output path helpers
"""
from __future__ import annotations
import uuid
from datetime import datetime
from pathlib import Path

from .. import config as cfg


def make_run_name(script: str = "", params: dict = None) -> str:
    """
    Produces:   train__lr0.01_bs32__0312_a3f2
    Script stem + top N params + date + short uid.
    Always unique, always tells you what it was.
    """
    ncfg     = cfg.load().get("naming", {})
    max_keys = ncfg.get("max_param_keys", 4)
    key_len  = ncfg.get("key_max_len", 8)

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

    uid   = uuid.uuid4().hex[:4]
    today = datetime.now().strftime("%m%d")
    name  = base
    if parts:
        name += "__" + "_".join(parts)
    name += f"__{today}_{uid}"
    return name


def output_path(filename: str, exp_name: str = "") -> Path:
    """Return outputs/<exp_name>/<filename>, creating dirs as needed."""
    conf = cfg.load()
    base = cfg.project_root() / conf.get("outputs_dir", "outputs")
    if exp_name:
        base = base / exp_name
    base.mkdir(parents=True, exist_ok=True)
    return base / filename
