"""
exptrack/core — Experiment class + database + git helpers

Re-exports everything so existing imports like
    from exptrack.core import Experiment, get_db
continue to work.
"""
from . import queries
from .db import (
    close_db,
    delete_experiment,
    finish_experiment,
    get_db,
    get_delete_preview,
    list_trashed_experiments,
    rename_output_folder,
    restore_experiment,
    trash_experiment,
)
from .experiment import Experiment
from .git import git_info
from .gpu import gpu_info
from .naming import make_run_name, output_path

__all__ = [
    "Experiment",
    "close_db",
    "delete_experiment",
    "finish_experiment",
    "get_db",
    "get_delete_preview",
    "git_info",
    "gpu_info",
    "list_trashed_experiments",
    "make_run_name",
    "output_path",
    "queries",
    "rename_output_folder",
    "restore_experiment",
    "trash_experiment",
]
