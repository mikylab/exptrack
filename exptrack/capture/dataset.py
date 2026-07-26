"""
exptrack/capture/dataset.py — back-compat shim.

Dataset/input versioning moved to ``exptrack.core.dataset`` to fix the
core→capture layering inversion (``core.experiment.finish`` needs it, and it
only depends on ``core``). This module re-exports the public + tested surface
so ``from exptrack.capture.dataset import …`` keeps working.
"""
from __future__ import annotations

from ..core.dataset import (  # noqa: F401  (re-exported for back-compat)
    _dir_manifest,
    _looks_like_dataset,
    build_manifest,
    capture_dataset_manifest,
)
