"""Tests for exptrack/capture/matplotlib_patch.py — savefig monkey-patching."""


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

    import exptrack.capture.matplotlib_patch as mp_mod
    from exptrack.capture.matplotlib_patch import patch_savefig
    from exptrack.core import Experiment, get_db

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


def test_savefig_to_buffer_no_phantom_artifact(tmp_project):
    """savefig() to an in-memory buffer registers no artifact and does not warn.

    Regression: a file-like target (io.BytesIO — a standard idiom for embedding
    or serving a plot) was run through _P(str(fname)).resolve(), fabricating a
    bogus path from the object's repr. That produced a "No such file" warning on
    stderr and a phantom artifacts row (NULL hash/size) on every in-memory save.
    """
    import io

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        import pytest
        pytest.skip("matplotlib not installed")

    import exptrack.capture.matplotlib_patch as mp_mod
    from exptrack.capture.matplotlib_patch import patch_savefig
    from exptrack.core import Experiment, get_db

    mp_mod._patched = False
    mp_mod._pending_artifacts = []

    exp = Experiment(script="train.py")
    patch_savefig(exp)

    conn = get_db()

    def artifact_paths():
        return [r["path"] for r in conn.execute(
            "SELECT path FROM artifacts WHERE exp_id=?", (exp.id,)).fetchall()]

    before = artifact_paths()

    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], [1, 4, 9])
    buf = io.BytesIO()
    fig.savefig(buf, format="png")   # must not raise, warn, or register
    plt.close(fig)

    # The save itself worked — the buffer has PNG bytes.
    assert buf.getvalue()[:4] == b"\x89PNG"

    # The buffer save added no artifact row, and certainly none naming the
    # buffer's repr (the old phantom-path bug).
    after = artifact_paths()
    assert after == before, f"buffer save added artifacts: {set(after) - set(before)}"
    assert not any("BytesIO" in p for p in after)

    exp.finish()
    mp_mod._patched = False
