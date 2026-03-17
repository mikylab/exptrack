"""
exptrack/core — Experiment class + database + git helpers

Re-exports everything so existing imports like
    from exptrack.core import Experiment, get_db
continue to work.
"""
from . import queries
from .db import close_db, delete_experiment, finish_experiment, get_db, rename_output_folder
from .experiment import Experiment
from .git import git_info
from .naming import make_run_name, output_path

__all__ = [
    "Experiment",
    "close_db",
    "delete_experiment",
    "finish_experiment",
    "get_db",
    "git_info",
    "make_run_name",
    "output_path",
    "queries",
    "rename_output_folder",
]
