"""
exptrack/capture — Zero-friction parameter capture

Two capture modes:
  1. argparse   — patches ArgumentParser.parse_args() AND parse_known_args()
                  so params are logged the moment the user's script calls it.
  2. notebook   — IPython post_execute hook that after EVERY cell:
                    - diffs the cell source against previous version (by content hash)
                    - captures new/changed scalar variables
                    - captures stdout/stderr output
                    - logs timeline events for ordering and context reconstruction
                  Stores snapshots in .exptrack/notebook_history/<nb_name>/
"""
from .argparse_patch import capture_argv, patch_argparse
from .matplotlib_patch import patch_savefig
from .notebook_hooks import (
    _nb_state,
    attach_notebook,
    attach_notebook_deferred,
    detach_notebook,
)
from .script_tracking import capture_script_snapshot

__all__ = [
    "_nb_state",
    "attach_notebook",
    "attach_notebook_deferred",
    "capture_argv",
    "capture_script_snapshot",
    "detach_notebook",
    "patch_argparse",
    "patch_savefig",
]
