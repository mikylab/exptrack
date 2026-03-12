"""
exptrack/core — Experiment class + database + git helpers

Re-exports everything so existing imports like
    from exptrack.core import Experiment, get_db
continue to work.
"""
from .db import get_db, delete_experiment, finish_experiment, rename_output_folder
from .git import git_info
from .naming import make_run_name, output_path
from .experiment import Experiment
from . import queries

__all__ = [
    "get_db",
    "delete_experiment",
    "finish_experiment",
    "rename_output_folder",
    "git_info",
    "make_run_name",
    "output_path",
    "Experiment",
    "queries",
]
