"""
exptrack/core — Experiment class + database + git helpers

Re-exports everything so existing imports like
    from exptrack.core import Experiment, get_db
continue to work.
"""
from .db import get_db, delete_experiment, finish_experiment
from .git import git_info
from .naming import make_run_name, output_path
from .experiment import Experiment

__all__ = [
    "get_db",
    "delete_experiment",
    "finish_experiment",
    "git_info",
    "make_run_name",
    "output_path",
    "Experiment",
]
