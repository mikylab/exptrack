"""Tests for exptrack/core/gpu.py — gpu_info, _nvidia_smi_query (no GPU needed)."""
from __future__ import annotations


def test_gpu_info_returns_dict_and_never_raises(monkeypatch):
    """gpu_info() returns a dict and doesn't throw, even without nvidia-smi."""
    from exptrack.core import gpu

    # Force the no-GPU path regardless of host (binary may be present in dev).
    monkeypatch.setattr(gpu, "_nvidia_smi_query", lambda: ([], []))
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    info = gpu.gpu_info()
    assert isinstance(info, dict)
    assert info["gpu_count"] == 0


def test_cuda_visible_devices_reflected(monkeypatch):
    """CUDA_VISIBLE_DEVICES from the env appears as cuda_visible_devices."""
    from exptrack.core import gpu

    monkeypatch.setattr(gpu, "_nvidia_smi_query", lambda: ([], []))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1,3")

    info = gpu.gpu_info()
    assert info["cuda_visible_devices"] == "1,3"


def test_cuda_visible_devices_absent_when_unset(monkeypatch):
    """When CUDA_VISIBLE_DEVICES is unset the key is omitted (matches source)."""
    from exptrack.core import gpu

    monkeypatch.setattr(gpu, "_nvidia_smi_query", lambda: ([], []))
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    info = gpu.gpu_info()
    assert "cuda_visible_devices" not in info


def test_nvidia_smi_query_missing_binary_returns_empty(monkeypatch):
    """_nvidia_smi_query returns ([], []) when the binary is missing."""
    import subprocess

    from exptrack.core import gpu

    def _boom(*a, **k):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert gpu._nvidia_smi_query() == ([], [])


def test_nvidia_smi_query_nonzero_exit_returns_empty(monkeypatch):
    """_nvidia_smi_query returns ([], []) when nvidia-smi exits nonzero."""
    import subprocess

    from exptrack.core import gpu

    class _R:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    assert gpu._nvidia_smi_query() == ([], [])


def test_nvidia_smi_query_parses_output(monkeypatch):
    """_nvidia_smi_query parses name + memory from csv output."""
    import subprocess

    from exptrack.core import gpu

    class _R:
        returncode = 0
        stdout = "NVIDIA A100, 40960\nNVIDIA A100, 40960\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    devices, memory = gpu._nvidia_smi_query()
    assert devices == ["NVIDIA A100", "NVIDIA A100"]
    assert memory == [40960, 40960]
