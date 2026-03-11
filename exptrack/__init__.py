"""exptrack — local-first experiment tracker for ML research"""

from .core import Experiment

__version__ = "2.0.0"
__all__ = ["Experiment"]


# ── IPython extension entry points ───────────────────────────────────────────
# %load_ext exptrack looks for these in the top-level package.

def load_ipython_extension(ip):
    from .notebook import load_ipython_extension as _load
    _load(ip)


def unload_ipython_extension(ip):
    from .notebook import detach_notebook
    detach_notebook()
