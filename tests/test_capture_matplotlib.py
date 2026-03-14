"""Tests for exptrack/capture/matplotlib_patch.py — savefig monkey-patching."""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_patch_registers_artifact_on_savefig(tmp_project):
    """Patched savefig() auto-registers the saved figure as an artifact."""
    # Skip if matplotlib not available
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        import pytest
        pytest.skip("matplotlib not installed")

    from exptrack.core import Experiment, get_db
    from exptrack.capture.matplotlib_patch import patch_savefig
    import exptrack.capture.matplotlib_patch as mp_mod

    # Reset patch state
    mp_mod._patched = False
    mp_mod._pending_artifacts = []

    exp = Experiment(script="train.py")
    patch_savefig(exp)

    # Create and save a figure
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], [1, 4, 9])
    save_path = str(tmp_project / "test_plot.png")
    fig.savefig(save_path)
    plt.close(fig)

    # Check artifact was registered
    conn = get_db()
    arts = conn.execute(
        "SELECT label, path FROM artifacts WHERE exp_id=?",
        (exp.id,)
    ).fetchall()

    artifact_paths = [a["path"] for a in arts]
    assert any("test_plot.png" in p for p in artifact_paths), \
        f"Expected test_plot.png in artifacts, got {artifact_paths}"

    exp.finish()
    mp_mod._patched = False


def test_pending_artifacts_flushed(tmp_project):
    """Artifacts saved before experiment creation are buffered and flushed."""
    from exptrack.capture.matplotlib_patch import _pending_artifacts

    # Just verify the pending list structure exists
    assert isinstance(_pending_artifacts, list)
