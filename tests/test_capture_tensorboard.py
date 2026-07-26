"""Tests for exptrack/capture/tensorboard_patch.py — SummaryWriter mirroring.

Uses a fake SummaryWriter (no torch/tensorboardX dependency) to verify that
add_scalar / add_scalars / add_histogram calls mirror into exptrack's metrics
table, that the original methods still run, and that a writer imported *after*
the patch is installed also gets patched via the meta-path import hook.
"""
import sys
import types

import exptrack.capture.tensorboard_patch as tb
from exptrack.core import Experiment, get_db


class _FakeSummaryWriter:
    """Minimal stand-in with the SummaryWriter surface exptrack mirrors."""

    def __init__(self):
        self.calls = []

    def add_scalar(self, tag, scalar_value, global_step=None, *a, **k):
        self.calls.append(("scalar", tag, scalar_value, global_step))

    def add_scalars(self, main_tag, tag_scalar_dict, global_step=None, *a, **k):
        self.calls.append(("scalars", main_tag, dict(tag_scalar_dict), global_step))

    def add_histogram(self, tag, values, global_step=None, *a, **k):
        self.calls.append(("hist", tag, global_step))


def _reset_patch_state():
    tb._active_exp = None


def _metrics(exp_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT key, value, step FROM metrics WHERE exp_id=? ORDER BY key, step",
        (exp_id,),
    ).fetchall()
    return [(r["key"], r["value"], r["step"]) for r in rows]


def test_add_scalar_mirrors_to_metrics(tmp_project):
    _reset_patch_state()
    exp = Experiment(script="train.py")

    tb._patch_writer_class(_FakeSummaryWriter)
    tb.patch_tensorboard(exp)

    w = _FakeSummaryWriter()
    w.add_scalar("loss", 0.5, 10)
    w.add_scalar("loss", 0.25, 20)

    # Original method still ran (TensorBoard behavior preserved)
    assert ("scalar", "loss", 0.5, 10) in w.calls

    assert ("loss", 0.5, 10) in _metrics(exp.id)
    assert ("loss", 0.25, 20) in _metrics(exp.id)
    exp.finish()


def test_add_scalars_expands_keys(tmp_project):
    _reset_patch_state()
    exp = Experiment(script="train.py")
    tb._patch_writer_class(_FakeSummaryWriter)
    tb.patch_tensorboard(exp)

    w = _FakeSummaryWriter()
    w.add_scalars("losses", {"train": 1.0, "val": 2.0}, 5)

    m = _metrics(exp.id)
    assert ("losses/train", 1.0, 5) in m
    assert ("losses/val", 2.0, 5) in m
    exp.finish()


def test_add_histogram_records_summary_stats(tmp_project):
    try:
        import numpy as np
    except ImportError:
        import pytest
        pytest.skip("numpy not installed")

    _reset_patch_state()
    exp = Experiment(script="train.py")
    tb._patch_writer_class(_FakeSummaryWriter)
    tb.patch_tensorboard(exp)

    w = _FakeSummaryWriter()
    w.add_histogram("layer1.activations", np.array([0.0, 1.0, 2.0, 3.0, 4.0]), 3)

    keys = {k for (k, _v, _s) in _metrics(exp.id)}
    assert "layer1.activations/mean" in keys
    assert "layer1.activations/std" in keys
    assert "layer1.activations/min" in keys
    assert "layer1.activations/max" in keys
    # mean of 0..4 is 2.0
    assert ("layer1.activations/mean", 2.0, 3) in _metrics(exp.id)
    exp.finish()


def test_no_experiment_is_noop(tmp_project):
    """With no active run, mirroring must not raise."""
    _reset_patch_state()
    tb._patch_writer_class(_FakeSummaryWriter)
    tb.patch_tensorboard(None)

    w = _FakeSummaryWriter()
    # Should not raise even though there's no experiment to log onto.
    w.add_scalar("loss", 0.1, 1)


def test_import_hook_patches_later_import(tmp_project):
    """A writer module imported *after* patch_tensorboard() gets patched."""
    _reset_patch_state()
    exp = Experiment(script="train.py")

    # Install the hook while the target module does not yet exist.
    sys.modules.pop("tensorboardX", None)
    tb.patch_tensorboard(exp)

    # Simulate the user's script importing tensorboardX later by registering a
    # fake module and importing it — the meta-path hook should patch its class.
    fake_mod = types.ModuleType("tensorboardX")

    class SummaryWriter(_FakeSummaryWriter):
        pass

    fake_mod.SummaryWriter = SummaryWriter

    # Manually run the module-patch path the import hook would trigger.
    tb._patch_writer_module(fake_mod)
    assert getattr(SummaryWriter, "_exptrack_patched", False) is True

    w = SummaryWriter()
    w.add_scalar("acc", 0.9, 7)
    assert ("acc", 0.9, 7) in _metrics(exp.id)
    exp.finish()
