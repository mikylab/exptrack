"""exptrack — local-first experiment tracker for ML research"""
from __future__ import annotations

from .core import Experiment, finish_experiment

__version__ = "2.0.0"
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
