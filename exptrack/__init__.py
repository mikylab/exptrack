"""exptrack — local-first experiment tracker for ML research"""
from __future__ import annotations

from .core import Experiment, finish_experiment

# Single source of truth: version is defined in pyproject.toml only.
# importlib.metadata reads it at runtime from the installed package.
try:
    from importlib.metadata import version as _get_version
    __version__ = _get_version("exptrack")
except Exception:
    __version__ = "0.0.0"  # fallback for uninstalled/dev usage
__all__ = ["Experiment", "finish_experiment"]


# ── IPython extension entry points ───────────────────────────────────────────
# %load_ext exptrack looks for these in the top-level package.

from typing import Any


def load_ipython_extension(ip: Any) -> None:
    from .notebook import load_ipython_extension as _load
    _load(ip)


def unload_ipython_extension(ip: Any) -> None:
    from .notebook import detach_notebook
    detach_notebook()
