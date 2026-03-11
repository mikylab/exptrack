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
from .argparse_patch import patch_argparse, capture_argv
from .notebook_hooks import (
    attach_notebook, attach_notebook_deferred, detach_notebook,
    _nb_state,
)
from .matplotlib_patch import patch_savefig
from .script_tracking import capture_script_snapshot
from .cell_lineage import cell_hash as _cell_hash

__all__ = [
    "patch_argparse",
    "capture_argv",
    "attach_notebook",
    "attach_notebook_deferred",
    "detach_notebook",
    "patch_savefig",
    "capture_script_snapshot",
    "_nb_state",
]
