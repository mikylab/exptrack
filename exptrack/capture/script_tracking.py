"""
exptrack/capture/script_tracking.py — Back-compat shim.

Script source capture moved to ``core/script_snapshot.py`` to fix a
core→capture layering inversion: ``core.experiment`` snapshots the script on
every run, and this module only ever depended on ``core``/``config``. Same
pattern as ``capture/dataset.py``. Import from ``exptrack.core.script_snapshot``
in new code.
"""
from __future__ import annotations

from ..core.script_snapshot import capture_script_snapshot

__all__ = ["capture_script_snapshot"]
